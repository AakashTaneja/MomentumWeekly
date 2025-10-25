# === trade_manager_all_nse.py ===
import os
import time
import json
import pandas as pd
import datetime as dt
from pathlib import Path
from live_scanner import get_token
from kiteconnect import KiteConnect, exceptions as kite_exceptions
from config.keys import get_api_key
import sys

sys.stdout.reconfigure(encoding='utf-8')

# === Configurable Parameters ===
MIN_PCT_CHANGE = 2.0
STOP_LOSS_PCT = 1.0
SCAN_INTERVAL_SECONDS = 30
MAX_TRADES = 5
CAPITAL_PER_TRADE = 20000
TOTAL_CAPITAL = MAX_TRADES * CAPITAL_PER_TRADE

# === VWAP Reliability by Liquidity (Reference Guide) ===
#
# Bucket | Volume Range        | Label        | Expected VWAP Reliability
# -------|---------------------|--------------|---------------------------
# 1      | < 50000             | Very Low     | ❌ Unreliable — skip; VWAP too noisy
# 2      | 50000–200000        | Moderate     | ⚠️ Mixed — usable only if price trend is smooth
# 3      | 200000–1000000      | High         | ✅ Reliable — good VWAP stability
# 4      | > 1000000           | Very High    | 💯 Ideal — institutional flow; VWAP most dependable
#
# Tip:
# if volume < 50000:        → skip  (unreliable VWAP)
# elif volume < 200000:     → moderate confidence
# elif volume < 1000000:    → reliable
# else:                     → ideal (most trustworthy)

MIN_VOLUME_THRESHOLD = 1000000  # skip low-volume stocks; VWAP unreliable below this

# download from https://www.nseindia.com/products-services/indices-nifty-total-market-index
CSV_SYMBOL_FILE = "nse_all_tickers.csv"
ACCESS_TOKEN_PATH = "access_token.txt"
VWAP_TREND_LOOKBACK_MIN = 15  # minutes to confirm VWAP rising

# === VWAP CACHE SYSTEM ===
vwap_cache = {}          # token -> {"timestamp": dt.datetime, "vwap_now": float|None, "vwap_prev": float|None}
VWAP_CACHE_TTL = 180     # seconds to reuse cached VWAP (3 minutes)

# === Setup Kite ===
API_KEY = get_api_key()
with open(ACCESS_TOKEN_PATH) as f:
    ACCESS_TOKEN = f.read().strip()

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

try:
    user_profile = kite.profile()
    print(f"✅ Token is valid. Logged in as: {user_profile['user_name']}")
except kite_exceptions.TokenException:
    print("❌ Invalid or expired access token. Please refresh using your token generator.")
    sys.exit(1)

# === VWAP helpers ===
def calculate_intraday_vwap_pair(kite, instrument_token, lookback_minutes=VWAP_TREND_LOOKBACK_MIN):
    """
    Returns (vwap_now, vwap_prev_15m).
    - vwap_now: VWAP from 09:15 up to 'now'
    - vwap_prev_15m: VWAP from 09:15 up to ('now' - lookback), or None if insufficient data

    Uses a small in-memory cache so we don't hammer historical_data every scan.
    Cache TTL is controlled by VWAP_CACHE_TTL (seconds).
    """
    now_time = dt.datetime.now()

    # --- Serve from cache if fresh ---
    cached = vwap_cache.get(instrument_token)
    if cached:
        age = (now_time - cached["timestamp"]).total_seconds()
        if age < VWAP_CACHE_TTL:
            return cached["vwap_now"], cached["vwap_prev"]

    from_date = now_time.replace(hour=9, minute=15, second=0, microsecond=0)
    to_date = now_time
    cutoff = to_date - dt.timedelta(minutes=lookback_minutes)

    try:
        candles = kite.historical_data(
            instrument_token, from_date, to_date, interval="minute", continuous=False
        )
        if not candles:
            vwap_cache[instrument_token] = {"timestamp": now_time, "vwap_now": None, "vwap_prev": None}
            return None, None

        # --- Convert timestamps to naive (remove tzinfo) ---
        for c in candles:
            if c['date'].tzinfo is not None:
                c['date'] = c['date'].replace(tzinfo=None)

        total_vol = 0
        total_tpvol = 0.0
        prev_total_vol = 0
        prev_total_tpvol = 0.0

        for c in candles:
            tp = (c['high'] + c['low'] + c['close']) / 3.0
            v = c['volume'] or 0
            total_tpvol += tp * v
            total_vol += v
            if c['date'] <= cutoff:
                prev_total_tpvol = total_tpvol
                prev_total_vol = total_vol

        vwap_now = (total_tpvol / total_vol) if total_vol else None
        vwap_prev = (prev_total_tpvol / prev_total_vol) if prev_total_vol else None

        vwap_cache[instrument_token] = {
            "timestamp": now_time,
            "vwap_now": vwap_now,
            "vwap_prev": vwap_prev
        }
        return vwap_now, vwap_prev

    except Exception as e:
        print(f"⚠️ VWAP calc error for token {instrument_token}: {e}")
        vwap_cache[instrument_token] = {"timestamp": now_time, "vwap_now": None, "vwap_prev": None}
        return None, None


# === Logging Setup ===
today_str = dt.datetime.now().strftime('%Y%m%d')
log_base = Path("logs/trade_manager_all_nse")
log_dir = log_base / today_str
log_dir.mkdir(parents=True, exist_ok=True)

log_file_path = log_dir / "run_log.txt"
json_path = log_dir / "active_trades.json"
csv_path = log_dir / "realized_trades.csv"
log_file = open(log_file_path, "a", encoding="utf-8")

# === Load Universe ===
symbols_df = pd.read_csv(CSV_SYMBOL_FILE)
symbols = symbols_df["tradingsymbol"].dropna().unique().tolist()

# === Resume From JSON ===
active_trades = {}
if json_path.exists():
    try:
        with open(json_path, "r") as f:
            raw = json.load(f)
            active_trades = {k: v for k, v in raw.items()}
            print(f"🔄 Resumed {len(active_trades)} active trades from file.")
    except Exception as e:
        print(f"⚠️ Could not resume active_trades.json: {e}")

# === Resume Realized ===
realized_trades = []
if csv_path.exists():
    try:
        realized_trades = pd.read_csv(csv_path).to_dict(orient="records")
        print(f"🔄 Loaded {len(realized_trades)} realized trades from file.")
    except Exception as e:
        print(f"⚠️ Could not load realized_trades.csv: {e}")

# === Strategy Info ===
print("\nStrategy Parameters:")
print(f"🟢 Entry: pct_change > {MIN_PCT_CHANGE}%, price > VWAP, VWAP rising over last {VWAP_TREND_LOOKBACK_MIN}m, and volume ≥ {MIN_VOLUME_THRESHOLD}")
print(f"🔴 Exit: stop loss or (price < VWAP and VWAP turning down over last {VWAP_TREND_LOOKBACK_MIN}m)")
print(f"🟡 Holding: if no exit condition met\n")

log_file.write("\nStrategy Parameters:\n")
log_file.write(f"🟢 Entry: pct_change > {MIN_PCT_CHANGE}%, price > VWAP, VWAP rising over last {VWAP_TREND_LOOKBACK_MIN}m, and volume ≥ {MIN_VOLUME_THRESHOLD}\n")
log_file.write(f"🔴 Exit: stop loss or (price < VWAP and VWAP turning down over last {VWAP_TREND_LOOKBACK_MIN}m)\n")
log_file.write(f"🟡 Holding: if no exit condition met\n\n")

print("Starting VWAP-based trade manager...")

# === Batch Fetch ===
def fetch_ltp_data_batched(symbols, kite, batch_size=200):
    all_data = []
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        try:
            quote_data = kite.quote(["NSE:" + s for s in batch])
            for sym in batch:
                full_key = "NSE:" + sym
                item = quote_data.get(full_key)
                if not item:
                    continue
                open_price = item["ohlc"]["open"]
                last_price = item["last_price"]
                volume = item.get("volume", 0)
                pct_change = ((last_price - open_price) / open_price * 100) if open_price else 0.0
                all_data.append({
                    "symbol": sym,
                    "open": open_price,
                    "last_price": last_price,
                    "volume": volume,
                    "pct_change": pct_change
                })
        except Exception as e:
            print(f"⚠️ Batch error: {e}")
        time.sleep(0.4)
    return pd.DataFrame(all_data)

# === Save ===
def save_trade_data():
    with open(json_path, "w") as f:
        json.dump(active_trades, f, indent=2, default=str)
    pd.DataFrame(realized_trades).to_csv(csv_path, index=False)

# === MAIN LOOP ===
try:
    while True:
        now_dt = dt.datetime.now()
        now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{now}] Scanning...")
        log_file.write(f"\n[{now}] Scanning...\n")

        if len(active_trades) >= MAX_TRADES:
            print("⚠️ MAX_TRADES reached. Skipping new entries.")
        else:
            ltp_data_df = fetch_ltp_data_batched(symbols, kite)
            potential_trades = []
            for _, row in ltp_data_df.iterrows():
                # Step 1: momentum first
                if row['pct_change'] <= MIN_PCT_CHANGE or row['symbol'] in active_trades:
                    continue

                # Step 2: volume threshold (log skip)
                if row['volume'] < MIN_VOLUME_THRESHOLD:
                    msg = f"⏩ Skipping {row['symbol']} (volume={row['volume']}) — VWAP unreliable below {MIN_VOLUME_THRESHOLD}"
                    print(msg)
                    log_file.write(msg + "\n")
                    continue

                # Step 3: VWAP validation (+ trend)
                token = get_token(row['symbol'])
                vwap_now, vwap_prev = calculate_intraday_vwap_pair(kite, token, VWAP_TREND_LOOKBACK_MIN)

                if vwap_now and row['last_price'] > vwap_now:
                    vwap_trend_ok = (vwap_prev is None) or (vwap_now > vwap_prev)
                    if not vwap_trend_ok:
                        continue

                    score = (0.8 * row['pct_change']) + (0.2 * ((row['last_price'] - vwap_now) / vwap_now * 100))
                    potential_trades.append({
                        'symbol': row['symbol'],
                        'last_price': row['last_price'],
                        'pct_change': row['pct_change'],
                        'vwap': vwap_now,
                        'vwap_prev_15m': vwap_prev,
                        'score': score,
                        'token': token,
                        'volume': row['volume']
                    })

            ranked = sorted(potential_trades, key=lambda x: x['score'], reverse=True)
            slots = MAX_TRADES - len(active_trades)
            for trade in ranked[:slots]:
                qty = max(1, int(CAPITAL_PER_TRADE / trade['last_price']))
                active_trades[trade['symbol']] = {
                    'entry_price': float(trade['last_price']),
                    'qty': int(qty),
                    'entry_time': now,
                    'token': trade['token']
                }
                vwap_prev_disp = f"{trade['vwap_prev_15m']:.2f}" if trade['vwap_prev_15m'] else "NA"
                msg = (
                    f"🟢 Entry: {trade['symbol']} | Price ₹{trade['last_price']:.2f} | "
                    f"VWAP ₹{trade['vwap']:.2f} | VWAP-{VWAP_TREND_LOOKBACK_MIN}m {vwap_prev_disp} | "
                    f"%Chg {trade['pct_change']:.2f}% | Volume {trade['volume']} "
                    f"(≥ {MIN_VOLUME_THRESHOLD}) | Score {trade['score']:.2f}"
                )
                print(msg)
                log_file.write(msg + "\n")

        # === EXIT / HOLD ===
        to_exit = []
        ltp_map = kite.ltp(["NSE:" + s for s in active_trades]) if active_trades else {}
        for symbol, trade in active_trades.items():
            ltp = ltp_map.get("NSE:" + symbol, {}).get("last_price", trade['entry_price'])
            vwap_now, vwap_prev = calculate_intraday_vwap_pair(kite, trade['token'], VWAP_TREND_LOOKBACK_MIN)
            stop_price = trade['entry_price'] * (1 - STOP_LOSS_PCT / 100)

            # EXIT: stop loss OR (price <= VWAP AND VWAP turning down or flat vs prev window)
            if (ltp <= stop_price) or (vwap_now and vwap_prev and (ltp <= vwap_now and vwap_now <= vwap_prev)):
                pnl = (ltp - trade['entry_price']) * trade['qty']
                realized_trades.append({
                    'symbol': symbol,
                    'entry_price': trade['entry_price'],
                    'exit_price': ltp,
                    'qty': trade['qty'],
                    'pnl': pnl
                })
                vwap_disp = f"{vwap_now:.2f}" if vwap_now else "0.00"
                msg = f"🔴 Exit: {symbol} | LTP ₹{ltp:.2f} | VWAP ₹{vwap_disp} | Stop ₹{stop_price:.2f} | P&L ₹{pnl:.2f}"
                print(msg)
                log_file.write(msg + "\n")
                to_exit.append(symbol)
            else:
                vwap_now_disp = f"{vwap_now:.2f}" if vwap_now else "0.00"
                vwap_prev_disp = f"{vwap_prev:.2f}" if vwap_prev else "NA"
                # Trend label
                if vwap_now and vwap_prev:
                    if vwap_now > vwap_prev:
                        trend = "⬆️ rising"
                    elif vwap_now < vwap_prev:
                        trend = "⬇️ falling"
                    else:
                        trend = "➡️ flat"
                else:
                    trend = "NA"

                msg = (
                    f"\n Holding: {symbol} | Entry ₹{trade['entry_price']:.2f} | "
                    f"LTP ₹{ltp:.2f} | VWAP ₹{vwap_now_disp} | "
                    f"VWAP-{VWAP_TREND_LOOKBACK_MIN}m ₹{vwap_prev_disp} | Trend {trend}"
                )
                print(msg)
                log_file.write(msg + "\n")

        for s in to_exit:
            active_trades.pop(s, None)

        # === P&L Summary ===
        total_unrealized = 0.0
        print("\n P&L Summary:")
        log_file.write("\n P&L Summary:\n")

        for s, t in active_trades.items():
            ltp = ltp_map.get("NSE:" + s, {}).get("last_price", t['entry_price'])
            pnl = (ltp - t['entry_price']) * t['qty']
            total_unrealized += pnl
            pct = (pnl / (t['entry_price'] * t['qty'])) * 100 if (t['entry_price'] * t['qty']) else 0.0
            msg = f"  {s}: Qty={t['qty']} | Entry ₹{t['entry_price']:.2f} | LTP ₹{ltp:.2f} | P&L ₹{pnl:.2f} ({pct:.2f}%)"
            print(msg)
            log_file.write(msg + "\n")

        total_realized = sum(t['pnl'] for t in realized_trades) if realized_trades else 0.0
        total_pnl = total_realized + total_unrealized

        pct_realized = (total_realized / TOTAL_CAPITAL) * 100
        pct_unrealized = (total_unrealized / TOTAL_CAPITAL) * 100
        pct_total = (total_pnl / TOTAL_CAPITAL) * 100

        print(f"\n🔵 Unrealized P&L: ₹{total_unrealized:.2f} ({pct_unrealized:.2f}%)")
        print(f"🔴 Realized P&L: ₹{total_realized:.2f} ({pct_realized:.2f}%)")
        print(f"🔄 Total P&L: ₹{total_pnl:.2f} ({pct_total:.2f}%)\n")

        log_file.write(f"\n🔵 Unrealized P&L: ₹{total_unrealized:.2f} ({pct_unrealized:.2f}%)\n")
        log_file.write(f"🔴 Realized P&L: ₹{total_realized:.2f} ({pct_realized:.2f}%)\n")
        log_file.write(f"🔄 Total P&L: ₹{total_pnl:.2f} ({pct_total:.2f}%)\n")

        save_trade_data()
        log_file.flush()
        for sec in range(SCAN_INTERVAL_SECONDS, 0, -1):
            print(f"\r⏳ Re-scan in {sec}s...", end="", flush=True)
            time.sleep(1)
        print()

except KeyboardInterrupt:
    print("\n❌ Interrupted. Saving state...")
    save_trade_data()
    log_file.close()
