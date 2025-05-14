import os
import pandas as pd
from kiteconnect import KiteConnect
from datetime import datetime, timedelta
from config.keys import get_api_key, get_api_secret

# === Config ===
API_KEY = get_api_key()
ACCESS_TOKEN_PATH = "access_token.txt"
NIFTY_200_CSV = "ind_nifty200list.csv"
DATA_DIR = "./data"
os.makedirs(DATA_DIR, exist_ok=True)

START_DATE = (datetime.today() - timedelta(days=5 * 365)).date()
END_DATE = datetime.today().date()

# === Start ===
print("🔧 Starting Kite Download Script...")
print("📅 Date range:", START_DATE, "to", END_DATE)
print("🔑 Using API Key:", API_KEY)

# === Load access token ===
with open(ACCESS_TOKEN_PATH) as f:
    access_token = f.read().strip()

print("🧾 Access Token Loaded:", access_token)

# === Init Kite Connect ===
kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(access_token)

# === Validate token ===
try:
    profile = kite.profile()
    print(f"✅ Token is valid. Logged in as: {profile['user_name']} ({profile['user_id']})")
except Exception as e:
    print("❌ Token validation failed:", e)
    exit()

# === Load ticker list ===
tickers = pd.read_csv(NIFTY_200_CSV)["Symbol"].str.upper().tolist()

# === Get instrument tokens ===
print("🔍 Fetching instrument list from NSE...")
instruments_df = pd.DataFrame(kite.instruments("NSE"))
instruments_df = instruments_df[instruments_df["tradingsymbol"].isin(tickers)]
symbol_token_map = instruments_df.set_index("tradingsymbol")["instrument_token"].to_dict()
print(f"🎯 Found {len(symbol_token_map)} tokens out of {len(tickers)} symbols.")

# === Download and update CSVs ===
for symbol in tickers:
    print(f"\n📊 Processing: {symbol}")
    if symbol not in symbol_token_map:
        print(f"⚠️  {symbol}: Instrument token not found. Skipping.")
        continue

    token = symbol_token_map[symbol]
    file_path = os.path.join(DATA_DIR, f"{symbol}.csv")

    # Determine start date
    if os.path.exists(file_path):
        df_existing = pd.read_csv(file_path, parse_dates=["date"])
        last_date = df_existing["date"].max().date()
        start = last_date + timedelta(days=1)
        print(f"📁 Existing file found. Last date: {last_date}. Start from: {start}")
    else:
        df_existing = pd.DataFrame()
        start = START_DATE
        print(f"📁 No existing file. Start from: {start}")

    if start > END_DATE:
        print(f"✅ {symbol}: Already up to date.")
        continue

    # Download in 100-day chunks
    df_all = []
    temp_start = start
    while temp_start <= END_DATE:
        temp_end = min(temp_start + timedelta(days=99), END_DATE)
        print(f"  ⏳ Fetching from {temp_start} to {temp_end}...")
        try:
            data = kite.historical_data(token, temp_start, temp_end, interval="day")
            df = pd.DataFrame(data)
            df_all.append(df)
        except Exception as e:
            print(f"  ❌ Error between {temp_start} - {temp_end}: {e}")
        temp_start = temp_end + timedelta(days=1)

    # Save if data fetched
    if df_all:
        df_new = pd.concat(df_all)
        if not df_new.empty:
            df_new["date"] = pd.to_datetime(df_new["date"])
            df_combined = pd.concat([df_existing, df_new]).drop_duplicates(subset="date").sort_values("date")
            df_combined.to_csv(file_path, index=False)
            print(f"✅ {symbol}: Data updated to {df_combined['date'].max().date()}")
        else:
            print(f"⚠️ {symbol}: No new data downloaded.")
    else:
        print(f"⚠️ {symbol}: No data chunks downloaded.")
