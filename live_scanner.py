import pandas as pd
import datetime as dt
from kiteconnect import KiteConnect
import os

# === Config ===
API_KEY = "your_api_key_here"
ACCESS_TOKEN = "your_access_token_here"
CSV_SYMBOL_FILE = "ind_nifty200list.csv"
SNAPSHOT_FILE = "ltp_snapshot_last.csv"

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)
instruments_df = pd.DataFrame(kite.instruments("NSE"))

# === Entry Variables ===
MIN_PCT_CHANGE = 2.0  # Price change from open
VOLUME_MULTIPLIER = 1.0  # Must exceed 1x of 10-day avg volume

# === Exit Variables (placeholders for later expansion) ===
STOP_LOSS_PCT = 1.0  # 1% below entry
VOLUME_SPIKE_MULTIPLIER = 2.0  # Volume spike definition
PRICE_STALL_THRESHOLD = 0.2  # Price move cutoff during spike

# === Helper Functions ===
def get_token(symbol):
    row = instruments_df[instruments_df['tradingsymbol'] == symbol]
    return row['instrument_token'].values[0] if not row.empty else None

def get_10day_avg_volume(token):
    end = dt.date.today()
    start = end - dt.timedelta(days=14)
    data = kite.historical_data(token, from_date=start, to_date=end, interval="day")
    volumes = [bar['volume'] for bar in data if bar['volume'] > 0]
    return sum(volumes[-10:]) / len(volumes[-10:]) if len(volumes) >= 5 else 0

def is_market_open():
    now = dt.datetime.now()
    weekday = now.weekday()
    return weekday < 5 and dt.time(9, 15) <= now.time() <= dt.time(15, 30)

def fetch_live_data(symbols):
    full_symbols = ["NSE:" + s for s in symbols]
    ltp_data = kite.ltp(full_symbols)
    results = []

    for full_sym, data in ltp_data.items():
        try:
            symbol = full_sym.split(":")[1]
            open_price = data['ohlc']['open']
            last_price = data['last_price']
            volume = data['volume']
            pct_change = round(((last_price - open_price) / open_price) * 100, 2)
            token = get_token(symbol)
            avg_volume = get_10day_avg_volume(token)

            if pct_change > MIN_PCT_CHANGE and volume > VOLUME_MULTIPLIER * avg_volume:
                results.append({
                    'symbol': symbol,
                    'pct_change': pct_change,
                    'volume': volume,
                    'avg_volume': int(avg_volume)
                })
        except Exception as e:
            print(f"Error processing {full_sym}: {e}")

    return pd.DataFrame(results).sort_values(by='volume', ascending=False)

# === Main Logic ===
if __name__ == "__main__":
    if not os.path.exists(CSV_SYMBOL_FILE):
        raise FileNotFoundError(f"Missing symbol list: {CSV_SYMBOL_FILE}")

    symbols = pd.read_csv(CSV_SYMBOL_FILE).iloc[:, 0].dropna().unique().tolist()

    if is_market_open():
        print("\n🔄 Market open. Scanning for entry signals...")
        df_signals = fetch_live_data(symbols)
        print("\n✅ Entry Candidates:")
        print(df_signals.to_string(index=False))
    else:
        print("\n🟡 Market is closed. Please run during market hours (9:15–15:30).")
