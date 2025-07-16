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

# === Simulated LTP fetch for offline testing ===
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

# === Real-time LTP fetch using Kite Connect ===
def fetch_kite_ltp_data(symbols, kite):
    exchange_symbols = [f"NSE:{symbol}" for symbol in symbols]
    quote_data = kite.quote(exchange_symbols)

    data = []
    for symbol in symbols:
        try:
            q = quote_data[f"NSE:{symbol}"]
            open_price = q['ohlc']['open']
            last_price = q['last_price']
            volume = q['volume']
            pct_change = round(((last_price - open_price) / open_price) * 100, 2)

            data.append({
                'symbol': symbol,
                'open': open_price,
                'last_price': last_price,
                'volume': volume,
                'pct_change': pct_change
            })
        except KeyError:
            continue  # Skip symbols with missing data

    return pd.DataFrame(data)

# === Load or Fetch Function ===
def load_or_fetch_ltp_data(symbols, kite=None, simulate=False):
    if is_market_open():
        print("🔄 Live market open. Using fresh data from Kite.")
        df = (
            fetch_live_kite_ltp_data(symbols)
            if simulate or kite is None
            else fetch_kite_ltp_data(symbols, kite)
        )
        df.to_csv(SNAPSHOT_FILE, index=False)
        print(f"📁 Snapshot saved to {SNAPSHOT_FILE}")
    else:
        print("🟡 Market closed. Using saved data from last session.")
        if os.path.exists(SNAPSHOT_FILE):
            df = pd.read_csv(SNAPSHOT_FILE)
        else:
            raise FileNotFoundError("❌ Saved snapshot not found. Please run on a market day to create it.")
    return df

# === MAIN EXECUTION (for standalone test) ===
if __name__ == "__main__":
    if not os.path.exists(CSV_SYMBOL_FILE):
        raise FileNotFoundError(f"Ticker list not found: {CSV_SYMBOL_FILE}")

    df = pd.read_csv(CSV_SYMBOL_FILE)
    symbol_col = "Symbol" if "Symbol" in df.columns else df.columns[0]
    nifty_symbols = df[symbol_col].dropna().unique().tolist()

    # For testing: simulate=True, kite=None
    ltp_data_df = load_or_fetch_ltp_data(nifty_symbols, simulate=True)

    filtered_df = ltp_data_df[ltp_data_df['pct_change'] > 0]
    top50_df = filtered_df.sort_values(by='volume', ascending=False).head(50)

    print("\n📈 Top 50 active gainers:")
    print(top50_df[['symbol', 'pct_change', 'volume']])
