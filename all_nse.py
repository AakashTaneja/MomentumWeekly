from kiteconnect import KiteConnect
from config.keys import get_api_key
import os
import pandas as pd

# === Config ===
API_KEY = get_api_key()
ACCESS_TOKEN_PATH = "access_token.txt"

# === Load access token ===
with open(ACCESS_TOKEN_PATH) as f:
    ACCESS_TOKEN = f.read().strip()

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# Fetch all instruments
instruments = kite.instruments("NSE")  # restrict directly to NSE
df = pd.DataFrame(instruments)

# Filter to likely equities (exclude bonds/SDLs/ETFs/REITs/InvITs)
df_equities = df[
    (df["instrument_type"] == "EQ") &
    (df["lot_size"] == 1) &
    (~df["tradingsymbol"].str.contains("-", na=False)) &
    (~df["name"].str.startswith(("SDL", "GS"), na=False)) &
    (~df["name"].str.contains("ETF|REIT|InvIT", na=False))
    ]

# Keep only required columns
df_out = df_equities[["name", "tradingsymbol"]].sort_values("tradingsymbol")

# Ensure ./data folder exists
os.makedirs("data", exist_ok=True)

# Save to CSV
output_path = "nse_all_tickers.csv"
df_out.to_csv(output_path, index=False)

print(f"Saved {len(df_out)} NSE tickers to {output_path}")
#print(df_out.head(10))
