import requests
import json
import csv
from datetime import datetime
import time

def fetch_all_market_data():
    print("Fetching ALL active markets with real price history...")
    print("=" * 60)
    
    # First get all active markets
    response = requests.get(
        "https://gamma-api.polymarket.com/markets",
        params={"closed": "false", "limit": 30, "order": "volume24hr", "ascending": "false"}
    )
    markets = response.json()
    
    print(f"Found {len(markets)} active markets")
    
    all_market_data = []
    successful_markets = 0
    
    for i, market in enumerate(markets):
        slug = market["slug"]
        question = market["question"]
        volume24hr = market["volume24hr"]
        
        print(f"\n{i+1}. {slug}")
        print(f"   Question: {question[:80]}...")
        print(f"   Volume 24hr: ${volume24hr:,.2f}")
        
        try:
            # Parse clobTokenIds
            clob_token_ids = json.loads(market["clobTokenIds"])
            if not clob_token_ids:
                print(f"   ✗ No clobTokenIds")
                continue
                
            yes_token_id = clob_token_ids[0]
            print(f"   Token ID: {yes_token_id[:30]}...")
            
            # Fetch price history
            price_response = requests.get(
                "https://clob.polymarket.com/prices-history",
                params={"market": yes_token_id, "interval": "max", "fidelity": "60"},
                timeout=15
            )
            
            if price_response.status_code != 200:
                print(f"   ✗ API Error: {price_response.status_code}")
                continue
                
            price_data = price_response.json()
            history = price_data.get("history", [])
            
            if not history:
                print(f"   ✗ Empty history")
                continue
                
            if len(history) < 256:
                print(f"   ✗ Insufficient data: {len(history)} points")
                continue
                
            # Check if price is reasonable (not too close to 0 or 1)
            current_price = history[-1]["p"]
            if current_price < 0.05 or current_price > 0.95:
                print(f"   ✗ Extreme price: {current_price:.3f}")
                continue
            
            # Save to CSV
            csv_filename = f"{slug}_prices.csv"
            with open(csv_filename, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "price"])
                for entry in history:
                    timestamp = datetime.fromtimestamp(entry["t"]).strftime("%Y-%m-%d %H:%M:%S")
                    writer.writerow([timestamp, entry["p"]])
            
            print(f"   ✓ SUCCESS: {len(history)} points")
            print(f"   Current price: {current_price:.3f}")
            print(f"   Time range: {datetime.fromtimestamp(history[0]['t']).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(history[-1]['t']).strftime('%Y-%m-%d')}")
            print(f"   Saved to: {csv_filename}")
            
            # Show quick sample
            print(f"\n   First 3 prices: {history[0]['p']:.3f}, {history[1]['p']:.3f}, {history[2]['p']:.3f}")
            print(f"   Last 3 prices: {history[-3]['p']:.3f}, {history[-2]['p']:.3f}, {history[-1]['p']:.3f}")
            
            # Store for TimesFM
            market_data = {
                "slug": slug,
                "question": question,
                "prices": [h["p"] for h in history],
                "timestamps": [datetime.fromtimestamp(h["t"]).strftime("%Y-%m-%d %H:%M:%S") for h in history],
                "current_price": current_price,
                "total_points": len(history),
                "volume24hr": volume24hr,
                "csv_file": csv_filename
            }
            all_market_data.append(market_data)
            successful_markets += 1
            
            # Rate limiting
            time.sleep(0.5)
            
        except Exception as e:
            print(f"   ✗ Exception: {e}")
            continue
    
    # Save combined data for TimesFM
    if all_market_data:
        output_file = "all_market_data_timesfm.json"
        with open(output_file, "w") as f:
            json.dump(all_market_data, f, indent=2)
        
        print(f"\n{'='*60}")
        print(f"STEP 2 COMPLETE!")
        print(f"Successfully fetched {successful_markets}/{len(markets)} markets")
        print(f"Saved combined data to: {output_file}")
        
        # Summary
        print("\nMarkets ready for TimesFM (sorted by volume):")
        all_market_data.sort(key=lambda x: x["volume24hr"], reverse=True)
        for i, m in enumerate(all_market_data[:10]):  # Top 10
            print(f"{i+1}. {m['slug']}")
            print(f"   Points: {m['total_points']}, Current: {m['current_price']:.3f}")
            print(f"   Volume: ${m['volume24hr']:,.2f}")
            print(f"   CSV: {m['csv_file']}")
            print()
    else:
        print("\nNo markets with sufficient data found!")
    
    return all_market_data

if __name__ == "__main__":
    fetch_all_market_data()