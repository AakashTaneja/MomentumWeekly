from kiteconnect import KiteConnect
from config.keys import get_api_key
import webbrowser

API_KEY = get_api_key()

kite = KiteConnect(api_key=API_KEY)
login_url = kite.login_url()

print("\n🔗 Open this URL in your browser and log in:")
print(login_url)

# Optional: auto-open browser
webbrowser.open(login_url)
