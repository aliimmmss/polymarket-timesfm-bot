import torch
import numpy as np
import timesfm
import json
from datetime import datetime

torch.set_float32_matmul_precision('high')
print('Loading TimesFM 2.5...')
model = timesfm.TimesFM_2p5_200M_torch.from_pretrained('google/timesfm-2.5-200m-pytorch')
print('Compiling model...')
model.compile(
    timesfm.ForecastConfig(
        max_context=1024,
        max_horizon=256,
        normalize_inputs=True,
        use_continuous_quantile_head=True,
        force_flip_invariance=True,
        infer_is_positive=True,
        fix_quantile_crossing=True,
    )
)
print('Model ready!')

# Load existing market data
print('Loading market data from all_market_data_timesfm.json...')
with open('all_market_data_timesfm.json', 'r') as f:
    markets_data = json.load(f)

print(f'Loaded {len(markets_data)} markets')
results = []

for m in markets_data:
    question = m.get('question', 'Unknown')
    prices = m.get('prices', [])
    
    if not isinstance(prices, list) or len(prices) < 256:
        continue
        
    # Trim to last 1024 points (max_context)
    prices_trimmed = prices[-1024:]
    print(f'\nForecasting: {question[:60]}')
    print(f'  Data points: {len(prices_trimmed)}, Current price: {prices_trimmed[-1]:.4f}')
    
    try:
        point, quantile = model.forecast(horizon=12, inputs=[prices_trimmed])
        has_nan = bool(np.isnan(point).any())
        forecast_vals = point[0].tolist() if len(point.shape) > 1 else point.tolist()
        current = prices_trimmed[-1]
        avg_forecast = sum(forecast_vals) / len(forecast_vals)
        print(f'  Forecast (12 steps): {[round(x,4) for x in forecast_vals]}')
        print(f'  Avg forecast: {avg_forecast:.4f}')
        print(f'  Signal: {"BULLISH" if avg_forecast > current else "BEARISH"}')
        print(f'  Has NaN: {has_nan}')
        results.append({
            'market': question,
            'data_points': len(prices_trimmed),
            'current_price': float(current),
            'forecast_12': [round(float(x),6) for x in forecast_vals],
            'avg_forecast': round(float(avg_forecast),6),
            'signal': 'BULLISH' if avg_forecast > current else 'BEARISH',
            'has_nan': has_nan,
        })
    except Exception as e:
        print(f'  ERROR: {e}')
        # If normalize=True fails with NaN, try False
        try:
            model.compile(timesfm.ForecastConfig(
                max_context=1024, max_horizon=256, normalize_inputs=False,
                use_continuous_quantile_head=True, force_flip_invariance=True,
            ))
            point, quantile = model.forecast(horizon=12, inputs=[prices_trimmed])
            forecast_vals = point[0].tolist()
            print(f'  RETRY (normalize=False) OK: {[round(x,4) for x in forecast_vals]}')
            results.append({
                'market': question,
                'data_points': len(prices_trimmed),
                'current_price': float(prices_trimmed[-1]),
                'forecast_12': [round(float(x),6) for x in forecast_vals],
                'has_nan': bool(np.isnan(point).any()),
                'signal': 'BULLISH' if sum(forecast_vals)/len(forecast_vals) > prices_trimmed[-1] else 'BEARISH',
            })
        except Exception as e2:
            print(f'  RETRY ALSO FAILED: {e2}')

# Save results
ts = datetime.now().strftime('%Y%m%d_%H%M%S')
outfile = f'data/forecasts/real_timesfm_{ts}.json'
with open(outfile, 'w') as f:
    json.dump(results, f, indent=2)
print(f'\n=== DONE: {len(results)} markets forecast ===')
print(f'Saved to: {outfile}')