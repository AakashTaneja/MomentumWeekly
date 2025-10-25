# === main.py ===

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import os
from config.keys import get_email_password
from log_run import log_run   # updated log_run will return ExitScore too

# === Email Config ===
EMAIL_SENDER = "yourlargecase@gmail.com"
EMAIL_PASSWORD = get_email_password()
EMAIL_RECEIVER = ["akashtaneja@gmail.com"]

# === Strategy Settings ===
TOP_N = 10
LOOKBACK_WEEKS = 12
CASH_THRESHOLD = 4.5
BUY_TIME_DESCRIPTION = "Monday 9:30 AM"

# === Portfolio Settings ===
TOTAL_CAPITAL = 5_00_000
ALLOWED_VARIANCE = 0.01
ALLOWED_WEIGHT_DEVIATION = 0.01

# -----------------------------------------------------------------------------
#  Helpers
# -----------------------------------------------------------------------------
def load_local_price_data(tickers, start_date, end_date):
    data = {}
    for symbol in tickers:
        fp = f"./data/{symbol}.csv"
        if not os.path.exists(fp):
            print(f"⚠️ {symbol}: file not found, skipping.")
            continue

        df = pd.read_csv(fp, parse_dates=["date"])
        df = df.set_index("date")
        start_ts = pd.to_datetime(start_date).tz_localize(None)
        end_ts   = pd.to_datetime(end_date).tz_localize(None)
        df = df[(df.index.tz_localize(None) >= start_ts) &
                (df.index.tz_localize(None) <= end_ts)]
        df = df[["close"]].rename(columns={"close": symbol})
        data[symbol] = df

    if not data:
        return pd.DataFrame()

    merged = pd.concat(data.values(), axis=1, join="outer")
    merged.index = pd.to_datetime(merged.index)
    return merged.sort_index().dropna(axis=1, how="all")

def compute_weekly_signals(data, lookback):
    weekly = data.resample("W-FRI").last()
    weekly_ret = weekly.pct_change()
    momentum   = weekly.pct_change(lookback)
    volatility = weekly_ret.rolling(lookback).std()
    score      = momentum / volatility
    return weekly, score

def simulate_backtest(weekly, score, daily, lookback, top_n, thresh):
    returns, dates, cash_flags, weights_rec = [], [], [], []

    for i in range(lookback, len(score)):
        signal_date = score.index[i]
        next_mon = signal_date + timedelta(days=3)

        cur_scores = score.iloc[i].dropna()
        top = cur_scores.sort_values(ascending=False).head(top_n)
        avg_score = top.mean()

        if avg_score < thresh:
            returns.append(0.0)
            cash_flags.append(True)
            dates.append(next_mon)
            weights_rec.append(None)
            continue

        weights = top / top.sum()
        weights_rec.append(weights)
        dates.append(next_mon)

        try:
            if next_mon not in daily.index:
                returns.append(0.0)
                cash_flags.append(False)
                continue

            mon_prices = daily.loc[next_mon, weights.index]
            nxt_idx = daily.index.get_loc(next_mon)

            if nxt_idx + 5 >= len(daily):
                returns.append(0.0)
                cash_flags.append(False)
                continue

            nxt_prices = daily.iloc[nxt_idx + 5][weights.index]
            ret = (nxt_prices / mon_prices - 1).fillna(0)

            returns.append((ret * weights).sum())
            cash_flags.append(False)

        except Exception as e:
            print(f"❌ Skipping return due to error: {e}")
            returns.append(0.0)
            cash_flags.append(False)

    returns_s = pd.Series(returns, index=dates)
    cumulative = (1 + returns_s).cumprod()

    print(f"\n✅ Final signal date (for Monday buy): {dates[-1] if dates else 'None'}")
    return returns_s, cumulative, cash_flags, weights_rec

def build_signal_table(latest_wts, daily,
    total_capital=TOTAL_CAPITAL,
    allowed_variance=ALLOWED_VARIANCE,
    allowed_weight_deviation=ALLOWED_WEIGHT_DEVIATION):

    if latest_wts is None or latest_wts.empty:
        print("⚠️ No signal weights found.")
        return pd.DataFrame()

    latest_date = daily[latest_wts.index].dropna().index.max()
    prices = daily.loc[latest_date, latest_wts.index].round(2)

    alloc = (latest_wts * total_capital).round(2)
    qty = (alloc / prices).round().astype(int)
    value = (qty * prices).round(2)
    capital_used = value.sum()

    achieved_weights = (value / capital_used * 100).round(2)
    desired_weights = (latest_wts * 100).round(2)

    df = pd.DataFrame({
        "Stock": latest_wts.index,
        "Price": prices.values,
        "Final Desired Weight %": desired_weights.values,
        "Final Achieved Weight %": achieved_weights.values,
        "Qty to Buy": qty.values,
        "Value (₹)": value.values
    })

    df = df.sort_values(by="Final Desired Weight %", ascending=False).reset_index(drop=True)
    return df

def plot_cumulative(cum, cash_flags, dates):
    plt.figure(figsize=(12, 6))
    plt.plot(cum.index, cum.values, label="Portfolio Cumulative Returns")
    cash_dates = [d for d, c in zip(dates, cash_flags) if c]
    plt.scatter(cum.loc[cash_dates].index,
                cum.loc[cash_dates].values,
                color="red", marker="x", label="Cash Periods")
    plt.title("12-Week Momentum Strategy: Cumulative Return")
    plt.xlabel("Date"); plt.ylabel("Cumulative Portfolio Value")
    plt.grid(True); plt.legend(); plt.tight_layout()
    plt.savefig("cumulative.png"); plt.close()

def send_email_report(tbl, log_tbl, cagr_label, dd_text, signal_date_str):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"]   = ", ".join(EMAIL_RECEIVER)
    msg["Subject"] = "Weekly Momentum Signal - 12-Week Lookback"

    try:
        html_table = tbl.to_html(index=False, justify='center')
        log_table  = log_tbl.to_html(index=False, justify='center') if log_tbl is not None else "<p>No change log available</p>"
    except Exception as e:
        print(f"❌ Failed to format table: {e}")
        html_table = "<p><b>⚠️ Error rendering allocation table.</b></p>"
        log_table  = "<p><b>⚠️ Error rendering change log.</b></p>"

    html = f"""
    <h2>Weekly Momentum Trading Signals</h2>
    <p><b>Buy Time:</b> {BUY_TIME_DESCRIPTION}</p>
    <p><b>{cagr_label}</b></p>
    <p><b>Max Drawdown:</b> {dd_text}</p>
    <p>Signal for Date: <span style="font-size:20px; font-weight:bold; color:#d9534f;">{signal_date_str}</span></p>

    <h3>Allocation Table</h3>
    {html_table}

    <h3>Change Log</h3>
    {log_table}

    <br><img src='cid:cumulative_plot'>
    """
    msg.attach(MIMEText(html, "html"))

    try:
        with open("cumulative.png", "rb") as f:
            from email.mime.image import MIMEImage
            img = MIMEImage(f.read(), name="cumulative.png")
            img.add_header("Content-ID", "<cumulative_plot>")
            msg.attach(img)
    except Exception as e:
        print(f"⚠️ Could not attach image: {e}")

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        server.quit()
        print("✅ Email sent!")
    except Exception as e:
        print(f"❌ Email sending failed: {e}")


if __name__ == "__main__":
    start_date = (datetime.today() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")
    end_date   = datetime.today().strftime("%Y-%m-%d")

    tickers = pd.read_csv("ind_nifty200list.csv")["Symbol"].str.upper().tolist()
    daily = load_local_price_data(tickers, start_date, end_date)
    weekly, score = compute_weekly_signals(daily, LOOKBACK_WEEKS)

    returns, cum, cash_flags, weights_rec = simulate_backtest(
        weekly, score, daily, LOOKBACK_WEEKS, TOP_N, CASH_THRESHOLD
    )

    latest_wts = weights_rec[-1]
    signal_tbl = build_signal_table(latest_wts, daily)

    # ✅ log_run now takes score too
    final_week_table = log_run(weights_rec, daily, returns, score)

    span_years = (cum.index[-1] - cum.index[0]).days / 365
    cagr       = (cum.iloc[-1] ** (1 / span_years)) - 1 if span_years > 0 else 0.0
    cagr_label = f"CAGR ({span_years:.2f} yrs): {cagr:.2%}"

    drawdown = (cum / cum.cummax() - 1).min()
    dd_text  = f"{drawdown:.2%}"

    signal_date_str = returns.index[-1].strftime("%Y-%m-%d")

    plot_cumulative(cum, cash_flags, returns.index)
    send_email_report(signal_tbl, final_week_table, cagr_label, dd_text, signal_date_str)
