import pandas as pd
import psycopg2
import os
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

AWIN_MAP = {
    'aw_product_id':     'external_id',
    'product_name':      'name',
    'description':       'description',
    'merchant_name':     'brand',
    'aw_image_url':      'image_url',
    'aw_deep_link':      'affiliate_url',
    'search_price':      'price',
    'merchant_category': 'category',
    'colour':            'colour',
    'gender':            'gender',
}

def ingest_csv(filepath: str, network: str = 'awin'):
    df = pd.read_csv(filepath, dtype=str, low_memory=False)
    df = df.rename(columns=AWIN_MAP)

    keep = list(AWIN_MAP.values())
    df = df[[c for c in keep if c in df.columns]]

    df = df.dropna(subset=['external_id', 'name', 'affiliate_url', 'image_url'])

    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    inserted = 0
    skipped = 0

    for _, row in df.iterrows():
        try:
            cur.execute("""
                INSERT INTO products
                  (external_id, network, name, description, brand,
                   image_url, affiliate_url, price, category,
                   colour, gender, last_seen)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (external_id, network) DO UPDATE SET
                  price     = EXCLUDED.price,
                  in_stock  = TRUE,
                  last_seen = EXCLUDED.last_seen
            """, (
                row.get('external_id'), network,
                row.get('name'),        row.get('description'),
                row.get('brand'),       row.get('image_url'),
                row.get('affiliate_url'), row.get('price'),
                row.get('category'),    row.get('colour'),
                row.get('gender'),
                datetime.now(timezone.utc)
            ))
            inserted += 1
        except Exception as e:
            skipped += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"Done: {inserted} inserted/updated, {skipped} skipped")

if __name__ == '__main__':
    ingest_csv('feeds/test.csv')