import pandas as pd
import datetime as dt
import matplotlib.pyplot as plt
from pathlib import Path
import io
import requests
import zipfile

# === CONFIG ===
BASE_LOG_DIR = Path("logs/trade_manager_all_nse")
DATE_FOLDER = dt.datetime.now().strftime("%Y%m%d")  # auto-select today's folder
REALIZED_CSV = BASE_LOG_DIR / DATE_FOLDER / "realized_trades.csv"

TODAY = dt.datetime.now().strftime("%d-%m-%Y")
BHVACOPY_DATE = dt.datetime.now().strftime("%d%m%Y")  # for NSE filename format like CM24OCT2025

# Volume reliability buckets
VOLUME_BUCKETS = [
    (0, 50000, "Very Low (❌ Unreliable)"),
    (50000, 200000, "Moderate (⚠️ Mixed)"),
    (200000, 1000000, "High (✅ Reliable)"),
    (1000000, float("inf"), "Very High (💯 Ideal)")
]

print(f"📊 Analyzing VWAP reliability for trades on {TODAY}")
print(f"📁 Using file: {REALIZED_CSV}\n")

# === 1. Load realized trades ===
if not REALIZED_CSV.exists():
    raise FileNotFoundError(f"❌ Could not find {REALIZED_CSV}")

df = pd.read_csv(REALIZED_CSV)

required_cols = {"symbol", "pnl", "entry_price", "qty"}
if not required_cols.issubset(df.columns):
    raise ValueError(f"❌ realized_trades.csv must contain columns: {required_cols}")

df["pnl_pct"] = (df["pnl"] / (df["entry_price"] * df["qty"])) * 100
symbols = df["symbol"].unique().tolist()
print(f"Loaded {len(df)} realized trades across {len(symbols)} symbols.\n")

# === 2. Download today's NSE Bhavcopy (for total traded volume) ===
def fetch_bhavcopy(date_str):
    """Fetch today's NSE Bhavcopy ZIP and return DataFrame with symbol & volume."""
    url = f"https://nsearchives.nseindia.com/content/historical/EQUITIES/{dt.datetime.now().year}/OCT/CM{BHVACOPY_DATE}BHV.csv.zip"
    # Replace OCT with dynamic month
    month = dt.datetime.now().strftime("%b").upper()
    url = url.replace("OCT", month)

    print(f"📥 Fetching NSE Bhavcopy from {url}")
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            print("⚠️ Failed to fetch Bhavcopy (HTTP", r.status_code, ")")
            return None
        z = zipfile.ZipFile(io.BytesIO(r.content))
        csv_name = [n for n in z.namelist() if n.endswith(".csv")][0]
        df_bhav = pd.read_csv(z.open(csv_name))
        df_bhav = df_bhav.rename(columns={"SYMBOL": "symbol", "TOTTRDQTY": "volume"})
        df_bhav["symbol"] = df_bhav["symbol"].str.strip()
        df_bhav["volume"] = df_bhav["volume"].astype(float)
        print(f"✅ Loaded {len(df_bhav)} rows from Bhavcopy.")
        return df_bhav
    except Exception as e:
        print(f"❌ Error fetching Bhavcopy: {e}")
        return None

bhav_df = fetch_bhavcopy(BHVACOPY_DATE)
if bhav_df is None:
    raise RuntimeError("❌ Could not retrieve NSE Bhavcopy. Try later or download manually.")

# === 3. Merge volumes with realized trades ===
df = df.merge(bhav_df[["symbol", "volume"]], on="symbol", how="left")

# Replace missing volumes with 0 to avoid pd.cut crash
df["volume"] = df["volume"].fillna(0).astype(float)

# === 4. Classify by VWAP reliability bucket ===
df["volume_bucket"] = pd.cut(
    df["volume"],
    bins=[b[0] for b in VOLUME_BUCKETS] + [float("inf")],
    labels=[b[2] for b in VOLUME_BUCKETS],
    include_lowest=True
)

# === 5. Summarize results ===
summary = (
    df.groupby("volume_bucket")
    .agg(
        trade_count=("symbol", "count"),
        avg_pnl_pct=("pnl_pct", "mean"),
        win_rate=("pnl_pct", lambda x: (x > 0).mean() * 100)
    )
    .reset_index()
    .sort_values("avg_pnl_pct", ascending=False)
)

print("\n=== VWAP Reliability vs Volume Summary ===\n")
print(summary.to_string(index=False, formatters={
    "avg_pnl_pct": "{:.2f}%".format,
    "win_rate": "{:.1f}%".format
}))

# === 6. Plot results ===
plt.figure(figsize=(8, 5))
plt.bar(summary["volume_bucket"], summary["avg_pnl_pct"], color="steelblue", alpha=0.8)
plt.title(f"VWAP Reliability vs Volume (as of {TODAY})")
plt.ylabel("Average P&L (%)")
plt.xticks(rotation=25, ha="right")
plt.grid(axis="y", linestyle="--", alpha=0.6)
plt.tight_layout()
plt.show()
