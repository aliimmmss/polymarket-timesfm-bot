import requests
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

def fetch_top_markets(limit=5):
    """Fetch top markets by volume from Gamma API."""
    url = f"https://gamma-api.polymarket.com/markets?limit={limit}&order=volume24hr&ascending=false"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching markets: {response.status_code}")
        return []

def fetch_price_history(token_id, interval="1h", fidelity="sparse"):
    """Fetch price history for a token from CLOB API."""
    url = f"https://clob.polymarket.com/prices-history"
    params = {
        "market": token_id,
        "interval": interval,
        "fidelity": fidelity
    }
    
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching price history for token {token_id[:20]}...: {response.status_code}")
        print(f"Response: {response.text[:200]}")
        return {"history": []}

def process_market_data(market):
    """Process a single market and fetch its price history."""
    print(f"\nProcessing market: {market['slug']}")
    print(f"Question: {market['question']}")
    print(f"Volume 24hr: ${market['volume24hr']}")
    
    # Parse CLOB token IDs
    try:
        clob_token_ids = json.loads(market['clobTokenIds'])
        yes_token_id = clob_token_ids[0]  # First token is YES
        no_token_id = clob_token_ids[1]   # Second token is NO
        
        print(f"YES token ID: {yes_token_id[:20]}...")
        print(f"NO token ID: {no_token_id[:20]}...")
        
        # Fetch YES token price history
        print("Fetching YES token price history...")
        yes_history = fetch_price_history(yes_token_id)
        
        # Fetch NO token price history
        print("Fetching NO token price history...")
        no_history = fetch_price_history(no_token_id)
        
        # Process data
        if yes_history.get("history") and len(yes_history["history"]) > 0:
            yes_df = pd.DataFrame(yes_history["history"])
            yes_df.rename(columns={"t": "timestamp", "p": "yes_price"}, inplace=True)
            yes_df["timestamp"] = pd.to_datetime(yes_df["timestamp"], unit="s")
            
            print(f"YES token: {len(yes_df)} data points")
            print(f"Time range: {yes_df['timestamp'].min()} to {yes_df['timestamp'].max()}")
            print(f"YES price range: {yes_df['yes_price'].min():.3f} to {yes_df['yes_price'].max():.3f}")
            
            return {
                "market_id": market["id"],
                "slug": market["slug"],
                "question": market["question"],
                "yes_token_id": yes_token_id,
                "no_token_id": no_token_id,
                "yes_prices": yes_df["yes_price"].tolist(),
                "timestamps": yes_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist(),
                "volume24hr": market["volume24hr"],
                "liquidity": market["liquidity"]
            }
        else:
            print(f"No YES price history available")
            return None
            
    except Exception as e:
        print(f"Error processing market {market['slug']}: {e}")
        return None

def main():
    print("Fetching Polymarket data...")
    
    # Fetch top markets
    markets = fetch_top_markets(5)
    print(f"Found {len(markets)} markets")
    
    # Process each market
    processed_data = []
    for market in markets:
        market_data = process_market_data(market)
        if market_data:
            processed_data.append(market_data)
        
        # Rate limiting
        time.sleep(1)
    
    print(f"\nSuccessfully processed {len(processed_data)} markets")
    
    # Save processed data
    if processed_data:
        output_file = "polymarket_data.json"
        with open(output_file, "w") as f:
            json.dump(processed_data, f, indent=2)
        print(f"\nData saved to {output_file}")
        
        # Display summary
        print("\nSummary of fetched data:")
        for data in processed_data:
            print(f"- {data['slug']}: {len(data['yes_prices'])} price points, "
                  f"YES price range: {min(data['yes_prices']):.3f}-{max(data['yes_prices']):.3f}, "
                  f"Volume: ${data['volume24hr']}")
    
    return processed_data

if __name__ == "__main__":
    main()