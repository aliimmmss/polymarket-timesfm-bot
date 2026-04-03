import requests
import json
import csv
from datetime import datetime

# Top 5 markets with good data
top_markets = [
    {
        "slug": "us-forces-enter-iran-by-april-30-899",
        "question": "US forces enter Iran by April 30?",
        "yes_token_id": "2916184120206223749839849644877707470354946028257066951797428049170871002238",
        "current_price": 0.785,
        "expected_points": 294,
        "volume": 3847026.12
    },
    {
        "slug": "will-spain-win-the-2026-fifa-world-cup-963",
        "question": "Will Spain win the 2026 FIFA World Cup?",
        "yes_token_id": "43943728873855182144716084482089794794945684769083728861496576139239317626375",
        "current_price": 0.159,
        "expected_points": 741,
        "volume": 987078.74
    },
    {
        "slug": "us-x-iran-ceasefire-by-april-30-194-679-389",
        "question": "US x Iran ceasefire by April 30?",
        "yes_token_id": "44149007410374101286260953227316621789614866583117711747258324772417971844181",
        "current_price": 0.185,
        "expected_points": 653,
        "volume": 904747.79
    },
    {
        "slug": "will-gavin-newsom-win-the-2028-us-presidential-election",
        "question": "Will Gavin Newsom win the 2028 US Presidential Election?",
        "yes_token_id": "98250445447699368679516529207346322023823301117195675344424684424295946242953",
        "current_price": 0.163,
        "expected_points": 602,
        "volume": 843132.94
    },
    {
        "slug": "will-the-san-antonio-spurs-win-the-2026-nba-finals",
        "question": "Will the San Antonio Spurs win the 2026 NBA Finals?",
        "yes_token_id": "10222718403596785008976698195805514859394814222394899748948621416558624211838",
        "current_price": 0.176,
        "expected_points": 720,
        "volume": 807643.92
    }
]

print("STEP 2: Fetch and save price history for top 5 markets")
print("=" * 60)

all_market_data = []

for i, market in enumerate(top_markets):
    print(f"\n{i+1}. {market['slug']}")
    print(f"   Question: {market['question']}")
    print(f"   Expected points: {market['expected_points']}")
    print(f"   Volume: ${market['volume']:,.2f}")
    
    try:
        # Fetch price history
        price_response = requests.get(
            "https://clob.polymarket.com/prices-history",
            params={"market": market["yes_token_id"], "interval": "max", "fidelity": "60"},
            timeout=15
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
                
                print(f"   ✓ Saved to: {csv_filename}")
                print(f"   Actual points: {len(history)}")
                print(f"   Time range: {datetime.fromtimestamp(history[0]['t']).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(history[-1]['t']).strftime('%Y-%m-%d')}")
                print(f"   Price range: {min(h['p'] for h in history):.3f} to {max(h['p'] for h in history):.3f}")
                print(f"   Current price: {history[-1]['p']:.3f}")
                
                # Show detailed sample
                print(f"\n   Sample (first 5):")
                for j in range(min(5, len(history))):
                    print(f"     {datetime.fromtimestamp(history[j]['t']).strftime('%Y-%m-%d %H:%M:%S')}: {history[j]['p']:.3f}")
                
                print(f"\n   Sample (last 5):")
                for j in range(max(0, len(history)-5), len(history)):
                    print(f"     {datetime.fromtimestamp(history[j]['t']).strftime('%Y-%m-%d %H:%M:%S')}: {history[j]['p']:.3f}")
                
                # Store for TimesFM
                market_data = {
                    "slug": market["slug"],
                    "question": market["question"],
                    "prices": [h["p"] for h in history],
                    "timestamps": [datetime.fromtimestamp(h["t"]).strftime("%Y-%m-%d %H:%M:%S") for h in history],
                    "current_price": float(history[-1]["p"]),
                    "total_points": len(history),
                    "volume": market["volume"],
                    "csv_file": csv_filename
                }
                all_market_data.append(market_data)
                
            else:
                print(f"   ✗ No history data")
                
        else:
            print(f"   ✗ API Error: {price_response.status_code}")
            
    except Exception as e:
        print(f"   ✗ Exception: {e}")
    
    print(f"\n   {'-'*50}")

# Save for TimesFM
if all_market_data:
    output_file = "timesfm_ready_data.json"
    with open(output_file, "w") as f:
        json.dump(all_market_data, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"STEP 2 COMPLETE: Saved data for {len(all_market_data)} markets to {output_file}")
    
    # Summary
    print("\nMarket Summary for TimesFM:")
    for m in all_market_data:
        print(f"- {m['slug']}")
        print(f"  Points: {m['total_points']}, Current: {m['current_price']:.3f}")
        print(f"  CSV: {m['csv_file']}")
        print()

print("\nReady for STEP 3: Running TimesFM on real data!")