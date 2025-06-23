import requests
import pandas as pd

def fetch_most_active_stocks(limit=50):
    url = "https://www.nseindia.com/api/live-analysis-most-active-securities"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/"
    }

    session = requests.Session()
    session.get("https://www.nseindia.com", headers=headers, timeout=5)  # Set cookie

    response = session.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    data = response.json()
    df = pd.DataFrame(data['data'])
    df = df[df['symbol'].notnull()]
    return df['symbol'].head(limit).tolist()

# Example use
top_50 = fetch_most_active_stocks()
print(top_50)
