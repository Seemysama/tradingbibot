import psycopg2
import pandas as pd
from src.config import load_config

def inspect_db():
    config = load_config()
    conn_str = f"host={config.QUESTDB_HOST} port=8812 user=admin password=quest dbname=qdb"
    symbol = "BTCUSDT"
    
    try:
        with psycopg2.connect(conn_str) as conn:
            print(f"--- Testing Aggregation for {symbol} ---")
            query = f"""
            SELECT 
                timestamp,
                first(price) as open,
                max(price) as high,
                min(price) as low,
                last(price) as close,
                sum(qty) as volume
            FROM trades
            WHERE symbol = '{symbol}' 
            SAMPLE BY 1s ALIGN TO CALENDAR
            ORDER BY timestamp ASC;
            """
            print(f"Query: {query}")
            df = pd.read_sql(query, conn)
            print(f"Result shape: {df.shape}")
            print(df.head())
            
            if df.empty:
                print("DataFrame is empty. Checking raw count...")
                count_query = f"SELECT count() FROM trades WHERE symbol = '{symbol}'"
                df_count = pd.read_sql(count_query, conn)
                print(f"Raw count: {df_count}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_db()
