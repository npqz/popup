#!/usr/bin/env python3
"""
github_key_manager.py

Manage ephemeral auth keys in a GitHub repo file.

Usage examples:
  # Add a key with 1 day (86400s)
  python github_key_manager.py add --owner npqz --repo popup --token $GITHUB_TOKEN --path Keys --key-id "faisal" --key-value "the_key" --duration 86400

  # Add with lifetime:
  python github_key_manager.py add --owner npqz --repo popup --token $GITHUB_TOKEN --path Keys --key-id "faisal" --key-value "the_key" --duration lifetime

  # Remove:
  python github_key_manager.py remove --owner npqz --repo popup --token $GITHUB_TOKEN --path Keys --key-id "faisal"

  # Cleanup expired (alias 'clean' also supported):
  python github_key_manager.py cleanup --owner npqz --repo popup --token $GITHUB_TOKEN --path Keys
  python github_key_manager.py clean   --owner npqz --repo popup --token $GITHUB_TOKEN --path Keys

  # List:
  python github_key_manager.py list --owner npqz --repo popup --token $GITHUB_TOKEN --path Keys
"""
from __future__ import annotations
import argparse
import json
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

try:
    # Modern PyGithub usage (Auth)
    from github import Github, Auth
except Exception:
    # Fallback if older PyGithub installed
    from github import Github  # type: ignore
    Auth = None  # type: ignore

DEFAULT_KEYS_PATH = "keys"
COMMIT_BASE_MSG = "[auth-key-manager]"

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def iso_to_dt(s: str) -> datetime:
    # parse ISO including timezone
    return datetime.fromisoformat(s)

class GitHubKeyManager:
    def __init__(self, gh_token: str, owner: str, repo_name: str, keys_path: str = DEFAULT_KEYS_PATH):
        # Use new Auth if available to avoid deprecation warnings
        try:
            if 'Auth' in globals() and Auth is not None:
                self.g = Github(auth=Auth.Token(gh_token))
            else:
                self.g = Github(gh_token)
        except Exception:
            # Fallback
            self.g = Github(gh_token)
        self.owner = owner
        self.repo_name = repo_name
        self.keys_path = keys_path
        self.repo = self.g.get_repo(f"{owner}/{repo_name}")

    def _get_file(self) -> (Dict[str, Any], Optional[str], str):
        """
        Returns (data_dict, file_sha, file_path). If the file doesn't exist, returns ({}, None, keys_path).
        """
        try:
            file = self.repo.get_contents(self.keys_path)
            content = file.decoded_content.decode()
            try:
                data = json.loads(content) if content.strip() else {}
            except json.JSONDecodeError:
                print(f"Warning: {self.keys_path} in repo is not valid JSON. Overwriting with an object.")
                data = {}
            return data, file.sha, file.path
        except Exception as e:
            # if not found, create new
            if getattr(e, "status", None) == 404 or "Not Found" in str(e):
                return {}, None, self.keys_path
            raise

    def _write_file(self, data: Dict[str, Any], message: str, sha: Optional[str]):
        content = json.dumps(data, indent=2, ensure_ascii=False)
        if sha:
            updated = self.repo.update_file(self.keys_path, message, content, sha)
            return updated
        else:
            created = self.repo.create_file(self.keys_path, message, content)
            return created

    def add_key(self, key_id: str, key_value: str, duration: Optional[int] = None, added_by: str = "script"):
        """
        duration: seconds integer, or None for lifetime (no expiry)
        """
        data, sha, path = self._get_file()
        expires_at_iso = None
        if duration is not None:
            expires_dt = datetime.now(timezone.utc) + timedelta(seconds=duration)
            expires_at_iso = expires_dt.isoformat()

        # Try to convert key_id to int if it's numeric
        try:
            key_id_stored = int(key_id)
        except ValueError:
            key_id_stored = key_id

        entry = {
            "value": key_value,
            "expires_at": expires_at_iso,  # None -> JSON null
            "added_by": added_by,
            "added_at": now_iso()
        }
        data[key_id_stored] = entry
        message = f"{COMMIT_BASE_MSG} add key {key_id} (expires {expires_at_iso})"
        result = self._write_file(data, message, sha)
        print(f"Added key '{key_id}' and committed: {message}")

        # Schedule in-process removal only for keys with numeric duration
        if duration is not None:
            def remove_later():
                try:
                    self.remove_key(str(key_id_stored), reason="auto-expire (timer)")
                    print(f"Auto-removed key '{key_id}' after {duration} seconds (timer).")
                except Exception as e:
                    print(f"Failed to auto-remove key {key_id}: {e}")

            timer = threading.Timer(duration, remove_later)
            timer.daemon = True
            timer.start()

        return result

    def remove_key(self, key_id: str, reason: str = "manual"):
        data, sha, path = self._get_file()
        
        # Strip whitespace from input key_id
        key_id = key_id.strip()
        
        if key_id not in data:
            print(f"\n[ERROR] Key '{key_id}' not found in {self.keys_path}.")
            print(f"\nAvailable keys ({len(data)}):")
            if data:
                for k in sorted(data.keys()):
                    print(f"  - '{k}'")
            else:
                print("  (no keys present)")
            print("\nNote: Key IDs are case-sensitive and must match exactly.")
            return None
            
        data.pop(key_id, None)
        message = f"{COMMIT_BASE_MSG} remove key {key_id} ({reason})"
        result = self._write_file(data, message, sha)
        print(f"[SUCCESS] Removed key '{key_id}'. Commit message: {message}")
        return result

    def cleanup_expired(self):
        data, sha, path = self._get_file()
        if not data:
            print("No keys found (or file missing).")
            return None

        now = datetime.now(timezone.utc)
        to_remove = []
        for k, v in list(data.items()):
            expires = v.get("expires_at", None)
            if expires is None:
                # lifetime key
                continue
            try:
                expires_dt = iso_to_dt(expires)
            except Exception:
                # can't parse -> remove to be safe
                to_remove.append(k)
                continue
            if expires_dt <= now:
                to_remove.append(k)

        if not to_remove:
            print("No expired keys to remove.")
            return None

        for k in to_remove:
            print(f"Removing expired key: {k}")
            data.pop(k, None)

        message = f"{COMMIT_BASE_MSG} cleanup expired keys: {', '.join(to_remove)}"
        result = self._write_file(data, message, sha)
        print(f"Removed expired keys: {to_remove}")
        return result

    def list_keys(self):
        data, sha, path = self._get_file()
        if not data:
            print("No keys present.")
            return {}
        
        print(f"\nKeys in {self.keys_path} ({len(data)} total):")
        print("=" * 70)
        
        # pretty print keys (showing expiry)
        for k, v in sorted(data.items()):
            exp = v.get("expires_at", None)
            added = v.get("added_at", "unknown")
            status = "LIFETIME" if exp is None else "expires"
            
            print(f"\nKey ID: '{k}'")
            print(f"  Status: {status}")
            if exp:
                print(f"  Expires: {exp}")
            print(f"  Added: {added}")
            
        print("=" * 70)
        return data

def parse_args():
    p = argparse.ArgumentParser(description="Manage ephemeral auth keys in a GitHub repo file.")
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--owner", required=True, help="GitHub repo owner (user or org)")
    common.add_argument("--repo", required=True, help="Repository name")
    common.add_argument("--token", required=True, help="GitHub Personal Access Token")
    common.add_argument("--path", default=DEFAULT_KEYS_PATH, help="Path in repo to store keys (default Keys)")

    a = sub.add_parser("add", parents=[common], help="Add a key with expiry")
    a.add_argument("--key-id", required=True, help="Identifier for the key (e.g. username or id)")
    a.add_argument("--key-value", required=True, help="The actual key or token string")
    a.add_argument("--duration", required=True, help="Duration in seconds or the word 'lifetime'")

    r = sub.add_parser("remove", parents=[common], help="Manually remove a key")
    r.add_argument("--key-id", required=True, help="Identifier for the key to remove")

    c = sub.add_parser("cleanup", parents=[common], help="Remove expired keys")
    c_alias = sub.add_parser("clean", parents=[common], help="Alias for cleanup (remove expired keys)")

    l = sub.add_parser("list", parents=[common], help="List keys")

    return p.parse_args()

def main():
    args = parse_args()
    manager = GitHubKeyManager(args.token, args.owner, args.repo, args.path)

    if args.cmd == "add":
        dur_arg = args.duration
        if isinstance(dur_arg, str) and dur_arg.lower() == "lifetime":
            duration = None
        else:
            try:
                duration = int(dur_arg)
            except Exception:
                print("Invalid duration. Use integer seconds or 'lifetime'.")
                return
        manager.add_key(args.key_id, args.key_value, duration, added_by="script")
        # run cleanup after adding
        manager.cleanup_expired()

    elif args.cmd == "remove":
        manager.remove_key(args.key_id, reason="manual")

    elif args.cmd in ("cleanup", "clean"):
        manager.cleanup_expired()

    elif args.cmd == "list":
        manager.list_keys()
    else:
        print("Unknown command")

if __name__ == "__main__":
    main()
