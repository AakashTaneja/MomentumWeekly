import os
from datetime import datetime

LOG_DIR = "./logs"
os.makedirs(LOG_DIR, exist_ok=True)

def get_log_filename():
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return os.path.join(LOG_DIR, f"weekly_log_{timestamp}.txt")

def log_run(weights_record, daily_data, returns_series):
    log_file = get_log_filename()
    starting_value = 100.0
    portfolio_value = starting_value

    with open(log_file, "w") as f:
        f.write("📊 Weekly Momentum Strategy Log\n")
        f.write(f"Run Timestamp: {datetime.now()}\n\n")

        for i in range(len(weights_record)):
            curr = weights_record[i]
            prev = weights_record[i - 1] if i > 0 else None

            if curr is None:
                f.write(f"💤 Week {i + 1}: No positions (cash week)\n\n")
                continue

            # === Portfolio change summary ===
            week_date = returns_series.index[i]
            f.write(f"📅 Week {i + 1} | Signal Date: {week_date.date()}\n")

            all_symbols = set()
            if prev is not None:
                all_symbols.update(prev.index)
            all_symbols.update(curr.index)
            all_symbols = sorted(list(all_symbols))

            f.write(f"{'Symbol':<10} {'PrevWt':>8} {'NowWt':>8} {'Price':>10}  Change\n")
            f.write("-" * 46 + "\n")

            price_date = daily_data.index.asof(week_date)
            prices = daily_data.loc[price_date, all_symbols]

            for sym in all_symbols:
                prev_wt = prev[sym] if prev is not None and sym in prev else 0.0
                curr_wt = curr[sym] if sym in curr else 0.0
                price = prices.get(sym, 'N/A')

                if prev_wt == 0 and curr_wt > 0:
                    status = "🆕 New"
                elif curr_wt == 0 and prev_wt > 0:
                    status = "❌ Exited"
                elif curr_wt > prev_wt:
                    status = "⬆️ Increased"
                elif curr_wt < prev_wt:
                    status = "⬇️ Decreased"
                else:
                    status = "⏸ No change"

                f.write(f"{sym:<10} {prev_wt:>7.2%} {curr_wt:>7.2%} {price:>10}  {status}\n")
            f.write("\n")

            # === Track portfolio value using actual return from backtest ===
            if i < len(returns_series):
                weekly_return = returns_series.iloc[i]
                portfolio_value *= (1 + weekly_return)
                pct_change = portfolio_value - starting_value
                f.write(f"💰 Portfolio Value: {portfolio_value:.2f} ({pct_change:+.2f}%)\n\n")

        f.write("✅ Log complete.\n")
