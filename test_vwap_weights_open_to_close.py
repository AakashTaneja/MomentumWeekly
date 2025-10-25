"""
Backtest VWAP-weighted momentum scoring using open→close returns.
For each of the last 10 trading days:
 - Compute score = (momentum_weight * %change) + (vwap_weight * VWAP distance %)
 - Rank stocks by score at close
 - Measure how top 5 performed from open→close
"""

import datetime as dt
import pandas as pd
from kiteconnect import KiteConnect
from config.keys import get_api_key
import time
from live_scanner import get_token

# === Config ===
ACCESS_TOKEN_PATH = "access_token.txt"
CSV_SYMBOL_FILE = "nse_all_tickers.csv"
MAX_TRADES = 5
NUM_DAYS = 10
BATCH_SIZE = 50
INTERVAL = "5minute"

# === Setup Kite ===
API_KEY = get_api_key()
with open(ACCESS_TOKEN_PATH) as f:
    ACCESS_TOKEN = f.read().strip()

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# === Load symbols ===
symbols_df = pd.read_csv(CSV_SYMBOL_FILE)
symbols = symbols_df["tradingsymbol"].dropna().unique().tolist()[:BATCH_SIZE]

# === Weight pairs to test ===
weight_combos = [(0.9, 0.1), (0.7, 0.3), (0.5, 0.5), (0.3, 0.7)]

# === Helper: get past N weekdays ===
def get_last_n_trading_days(n):
    days = []
    today = dt.date.today()
    d = today - dt.timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:  # Mon-Fri
            days.append(d)
        d -= dt.timedelta(days=1)
    return list(reversed(days))

# === Helper: VWAP calc ===
def calculate_vwap(df):
    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
    df["cum_vol_x_price"] = (df["typical_price"] * df["volume"]).cumsum()
    df["cum_vol"] = df["volume"].cumsum()
    df["vwap"] = df["cum_vol_x_price"] / df["cum_vol"]
    return df

# === Main loop ===
trading_days = get_last_n_trading_days(NUM_DAYS)
results_all_days = []

print(f"Testing {len(weight_combos)} weight pairs on {len(symbols)} symbols over {len(trading_days)} trading days...\n")

for date in trading_days:
    print(f"\n📅 {date} results:")
    day_summary = []

    # Fetch data for all stocks once
    stock_data = []
    for symbol in symbols:
        try:
            token = get_token(symbol)
            candles = kite.historical_data(
                token,
                dt.datetime.combine(date, dt.time(9, 15)),
                dt.datetime.combine(date, dt.time(15, 30)),
                interval=INTERVAL,
                continuous=False
            )
            if len(candles) < 5:
                continue
            df = pd.DataFrame(candles)
            df = calculate_vwap(df)

            open_price = df["open"].iloc[0]
            close_price = df["close"].iloc[-1]
            vwap = df["vwap"].iloc[-1]

            pct_change = ((close_price - open_price) / open_price) * 100
            vwap_dist = ((close_price - vwap) / vwap * 100)

            stock_data.append({
                "symbol": symbol,
                "pct_change": pct_change,
                "vwap_dist": vwap_dist,
                "open": open_price,
                "close": close_price
            })
        except Exception:
            continue
        time.sleep(0.05)

    if not stock_data:
        continue
    df_day = pd.DataFrame(stock_data)

    # Test all weight pairs
    for mw, vw in weight_combos:
        df_day["score"] = (mw * df_day["pct_change"]) + (vw * df_day["vwap_dist"])
        top5 = df_day.sort_values("score", ascending=False).head(MAX_TRADES)
        avg_return = top5["pct_change"].mean()  # open→close return
        day_summary.append({
            "date": date,
            "momentum_weight": mw,
            "vwap_weight": vw,
            "avg_return_%": round(avg_return, 3)
        })

    day_result_df = pd.DataFrame(day_summary).sort_values("avg_return_%", ascending=False)
    results_all_days.extend(day_summary)
    print(day_result_df.to_string(index=False))

# === Final summary ===
summary_df = pd.DataFrame(results_all_days)
summary_grouped = (
    summary_df.groupby(["momentum_weight", "vwap_weight"])["avg_return_%"]
    .mean()
    .reset_index()
    .sort_values("avg_return_%", ascending=False)
)

print("\n\n=== 📊 10-Day Average Return Summary (Top 5 Picks) ===")
print(summary_grouped.to_string(index=False))
