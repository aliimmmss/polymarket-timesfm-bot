import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from scipy import stats

def load_polymarket_data(file_path="polymarket_data.json"):
    """Load previously fetched Polymarket data."""
    with open(file_path, "r") as f:
        return json.load(f)

def analyze_trend(prices):
    """Analyze price trend using linear regression."""
    x = np.arange(len(prices))
    slope, intercept, r_value, p_value, std_err = stats.linregress(x, prices)
    
    return {
        "slope": slope,
        "intercept": intercept,
        "r_squared": r_value**2,
        "p_value": p_value,
        "std_err": std_err,
        "trend": "UP" if slope > 0 else "DOWN",
        "strength": abs(slope) * len(prices)  # Simple strength metric
    }

def forecast_simple(prices, horizon=24):
    """Simple forecasting using linear regression."""
    if len(prices) < 2:
        return None
    
    x = np.arange(len(prices))
    slope, intercept, _, _, _ = stats.linregress(x, prices)
    
    # Extend forecast
    forecast_x = np.arange(len(prices), len(prices) + horizon)
    forecast_prices = intercept + slope * forecast_x
    
    # Clip to [0, 1] range
    forecast_prices = np.clip(forecast_prices, 0, 1)
    
    return forecast_prices

def calculate_volatility(prices):
    """Calculate volatility metrics."""
    returns = np.diff(prices) / prices[:-1]
    
    return {
        "volatility": np.std(returns) * np.sqrt(252 * 24),  # Annualized assuming hourly data
        "max_drawdown": calculate_max_drawdown(prices),
        "sharpe_ratio": calculate_sharpe_ratio(returns) if len(returns) > 0 else 0
    }

def calculate_max_drawdown(prices):
    """Calculate maximum drawdown."""
    peak = prices[0]
    max_dd = 0
    
    for price in prices:
        if price > peak:
            peak = price
        dd = (peak - price) / peak
        if dd > max_dd:
            max_dd = dd
    
    return max_dd

def calculate_sharpe_ratio(returns, risk_free_rate=0.02):
    """Calculate Sharpe ratio."""
    if len(returns) == 0 or np.std(returns) == 0:
        return 0
    
    excess_returns = returns - risk_free_rate / (252 * 24)  # Hourly risk-free rate
    return np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252 * 24)

def generate_trading_signals(data):
    """Generate trading signals based on analysis."""
    prices = np.array(data["yes_prices"])
    current_price = prices[-1]
    
    # Trend analysis
    trend = analyze_trend(prices[-20:])  # Look at last 20 points
    forecast = forecast_simple(prices, horizon=24)
    volatility = calculate_volatility(prices)
    
    if forecast is None:
        return None
    
    # Calculate expected return
    expected_return = forecast[-1] - current_price
    
    # Risk-adjusted return
    risk_adjusted_return = expected_return / (volatility["volatility"] + 1e-6)
    
    # Generate signal
    if expected_return > 0.05:  # 5% expected return threshold
        signal = "STRONG_BUY"
    elif expected_return > 0.02:
        signal = "BUY"
    elif expected_return < -0.05:
        signal = "STRONG_SELL"
    elif expected_return < -0.02:
        signal = "SELL"
    else:
        signal = "HOLD"
    
    # Confidence score (0-100)
    confidence = min(100, abs(expected_return) * 1000 + trend["r_squared"] * 50)
    
    return {
        "signal": signal,
        "confidence": confidence,
        "expected_return": expected_return,
        "risk_adjusted_return": risk_adjusted_return,
        "trend_strength": trend["strength"],
        "volatility": volatility["volatility"],
        "max_drawdown": volatility["max_drawdown"],
        "forecast_final": forecast[-1]
    }

def plot_analysis(data, signals, forecast_prices=None):
    """Plot analysis results."""
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    
    prices = np.array(data["yes_prices"])
    timestamps = data["timestamps"]
    
    # Plot 1: Price history
    ax1 = axes[0, 0]
    ax1.plot(prices, 'b-', linewidth=2)
    ax1.set_xlabel('Time Steps')
    ax1.set_ylabel('YES Token Price')
    ax1.set_title(f'Price History: {data["slug"]}')
    ax1.grid(True, alpha=0.3)
    
    # Add buy/sell markers if significant signal
    if signals["signal"] in ["STRONG_BUY", "BUY"]:
        ax1.plot(len(prices)-1, prices[-1], 'g^', markersize=10, label=f'{signals["signal"]}')
    elif signals["signal"] in ["STRONG_SELL", "SELL"]:
        ax1.plot(len(prices)-1, prices[-1], 'rv', markersize=10, label=f'{signals["signal"]}')
    
    ax1.legend()
    
    # Plot 2: Returns distribution
    ax2 = axes[0, 1]
    returns = np.diff(prices) / prices[:-1]
    ax2.hist(returns, bins=20, alpha=0.7, edgecolor='black')
    ax2.set_xlabel('Returns')
    ax2.set_ylabel('Frequency')
    ax2.set_title(f'Returns Distribution (Volatility: {signals["volatility"]:.3f})')
    ax2.axvline(x=0, color='r', linestyle='--')
    ax2.grid(True, alpha=0.3)
    
    # Plot 3: Forecast if available
    ax3 = axes[1, 0]
    if forecast_prices is not None:
        ax3.plot(prices, 'b-', label='Historical', linewidth=2)
        ax3.plot(range(len(prices), len(prices) + len(forecast_prices)), 
                forecast_prices, 'r--', label='Forecast', linewidth=2)
        ax3.axhline(y=prices[-1], color='g', linestyle=':', label='Current Price')
        ax3.set_xlabel('Time Steps')
        ax3.set_ylabel('Price')
        ax3.set_title(f'Forecast (Expected Return: {signals["expected_return"]:.3f})')
        ax3.legend()
        ax3.grid(True, alpha=0.3)
    
    # Plot 4: Metrics visualization
    ax4 = axes[1, 1]
    metrics = {
        'Expected Return': signals["expected_return"],
        'Volatility': signals["volatility"],
        'Max Drawdown': signals["max_drawdown"],
        'Trend Strength': signals["trend_strength"]
    }
    
    colors = ['green' if val > 0 else 'red' for val in [signals["expected_return"], 
                                                       -signals["volatility"], 
                                                       -signals["max_drawdown"],
                                                       abs(signals["trend_strength"])]]
    
    bars = ax4.bar(range(len(metrics)), list(metrics.values()), color=colors)
    ax4.set_xlabel('Metrics')
    ax4.set_ylabel('Value')
    ax4.set_title('Trading Metrics')
    ax4.set_xticks(range(len(metrics)))
    ax4.set_xticklabels(list(metrics.keys()), rotation=45)
    ax4.grid(True, alpha=0.3, axis='y')
    
    # Add value labels
    for bar, val in zip(bars, metrics.values()):
        ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height(), 
                f'{val:.3f}', ha='center', va='bottom')
    
    plt.suptitle(f'{data["question"]}\nSignal: {signals["signal"]} (Confidence: {signals["confidence"]:.1f}%)', 
                fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(f'analysis_{data["slug"]}.png', dpi=150)
    plt.close()

def main():
    print("Polymarket Trading Analysis")
    print("=" * 60)
    
    # Load data
    try:
        data_list = load_polymarket_data()
        print(f"Loaded data for {len(data_list)} markets")
    except Exception as e:
        print(f"Error loading data: {e}")
        return
    
    results = []
    
    for data in data_list:
        print(f"\n{'='*60}")
        print(f"Analyzing: {data['slug']}")
        print(f"Question: {data['question']}")
        print(f"Current price: {data['yes_prices'][-1]:.3f}")
        print(f"Data points: {len(data['yes_prices'])}")
        print(f"Volume 24hr: ${data['volume24hr']:.2f}")
        print(f"Liquidity: ${float(data['liquidity']):.2f}")
        
        # Generate trading signals
        signals = generate_trading_signals(data)
        
        if signals:
            print(f"\nAnalysis Results:")
            print(f"  Signal: {signals['signal']}")
            print(f"  Confidence: {signals['confidence']:.1f}%")
            print(f"  Expected Return: {signals['expected_return']:.3f}")
            print(f"  Risk-Adjusted Return: {signals['risk_adjusted_return']:.3f}")
            print(f"  Volatility: {signals['volatility']:.3f}")
            print(f"  Max Drawdown: {signals['max_drawdown']:.3f}")
            
            # Forecast for visualization
            forecast_prices = forecast_simple(np.array(data["yes_prices"]), horizon=24)
            
            # Plot analysis
            plot_analysis(data, signals, forecast_prices)
            print(f"  Plot saved as analysis_{data['slug']}.png")
            
            # Save results
            results.append({
                "market_slug": data["slug"],
                "question": data["question"],
                "current_price": float(data["yes_prices"][-1]),
                "signal": signals["signal"],
                "confidence": float(signals["confidence"]),
                "expected_return": float(signals["expected_return"]),
                "risk_adjusted_return": float(signals["risk_adjusted_return"]),
                "volatility": float(signals["volatility"]),
                "max_drawdown": float(signals["max_drawdown"]),
                "volume24hr": data["volume24hr"],
                "liquidity": data["liquidity"]
            })
    
    # Save all results
    if results:
        output_file = "trading_analysis_results.json"
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\n{'='*60}")
        print(f"Saved analysis results to {output_file}")
        
        # Summary report
        print("\nTrading Recommendations Summary:")
        print("-" * 60)
        
        # Sort by confidence
        results.sort(key=lambda x: x["confidence"], reverse=True)
        
        for result in results:
            print(f"{result['market_slug'][:30]:30} | "
                  f"{result['signal']:12} | "
                  f"Conf: {result['confidence']:5.1f}% | "
                  f"ExpReturn: {result['expected_return']:7.3f} | "
                  f"Vol: {result['volatility']:6.3f} | "
                  f"Volume: ${result['volume24hr']:,.0f}")

if __name__ == "__main__":
    main()