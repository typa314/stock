import os
import json
import uuid
import urllib.request

env = {}
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(env_path):
    for line in open(env_path, "r", encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")

token = env.get("CF_API_TOKEN")
account_id = env.get("CF_ACCOUNT_ID")
worker_name = env.get("CF_WORKER_NAME", "tw-stock-bpa-router")

worker_path = os.path.join(os.path.dirname(__file__), "..", "cloudflare_worker", "worker.js")
code = open(worker_path, "r", encoding="utf-8").read()

boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
parts = []

parts.append(f"--{boundary}\r\n".encode("utf-8"))
parts.append(b'Content-Disposition: form-data; name="index.js"; filename="index.js"\r\n')
parts.append(b"Content-Type: application/javascript+module\r\n\r\n")
parts.append(code.encode("utf-8"))
parts.append(b"\r\n")

metadata = json.dumps({"main_module": "index.js", "compatibility_date": "2026-09-07"})
parts.append(f"--{boundary}\r\n".encode("utf-8"))
parts.append(b'Content-Disposition: form-data; name="metadata"\r\n')
parts.append(b"Content-Type: application/json\r\n\r\n")
parts.append(metadata.encode("utf-8"))
parts.append(b"\r\n")

parts.append(f"--{boundary}--\r\n".encode("utf-8"))

body_data = b"".join(parts)

url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/workers/scripts/{worker_name}"
req = urllib.request.Request(
    url,
    data=body_data,
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}"
    },
    method="PUT"
)

try:
    res = urllib.request.urlopen(req, timeout=15)
    data = json.loads(res.read().decode())
    print("Deploy Worker Code Success:", data.get("success"))
except urllib.error.HTTPError as e:
    print("Deploy Worker Code Error:", e.code, e.read().decode())
