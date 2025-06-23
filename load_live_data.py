import pandas as pd
import datetime as dt
import os
import random

# === File path for saved snapshot ===
SNAPSHOT_FILE = "ltp_snapshot_last.csv"
CSV_SYMBOL_FILE = "ind_nifty200list.csv"  # Your Nifty 200 list

# === Utility: Check if Market is Open (Mon–Fri, 9:15–15:30) ===
def is_market_open():
    now = dt.datetime.now()
    weekday = now.weekday()  # Monday = 0, Sunday = 6
    return weekday < 5 and dt.time(9, 15) <= now.time() <= dt.time(15, 30)

# === Simulated Kite LTP fetch (replace with actual kite.ltp() call in live mode) ===
def fetch_live_kite_ltp_data(symbols):
    dummy_data = []
    for symbol in symbols:
        open_price = round(random.uniform(100, 2500), 2)
        last_price = round(open_price * random.uniform(0.95, 1.07), 2)
        volume = random.randint(50000, 8000000)
        pct_change = round(((last_price - open_price) / open_price) * 100, 2)
        dummy_data.append({
            'symbol': symbol,
            'open': open_price,
            'last_price': last_price,
            'volume': volume,
            'pct_change': pct_change
        })
    return pd.DataFrame(dummy_data)

# === Load or Fetch Function ===
def load_or_fetch_ltp_data(symbols):
    if is_market_open():
        print("🔄 Live market open. Using fresh data from Kite.")
        df = fetch_live_kite_ltp_data(symbols)  # Replace this with kite.ltp() for live
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

    df = pd.read_csv(CSV_SYMBOL_FILE)
    symbol_col = df.columns[0]  # Use the first column dynamically
    nifty_symbols = df[symbol_col].dropna().unique().tolist()

    # Load or fetch the LTP data
    ltp_data_df = load_or_fetch_ltp_data(nifty_symbols)

    # Filter: only stocks with positive intraday price change
    filtered_df = ltp_data_df[ltp_data_df['pct_change'] > 0]

    # Sort by volume descending and get top 50
    top50_df = filtered_df.sort_values(by='volume', ascending=False).head(50)

    # Display final selection
    print("\n📈 Top 50 active gainers:")
    print(top50_df[['symbol', 'pct_change', 'volume']])
