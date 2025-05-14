from kiteconnect import KiteConnect
from config.keys import get_api_key, get_api_secret

API_KEY = get_api_key()
API_SECRET = get_api_secret()

request_token = input("🔑 Paste the request_token from browser URL: ").strip()

kite = KiteConnect(api_key=API_KEY)

try:
    session = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = session["access_token"]
    with open("access_token.txt", "w") as f:
        f.write(access_token)
    print("✅ Access token saved to access_token.txt")
except Exception as e:
    print("❌ Failed to generate access token:", e)
