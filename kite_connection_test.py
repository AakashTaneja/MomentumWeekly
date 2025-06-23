from kiteconnect import KiteConnect, exceptions as kite_exceptions
from config.keys import get_api_key

ACCESS_TOKEN_PATH = "access_token.txt"
API_KEY = get_api_key()

# Read access token from file
with open(ACCESS_TOKEN_PATH) as f:
    ACCESS_TOKEN = f.read().strip()

# Try Kite connection
try:
    kite = KiteConnect(api_key=API_KEY)
    kite.set_access_token(ACCESS_TOKEN)
    print("✅ Kite Connect: Connection successful.")
except kite_exceptions.TokenException:
    print("❌ Invalid or expired access token. Please re-authenticate and update access_token.txt.")
    exit()
