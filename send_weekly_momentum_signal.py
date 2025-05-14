import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import os
from config.keys import get_email_password

# === Email Config ===
EMAIL_SENDER = "yourlargecase@gmail.com"
EMAIL_PASSWORD = get_email_password()
EMAIL_RECEIVER = ["akashtaneja@gmail.com"]

# === Settings ===
TOP_N = 10
LOOKBACK_WEEKS = 12
CASH_THRESHOLD = 4.5
BUY_TIME_DESCRIPTION = "Monday 9:30 AM"

# === Load local data ===
def load_local_price_data(tickers, start_date, end_date):
    data = {}
    for symbol in tickers:
        file_path = f"./data/{symbol}.csv"
        if not os.path.exists(file_path):
            print(f"⚠️ {symbol}: file not found, skipping.")
            continue

        df = pd.read_csv(file_path, parse_dates=["date"])
        df = df.set_index("date")
        start_ts = pd.to_datetime(start_date).tz_localize(None)
        end_ts = pd.to_datetime(end_date).tz_localize(None)
        df = df[(df.index.tz_localize(None) >= start_ts) & (df.index.tz_localize(None) <= end_ts)]
        df = df[["close"]].rename(columns={"close": symbol})
        data[symbol] = df

    merged = pd.concat(data.values(), axis=1, join="outer")
    merged.index = pd.to_datetime(merged.index)
    merged = merged.sort_index()
    return merged.dropna(axis=1, how="all")

# === Compute weekly data and score ===
def compute_weekly_signals(data, lookback):
    weekly_data = data.resample('W-FRI').last()
    weekly_returns = weekly_data.pct_change()
    momentum = weekly_data.pct_change(lookback)
    volatility = weekly_returns.rolling(window=lookback).std()
    score = momentum / volatility
    return weekly_data, score

# === Backtest simulation ===
def simulate_backtest(weekly_data, score, daily_data, lookback, top_n, threshold):
    returns, dates, cash_flags, weights_record = [], [], [], []

    for i in range(lookback, len(score) - 1):
        signal_date = score.index[i]
        next_monday = signal_date + timedelta(days=3)
        if next_monday not in daily_data.index:
            continue

        current_scores = score.iloc[i].dropna()
        top = current_scores.sort_values(ascending=False).head(top_n)
        avg_score = top.mean()

        if avg_score < threshold:
            returns.append(0.0)
            cash_flags.append(True)
            dates.append(next_monday)
            weights_record.append(None)
            continue

        weights = top / top.sum()

        try:
            monday_prices = daily_data.loc[next_monday, weights.index]
            next_index = daily_data.index.get_loc(next_monday)
            next_week_prices = daily_data.iloc[next_index + 5][weights.index]
        except:
            continue

        ret = (next_week_prices / monday_prices - 1).fillna(0)
        weekly_return = (ret * weights).sum()

        returns.append(weekly_return)
        cash_flags.append(False)
        dates.append(next_monday)
        weights_record.append(weights)

    returns_series = pd.Series(returns, index=dates)
    cumulative = (1 + returns_series).cumprod()
    return returns_series, cumulative, cash_flags, weights_record

# === Generate trading signals ===
def generate_trading_signals(latest_weights):
    if latest_weights is None or latest_weights.empty:
        return pd.DataFrame()
    signals = pd.DataFrame({
        "Stock": latest_weights.index,
        "Final Desired Weight %": (latest_weights.values * 100).round(2)
    })
    return signals

# === Plot backtest ===
def plot_cumulative(cumulative, cash_flags, dates):
    plt.figure(figsize=(12, 6))
    plt.plot(cumulative.index, cumulative.values, label='Portfolio Cumulative Returns')
    cash_dates = [date for date, is_cash in zip(dates, cash_flags) if is_cash]
    cash_values = cumulative.loc[cash_dates]
    plt.scatter(cash_values.index, cash_values.values, color='red', marker='x', label='Cash Periods')
    plt.title("12-Week Momentum Strategy: Cumulative Return")
    plt.xlabel("Date")
    plt.ylabel("Cumulative Portfolio Value")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig("cumulative.png")
    plt.close()

# === Email Report ===
def send_email_report(signals_table, cagr_text, drawdown_text):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = ", ".join(EMAIL_RECEIVER)
    msg['Subject'] = "Weekly Momentum Signal - 12 Week Strategy"

    html = f"""
    <h2>Weekly Momentum Trading Signals</h2>
    <p><b>Buy Time:</b> {BUY_TIME_DESCRIPTION}</p>
    <p><b>CAGR:</b> {cagr_text}</p>
    <p><b>Max Drawdown:</b> {drawdown_text}</p>
    {signals_table.to_html(index=False)}
    <br><img src='cid:cumulative_plot'>
    """

    msg.attach(MIMEText(html, 'html'))

    with open("cumulative.png", 'rb') as f:
        img = f.read()

    from email.mime.image import MIMEImage
    image = MIMEImage(img, name='cumulative.png')
    image.add_header('Content-ID', '<cumulative_plot>')
    msg.attach(image)

    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(EMAIL_SENDER, EMAIL_PASSWORD)
    server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
    server.quit()

# === Main ===
if __name__ == "__main__":
    try:
        start_date = (datetime.today() - timedelta(days=5*365)).strftime("%Y-%m-%d")
        end_date = datetime.today().strftime("%Y-%m-%d")

        print(f"📥 Loading ticker list from CSV...")
        tickers = pd.read_csv("ind_nifty200list.csv")["Symbol"].str.upper().tolist()

        print(f"📊 Loading price data from local CSV files...")
        daily_data = load_local_price_data(tickers, start_date, end_date)

        print(f"📈 Computing weekly scores and signals...")
        weekly_data, score = compute_weekly_signals(daily_data, LOOKBACK_WEEKS)

        returns, cumulative, cash_flags, weights_record = simulate_backtest(
            weekly_data, score, daily_data, LOOKBACK_WEEKS, TOP_N, CASH_THRESHOLD
        )

        latest_weights = weights_record[-1]
        signals_table = generate_trading_signals(latest_weights)

        cagr = (cumulative.iloc[-1] ** (1/5)) - 1
        cagr_text = f"{cagr:.2%}"
        drawdown = (cumulative / cumulative.cummax() - 1).min()
        drawdown_text = f"{drawdown:.2%}"

        print(f"📤 Plotting and sending email...")
        plot_cumulative(cumulative, cash_flags, returns.index)
        send_email_report(signals_table, cagr_text, drawdown_text)

        print("✅ Email sent successfully!")

    except Exception as e:
        print(f"⚠️ Script exited with error: {e}")
