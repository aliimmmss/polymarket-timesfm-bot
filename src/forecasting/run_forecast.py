#!/usr/bin/env python3
"""
TimesFM Forecasting for Polymarket Markets
Loads market data and forecasts price movements for the next 1-7 days
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import os
import json
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# Configuration
DATA_DIR = Path.home() / "polymarket-bot" / "data"
OUTPUT_DIR = DATA_DIR / "forecasts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

class TimesFMForecaster:
    def __init__(self):
        """Initialize TimesFM forecaster"""
        self.model = None
        self.context_length = 512
        self.horizon = 7
        
        # Try to import TimesFM
        try:
            import timesfm
            self.timesfm_available = True
            print("TimesFM imported successfully")
        except ImportError:
            self.timesfm_available = False
            print("TimesFM not available - using mock forecasts")
    
    def load_market_data(self, market_file="markets.csv"):
        """Load Polymarket market data"""
        try:
            filepath = DATA_DIR / market_file
            df = pd.read_csv(filepath)
            print(f"Loaded {len(df)} markets from {filepath}")
            
            # Filter active markets
            active_markets = df[df['active'] == True].copy()
            print(f"Active markets: {len(active_markets)}")
            
            # Parse dates
            if 'end_date_iso' in active_markets.columns:
                active_markets['end_date'] = pd.to_datetime(active_markets['end_date_iso'], errors='coerce')
            
            # Extract relevant columns
            market_data = []
            for _, row in active_markets.iterrows():
                market = {
                    'condition_id': row.get('condition_id', ''),
                    'question': row.get('question', ''),
                    'market_slug': row.get('market_slug', ''),
                    'end_date': row.get('end_date', None),
                    'active': row.get('active', False),
                }
                market_data.append(market)
            
            return market_data
        except Exception as e:
            print(f"Error loading market data: {e}")
            return []
    
    def generate_mock_price_series(self, market_id, days=30):
        """Generate mock price series for demonstration"""
        np.random.seed(hash(market_id) % 10000)
        
        # Base price between 0.1 and 0.9
        base_price = 0.3 + (hash(market_id) % 700) / 1000
        
        dates = [datetime.now() - timedelta(days=i) for i in range(days, 0, -1)]
        
        # Generate price series with some trend and randomness
        prices = []
        trend = np.random.uniform(-0.02, 0.02)
        
        for i in range(days):
            noise = np.random.normal(0, 0.05)
            price = base_price + trend * i + noise
            price = max(0.01, min(0.99, price))
            prices.append(price)
        
        return pd.DataFrame({
            'date': dates,
            'price': prices,
            'market_id': market_id
        })
    
    def forecast_with_timesfm(self, price_series, horizon=7):
        """Forecast using TimesFM"""
        if not self.timesfm_available:
            print("TimesFM not available, using mock forecast")
            return self._mock_forecast(price_series, horizon)
        
        try:
            import timesfm
            
            # Prepare time series data
            prices = price_series['price'].values
            
            # Ensure we have enough data
            if len(prices) < 10:
                print(f"Not enough data for forecast (needs at least 10 points, got {len(prices)})")
                return self._mock_forecast(price_series, horizon)
            
            # For demo, use mock forecast even if TimesFM is available
            print("Using TimesFM mock forecast for demonstration")
            return self._mock_forecast(price_series, horizon)
            
        except Exception as e:
            print(f"Error using TimesFM: {e}")
            return self._mock_forecast(price_series, horizon)
    
    def _mock_forecast(self, price_series, horizon):
        """Generate mock forecast for demonstration"""
        prices = price_series['price'].values
        
        if len(prices) < 5:
            return [prices[-1]] * horizon if len(prices) > 0 else [0.5] * horizon
        
        # Simple forecast: extrapolate with slight noise
        last_price = prices[-1]
        second_last = prices[-2] if len(prices) > 1 else last_price
        trend = last_price - second_last
        
        forecast = []
        for i in range(horizon):
            noise = np.random.normal(0, 0.02)
            forecast_price = last_price + trend * (i + 1) * 0.5 + noise
            forecast_price = max(0.01, min(0.99, forecast_price))
            forecast.append(forecast_price)
        
        return forecast
    
    def calculate_mispricing(self, current_price, forecast_prices):
        """Calculate mispricing metrics"""
        if not forecast_prices:
            return {'mispricing_score': 0, 'forecast_mean': current_price, 'forecast_std': 0}
        
        forecast_mean = np.mean(forecast_prices)
        forecast_std = np.std(forecast_prices)
        
        # Mispricing score: difference between current price and forecast mean
        mispricing_score = (forecast_mean - current_price) / max(forecast_std, 0.01)
        
        return {
            'mispricing_score': mispricing_score,
            'forecast_mean': forecast_mean,
            'forecast_std': forecast_std,
            'current_price': current_price,
        }
    
    def analyze_markets(self, num_markets=5, forecast_horizon=7):
        """Analyze multiple markets and identify mispriced opportunities"""
        print("\n=== TimesFM Market Analysis ===")
        
        # Load market data
        markets = self.load_market_data()
        if not markets:
            print("No market data available")
            return []
        
        # Select markets for analysis
        selected_markets = markets[:min(num_markets, len(markets))]
        
        analysis_results = []
        
        for i, market in enumerate(selected_markets, 1):
            market_id = market.get('condition_id', '')
            question = market.get('question', 'Unknown')[:50] + "..."
            
            print(f"\n[{i}/{len(selected_markets)}] Analyzing: {question}")
            
            # Generate mock price series
            price_series = self.generate_mock_price_series(market_id, days=30)
            
            if len(price_series) < 10:
                print(f"  Insufficient data for {market_id[:10]}...")
                continue
            
            current_price = price_series['price'].iloc[-1]
            print(f"  Current mock price: {current_price:.3f}")
            
            # Generate forecast
            forecast_prices = self.forecast_with_timesfm(price_series, forecast_horizon)
            
            # Calculate mispricing
            mispricing = self.calculate_mispricing(current_price, forecast_prices)
            
            result = {
                'market_id': market_id,
                'question': market.get('question', ''),
                'market_slug': market.get('market_slug', ''),
                'current_price': current_price,
                'forecast_mean': mispricing['forecast_mean'],
                'forecast_std': mispricing['forecast_std'],
                'mispricing_score': mispricing['mispricing_score'],
                'forecast_prices': forecast_prices,
                'recommendation': self._generate_recommendation(mispricing['mispricing_score'])
            }
            
            analysis_results.append(result)
            
            print(f"  Forecast mean: {mispricing['forecast_mean']:.3f}")
            print(f"  Mispricing score: {mispricing['mispricing_score']:.3f}")
            print(f"  Recommendation: {result['recommendation']}")
        
        # Sort by absolute mispricing
        analysis_results.sort(key=lambda x: abs(x['mispricing_score']), reverse=True)
        
        # Save results
        self._save_results(analysis_results)
        
        return analysis_results
    
    def _generate_recommendation(self, mispricing_score):
        """Generate trading recommendation"""
        abs_score = abs(mispricing_score)
        
        if abs_score < 0.5:
            return "HOLD"
        elif mispricing_score > 0:
            if abs_score < 1.0:
                return "BUY"
            elif abs_score < 2.0:
                return "STRONG BUY"
            else:
                return "AGGRESSIVE BUY"
        else:
            if abs_score < 1.0:
                return "SELL"
            elif abs_score < 2.0:
                return "STRONG SELL"
            else:
                return "AGGRESSIVE SELL"
    
    def _save_results(self, analysis_results):
        """Save analysis results"""
        try:
            filename = f"market_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            filepath = OUTPUT_DIR / filename
            
            # Convert to DataFrame
            df_data = []
            for result in analysis_results:
                df_data.append({
                    'market_id': result['market_id'],
                    'question': result['question'][:100],
                    'current_price': result['current_price'],
                    'forecast_mean': result['forecast_mean'],
                    'forecast_std': result['forecast_std'],
                    'mispricing_score': result['mispricing_score'],
                    'recommendation': result['recommendation'],
                    'abs_mispricing': abs(result['mispricing_score'])
                })
            
            df = pd.DataFrame(df_data)
            df.to_csv(filepath, index=False)
            
            print(f"\nSaved analysis to {filepath}")
            print(f"Total markets analyzed: {len(df)}")
            
        except Exception as e:
            print(f"Error saving results: {e}")
    
    def print_summary(self, analysis_results):
        """Print summary of analysis"""
        print("\n=== MARKET MISPRICING SUMMARY ===")
        print(f"{'Market':<30} {'Curr Price':>10} {'Forecast':>10} {'Mispricing':>12} {'Recommendation':<20}")
        print("-" * 90)
        
        for result in analysis_results[:10]:
            question_short = (result['question'][:27] + "...") if len(result['question']) > 30 else result['question']
            print(f"{question_short:<30} {result['current_price']:>10.3f} {result['forecast_mean']:>10.3f} {result['mispricing_score']:>12.3f} {result['recommendation']:<20}")
        
        print("\n=== TOP OPPORTUNITIES ===")
        
        # Top buys
        buys = [r for r in analysis_results if r['mispricing_score'] > 0.5]
        if buys:
            print("\nTop BUY opportunities (most underpriced):")
            for i, buy in enumerate(buys[:3], 1):
                print(f"{i}. {buy['question'][:50]}...")
                print(f"   Current: {buy['current_price']:.3f}, Forecast: {buy['forecast_mean']:.3f}, Score: {buy['mispricing_score']:.3f}")
        
        # Top sells
        sells = [r for r in analysis_results if r['mispricing_score'] < -0.5]
        if sells:
            print("\nTop SELL opportunities (most overpriced):")
            for i, sell in enumerate(sells[:3], 1):
                print(f"{i}. {sell['question'][:50]}...")
                print(f"   Current: {sell['current_price']:.3f}, Forecast: {sell['forecast_mean']:.3f}, Score: {sell['mispricing_score']:.3f}")

def main():
    """Main function to run TimesFM forecasting"""
    print("=== TimesFM Polymarket Forecasting ===")
    print(f"Data directory: {DATA_DIR}")
    print(f"Forecast horizon: 7 days")
    
    forecaster = TimesFMForecaster()
    
    # Analyze markets
    analysis_results = forecaster.analyze_markets(num_markets=10, forecast_horizon=7)
    
    if analysis_results:
        # Print summary
        forecaster.print_summary(analysis_results)
        
        print("\n=== Files Generated ===")
        print(f"Forecast files saved to: {OUTPUT_DIR}")
        print(f"Total markets analyzed: {len(analysis_results)}")
        
        # Show top opportunity
        top = analysis_results[0]
        print(f"\nTop opportunity: {top['question'][:60]}...")
        print(f"Mispricing score: {top['mispricing_score']:.3f} ({top['recommendation']})")
    else:
        print("No analysis results generated")

if __name__ == "__main__":
    main()
