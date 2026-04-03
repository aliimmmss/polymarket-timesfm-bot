#!/usr/bin/env python3
"""
TimesFM 2.5 Forecasting Script for Polymarket Data
Uses the CORRECT TimesFM 2.5 API
"""

import torch
import numpy as np
import pandas as pd
import timesfm
from datetime import datetime
import json
import os
from pathlib import Path
import sys

# Add timesfm to path if needed
sys.path.append('/tmp/timesfm-install')

def setup_timesfm_model():
    """Initialize TimesFM 2.5 model with correct configuration"""
    print("Initializing TimesFM 2.5 model...")
    
    # CRITICAL: Use TimesFM_2p5_200M_torch.from_pretrained
    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained('google/timesfm-2.5-200m-pytorch')
    
    # CRITICAL: Use ForecastConfig (NOT TimesFmHparams/TimesFmCheckpoint)
    model.compile(
        timesfm.ForecastConfig(
            max_context=256,           # MUST match input length exactly
            max_horizon=12,            # Forecast horizon (12 steps)
            normalize_inputs=False,    # False works better with zero-mean data
            use_continuous_quantile_head=True,
            force_flip_invariance=False,
            infer_is_positive=False,
            fix_quantile_crossing=True,
        )
    )
    
    print("✓ TimesFM 2.5 model initialized")
    print(f"   max_context: {model.forecast_config.max_context}")
    print(f"   max_horizon: {model.forecast_config.max_horizon}")
    print(f"   normalize_inputs: {model.forecast_config.normalize_inputs}")
    return model

def fetch_real_polymarket_data():
    """
    Fetch REAL Polymarket price history data
    Returns: List of dicts with market_id, prices (list of floats)
    """
    print("\nFetching real Polymarket data...")
    
    # TODO: Replace with actual API calls to CLOB API
    # For now, use sample data to demonstrate the pipeline
    
    # Sample real data structure - replace with actual API response
    sample_markets = [
        {
            'market_id': '0x6d0e09d0f04572d9b1',
            'market_name': 'US forces enter Iran by April 30?',
            'prices': np.random.uniform(0.5, 0.8, 256).tolist(),  # 256 points exactly
        },
        {
            'market_id': '0x40b063d0ec332f54c6',
            'market_name': 'Suns vs Hornets',
            'prices': np.random.uniform(0.01, 0.2, 256).tolist(),  # 256 points exactly
        },
        {
            'market_id': '0x9df006923390474e5c',
            'market_name': 'Lakers vs Thunder',
            'prices': np.random.uniform(0.01, 0.1, 256).tolist(),  # 256 points exactly
        },
    ]
    
    print(f"Loaded {len(sample_markets)} markets")
    for market in sample_markets:
        print(f"  {market['market_name']}: {len(market['prices'])} points, "
              f"price range: {min(market['prices']):.3f}-{max(market['prices']):.3f}")
    
    return sample_markets

def prepare_inputs(market_data):
    """Prepare inputs for TimesFM - must be exactly 256 points"""
    prepared_data = []
    
    for market in market_data:
        prices = market['prices']
        
        # CRITICAL: TimesFM requires EXACTLY max_context length (256)
        if len(prices) < 256:
            print(f"Warning: Market {market['market_name']} has only {len(prices)} points, padding...")
            # Pad with mean of existing data
            pad_len = 256 - len(prices)
            mean_price = np.mean(prices)
            prices = [mean_price] * pad_len + prices
        
        elif len(prices) > 256:
            # Use last 256 points
            prices = prices[-256:]
        
        # Convert to numpy array (float32)
        prices_array = np.array(prices, dtype=np.float32)
        
        # Zero-mean normalization (works better with normalize_inputs=False)
        prices_mean = np.mean(prices_array)
        if prices_mean != 0:
            prices_array = prices_array - prices_mean
        
        prepared_data.append({
            **market,
            'prices_array': prices_array,
            'original_mean': prices_mean,
        })
    
    return prepared_data

def run_forecasts(model, prepared_data):
    """Run TimesFM forecasts on prepared data"""
    print("\nRunning TimesFM forecasts...")
    
    results = []
    
    for market in prepared_data:
        print(f"\nForecasting: {market['market_name']}")
        print(f"  Input shape: {market['prices_array'].shape}")
        print(f"  Input range: {market['prices_array'].min():.3f} to {market['prices_array'].max():.3f}")
        
        # CRITICAL: Input must be list of numpy arrays
        point_forecast, quantile_forecast = model.forecast(
            horizon=12,
            inputs=[market['prices_array']]  # List of arrays
        )
        
        # Denormalize if we normalized
        if market['original_mean'] != 0:
            point_forecast = point_forecast + market['original_mean']
            quantile_forecast = quantile_forecast + market['original_mean']
        
        # Ensure forecasts stay in valid range (0-1 for probabilities)
        point_forecast = np.clip(point_forecast, 0.0, 1.0)
        quantile_forecast = np.clip(quantile_forecast, 0.0, 1.0)
        
        # Check for NaN
        has_nan = np.isnan(point_forecast).any()
        
        # Calculate expected return (7-day forecast vs current)
        current_price = market['prices_array'][-1] + market['original_mean']
        forecast_7d = point_forecast[0][6]  # 7th day (index 6)
        expected_return = (forecast_7d - current_price) / current_price * 100
        
        print(f"  Current price: {current_price:.3f}")
        print(f"  7-day forecast: {forecast_7d:.3f}")
        print(f"  Expected return: {expected_return:+.1f}%")
        print(f"  Has NaN: {has_nan}")
        
        results.append({
            'market_id': market['market_id'],
            'market_name': market['market_name'],
            'current_price': float(current_price),
            'forecast_7d': float(forecast_7d),
            'expected_return_pct': float(expected_return),
            'has_nan': bool(has_nan),
            'point_forecast': point_forecast[0].tolist(),
            'quantile_forecast': quantile_forecast[0].tolist(),
            'input_points': len(market['prices_array']),
            'timestamp': datetime.now().isoformat(),
        })
    
    return results

def save_results(results):
    """Save forecast results to file"""
    output_dir = Path.home() / "polymarket-bot" / "data" / "forecasts"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Save JSON
    json_file = output_dir / f"timesfm2p5_forecasts_{timestamp}.json"
    with open(json_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved JSON results to: {json_file}")
    
    # Save CSV
    csv_data = []
    for result in results:
        csv_data.append({
            'market_id': result['market_id'],
            'market_name': result['market_name'],
            'current_price': result['current_price'],
            'forecast_7d': result['forecast_7d'],
            'expected_return_pct': result['expected_return_pct'],
            'has_nan': result['has_nan'],
            'input_points': result['input_points'],
            'timestamp': result['timestamp'],
        })
    
    csv_file = output_dir / f"timesfm2p5_forecasts_{timestamp}.csv"
    pd.DataFrame(csv_data).to_csv(csv_file, index=False)
    print(f"Saved CSV results to: {csv_file}")
    
    return json_file, csv_file

def main():
    print("=" * 60)
    print("TimesFM 2.5 Forecasting Pipeline")
    print("=" * 60)
    
    # Step 1: Setup model
    model = setup_timesfm_model()
    
    # Step 2: Fetch real data
    market_data = fetch_real_polymarket_data()
    
    # Step 3: Prepare inputs
    prepared_data = prepare_inputs(market_data)
    
    # Step 4: Run forecasts
    results = run_forecasts(model, prepared_data)
    
    # Step 5: Save results
    json_file, csv_file = save_results(results)
    
    # Step 6: Summary
    print("\n" + "=" * 60)
    print("FORECASTING COMPLETE")
    print("=" * 60)
    
    nan_count = sum(1 for r in results if r['has_nan'])
    print(f"Markets analyzed: {len(results)}")
    print(f"Markets with NaN forecasts: {nan_count}")
    print(f"Average expected return: {np.mean([r['expected_return_pct'] for r in results]):+.1f}%")
    
    print(f"\nResults saved to:")
    print(f"  JSON: {json_file}")
    print(f"  CSV:  {csv_file}")
    
    # Show sample forecast
    if results:
        print(f"\nSample forecast (first market):")
        result = results[0]
        print(f"  Market: {result['market_name']}")
        print(f"  Current: {result['current_price']:.3f}")
        print(f"  7-day forecast: {result['forecast_7d']:.3f}")
        print(f"  Expected return: {result['expected_return_pct']:+.1f}%")
        print(f"  Point forecast (first 5): {result['point_forecast'][:5]}")
        print(f"  Has NaN: {result['has_nan']}")

if __name__ == "__main__":
    main()