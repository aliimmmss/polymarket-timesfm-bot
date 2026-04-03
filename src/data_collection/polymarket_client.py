#!/usr/bin/env python3
"""
Polymarket CLOB API Client for fetching active markets and price history.
Data saved to ~/polymarket-bot/data/
"""

import requests
import pandas as pd
import json
import time
from datetime import datetime, timedelta
import os
from pathlib import Path

# Configuration
BASE_URL = "https://clob.polymarket.com"
DATA_DIR = Path.home() / "polymarket-bot" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

class PolymarketClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "PolymarketBot/1.0"
        })
    
    def get_active_markets(self, limit=50):
        """Fetch active markets from Polymarket CLOB API"""
        try:
            url = f"{BASE_URL}/markets"
            params = {
                "limit": limit,
                "active": "true",
                "sort": "volume_desc"
            }
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            # Return the 'data' field which contains the markets
            return {
                'data': data.get('data', []),
                'total': data.get('count', 0),
                'next_cursor': data.get('next_cursor')
            }
        except Exception as e:
            print(f"Error fetching markets: {e}")
            return {'data': [], 'total': 0, 'next_cursor': None}
    
    def get_market_details(self, market_id):
        """Get detailed information for a specific market"""
        try:
            url = f"{BASE_URL}/markets/{market_id}"
            response = self.session.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching market {market_id}: {e}")
            return None
    
    def get_order_book(self, market_id):
        """Get order book (bids/asks) for a market"""
        try:
            url = f"{BASE_URL}/markets/{market_id}/book"
            response = self.session.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching order book for {market_id}: {e}")
            return None
    
    def get_price_history(self, market_id, hours=24):
        """Get price history for a market (simplified - using order book snapshots)"""
        try:
            # For now, we'll use the current order book as a snapshot
            # In a real implementation, you'd want to fetch historical trades
            order_book = self.get_order_book(market_id)
            if not order_book:
                return []
            
            # Extract best bid and ask prices
            bids = order_book.get('bids', [])
            asks = order_book.get('asks', [])
            
            if bids and asks:
                best_bid = float(bids[0]['price']) if bids else 0
                best_ask = float(asks[0]['price']) if asks else 0
                mid_price = (best_bid + best_ask) / 2 if best_bid and best_ask else best_ask or best_bid
                
                return [{
                    'timestamp': datetime.now().isoformat(),
                    'market_id': market_id,
                    'bid': best_bid,
                    'ask': best_ask,
                    'mid_price': mid_price,
                    'bid_size': float(bids[0]['size']) if bids else 0,
                    'ask_size': float(asks[0]['size']) if asks else 0
                }]
            return []
        except Exception as e:
            print(f"Error fetching price history for {market_id}: {e}")
            return []
    
    def save_markets_to_csv(self, markets, filename="markets.csv"):
        """Save markets data to CSV"""
        try:
            df = pd.DataFrame(markets)
            filepath = DATA_DIR / filename
            df.to_csv(filepath, index=False)
            print(f"Saved {len(markets)} markets to {filepath}")
            return filepath
        except Exception as e:
            print(f"Error saving markets to CSV: {e}")
            return None
    
    def save_price_history(self, price_data, market_id, filename=None):
        """Save price history to CSV"""
        try:
            if not filename:
                filename = f"price_history_{market_id[:8]}.csv"
            
            df = pd.DataFrame(price_data)
            filepath = DATA_DIR / filename
            df.to_csv(filepath, index=False)
            print(f"Saved {len(price_data)} price points to {filepath}")
            return filepath
        except Exception as e:
            print(f"Error saving price history: {e}")
            return None


def main():
    """Main function to fetch and save Polymarket data"""
    print("=== Polymarket Data Collection ===")
    print(f"Data directory: {DATA_DIR}")
    
    client = PolymarketClient()
    
    # Fetch active markets
    print("\nFetching active markets...")
    response = client.get_active_markets(limit=20)
    
    # Extract markets from response
    markets = response.get('data', [])
    total_markets = response.get('total', len(markets))
    print(f"API Response: {len(markets)} markets out of {total_markets} total")
    
    if not markets:
        print("No markets found!")
        return
    
    print(f"Found {len(markets)} active markets")
    
    # Save markets data
    markets_file = client.save_markets_to_csv(markets)
    
    # Select top 3 markets for detailed data collection
    selected_markets = markets[:3]
    
    all_price_data = []
    for i, market in enumerate(selected_markets, 1):
        market_id = market.get('id', '')
        if not market_id:
            continue
        
        print(f"\n[{i}/{len(selected_markets)}] Processing market: {market.get('question', market_id[:20])}")
        
        # Get market details
        details = client.get_market_details(market_id)
        if details:
            print(f"  Status: {details.get('status', 'Unknown')}")
            print(f"  Volume: ${details.get('volume', 0):.2f}")
        
        # Get price history (current snapshot)
        price_data = client.get_price_history(market_id)
        if price_data:
            all_price_data.extend(price_data)
            
            # Save individual market price history
            client.save_price_history(price_data, market_id)
        
        time.sleep(0.5)  # Rate limiting
    
    # Save combined price data
    if all_price_data:
        combined_file = DATA_DIR / "combined_price_data.csv"
        pd.DataFrame(all_price_data).to_csv(combined_file, index=False)
        print(f"\nSaved combined price data to {combined_file}")
    
    print("\n=== Data Collection Complete ===")
    print(f"Total markets available: {total_markets}")
    print(f"Detailed data collected for: {len(selected_markets)} markets")


if __name__ == "__main__":
    main()
