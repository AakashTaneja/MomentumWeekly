# === log_run.py ===

import os
import pandas as pd
from datetime import datetime

LOG_DIR = "./logs"
os.makedirs(LOG_DIR, exist_ok=True)

def get_log_filename():
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return os.path.join(LOG_DIR, f"weekly_log_{timestamp}.txt")

def log_run(weights_record, daily_data, returns_series, score):
    log_file = get_log_filename()
    starting_value = 100.0
    portfolio_value = starting_value

    final_week_table = None

    with open(log_file, "w") as f:
        f.write("📊 Weekly Momentum Strategy Log\n")
        f.write(f"Run Timestamp: {datetime.now()}\n\n")

        for i in range(len(weights_record)):
            curr = weights_record[i]
            prev = weights_record[i - 1] if i > 0 else None

            if curr is None:
                f.write(f"💤 Week {i + 1}: No positions (cash week)\n\n")
                continue

            week_date = returns_series.index[i]
            f.write(f"📅 Week {i + 1} | Signal Date: {week_date.date()}\n")

            all_symbols = set()
            if prev is not None:
                all_symbols.update(prev.index)
            all_symbols.update(curr.index)
            all_symbols = sorted(list(all_symbols))

            # Header
            f.write(f"{'Symbol':<10} {'PrevWt':>8} {'NowWt':>8} {'Price':>10}  {'Change':<12} {'Score':>10}\n")
            f.write("-" * 70 + "\n")

            # Price date = closest available
            price_date = daily_data.index.asof(week_date)
            prices = daily_data.loc[price_date, all_symbols]

            # ✅ Align to last Friday’s score (3 days before rebalance Monday)
            score_date = score.index.asof(week_date - pd.Timedelta(days=3))
            all_scores = score.loc[score_date] if pd.notna(score_date) else pd.Series()

            week_rows = []

            for sym in all_symbols:
                prev_wt = prev[sym] if prev is not None and sym in prev else 0.0
                curr_wt = curr[sym] if sym in curr else 0.0
                price = prices.get(sym, 'N/A')

                # Change classification
                if prev_wt > 0 and curr_wt == 0:
                    status = "❌ Exited"
                elif prev_wt == 0 and curr_wt > 0:
                    status = "🆕 New"
                elif curr_wt > prev_wt:
                    status = "⬆️ Increased"
                elif curr_wt < prev_wt:
                    status = "⬇️ Decreased"
                else:
                    status = "⏸ No change"

                # Always pull score (not just for exits)
                score_val = all_scores.get(sym, None)

                f.write(
                    f"{sym:<10} {prev_wt:>7.2%} {curr_wt:>7.2%} {price:>10}  {status:<12} "
                    f"{score_val if score_val is not None else '-'}\n"
                )

                week_rows.append({
                    "Symbol": sym,
                    "PrevWt": f"{prev_wt:.2%}",
                    "NowWt": f"{curr_wt:.2%}",
                    "Price": f"{price:.2f}" if isinstance(price, (float, int)) else price,
                    "Change": status,
                    "Score": f"{score_val:.4f}" if score_val is not None else "—"
                })

            f.write("\n")

            if i < len(returns_series):
                weekly_return = returns_series.iloc[i]
                portfolio_value *= (1 + weekly_return)
                pct_change = portfolio_value - starting_value
                f.write(f"💰 Portfolio Value: {portfolio_value:.2f} ({pct_change:+.2f}%)\n\n")

            final_week_table = pd.DataFrame(week_rows)

        f.write("✅ Log complete.\n")

    return final_week_table

