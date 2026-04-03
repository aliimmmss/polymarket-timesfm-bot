import requests
import json
import pandas as pd
import sys
import os

# Top 5 markets by volume with sufficient data
top_markets = [
    {
        "slug": "us-forces-enter-iran-by-april-30-899",
        "yes_token_id": "2916184120206223749839849644877707470354946028257066951797428049170871002238",
        "volume": 3147738.66
    },
    {
        "slug": "will-trump-talk-to-xi-jinping-in-march-165", 
        "yes_token_id": "9779954861788356237110411061682108412713152752753538345936642621511592621707",
        "volume": 1398646.46
    },
    {
        "slug": "will-scotland-win-the-2026-fifa-world-cup",
        "yes_token_id": "10525220699788525235895989706906458822004113498064708908121480837087543285959",
        "volume": 1233658.16
    },
    {
        "slug": "us-forces-enter-iran-by-march-31-222-191-243-517-878-439-519",
        "yes_token_id": "42750054381142639205121368121349001899991594829106133617802908500123525370925",
        "volume": 1179492.77
    },
    {
        "slug": "will-spain-win-the-2026-fifa-world-cup-963",
        "yes_token_id": "43943728873855182144824685698777358301067955586187827878232862620405782446750",
        "volume": 962440.38
    }
]

def fetch_and_save_market_data():
    print("STEP 2: Fetch and save price history for top 5 markets")
    print("=" * 60)
    
    market_data_list = []
    
    for i, market in enumerate(top_markets):
        print(f"\n{i+1}. {market['slug']}")
        print(f"   Volume: ${market['volume']:,.2f}")
        
        try:
            # Fetch price history
            price_response = requests.get(
                "https://clob.polymarket.com/prices-history",
                params={"market": market["yes_token_id"], "interval": "max", "fidelity": "60"},
                timeout=30
            )
            
            if price_response.status_code == 200:
                price_data = price_response.json()
                history = price_data.get("history", [])
                
                if not history:
                    print(f"   ✗ No price history data")
                    continue
                
                # Convert to DataFrame
                df = pd.DataFrame(history)
                df.rename(columns={"t": "timestamp", "p": "price"}, inplace=True)
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
                
                # Save to CSV
                csv_filename = f"{market['slug']}_prices.csv"
                df.to_csv(csv_filename, index=False)
                
                print(f"   Data points: {len(df)}")
                print(f"   Time range: {df['timestamp'].min()} to {df['timestamp'].max()}")
                print(f"   Price range: {df['price'].min():.3f} to {df['price'].max():.3f}")
                print(f"   Current price: {df['price'].iloc[-1]:.3f}")
                print(f"   Saved to: {csv_filename}")
                
                # Show first 5 and last 5 rows
                print(f"\n   First 5 rows:")
                print(df.head().to_string(index=False))
                print(f"\n   Last 5 rows:")
                print(df.tail().to_string(index=False))
                
                # Store for TimesFM
                market["price_data"] = df["price"].values.tolist()
                market["timestamps"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist()
                market["current_price"] = float(df["price"].iloc[-1])
                market["data_points"] = len(df)
                
                market_data_list.append(market)
                
            else:
                print(f"   ✗ ERROR: {price_response.status_code}")
                
        except Exception as e:
            print(f"   ✗ Exception: {e}")
        
        print(f"\n   {'-'*50}")
    
    # Save combined data for TimesFM
    if market_data_list:
        output_file = "timesfm_input_data.json"
        with open(output_file, "w") as f:
            json.dump(market_data_list, f, indent=2)
        print(f"\n{'='*60}")
        print(f"Saved combined data for TimesFM to: {output_file}")
        
        # Summary
        print("\nSummary of fetched markets:")
        for m in market_data_list:
            print(f"- {m['slug']}: {m['data_points']} points, Current: {m['current_price']:.3f}")
    
    return market_data_list

if __name__ == "__main__":
    fetch_and_save_market_data()