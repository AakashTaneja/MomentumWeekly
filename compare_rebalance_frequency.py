import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

# === Settings (same as main script) ===
TOP_N = 10
LOOKBACK_WEEKS = 12
CASH_THRESHOLD = 4.5
TICKERS_FILE = "ind_nifty200list.csv"
DATA_DIR = "./data"

# === Load local price data (identical logic) ===
def load_local_price_data(tickers, start_date, end_date):
    data = {}
    for symbol in tickers:
        file_path = os.path.join(DATA_DIR, f"{symbol}.csv")
        if not os.path.exists(file_path):
            continue
        df = pd.read_csv(file_path, parse_dates=["date"])
        df.index = df["date"].dt.tz_localize(None)
        df = df[(df.index >= pd.to_datetime(start_date).tz_localize(None)) &
                (df.index <= pd.to_datetime(end_date).tz_localize(None))]
        df = df[["close"]].rename(columns={"close": symbol})
        data[symbol] = df
    merged = pd.concat(data.values(), axis=1, join="outer")
    merged = merged.dropna(axis=1, how="all")
    return merged.sort_index()

# === Compute signals (same logic) ===
def compute_weekly_signals(data, lookback):
    weekly_data = data.resample('W-FRI').last()
    weekly_returns = weekly_data.pct_change()
    momentum = weekly_data.pct_change(lookback)
    volatility = weekly_returns.rolling(window=lookback).std()
    score = momentum / volatility
    return weekly_data, score

# === Simulate backtest with variable rebalance frequency ===
def simulate_backtest(weekly_data, score, daily_data, lookback, top_n, threshold, rebalance_gap=1):
    returns, dates, cash_flags, weights_record = [], [], [], []
    i = lookback
    while i < len(score) - 1:
        signal_date = score.index[i]
        next_monday = signal_date + timedelta(days=3)
        if next_monday not in daily_data.index:
            i += rebalance_gap
            continue

        current_scores = score.iloc[i].dropna()
        top = current_scores.sort_values(ascending=False).head(top_n)
        avg_score = top.mean()

        if avg_score < threshold:
            returns.append(0.0)
            cash_flags.append(True)
            dates.append(next_monday)
            weights_record.append(None)
            i += rebalance_gap
            continue

        weights = top / top.sum()

        try:
            monday_prices = daily_data.loc[next_monday, weights.index]
            next_index = daily_data.index.get_loc(next_monday)
            next_week_prices = daily_data.iloc[next_index + 5][weights.index]
        except:
            i += rebalance_gap
            continue

        ret = (next_week_prices / monday_prices - 1).fillna(0)
        weekly_return = (ret * weights).sum()

        returns.append(weekly_return)
        cash_flags.append(False)
        dates.append(next_monday)
        weights_record.append(weights)

        i += rebalance_gap

    returns_series = pd.Series(returns, index=dates)
    cumulative = (1 + returns_series).cumprod()
    return returns_series, cumulative

# === Main comparison ===
if __name__ == "__main__":
    start_date = (datetime.today() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")
    end_date = datetime.today().strftime("%Y-%m-%d")

    tickers = pd.read_csv(TICKERS_FILE)["Symbol"].str.upper().tolist()
    daily_data = load_local_price_data(tickers, start_date, end_date)
    weekly_data, score = compute_weekly_signals(daily_data, LOOKBACK_WEEKS)

    print("\n📊 Aligned CAGR Comparison by Rebalancing Frequency:\n")
    for gap in [1, 2, 3, 4]:
        returns, cumulative = simulate_backtest(
            weekly_data, score, daily_data,
            LOOKBACK_WEEKS, TOP_N, CASH_THRESHOLD, rebalance_gap=gap
        )
        years = (cumulative.index[-1] - cumulative.index[0]).days / 365
        cagr = (cumulative.iloc[-1] ** (1 / years)) - 1
        print(f"🔁 Every {gap}-week Rebalance → CAGR: {cagr:.2%}")
