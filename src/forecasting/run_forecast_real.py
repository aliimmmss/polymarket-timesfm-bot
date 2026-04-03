#!/usr/bin/env python3
"""
Run TimesFM forecasts on REAL Polymarket price history data.
Uses actual price history CSV files generated from Gamma API data.
"""

import torch
import numpy as np
import timesfm
from timesfm.timesfm_2p5 import timesfm_2p5_torch
import pandas as pd
from datetime import datetime
import os
import glob
from pathlib import Path

# Configuration
DATA_DIR = Path.home() / "polymarket-bot" / "data"
PRICE_HISTORY_DIR = DATA_DIR / "price_history"
FORECASTS_DIR = DATA_DIR / "forecasts"
FORECASTS_DIR.mkdir(parents=True, exist_ok=True)

def load_timesfm_model():
    """Load and compile TimesFM model"""
    print("Loading TimesFM 2.5 model...")
    model = timesfm_2p5_torch.TimesFM_2p5_200M_torch.from_pretrained('google/timesfm-2.5-200m-pytorch')
    config = timesfm.ForecastConfig(
        max_context=256,
        max_horizon=32,
        normalize_inputs=True,
        use_continuous_quantile_head=False,
    )
    model.compile(config)
    print("Model loaded and compiled")
    return model

def load_price_history_files():
    """Load all price history CSV files from data directory"""
    pattern = str(PRICE_HISTORY_DIR / "price_history_*.csv")
    files = glob.glob(pattern)
    print(f"Found {len(files)} price history files")
    return files

def prepare_input_for_timesfm(price_series):
    """
    Prepare price series for TimesFM input.
    TimesFM requires exactly max_context (256) points.
    """
    if len(price_series) >= 256:
        # Use the most recent 256 points
        return price_series[-256:].astype(np.float32)
    else:
        # Pad with earliest available price
        padding_needed = 256 - len(price_series)
        padded_series = np.pad(price_series, (padding_needed, 0), mode='edge')
        return padded_series.astype(np.float32)

def calculate_mispricing_score(forecast_mean, current_price):
    """Calculate mispricing score (z-score of forecast vs current)"""
    if current_price <= 0 or current_price >= 1:
        return 0
    # Use binomial variance for probability estimates
    variance = current_price * (1 - current_price)
    if variance <= 0:
        return 0
    return (forecast_mean - current_price) / np.sqrt(variance)

def run_forecasts_on_real_data():
    """Run TimesFM forecasts on real Polymarket price history"""
    print("=== REAL TIMESFM FORECASTS WITH POLYMARKET DATA ===")
    print(f"Price history directory: {PRICE_HISTORY_DIR}")
    
    # Load model
    model = load_timesfm_model()
    
    # Load price history files
    price_files = load_price_history_files()
    if not price_files:
        print("ERROR: No price history files found")
        return
    
    forecasts = []
    
    for i, filepath in enumerate(price_files[:5], 1):  # Process first 5 files
        try:
            print(f"\n[{i}/{min(5, len(price_files))}] Processing: {os.path.basename(filepath)}")
            
            # Load CSV data
            df = pd.read_csv(filepath)
            if len(df) == 0:
                print("  SKIPPING: Empty CSV file")
                continue
            
            # Extract price series
            price_series = df['price'].values
            current_price = df['current_price'].iloc[0] if 'current_price' in df.columns else 0.5
            market_name = df['market_name'].iloc[0] if 'market_name' in df.columns else f"Market_{i}"
            condition_id = df['condition_id'].iloc[0] if 'condition_id' in df.columns else "unknown"
            
            print(f"  Market: {market_name[:50]}...")
            print(f"  Data points: {len(price_series)}")
            print(f"  Current price (from Gamma API): {current_price:.4f}")
            print(f"  Price range: [{price_series.min():.4f}, {price_series.max():.4f}]")
            
            # Prepare input for TimesFM
            timesfm_input = prepare_input_for_timesfm(price_series)
            print(f"  TimesFM input shape: {timesfm_input.shape}")
            
            # Run TimesFM forecast
            point_forecast, _ = model.forecast(
                horizon=7,
                inputs=[timesfm_input],
            )
            
            forecast_mean = float(point_forecast[0].mean())
            forecast_values = [round(v, 4) for v in point_forecast[0].tolist()]
            
            # Calculate metrics
            expected_return_pct = round((forecast_mean - current_price) / current_price * 100, 2) if current_price > 0 else 0
            mispricing_score = calculate_mispricing_score(forecast_mean, current_price)
            
            forecasts.append({
                'market_id': condition_id[:20],
                'market_name': market_name[:100],
                'price_history_file': os.path.basename(filepath),
                'current_price': round(current_price, 4),
                'forecast_mean': round(forecast_mean, 4),
                'expected_return_pct': expected_return_pct,
                'mispricing_score': round(mispricing_score, 3),
                'forecast_values': forecast_values,
                'data_points': len(price_series),
                'input_preview': f"[{timesfm_input[0]:.3f}, ..., {timesfm_input[-1]:.3f}]"
            })
            
            print(f"  TimesFM forecast mean: {forecast_mean:.4f}")
            print(f"  Expected return: {expected_return_pct:+.2f}%")
            print(f"  Mispricing score: {mispricing_score:.3f}")
            
        except Exception as e:
            print(f"  ERROR processing {filepath}: {e}")
            import traceback
            traceback.print_exc()
            forecasts.append({
                'market_id': f"error_{i}",
                'market_name': f"Error processing {os.path.basename(filepath)}",
                'price_history_file': os.path.basename(filepath),
                'current_price': None,
                'forecast_mean': None,
                'expected_return_pct': None,
                'mispricing_score': None,
                'forecast_values': None,
                'error': str(e)
            })
    
    # Save results with timestamp
    if forecasts:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = FORECASTS_DIR / f"real_timesfm_forecasts_{timestamp}.csv"
        
        results_df = pd.DataFrame(forecasts)
        results_df.to_csv(output_file, index=False)
        
        print(f"\n=== RESULTS SUMMARY ===")
        print(f"Markets analyzed: {len(forecasts)}")
        print(f"Successful forecasts: {sum(1 for f in forecasts if f['forecast_mean'] is not None)}")
        print(f"Failed forecasts: {sum(1 for f in forecasts if f['forecast_mean'] is None)}")
        print(f"Output saved to: {output_file}")
        
        # Show top opportunities
        valid_forecasts = [f for f in forecasts if f['forecast_mean'] is not None]
        if valid_forecasts:
            sorted_by_return = sorted(valid_forecasts, 
                                    key=lambda x: x['expected_return_pct'] if x['expected_return_pct'] is not None else -999, 
                                    reverse=True)
            
            print("\n=== TOP BUY OPPORTUNITIES (Highest Expected Return) ===")
            for f in sorted_by_return[:3]:
                if f['expected_return_pct'] is not None and f['expected_return_pct'] > 0:
                    print(f"{f['market_name'][:40]}...")
                    print(f"  Current: {f['current_price']}, Forecast: {f['forecast_mean']}")
                    print(f"  Return: {f['expected_return_pct']:+.2f}%, Score: {f['mispricing_score']:.3f}")
            
            print("\n=== TOP SELL OPPORTUNITIES (Lowest Expected Return) ===")
            for f in sorted_by_return[-3:]:
                if f['expected_return_pct'] is not None and f['expected_return_pct'] < 0:
                    print(f"{f['market_name'][:40]}...")
                    print(f"  Current: {f['current_price']}, Forecast: {f['forecast_mean']}")
                    print(f"  Return: {f['expected_return_pct']:+.2f}%, Score: {f['mispricing_score']:.3f}")
        
        # Show sample forecast values
        if valid_forecasts:
            print("\n=== SAMPLE FORECAST VALUES ===")
            sample = valid_forecasts[0]
            print(f"Market: {sample['market_name'][:50]}...")
            print(f"Forecast values (7-day): {sample['forecast_values']}")
    
    else:
        print("ERROR: No forecasts generated")

def main():
    """Main execution function"""
    print("Running TimesFM forecasts on REAL Polymarket price history...")
    run_forecasts_on_real_data()

if __name__ == "__main__":
    main()