#!/usr/bin/env python3
"""BTC 15-Minute Market Forecast Pipeline.

Fetches BTC price data from CoinGecko, runs TimesFM forecast,
compares to Polymarket BTC 15-min market odds, and generates trading signals.
"""

import sys
import os
import json
import logging
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_collection.btc_price_fetcher import BTCPriceFetcher
from src.data_collection.polymarket_client import PolymarketBTCClient
from src.forecasting.forecaster import TimesFMForecaster
from src.forecasting.signal_generator import BTCSignalGenerator


def main():
    parser = argparse.ArgumentParser(description='BTC 15-min market forecaster')
    parser.add_argument('--markets', type=int, default=3, help='Number of upcoming markets to check')
    parser.add_argument('--horizon', type=int, default=15, help='Forecast steps')
    args = parser.parse_args()
    
    # Setup directories
    os.makedirs('data/logs', exist_ok=True)
    os.makedirs('data/forecasts', exist_ok=True)
    os.makedirs('data/price_history', exist_ok=True)
    
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(f'data/logs/btc_{ts}.log'),
        ]
    )
    logger = logging.getLogger('main')
    
    # 1. Get BTC price data from CoinGecko
    logger.info('='*60)
    logger.info('STEP 1: FETCHING BTC PRICE DATA FROM COINGECKO')
    logger.info('='*60)
    btc_fetcher = BTCPriceFetcher()
    btc_hourly = btc_fetcher.get_hourly_prices(days=30)
    btc_current = btc_fetcher.get_current_price()
    logger.info(f'BTC current price: ${btc_current:.2f} ({len(btc_hourly)} hourly data points)')
    
    # 2. Get active BTC 15-min markets from Polymarket
    logger.info('')
    logger.info('='*60)
    logger.info('STEP 2: FINDING ACTIVE BTC 15-MIN MARKETS')
    logger.info('='*60)
    poly_client = PolymarketBTCClient()
    markets = poly_client.find_active_btc_markets(count=args.markets)
    logger.info(f'Found {len(markets)} active markets')
    
    if not markets:
        logger.warning('No active BTC 15-min markets found. Markets may not exist yet.')
        return
    
    # 3. Load TimesFM model
    logger.info('')
    logger.info('='*60)
    logger.info('STEP 3: LOADING TIMESFM 2.5 MODEL')
    logger.info('='*60)
    forecaster = TimesFMForecaster()
    
    # 4. Process each market
    results = []
    for m in markets:
        logger.info('')
        logger.info('='*60)
        logger.info(f'PROCESSING: {m.get("question", "Unknown")}')
        logger.info('='*60)
        
        # Get Polymarket's UP price
        outcome_prices = m.get('outcomePrices', [0.5, 0.5])
        up_price = float(outcome_prices[0]) if outcome_prices else 0.5
        logger.info(f"Polymarket 'Up' price: {up_price}")
        
        # Run TimesFM forecast
        fc = forecaster.forecast(btc_hourly, horizon=args.horizon)
        
        # Generate trading signal
        sig = BTCSignalGenerator.generate(fc, btc_current, up_price)
        
        result = {
            'market': m.get('question'),
            'market_id': m.get('id'),
            'slug': m.get('slug'),
            'data_points': len(btc_hourly),
            'current_btc_price': round(btc_current, 2),
            'forecast': fc['point_forecast'],
            'signal': sig['signal'],
            'confidence': sig['confidence'],
            'timesfm_up_prob': sig['timesfm_up_prob'],
            'polymarket_up_price': sig['polymarket_up_price'],
            'disagreement': sig['disagreement'],
            'up_count': sig['up_count'],
            'total_steps': sig['total_steps'],
            'has_nan': bool(fc['has_nan']),
        }
        results.append(result)
        
        # Log summary
        logger.info('')
        logger.info('TRADING SIGNAL:')
        logger.info(f'  TimesFM UP probability: {sig["timesfm_up_prob"]*100:.1f}% ({sig["up_count"]}/{sig["total_steps"]} steps)')
        logger.info(f'  Polymarket UP price: {sig["polymarket_up_price"]*100:.1f}%')
        logger.info(f'  Disagreement: {sig["disagreement"]:+.2f}')
        logger.info(f'  SIGNAL: {sig["signal"]} (confidence: {sig["confidence"]:.2f})')
        
        if sig['signal'] == 'BUY_UP':
            logger.info('  Action: Market UNDERPRICES upside - consider buying UP token')
        elif sig['signal'] == 'BUY_DOWN':
            logger.info('  Action: Market OVERPRICES upside - consider buying DOWN token')
        else:
            logger.info('  Action: No significant disagreement - hold')
    
    # 5. Save results
    logger.info('')
    logger.info('='*60)
    logger.info('SAVING RESULTS')
    logger.info('='*60)
    os.makedirs('data/forecasts', exist_ok=True)
    outfile = f'data/forecasts/btc_forecast_{ts}.json'
    
    with open(outfile, 'w') as f:
        json.dump(results, f, indent=2)
    
    logger.info(f'Saved {len(results)} forecasts to {outfile}')
    logger.info('')
    logger.info('='*60)
    logger.info('DONE')
    logger.info('='*60)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
