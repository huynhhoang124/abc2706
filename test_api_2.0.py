import urllib.request
import json
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

api_key = ""
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"

payload = {
    "contents": [{"parts": [{"text": "Hello, write a 3-word response."}]}]
}

headers = {"Content-Type": "application/json"}
req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

try:
    print("Sending request to Google Gemini API (gemini-2.0-flash)...")
    with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
        print("Success! Response Code:", response.getcode())
        res = json.loads(response.read().decode("utf-8"))
        print("Response Text:", res["candidates"][0]["content"]["parts"][0]["text"].strip())
except urllib.error.HTTPError as e:
    print("HTTP Error Code:", e.code)
    print("HTTP Error Reason:", e.reason)
    print("HTTP Error Body:")
    print(e.read().decode("utf-8"))
except Exception as e:
    print("General Error:", e)
