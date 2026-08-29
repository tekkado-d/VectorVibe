import pandas as pd
from pathlib import Path

FEED = Path(__file__).resolve().parent / 'feeds' / '23351-54839-en_US-M_S_US.csv'

df = pd.read_csv(FEED, dtype=str, low_memory=False,
                 usecols=['merchant_name', 'aw_image_url', 'merchant_image_url'])

print(f"Rows: {len(df)}")
print(f"merchant_image_url null rate: {df['merchant_image_url'].isna().mean():.1%}\n")

print("Null rate by merchant (worst 10):")
by_merchant = (df.groupby('merchant_name')['merchant_image_url']
                 .agg(rows='size', null_rate=lambda s: s.isna().mean())
                 .sort_values('null_rate', ascending=False))
print(by_merchant.head(10))

print("\nCerqular / boohoo specifically:")
print(by_merchant[by_merchant.index.str.contains('Cerqular|boohoo', case=False, na=False)])

print("\nSample merchant_image_url values:")
for url in df['merchant_image_url'].dropna().sample(5, random_state=1):
    print(" ", url)