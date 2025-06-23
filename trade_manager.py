import time
import pandas as pd
import os
from load_live_data import load_or_fetch_ltp_data
from live_scanner import fetch_live_data, get_token, get_10day_avg_volume
from kiteconnect import KiteConnect, exceptions as kite_exceptions
from config.keys import get_api_key
import datetime as dt

# === Configurable Parameters ===
MIN_PCT_CHANGE = 2.0
VOLUME_MULTIPLIER = 1.0
STOP_LOSS_PCT = 1.0
EXIT_VOLUME_DROP_MULTIPLIER = 0.5  # Exit if volume drops below this multiple of avg
# Example: if avg_volume = 1,000,000 → exit if live volume < 500,000
AVG_VOLUME_LOOKBACK_DAYS = 10       # Number of days to calculate avg daily volume
SCAN_INTERVAL_SECONDS = 300  # Every 5 minutes
MAX_TRADES = 5
CAPITAL_PER_TRADE = 20000
TOTAL_CAPITAL = MAX_TRADES * CAPITAL_PER_TRADE
CSV_SYMBOL_FILE = "ind_nifty200list.csv"
ACCESS_TOKEN_PATH = "access_token.txt"

# === Setup Kite ===
API_KEY = get_api_key()
with open(ACCESS_TOKEN_PATH) as f:
    ACCESS_TOKEN = f.read().strip()

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# === Logging Setup ===
start_time = dt.datetime.now()
log_filename = f"logs/trading_{start_time.strftime('%Y%m%d_%H%M%S')}.txt"
os.makedirs("logs", exist_ok=True)
log_file = open(log_filename, "w")

# === Load Universe ===
symbols = pd.read_csv(CSV_SYMBOL_FILE).iloc[:, 0].dropna().unique().tolist()

# === Active Trades Tracker ===
active_trades = {}

# === Main Loop ===
print("\n🚀 Starting trade manager...")
log_file.write("🚀 Starting trade manager...\n")
while True:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{now}] Scanning for new trades and monitoring active positions...")
    log_file.write(f"\n[{now}] Scanning for new trades and monitoring active positions...\n")

    # Load or fetch data
    ltp_data_df = load_or_fetch_ltp_data(symbols)

    # === ENTRY CRITERIA ===
    # We only consider stocks that have:
    # 1. Price change from open > MIN_PCT_CHANGE (e.g. 2%)
    # 2. Current volume > VOLUME_MULTIPLIER × average 10-day volume
    candidates = []
    for _, row in ltp_data_df.iterrows():
        if row['pct_change'] > MIN_PCT_CHANGE:
            token = get_token(row['symbol'])
            try:
                avg_volume = get_10day_avg_volume(token, days=AVG_VOLUME_LOOKBACK_DAYS)
            except kite_exceptions.TokenException as e:
                print("⚠️  Cannot fetch historical volume data. Possible reasons:")
                print("   - Market is closed (no historical candle for today)")
                print("   - Invalid or expired access token")
                print(f"   - Error: {str(e)}")
                log_file.write(f"⚠️  Skipping {row['symbol']}: {str(e)}\n")
                continue

            if row['volume'] > VOLUME_MULTIPLIER * avg_volume:
                candidates.append({
                    'symbol': row['symbol'],
                    'entry_price': row['last_price'],
                    'open': row['open'],
                    'volume': row['volume'],
                    'token': token,
                    'entry_time': now,
                    'avg_volume': avg_volume
                })

    # === ENTER TRADES ===
    for c in candidates:
        if len(active_trades) >= MAX_TRADES:
            break
        if c['symbol'] not in active_trades:
            qty = max(1, int(CAPITAL_PER_TRADE / c['entry_price']))
            active_trades[c['symbol']] = {
                'entry_price': c['entry_price'],
                'qty': qty,
                'entry_time': c['entry_time'],
                'token': c['token'],
                'avg_volume': c['avg_volume']
            }
            entry_msg = f"🟢 Entry: {c['symbol']} at ₹{c['entry_price']} x {qty} shares"
            print(entry_msg)
            log_file.write(entry_msg + "\n")

    # === EXIT LOGIC ===
    # We exit if:
    # 1. Price hits STOP_LOSS_PCT (e.g. -1%)
    # 2. Volume fades below EXIT_VOLUME_DROP_MULTIPLIER × avg_volume (e.g. <50%)
    # Volume fade often suggests weakening interest/momentum.
    # Example: If entry was at ₹100 and STOP_LOSS_PCT is 1%, exit at ₹99
    # Example: If avg_volume is 1M and today's volume is <500k, exit
    to_exit = []
    if active_trades:
        try:
            ltp_map = kite.ltp(["NSE:" + s for s in active_trades.keys()])
        except kite_exceptions.TokenException as e:
            print("⚠️  Could not fetch LTP for active trades.")
            print("   - Check if access token is valid or if market is open.")
            print(f"   - Error: {str(e)}")
            log_file.write(f"⚠️  Failed to fetch LTP: {str(e)}\n")
            break

        for symbol, trade in active_trades.items():
            last_price = ltp_map["NSE:" + symbol]['last_price']
            stop_price = trade['entry_price'] * (1 - STOP_LOSS_PCT / 100)
            if last_price <= stop_price:
                exit_msg = f"🔴 Stop Loss Hit: {symbol} exited at ₹{last_price} | Entry: ₹{trade['entry_price']}"
                print(exit_msg)
                log_file.write(exit_msg + "\n")
                to_exit.append(symbol)
            # Volume fade condition based on real-time volume vs avg
            elif trade['avg_volume'] > 0 and row['volume'] < EXIT_VOLUME_DROP_MULTIPLIER * trade['avg_volume']:
                exit_msg = f"🔁 Volume fade exit: {symbol} at ₹{last_price}"
                print(exit_msg)
                log_file.write(exit_msg + "\n")
                to_exit.append(symbol)

    for symbol in to_exit:
        del active_trades[symbol]

    status_msg = f"📝 Active Trades: {len(active_trades)} | Capital in Use: ₹{len(active_trades) * CAPITAL_PER_TRADE}"
    print(status_msg)
    log_file.write(status_msg + "\n")
    log_file.flush()
    time.sleep(SCAN_INTERVAL_SECONDS)
