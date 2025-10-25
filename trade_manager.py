import time
import pandas as pd
import os
from load_live_data import load_or_fetch_ltp_data
from live_scanner import fetch_live_data, get_token, get_10day_avg_volume
from kiteconnect import KiteConnect, exceptions as kite_exceptions
from config.keys import get_api_key
import datetime as dt

# === Configurable Parameters ===
MIN_PCT_CHANGE = 1.0
VOLUME_MULTIPLIER = 1.5
STOP_LOSS_PCT = 1.0
EXIT_VOLUME_DROP_MULTIPLIER = 1
AVG_VOLUME_LOOKBACK_DAYS = 10
SCAN_INTERVAL_SECONDS = 90
MAX_TRADES = 5
CAPITAL_PER_TRADE = 20000
TOTAL_CAPITAL = MAX_TRADES * CAPITAL_PER_TRADE
CSV_SYMBOL_FILE = "ind_nifty200list.csv"
#CSV_SYMBOL_FILE = os.path.join( "data", "tickers", "nse_all_tickers.csv")

ACCESS_TOKEN_PATH = "access_token.txt"
CONSIDER_LIVE_TRADES = False  # consider previous trades

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
    exit()

# === VWAP Calculation ===
def calculate_intraday_vwap(kite, instrument_token):
    from_date = dt.datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
    to_date = dt.datetime.now()
    try:
        candles = kite.historical_data(
            instrument_token,
            from_date,
            to_date,
            interval="minute",
            continuous=False
        )
        total_volume = 0
        total_vwap = 0
        for candle in candles:
            high = candle['high']
            low = candle['low']
            close = candle['close']
            volume = candle['volume']
            typical_price = (high + low + close) / 3
            total_vwap += typical_price * volume
            total_volume += volume
        if total_volume == 0:
            return None
        return total_vwap / total_volume
    except Exception as e:
        print(f"⚠️ VWAP calc error for token {instrument_token}: {e}")
        return None

# === Logging Setup ===
start_time = dt.datetime.now()
log_filename = f"logs/trading_{start_time.strftime('%Y%m%d_%H%M%S')}.txt"
os.makedirs("logs", exist_ok=True)
log_file = open(log_filename, "w", encoding="utf-8")

# === Load Universe ===
symbols_df = pd.read_csv(CSV_SYMBOL_FILE)
symbols = symbols_df["Symbol"].dropna().unique().tolist()

# === Active Trades Tracker ===
active_trades = {}
realized_trades = []

# === Print Strategy Info ===
print("\n📋 Strategy Parameters:")
print(f"🟢 Entry: pct_change > {MIN_PCT_CHANGE} and volume > {VOLUME_MULTIPLIER}x 10-day avg and price > VWAP")
print(f"🔴 Exit: price <= {STOP_LOSS_PCT}% stop loss")
print(f"🔻 Exit: volume < {EXIT_VOLUME_DROP_MULTIPLIER}x 10-day avg or price < VWAP")
print(f"🟡 Holding: if no exit condition met")

log_file.write("\n📋 Strategy Parameters:\n")
log_file.write(f"🟢 Entry: pct_change > {MIN_PCT_CHANGE} and volume > {VOLUME_MULTIPLIER}x 10-day avg and price > VWAP\n")
log_file.write(f"🔴 Exit: price <= {STOP_LOSS_PCT}% stop loss\n")
log_file.write(f"🔻 Exit: volume < {EXIT_VOLUME_DROP_MULTIPLIER}x 10-day avg or price < VWAP\n")
log_file.write(f"🟡 Holding: if no exit condition met\n")

# 👇 Continue with your full loop and logic after this section

print("\n🚀 Starting trade manager...")
log_file.write("🚀 Starting trade manager...\n")

try:
    while True:
        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{now}] Scanning for new trades and monitoring active positions...")
        log_file.write(f"\n[{now}] Scanning for new trades and monitoring active positions...\n")

        ltp_data_df = load_or_fetch_ltp_data(symbols, kite=kite, simulate=False)

        candidates = []
        for _, row in ltp_data_df.iterrows():
            pct = row['pct_change']
            log_file.write(f"🔍 {row['symbol']} | Open: {row['open']} | Last: {row['last_price']} | % Change: {pct:.2f}\n")

            if pct > MIN_PCT_CHANGE:
                token = get_token(row['symbol'])
                try:
                    avg_volume = get_10day_avg_volume(kite, token, lookback_days=AVG_VOLUME_LOOKBACK_DAYS)
                except kite_exceptions.KiteException as e:
                    print("⚠️  Cannot fetch historical volume data.")
                    print(f"   - Error: {str(e)}")
                    log_file.write(f"⚠️  Skipping {row['symbol']}: {str(e)}\n")
                    continue

                ratio = row['volume'] / avg_volume if avg_volume > 0 else 0

                if row['volume'] > VOLUME_MULTIPLIER * avg_volume:
                    candidates.append({
                        'symbol': row['symbol'],
                        'entry_price': row['last_price'],
                        'open': row['open'],
                        'volume': row['volume'],
                        'token': token,
                        'entry_time': now,
                        'avg_volume': avg_volume,
                        'pct_change': pct
                    })

        # === ENTER TRADES ===
        if len(active_trades) < MAX_TRADES:
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
                        'avg_volume': c['avg_volume'],
                        'pct_change': c['pct_change']
                    }
                    entry_msg = f"🟢 Entry: {c['symbol']} at ₹{c['entry_price']} x {qty} shares | Volume: {c['volume']} > Avg: {c['avg_volume']} | Ratio: {c['volume']/c['avg_volume']:.2f} (over {AVG_VOLUME_LOOKBACK_DAYS} days) | % Change: {c['pct_change']:.2f}"
                    print(entry_msg)
                    log_file.write(entry_msg + "\n")
        else:
            print("⚠️  MAX_TRADES reached. Skipping new entries.")
            log_file.write("⚠️  MAX_TRADES reached. Skipping new entries.\n")

        # === EXIT & HOLD LOGIC ===
        to_exit = []
        if active_trades:
            try:
                ltp_map = kite.ltp(["NSE:" + s for s in active_trades.keys()])
            except kite_exceptions.KiteException as e:
                print("⚠️  Could not fetch LTP for active trades.")
                log_file.write(f"⚠️  Failed to fetch LTP: {str(e)}\n")
                break

            for symbol, trade in active_trades.items():
                ltp_key = "NSE:" + symbol
                if ltp_key not in ltp_map:
                    print(f"⚠️  LTP not found for {symbol}, skipping...")
                    log_file.write(f"⚠️  LTP not found for {symbol}, skipping...\n")
                    continue

                last_price = ltp_map[ltp_key]['last_price']
                stop_price = trade['entry_price'] * (1 - STOP_LOSS_PCT / 100)

                try:
                    avg_volume = trade['avg_volume']
                    current_volume = ltp_data_df.loc[ltp_data_df['symbol'] == symbol, 'volume'].values[0]
                except (KeyError, IndexError):
                    current_volume = avg_volume

                if last_price <= stop_price:
                    exit_msg = f"🔴 Stop Loss Hit: {symbol} exited at ₹{last_price} | Entry: ₹{trade['entry_price']}"
                    print(exit_msg)
                    log_file.write(exit_msg + "\n")
                    to_exit.append(symbol)
                elif current_volume < avg_volume * EXIT_VOLUME_DROP_MULTIPLIER:
                    exit_msg = f"🔻 Volume Drop Exit: {symbol} exited at ₹{last_price} | Volume: {current_volume} < {EXIT_VOLUME_DROP_MULTIPLIER} x {avg_volume}"
                    print(exit_msg)
                    log_file.write(exit_msg + "\n")
                    to_exit.append(symbol)
                else:
                    exit_volume_threshold = avg_volume * EXIT_VOLUME_DROP_MULTIPLIER
                    comparison = '<' if current_volume < exit_volume_threshold else '>'

                    hold_msg = (
                        f"🟡 Holding: {symbol} | Entry: ₹{trade['entry_price']} | LTP: ₹{last_price} | SL: ₹{stop_price:.2f} | "
                        f"Qty: {trade['qty']} | Volume: {current_volume} {comparison} ExitVol: {exit_volume_threshold:.0f}"
                    )
                    print(hold_msg)
                    log_file.write(hold_msg + "\n")

        for symbol in to_exit:
            trade = active_trades[symbol]
            exit_price = ltp_map.get("NSE:" + symbol, {}).get('last_price', trade['entry_price'])
            realized_trades.append({
                'symbol': symbol,
                'entry_price': trade['entry_price'],
                'exit_price': exit_price,
                'qty': trade['qty'],
                'pnl': (exit_price - trade['entry_price']) * trade['qty']
            })
            del active_trades[symbol]

        # === P&L Summary ===
        if active_trades:
            try:
                ltp_map = kite.ltp(["NSE:" + s for s in active_trades.keys()])
                total_pnl = 0
                print("\n💰 P&L Summary:")
                log_file.write("\n💰 P&L Summary:\n")
                for symbol, trade in active_trades.items():
                    ltp_key = "NSE:" + symbol
                    if ltp_key in ltp_map:
                        current_price = ltp_map[ltp_key]['last_price']
                        pnl = (current_price - trade['entry_price']) * trade['qty']
                        total_pnl += pnl
                        pnl_msg = (
                            f"   {symbol}: Qty={trade['qty']} | Entry=₹{trade['entry_price']:.2f} "
                            f"| LTP=₹{current_price:.2f} | P&L=₹{pnl:.2f}"
                        )
                        print(pnl_msg)
                        log_file.write(pnl_msg + "\n")
                capital_in_use = len(active_trades) * CAPITAL_PER_TRADE
                pnl_pct = (total_pnl / capital_in_use) * 100 if capital_in_use > 0 else 0
                print(f"   🔄 Total Unrealized P&L: ₹{total_pnl:.2f} ({pnl_pct:.2f}%)")
                log_file.write(f"   🔄 Total Unrealized P&L: ₹{total_pnl:.2f} ({pnl_pct:.2f}%)\n")

                # === Realized P&L So Far ===
                if realized_trades:
                    total_realized = sum(t['pnl'] for t in realized_trades)
                    print(f"💰 Total Realized P&L so far: ₹{total_realized:.2f}")
                    log_file.write(f"💰 Total Realized P&L so far: ₹{total_realized:.2f}\n")

                    net_pnl = total_pnl + total_realized
                    net_pct = (net_pnl / TOTAL_CAPITAL) * 100 if TOTAL_CAPITAL > 0 else 0
                    print(f"🧾 Net P&L (Realized + Unrealized): ₹{net_pnl:.2f} ({net_pct:.2f}%)")
                    log_file.write(f"🧾 Net P&L (Realized + Unrealized): ₹{net_pnl:.2f} ({net_pct:.2f}%)\n")

            except kite_exceptions.KiteException as e:
                print("⚠️  Could not fetch LTP for P&L Summary.")
                log_file.write(f"⚠️  Failed to fetch P&L LTP: {str(e)}\n")

        status_msg = f"📝 Active Trades: {len(active_trades)} | Capital in Use: ₹{len(active_trades) * CAPITAL_PER_TRADE}"
        print(status_msg)
        log_file.write(status_msg + "\n")
        log_file.flush()

        for remaining in range(SCAN_INTERVAL_SECONDS, 0, -1):
            print(f"\r⏳ Re-scanning in {remaining} seconds...", end="", flush=True)
            time.sleep(1)
        print()

except KeyboardInterrupt:
    print("\n🛑 Script manually stopped. Printing final realized P&L...\n")
    log_file.write("\n🛑 Script manually stopped. Printing final realized P&L...\n")

    total_realized = 0
    for trade in realized_trades:
        msg = (
            f"   {trade['symbol']}: Qty={trade['qty']} | Entry=₹{trade['entry_price']:.2f} "
            f"| Exit=₹{trade['exit_price']:.2f} | P&L=₹{trade['pnl']:.2f}"
        )
        print(msg)
        log_file.write(msg + "\n")
        total_realized += trade['pnl']

    print(f"💰 Total Realized P&L: ₹{total_realized:.2f}")
    log_file.write(f"💰 Total Realized P&L: ₹{total_realized:.2f}\n")
    log_file.close()
