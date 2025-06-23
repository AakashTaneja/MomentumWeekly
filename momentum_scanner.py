from load_live_data import load_or_fetch_ltp_data
import pandas as pd

# === Step 1: Load Nifty 200 stock symbols ===
nifty_symbols = pd.read_csv("ind_nifty200list.csv").iloc[:, 0].dropna().unique().tolist()

# === Step 2: Get latest price and volume data (from snapshot or simulated) ===
ltp_data_df = load_or_fetch_ltp_data(nifty_symbols)

# === Step 3: Apply momentum strategy filter ===
# Filter for stocks that gained today
momentum_candidates = ltp_data_df[ltp_data_df['pct_change'] > 2]

# Further filter: stocks with volume above threshold
momentum_candidates = momentum_candidates[momentum_candidates['volume'] > 1_000_000]

# Sort by volume descending
momentum_candidates = momentum_candidates.sort_values(by='volume', ascending=False).reset_index(drop=True)

# Display result without index
print("\n🔥 Intraday Momentum Candidates:")
print(momentum_candidates[['symbol', 'pct_change', 'volume']].to_string(index=False))
