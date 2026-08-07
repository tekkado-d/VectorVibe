import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

def ingest_csv(filepath: str, network: str = 'awin'):
    df = pd.read_csv(filepath, dtype=str, low_memory=False)
    print(f"Total rows: {len(df)}")

    # Drop rows missing essential fields
    df = df.dropna(subset=['aw_product_id', 'product_name',
                           'aw_deep_link', 'aw_image_url'])

    # Deduplicate by product name and brand — removes size variants
    df = df.drop_duplicates(subset=['product_name', 'merchant_name'], keep='first')
    print(f"Unique products after dedup: {len(df)}")

    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()

    # Build all rows at once
    rows_to_insert = []
    for _, row in df.iterrows():
        rows_to_insert.append((
            row.get('aw_product_id'),
            network,
            row.get('product_name'),
            row.get('description'),
            row.get('merchant_name'),
            row.get('aw_image_url'),
            row.get('aw_deep_link'),
            row.get('search_price'),
            row.get('merchant_category'),
            row.get('colour'),
            None,
            datetime.now(timezone.utc)
        ))

    print(f"Inserting {len(rows_to_insert)} products...")

    execute_values(cur, """
        INSERT INTO products
          (external_id, network, name, description, brand,
           image_url, affiliate_url, price, category,
           colour, gender, last_seen)
        VALUES %s
        ON CONFLICT (external_id, network) DO UPDATE SET
          price     = EXCLUDED.price,
          in_stock  = TRUE,
          last_seen = EXCLUDED.last_seen
    """, rows_to_insert)

    conn.commit()
    cur.close()
    conn.close()
    print(f"Done: {len(rows_to_insert)} inserted/updated")

if __name__ == '__main__':
    ingest_csv('feeds/60703-112084-en_US-BoohooUS_25.csv', network='awin')