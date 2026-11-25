"""Simulate an Instagram messages webhook against the live bot."""
import hashlib
import hmac
import json
import os
import time
import urllib.request

SECRET = os.environ.get("APP_SECRET", "62054e2e7c3fc52d01a96e13b42049ac")
URL = os.environ.get("WEBHOOK_URL", "https://recipebot-jakl.onrender.com/webhook")
SENDER = os.environ.get("SENDER", "7770001112223334")

payload = {
    "object": "instagram",
    "entry": [{
        "id": "17841480800673182",
        "time": int(time.time()),
        "changes": [{
            "field": "messages",
            "value": {
                "messaging": [{
                    "sender": {"id": "7770001112223334"},
                    "recipient": {"id": "17841480800673182"},
                    "timestamp": int(time.time()),
                    "message": {
                        "mid": "echo|simtest-%d" % int(time.time()),
                        "text": None,
                        "attachments": [{
                            "type": "video",
                            "payload": {"video": {
                                "url": os.environ.get(
                                    "VIDEO_URL",
                                    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4"),
                                "mime_type": "video/mp4",
                                "length": 2000000,
                            }},
                        }],
                    },
                }],
            },
        }],
    }],
}

body = json.dumps(payload).encode()
sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
req = urllib.request.Request(URL, data=body, headers={
    "Content-Type": "application/json",
    "X-Hub-Signature-256": "sha256=" + sig,
})
with urllib.request.urlopen(req, timeout=60) as resp:
    print(resp.status, resp.read()[:200])
