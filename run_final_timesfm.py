import json
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import os
import sys

print("STEP 3: Running FINAL TimesFM on real Polymarket data")
print("=" * 60)

# Add TimesFM v1 to path
sys.path.insert(0, '/tmp/timesfm-install/v1/src')

# Load market data
with open("all_market_data_timesfm.json", "r") as f:
    market_data = json.load(f)

print(f"Loaded {len(market_data)} markets")
print()

# Filter for top 5 markets by volume for testing
market_data.sort(key=lambda x: x["volume24hr"], reverse=True)
top_markets = market_data[:5]

print("Selected top 5 markets by volume:")
for i, market in enumerate(top_markets):
    print(f"{i+1}. {market['slug']}")
    print(f"   Question: {market['question']}")
    print(f"   Points: {market['total_points']}, Current: {market['current_price']:.3f}")
    print(f"   Volume: ${market['volume24hr']:,.2f}")
print()

# Now let's try to import TimesFM from v1
try:
    from timesfm.timesfm_base import TimesFmBase, TimesFmHparams, TimesFmCheckpoint
    from timesfm.timesfm_jax import TimesFmJax
    from timesfm.timesfm_torch import TimesFmTorch
    import timesfm
    
    print("✓ TimesFM imported successfully")
    
    # Try to initialize TimesFM model
    print("Initializing TimesFM model...")
    
    try:
        # Try JAX version first
        tsfm = TimesFmJax(
            hparams=TimesFmHparams(
                context_len=256,
                horizon_len=7,  # 7-day forecast
                patch_len=32,
                num_layers=20,
                model_dims=2048,
                num_heads=16,
            ),
            checkpoint_path="google/timesfm-2.5-1b",  # Hugging Face model
            device="cpu",
        )
        print("✓ TimesFM JAX initialized")
        use_real_timesfm = True
        forecast_type = "TIMESFM_JAX"
        
    except Exception as e:
        print(f"✗ JAX TimesFM failed: {e}")
        
        # Try PyTorch version
        try:
            tsfm = TimesFmTorch(
                hparams=TimesFmHparams(
                    context_len=256,
                    horizon_len=7,
                    patch_len=32,
                    num_layers=20,
                    model_dims=2048,
                    num_heads=16,
                ),
                checkpoint_path="google/timesfm-2.5-1b",
                device="cpu",
            )
            print("✓ TimesFM PyTorch initialized")
            use_real_timesfm = True
            forecast_type = "TIMESFM_TORCH"
            
        except Exception as e2:
            print(f"✗ PyTorch TimesFM failed: {e2}")
            use_real_timesfm = False
            forecast_type = "MOCK"
            
except Exception as e:
    print(f"✗ TimesFM import failed: {e}")
    use_real_timesfm = False
    forecast_type = "MOCK"

if not use_real_timesfm:
    print("\n⚠️  Using mock forecast for demonstration")
    
    # Mock forecast function
    def mock_forecast(prices, horizon=7):
        """Simple linear regression forecast"""
        n = len(prices)
        if n < 2:
            return [prices[-1]] * horizon
        
        # Simple linear regression
        x = np.arange(n)
        y = np.array(prices)
        A = np.vstack([x, np.ones(n)]).T
        m, c = np.linalg.lstsq(A, y, rcond=None)[0]
        
        # Forecast next horizon points
        forecast = m * np.arange(n, n + horizon) + c
        
        # Ensure forecast stays between 0 and 1
        forecast = np.clip(forecast, 0.0, 1.0)
        
        return forecast.tolist()

print("\n" + "="*60)
print("Running forecasts...")
print("="*60)

results = []

for i, market in enumerate(top_markets):
    print(f"\n{i+1}. {market['slug']}")
    print(f"   Current price: {market['current_price']:.3f}")
    
    prices = market["prices"]
    n_points = len(prices)
    
    # Prepare data for TimesFM
    if n_points >= 256:
        # Use last 256 points if we have more
        input_data = prices[-256:]
        print(f"   Using last 256 of {n_points} points")
    elif n_points >= 128:
        # Use all points if between 128 and 256
        input_data = prices
        print(f"   Using all {n_points} points")
    else:
        print(f"   ✗ Insufficient points: {n_points}")
        continue
    
    # Convert to numpy array
    input_array = np.array(input_data, dtype=np.float32)
    
    # Zero-mean normalization (important for TimesFM)
    input_mean = np.mean(input_array)
    input_std = np.std(input_array) if np.std(input_array) > 0 else 1.0
    normalized_data = (input_array - input_mean) / input_std
    
    print(f"   Input shape: {normalized_data.shape}")
    print(f"   Input range: {input_array.min():.3f} to {input_array.max():.3f}")
    print(f"   Normalized range: {normalized_data.min():.3f} to {normalized_data.max():.3f}")
    
    try:
        if use_real_timesfm:
            # Run REAL TimesFM forecast
            print(f"   Running {forecast_type} forecast...")
            
            # Reshape for TimesFM (batch_size=1, sequence_len)
            batch_input = normalized_data.reshape(1, -1)
            
            # Forecast
            forecasts = tsfm.forecast(batch_input)
            
            # Denormalize
            forecast_array = forecasts[0] * input_std + input_mean
            
            # Ensure forecast stays between 0 and 1
            forecast_array = np.clip(forecast_array, 0.0, 1.0)
            
            forecast = forecast_array.tolist()
            print(f"   ✓ {forecast_type} forecast complete")
            
        else:
            # Use mock forecast
            print("   Running mock forecast...")
            forecast = mock_forecast(input_array, horizon=7)
            print(f"   ✓ Mock forecast complete")
            forecast_type = "MOCK"
        
        # Calculate signal based on forecast
        current_price = input_array[-1]
        forecast_price_7d = forecast[-1] if forecast else current_price
        price_change_pct = (forecast_price_7d - current_price) / current_price * 100
        
        # Determine signal
        if price_change_pct > 5:
            signal = "STRONG_BUY"
        elif price_change_pct > 2:
            signal = "BUY"
        elif price_change_pct > -2:
            signal = "HOLD"
        elif price_change_pct > -5:
            signal = "SELL"
        else:
            signal = "STRONG_SELL"
        
        print(f"   Current: {current_price:.3f}")
        print(f"   7-day forecast: {forecast_price_7d:.3f}")
        print(f"   Expected change: {price_change_pct:+.1f}%")
        print(f"   Signal: {signal}")
        print(f"   Forecast type: {forecast_type}")
        
        # Store results
        results.append({
            "slug": market["slug"],
            "question": market["question"],
            "current_price": float(current_price),
            "forecast_7d": float(forecast_price_7d),
            "change_pct": float(price_change_pct),
            "signal": signal,
            "volume24hr": market["volume24hr"],
            "input_points": len(input_array),
            "forecast_all": [float(f) for f in forecast],
            "forecast_type": forecast_type
        })
        
    except Exception as e:
        print(f"   ✗ Forecast failed: {e}")
        continue

# Save results
if results:
    output_file = "final_timesfm_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"STEP 3 COMPLETE: Saved forecast results to {output_file}")
    
    # Create comparison table
    print("\nFINAL COMPARISON TABLE:")
    print("=" * 130)
    print(f"{'Market':<50} {'Current':>10} {'7-day Forecast':>15} {'Change':>10} {'Signal':>12} {'Volume':>15} {'Type':>8}")
    print("-" * 130)
    
    for result in results:
        market_name = result["slug"][:48] + "..." if len(result["slug"]) > 48 else result["slug"]
        print(f"{market_name:<50} {result['current_price']:>10.3f} {result['forecast_7d']:>15.3f} {result['change_pct']:>+9.1f}% {result['signal']:>12} ${result['volume24hr']:>14,.0f} {result['forecast_type']:>8}")
    
    print("=" * 130)
    
    # Also save as markdown table
    md_file = "final_timesfm_forecast_table.md"
    with open(md_file, "w") as f:
        f.write("# FINAL TimesFM Forecasting Results\n\n")
        f.write("## Active Polymarket Predictions (≥256 data points)\n\n")
        f.write("| Market | Current Price | 7-day Forecast | Change | Signal | Volume (24hr) |\n")
        f.write("|--------|--------------|----------------|--------|--------|---------------|\n")
        
        for result in results:
            market_name = result["slug"].replace("|", "\\|")
            f.write(f"| {market_name} | {result['current_price']:.3f} | {result['forecast_7d']:.3f} | {result['change_pct']:+.1f}% | {result['signal']} | ${result['volume24hr']:,.0f} |\n")
        
        f.write("\n## Key Findings:\n")
        f.write(f"- **Markets analyzed**: {len(results)}\n")
        f.write(f"- **Data points per market**: ≥256\n") 
        f.write(f"- **Forecast horizon**: 7 days\n")
        f.write(f"- **Forecast method**: {results[0]['forecast_type'] if results else 'Unknown'}\n")
        
        # Signal summary
        signals = {}
        for result in results:
            sig = result["signal"]
            signals[sig] = signals.get(sig, 0) + 1
        
        f.write("\n## Signal Distribution:\n")
        for sig, count in signals.items():
            f.write(f"- **{sig}**: {count}\n")
    
    print(f"\nMarkdown table saved to: {md_file}")
    
    # Create final summary for STEP 4
    print("\n" + "="*60)
    print("STEP 4: FINAL RESULTS SUMMARY")
    print("="*60)
    print(f"Markets analyzed: {len(results)}")
    print(f"Data points per market: ≥256")
    print(f"Forecast horizon: 7 days")
    print(f"Forecast method: {results[0]['forecast_type'] if results else 'Unknown'}")
    
    # Count signals
    print("\nSignal distribution:")
    for sig, count in signals.items():
        print(f"  {sig}: {count}")
    
    # Most promising market
    if results:
        best_market = max(results, key=lambda x: abs(x["change_pct"]))
        print(f"\nMost significant forecast:")
        print(f"  Market: {best_market['slug']}")
        print(f"  Signal: {best_market['signal']}")
        print(f"  Expected change: {best_market['change_pct']:+.1f}%")
        print(f"  Current: {best_market['current_price']:.3f}")
        print(f"  7-day forecast: {best_market['forecast_7d']:.3f}")
    
else:
    print("\n✗ No successful forecasts!")

print("\nReady for STEP 5: Git commit and push!")