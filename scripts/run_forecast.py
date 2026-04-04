#!/usr/bin/env python3
"""Main entry point: fetch markets -> TimesFM forecast -> save results."""

import sys
import os
import json
import logging
import argparse
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_collection.polymarket_client import PolymarketClient
from src.forecasting.forecaster import TimesFMForecaster
from src.forecasting.signal_generator import SignalGenerator


def setup_logging():
    """Configure logging to file and console."""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    os.makedirs('data/logs', exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(f'data/logs/forecast_{ts}.log'),
        ]
    )
    return logging.getLogger('main')


def main():
    parser = argparse.ArgumentParser(
        description='Run TimesFM forecasts on Polymarket markets'
    )
    parser.add_argument(
        '--markets', type=int, default=10,
        help='Number of markets to fetch (default: 10)'
    )
    parser.add_argument(
        '--horizon', type=int, default=12,
        help='Forecast horizon (default: 12)'
    )
    args = parser.parse_args()
    
    logger = setup_logging()
    logger.info(f'Starting forecast: {args.markets} markets, horizon={args.horizon}')
    
    # Fetch markets
    client = PolymarketClient()
    markets = client.get_active_markets(limit=args.markets)
    logger.info(f'Fetched {len(markets)} markets')
    
    if not markets:
        logger.error('No markets fetched, exiting')
        return 1
    
    # Load TimesFM
    forecaster = TimesFMForecaster()
    results = []
    
    for m in markets:
        # Get clobTokenIds - it's a JSON string in Gamma API
        clob_ids = m.get('clobTokenIds', '')
        if not clob_ids:
            logger.debug(f"No clobTokenIds for {m.get('question', 'unknown')[:40]}")
            continue
        
        # Parse the token ID (first one is YES token)
        try:
            # Handle both JSON string and list formats
            if isinstance(clob_ids, str):
                import json as json_mod
                token_list = json_mod.loads(clob_ids)
            else:
                token_list = clob_ids
            
            if not token_list:
                continue
            token_id = token_list[0] if isinstance(token_list, list) else str(token_list)
        except Exception as e:
            logger.warning(f"Failed to parse clobTokenIds: {e}")
            continue
        
        # Fetch price history
        try:
            history = client.get_price_history(token_id)
            prices = [p['p'] for p in history if 'p' in p]
        except Exception as e:
            logger.warning(f'Failed to fetch {m["question"][:40]}: {e}')
            continue
        
        if len(prices) < 256:
            logger.info(f'SKIP {m["question"][:40]} — only {len(prices)} points')
            continue
        
        current = prices[-1]
        logger.info(f'Processing {m["question"][:50]}... ({len(prices)} points, current={current:.4f})')
        
        # Run forecast
        fc = forecaster.forecast(prices[-1024:], horizon=args.horizon)
        sig = SignalGenerator.generate(fc, current)
        
        results.append({
            'market': m['question'],
            'market_id': m.get('conditionId', ''),
            'data_points': len(prices),
            'current_price': round(current, 6),
            'forecast': fc['point_forecast'],
            'signal': sig['signal'],
            'confidence': sig['confidence'],
            'pct_diff': sig['pct_diff'],
            'has_nan': bool(fc['has_nan']),
        })
        
        logger.info(f'{m["question"][:40]}: {sig["signal"]} ({sig["pct_diff"]:+.2f}%)')
    
    # Save results
    os.makedirs('data/forecasts', exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    outfile = f'data/forecasts/timesfm_{ts}.json'
    
    with open(outfile, 'w') as f:
        json.dump(results, f, indent=2)
    
    logger.info(f'Done: {len(results)} markets forecast. Saved to {outfile}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
