import os
import json
from datetime import datetime, timedelta

KEY_FILE = "Keys"
DATA_FILE = "key_data.json"

# Load key data (expiration times)
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        key_data = json.load(f)
else:
    key_data = {}

# Remove expired keys
now = datetime.now().timestamp()
for key, exp_time in list(key_data.items()):
    if exp_time < now:
        print(f"🗑️ Removing expired key: {key}")
        key_data.pop(key)

# Save updated key data
with open(DATA_FILE, "w") as f:
    json.dump(key_data, f, indent=4)

# Keep only valid keys in Keys file
if os.path.exists(KEY_FILE):
    with open(KEY_FILE, "r") as f:
        lines = [line.strip() for line in f.readlines()]

    valid_keys = [k for k in lines if k in key_data]
    with open(KEY_FILE, "w") as f:
        f.write("\n".join(valid_keys) + "\n")

print("✅ Cleanup complete.")

# Example: add a new key manually (for testing)
# from datetime import datetime, timedelta
# key_data["example_key"] = (datetime.now() + timedelta(days=1)).timestamp()
# with open(DATA_FILE, "w") as f:
#     json.dump(key_data, f, indent=4)
