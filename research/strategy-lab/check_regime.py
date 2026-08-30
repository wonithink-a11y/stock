import pandas as pd
df = pd.read_parquet('research/strategy-lab/data/market-regime/regime_labels.parquet')
print('Columns:', list(df.columns))
print('Shape:', df.shape)
print(df.head(3))
print()
for c in df.columns:
    vals = df[c].unique()[:10]
    print(f'Column {c}: {vals}')