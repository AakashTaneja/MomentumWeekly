import pandas as pd
import datetime as dt
import os
from kiteconnect import KiteConnect

# === File path for saved snapshot ===
SNAPSHOT_FILE = "ltp_snapshot_last.csv"
CSV_SYMBOL_FILE = "ind_nifty200list.csv"  # Your Nifty 200 list

# === Kite Connect Configuration ===
API_KEY = "your_api_key_here"
ACCESS_TOKEN = "your_access_token_here"

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# === Utility: Check if Market is Open (Mon–Fri, 9:15–15:30) ===
def is_market_open():
    now = dt.datetime.now()
    weekday = now.weekday()  # Monday = 0, Sunday = 6
    return weekday < 5 and dt.time(9, 15) <= now.time() <= dt.time(15, 30)

# === Live Kite LTP Fetch ===
def fetch_live_kite_ltp_data(symbols):
    full_symbols = ["NSE:" + sym for sym in symbols]
    ltp_data = kite.ltp(full_symbols)
    records = []

    for full_sym, data in ltp_data.items():
        try:
            open_price = data['ohlc']['open']
            last_price = data['last_price']
            volume = data['volume']
            pct_change = round(((last_price - open_price) / open_price) * 100, 2)

            records.append({
                'symbol': full_sym.split(":")[1],
                'open': open_price,
                'last_price': last_price,
                'volume': volume,
                'pct_change': pct_change
            })
        except Exception as e:
            print(f"Skipping {full_sym}: {e}")
            continue

    return pd.DataFrame(records)

# === Load or Fetch Function ===
def load_or_fetch_ltp_data(symbols):
    if is_market_open():
        print("🔄 Live market open. Using fresh data from Kite.")
        df = fetch_live_kite_ltp_data(symbols)
        df.to_csv(SNAPSHOT_FILE, index=False)
        print(f"📁 Snapshot saved to {SNAPSHOT_FILE}")
    else:
        print("🟡 Market closed. Using saved data from last session.")
        if os.path.exists(SNAPSHOT_FILE):
            df = pd.read_csv(SNAPSHOT_FILE)
        else:
            raise FileNotFoundError("❌ Saved snapshot not found. Please run on a market day to create it.")
    return df

# === MAIN EXECUTION ===
if __name__ == "__main__":
    # Load Nifty 200 tickers from CSV
    if not os.path.exists(CSV_SYMBOL_FILE):
        raise FileNotFoundError(f"Ticker list not found: {CSV_SYMBOL_FILE}")

    df_symbols = pd.read_csv(CSV_SYMBOL_FILE)
    symbol_col = df_symbols.columns[0]
    nifty_symbols = df_symbols[symbol_col].dropna().unique().tolist()

    # Load or fetch the LTP data
    ltp_data_df = load_or_fetch_ltp_data(nifty_symbols)

    # Filter: only stocks with positive intraday price change
    filtered_df = ltp_data_df[ltp_data_df['pct_change'] > 0]

    # Sort by volume descending and get top 50
    top50_df = filtered_df.sort_values(by='volume', ascending=False).head(50)

    # Display final selection
    print("\n📈 Top 50 active gainers:")
    print(top50_df[['symbol', 'pct_change', 'volume']].to_string(index=False))
