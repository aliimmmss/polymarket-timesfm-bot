import json
import numpy as np
import pandas as pd
import pickle
from datetime import datetime
import matplotlib.pyplot as plt
from timesfm import TimesFm

def load_polymarket_data(file_path="polymarket_data.json"):
    """Load previously fetched Polymarket data."""
    with open(file_path, "r") as f:
        return json.load(f)

def prepare_timesfm_input(data, max_context=256):
    """Prepare data for TimesFM model."""
    # Extract YES prices
    prices = np.array(data["yes_prices"])
    
    # Normalize to zero mean (important for TimesFM)
    mean_price = np.mean(prices)
    normalized_prices = prices - mean_price
    
    # Pad or truncate to max_context length
    if len(normalized_prices) < max_context:
        # Pad with zeros (or repeat last value)
        padding = np.zeros(max_context - len(normalized_prices))
        input_series = np.concatenate([normalized_prices, padding])
    elif len(normalized_prices) > max_context:
        # Truncate to max_context
        input_series = normalized_prices[:max_context]
    else:
        input_series = normalized_prices
    
    return input_series, mean_price

def forecast_with_timesfm(input_series, horizon=24, max_context=256):
    """Run TimesFM forecast."""
    try:
        # Initialize TimesFM
        print("Initializing TimesFM model...")
        model = TimesFm()
        
        # Reshape input for TimesFM (batch_size=1, sequence_length=max_context, n_variates=1)
        input_array = input_series.reshape(1, max_context, 1)
        
        print(f"Input shape: {input_array.shape}")
        print(f"Input range: {input_array.min():.3f} to {input_array.max():.3f}")
        
        # Run forecast
        print(f"Running forecast for horizon={horizon}...")
        forecasts, forecast_times = model.forecast_on_array(
            input_array,
            horizon=horizon,
            exogenous_vars=None,
            freq="H"  # Hourly frequency
        )
        
        return forecasts, forecast_times
        
    except Exception as e:
        print(f"Error in TimesFM forecast: {e}")
        return None, None

def analyze_market_forecasts(data_list, horizon=24):
    """Analyze multiple markets with TimesFM."""
    results = []
    
    for data in data_list:
        print(f"\n{'='*60}")
        print(f"Analyzing market: {data['slug']}")
        print(f"Question: {data['question']}")
        
        # Prepare input for TimesFM
        input_series, mean_price = prepare_timesfm_input(data)
        
        print(f"Original price range: {min(data['yes_prices']):.3f} to {max(data['yes_prices']):.3f}")
        print(f"Mean price: {mean_price:.3f}")
        print(f"Input series shape: {input_series.shape}")
        print(f"Input series range: {input_series.min():.3f} to {input_series.max():.3f}")
        
        # Run forecast
        forecasts, forecast_times = forecast_with_timesfm(input_series, horizon=horizon)
        
        if forecasts is not None:
            # Denormalize forecasts
            forecast_prices = forecasts[0, :, 0] + mean_price
            
            # Clip to [0, 1] range (price should be between 0 and 1)
            forecast_prices = np.clip(forecast_prices, 0, 1)
            
            print(f"\nForecast results:")
            print(f"Forecast shape: {forecast_prices.shape}")
            print(f"Forecast range: {forecast_prices.min():.3f} to {forecast_prices.max():.3f}")
            
            # Calculate forecast metrics
            forecast_mean = np.mean(forecast_prices)
            forecast_std = np.std(forecast_prices)
            forecast_trend = forecast_prices[-1] - forecast_prices[0]
            
            print(f"Forecast mean: {forecast_mean:.3f}")
            print(f"Forecast std: {forecast_std:.3f}")
            print(f"Forecast trend (final - initial): {forecast_trend:.3f}")
            
            # Determine recommendation
            current_price = data["yes_prices"][-1]
            forecast_final = forecast_prices[-1]
            
            if forecast_final > current_price:
                recommendation = "BUY"
                confidence = abs(forecast_final - current_price)
            elif forecast_final < current_price:
                recommendation = "SELL"
                confidence = abs(forecast_final - current_price)
            else:
                recommendation = "HOLD"
                confidence = 0
            
            print(f"\nTrading Recommendation:")
            print(f"Current price: {current_price:.3f}")
            print(f"Forecast final price: {forecast_final:.3f}")
            print(f"Action: {recommendation}")
            print(f"Confidence: {confidence:.3f}")
            
            # Save results
            results.append({
                "market_slug": data["slug"],
                "question": data["question"],
                "current_price": float(current_price),
                "forecast_prices": forecast_prices.tolist(),
                "forecast_mean": float(forecast_mean),
                "forecast_std": float(forecast_std),
                "forecast_trend": float(forecast_trend),
                "recommendation": recommendation,
                "confidence": float(confidence),
                "volume24hr": data["volume24hr"],
                "liquidity": data["liquidity"]
            })
            
            # Plot results
            plot_forecast(data, forecast_prices)
            
        else:
            print("Forecast failed for this market")
    
    return results

def plot_forecast(data, forecast_prices):
    """Plot historical prices and forecast."""
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # Historical prices
    historical_prices = data["yes_prices"]
    timestamps = data["timestamps"]
    
    # Convert timestamps for plotting
    hist_times = list(range(len(historical_prices)))
    forecast_times = list(range(len(historical_prices), len(historical_prices) + len(forecast_prices)))
    
    # Plot historical
    ax.plot(hist_times, historical_prices, 'b-', label='Historical Prices', linewidth=2)
    
    # Plot forecast
    ax.plot(forecast_times, forecast_prices, 'r--', label='TimesFM Forecast', linewidth=2)
    
    # Mark current price
    ax.axhline(y=historical_prices[-1], color='g', linestyle=':', label='Current Price')
    
    ax.set_xlabel('Time Steps')
    ax.set_ylabel('YES Token Price')
    ax.set_title(f'{data["slug"]}\n{data["question"]}')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(f'forecast_{data["slug"]}.png', dpi=150)
    plt.close()
    
    print(f"Plot saved as forecast_{data['slug']}.png")

def main():
    print("Polymarket TimesFM Forecasting Analysis")
    print("=" * 60)
    
    # Load data
    try:
        data_list = load_polymarket_data()
        print(f"Loaded data for {len(data_list)} markets")
    except Exception as e:
        print(f"Error loading data: {e}")
        return
    
    # Run forecasts
    results = analyze_market_forecasts(data_list, horizon=24)
    
    # Save results
    if results:
        output_file = "timesfm_forecast_results.json"
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\n{'='*60}")
        print(f"Saved forecast results to {output_file}")
        
        # Summary
        print("\nForecast Summary:")
        for result in results:
            print(f"{result['market_slug']}: {result['recommendation']} "
                  f"(current: {result['current_price']:.3f}, "
                  f"forecast: {result['forecast_mean']:.3f} ± {result['forecast_std']:.3f}, "
                  f"confidence: {result['confidence']:.3f})")

if __name__ == "__main__":
    main()