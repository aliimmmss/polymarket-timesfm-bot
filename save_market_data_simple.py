import requests
import json
import csv
from datetime import datetime

# Markets with reasonable prices (>0.05)
selected_markets = [
    {
        "slug": "us-forces-enter-iran-by-april-30-899",
        "yes_token_id": "2916184120206223749839849644877707470354946028257066951797428049170871002238",
        "current_price": 0.785,
        "expected_points": 294,
        "volume": 3485757.88
    },
    {
        "slug": "will-spain-win-the-2026-fifa-world-cup-963",
        "yes_token_id": "43943728873855182144824685698777358301067955586187827878232862620405782446750",
        "current_price": 0.160,
        "expected_points": 741,
        "volume": 973437.88
    },
    {
        "slug": "us-x-iran-ceasefire-by-april-30-194-679-389",
        "yes_token_id": "44149007410374101286100866753546445087494739140486468013316210270143218515077",
        "current_price": 0.185,
        "expected_points": 653,
        "volume": 885572.70
    },
    {
        "slug": "will-gavin-newsom-win-the-2028-us-presidential-election",
        "yes_token_id": "98250445447699368679036616977625686783861113848826276490609236575705024480378",
        "current_price": 0.162,
        "expected_points": 602,
        "volume": 843795.32
    },
    {
        "slug": "will-the-san-antonio-spurs-win-the-2026-nba-finals",
        "yes_token_id": "10222718403596785008428983062063944200655967586545239912616873626865677416537",
        "current_price": 0.177,
        "expected_points": 720,
        "volume": 810118.75
    }
]

print("Fetching and saving detailed price data...")
print("=" * 60)

all_market_data = []

for i, market in enumerate(selected_markets):
    print(f"\n{i+1}. {market['slug']}")
    print(f"   Current price: {market['current_price']:.3f}")
    print(f"   Expected points: {market['expected_points']}")
    print(f"   Volume: ${market['volume']:,.2f}")
    
    try:
        # Fetch price history
        price_response = requests.get(
            "https://clob.polymarket.com/prices-history",
            params={"market": market["yes_token_id"], "interval": "max", "fidelity": "60"},
            timeout=10
        )
        
        if price_response.status_code == 200:
            price_data = price_response.json()
            history = price_data.get("history", [])
            
            if history:
                # Save to CSV
                csv_filename = f"{market['slug']}_prices.csv"
                with open(csv_filename, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["timestamp", "price"])
                    for entry in history:
                        timestamp = datetime.fromtimestamp(entry["t"]).strftime("%Y-%m-%d %H:%M:%S")
                        writer.writerow([timestamp, entry["p"]])
                
                print(f"   Saved to: {csv_filename}")
                print(f"   Actual points: {len(history)}")
                print(f"   First timestamp: {datetime.fromtimestamp(history[0]['t']).strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"   Last timestamp: {datetime.fromtimestamp(history[-1]['t']).strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"   First price: {history[0]['p']:.3f}")
                print(f"   Last price: {history[-1]['p']:.3f}")
                print(f"   Min price: {min(h['p'] for h in history):.3f}")
                print(f"   Max price: {max(h['p'] for h in history):.3f}")
                
                # Show sample
                print(f"\n   Sample (first 3):")
                for j in range(min(3, len(history))):
                    print(f"     {datetime.fromtimestamp(history[j]['t']).strftime('%Y-%m-%d %H:%M:%S')}: {history[j]['p']:.3f}")
                
                print(f"   Sample (last 3):")
                for j in range(max(0, len(history)-3), len(history)):
                    print(f"     {datetime.fromtimestamp(history[j]['t']).strftime('%Y-%m-%d %H:%M:%S')}: {history[j]['p']:.3f}")
                
                # Store for TimesFM
                market_data = {
                    "slug": market["slug"],
                    "prices": [h["p"] for h in history],
                    "timestamps": [datetime.fromtimestamp(h["t"]).strftime("%Y-%m-%d %H:%M:%S") for h in history],
                    "current_price": float(history[-1]["p"]),
                    "total_points": len(history),
                    "volume": market["volume"]
                }
                all_market_data.append(market_data)
                
            else:
                print(f"   ✗ No history data")
                
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    print(f"\n   {'-'*50}")

# Save for TimesFM
if all_market_data:
    output_file = "timesfm_market_data.json"
    with open(output_file, "w") as f:
        json.dump(all_market_data, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"Saved data for {len(all_market_data)} markets to {output_file}")
    
    # Summary
    print("\nMarket Summary:")
    for m in all_market_data:
        print(f"- {m['slug']}: {m['total_points']} pts, Current: {m['current_price']:.3f}, Volume: ${m['volume']:,.2f}")