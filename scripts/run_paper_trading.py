#!/usr/bin/env python3
"""Paper Trading Pipeline for Polymarket TimesFM Bot."""

import sys
import os
import json
import time
import logging
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_collection.btc_price_fetcher import BTCPriceFetcher
from src.data_collection.polymarket_client import PolymarketBTCClient
from src.forecasting.forecaster import TimesFMForecaster
from src.forecasting.signal_generator import BTCSignalGenerator
from src.trading.order_executor import OrderExecutor, Order

# Trade journal integration
try:
    from src.trading.trade_journal import TradeJournal
    HAS_TRADE_JOURNAL = True
except ImportError:
    HAS_TRADE_JOURNAL = False


def setup_logging(paper_trading: bool = True):
    os.makedirs('data/logs', exist_ok=True)
    os.makedirs('data/paper_trades', exist_ok=True)
    
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = f'data/logs/paper_trading_{ts}.log'
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file),
        ]
    )
    
    logger = logging.getLogger('paper_trading')
    logger.info('='*60)
    logger.info('PAPER TRADING MODE - NO REAL ORDERS WILL BE EXECUTED')
    logger.info('='*60)
    return logger


class PaperTradingPipeline:
    def __init__(self, max_order_size: float = 10.0, daily_loss_limit: float = 20.0):
        self.logger = logging.getLogger('paper_trading')
        self.btc_fetcher = BTCPriceFetcher()
        self.poly_client = PolymarketBTCClient()
        self.forecaster = TimesFMForecaster()
        
        self.executor = OrderExecutor(
            dry_run=True,
            max_order_size=max_order_size,
            daily_loss_limit=daily_loss_limit,
        )
        
        # Initialize trade journal
        self.trade_journal = None
        if HAS_TRADE_JOURNAL:
            try:
                self.trade_journal = TradeJournal()
                logger.info("Trade journal initialized")
            except Exception as e:
                logger.warning(f"Failed to init trade journal: {e}")
        
        self.trade_history = []
        self.paper_balance = {'USDC': 1000.0, 'positions': {}}
        
        self.logger.info(f"Paper trading initialized with ${self.paper_balance['USDC']:.2f} USDC")
        
    def fetch_and_forecast(self):
        self.logger.info("Fetching BTC price data...")
        btc_hourly = self.btc_fetcher.get_hourly_prices(days=30)
        btc_current = self.btc_fetcher.get_current_price()
        
        if not btc_hourly or btc_current is None:
            self.logger.error("Failed to fetch BTC data")
            return None, None, None
            
        self.logger.info(f"BTC Current: ${btc_current:.2f} ({len(btc_hourly)} hourly points)")
        
        self.logger.info("Running TimesFM forecast...")
        forecast_result = self.forecaster.forecast(btc_hourly, horizon=15)
        
        if forecast_result.get('has_nan') or not forecast_result.get('point_forecast'):
            self.logger.error("Forecast failed or returned NaN")
            return None, None, None
            
        return btc_hourly, btc_current, forecast_result
        
    def generate_signal_for_market(self, market, forecast_result, btc_current):
        outcome_prices = market.get('outcomePrices', [0.5, 0.5])
        up_price = float(outcome_prices[0]) if outcome_prices else 0.5
        
        signal = BTCSignalGenerator.generate(forecast_result, btc_current, up_price)
        
        self.logger.info(f"Market: {market.get('question', 'Unknown')}")
        self.logger.info(f"TimesFM UP prob: {signal['timesfm_up_prob']*100:.1f}%")
        self.logger.info(f"Polymarket UP price: {signal['polymarket_up_price']*100:.1f}%")
        self.logger.info(f"Signal: {signal['signal']} (confidence: {signal['confidence']:.2f})")
        
        return signal
        
    def execute_paper_trade(self, market, signal):
        outcome_prices = market.get('outcomePrices', [0.5, 0.5])
        clob_token_ids = market.get('clobTokenIds', ['', ''])
        
        trade_record = {
            'timestamp': datetime.now().isoformat(),
            'market_id': market.get('id'),
            'market_slug': market.get('slug'),
            'signal': signal['signal'],
            'confidence': signal['confidence'],
            'timesfm_up_prob': signal['timesfm_up_prob'],
            'polymarket_up_price': signal['polymarket_up_price'],
            'disagreement': signal['disagreement'],
            'executed': False,
            'order_result': None,
            'paper_balance_after': None,
        }
        
        if signal['signal'] == 'BUY_UP':
            token_id = clob_token_ids[0]
            price = float(outcome_prices[0])
            trade_record['side'] = 'BUY_UP'
            trade_record['token_id'] = token_id
            
            self.logger.info("[PAPER TRADE] Buying UP token...")
            order_result = self.executor.buy_token(
                token_id=token_id,
                price=price,
                size_usdc=5.0,
            )
            trade_record['order_result'] = order_result
            trade_record['executed'] = order_result['success']
            
            if order_result['success']:
                self.paper_balance['USDC'] -= 5.0
                self.paper_balance['positions'][token_id] = self.paper_balance['positions'].get(token_id, 0) + (5.0 / price)
                self.logger.info(f"[PAPER] Bought ${5.0} of UP at {price:.4f}")
                
        elif signal['signal'] == 'BUY_DOWN':
            token_id = clob_token_ids[1]
            price = float(outcome_prices[1])
            trade_record['side'] = 'BUY_DOWN'
            trade_record['token_id'] = token_id
            
            self.logger.info("[PAPER TRADE] Buying DOWN token...")
            order_result = self.executor.buy_token(
                token_id=token_id,
                price=price,
                size_usdc=5.0,
            )
            trade_record['order_result'] = order_result
            trade_record['executed'] = order_result['success']
            
            if order_result['success']:
                self.paper_balance['USDC'] -= 5.0
                self.paper_balance['positions'][token_id] = self.paper_balance['positions'].get(token_id, 0) + (5.0 / price)
                self.logger.info(f"[PAPER] Bought ${5.0} of DOWN at {price:.4f}")
                
        else:
            self.logger.info("[PAPER TRADE] HOLD - No trade generated")
            
        trade_record['paper_balance_after'] = self.paper_balance['USDC']
        self.trade_history.append(trade_record)
        
        # Also log to trade journal
        if self.trade_journal:
            try:
                journal_entry = {
                    "date": trade_record.get("timestamp"),
                    "market": trade_record.get("market_slug", trade_record.get("market_id", "Unknown")),
                    "position": "YES" if trade_record.get('side') == 'BUY_UP' else "NO",
                    "entry_price": trade_record.get("polymarket_up_price") if trade_record.get('side') == 'BUY_UP' else 1 - trade_record.get("polymarket_up_price"),
                    "size_usdc": 5.0,  # hardcoded in script
                    "thesis": f"TimesFM UP prob={trade_record.get('timesfm_up_prob', 0):.2%}, Market={trade_record.get('polymarket_up_price', 0):.2%}, Gap={trade_record.get('disagreement', 0):.2%}",
                    "confidence": trade_record.get("confidence", 0.0),
                    "strategy": "timesfm_btc_15min",
                    "time_horizon": "15 minutes",
                    "outcome": "filled" if trade_record.get("executed") else "skipped",
                }
                self.trade_journal.log_entry(journal_entry)
            except Exception as e:
                logger.error(f"Trade journal logging failed: {e}")
        
        return trade_record
        
    def run_single_market(self, market_slug=None):
        self.logger.info("="*60)
        self.logger.info("SINGLE MARKET PAPER TRADING RUN")
        self.logger.info("="*60)
        
        btc_hourly, btc_current, forecast = self.fetch_and_forecast()
        if not forecast:
            self.logger.error("Forecast failed, aborting")
            return
            
        if market_slug:
            markets = self.poly_client.find_active_btc_markets(count=10)
            target_market = next((m for m in markets if m.get('slug') == market_slug), None)
        else:
            markets = self.poly_client.find_active_btc_markets(count=3)
            target_market = markets[0] if markets else None
            
        if not target_market:
            self.logger.error("No active market found")
            return
            
        self.logger.info(f"Selected market: {target_market.get('question')}")
        
        signal = self.generate_signal_for_market(target_market, forecast, btc_current)
        trade_record = self.execute_paper_trade(target_market, signal)
        
        self._save_run_results([trade_record], 'single')
        
        self.logger.info("="*60)
        self.logger.info("PAPER TRADING RUN COMPLETE")
        self.logger.info(f"Paper balance: ${self.paper_balance['USDC']:.2f} USDC")
        self.logger.info("="*60)
        
    def run_monitor_loop(self, interval_seconds=300):
        self.logger.info("="*60)
        self.logger.info(f"STARTING MONITOR LOOP (interval: {interval_seconds}s)")
        self.logger.info("Press Ctrl+C to stop")
        self.logger.info("="*60)
        
        try:
            while True:
                cycle_start = time.time()
                
                self.logger.info("")
                self.logger.info("="*60)
                self.logger.info(f"MONITOR CYCLE: {datetime.now().isoformat()}")
                self.logger.info("="*60)
                
                try:
                    self.run_single_market()
                except Exception as e:
                    self.logger.error(f"Cycle failed: {e}", exc_info=True)
                    
                elapsed = time.time() - cycle_start
                sleep_time = max(0, interval_seconds - elapsed)
                
                if sleep_time > 0:
                    self.logger.info(f"Sleeping {sleep_time:.0f}s until next cycle...")
                    time.sleep(sleep_time)
                    
        except KeyboardInterrupt:
            self.logger.info("")
            self.logger.info("="*60)
            self.logger.info("MONITOR LOOP STOPPED BY USER")
            self.logger.info("="*60)
            self._save_final_report()
            
    def _save_run_results(self, trades, run_type):
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'data/paper_trades/{run_type}_{ts}.json'
        
        data = {
            'timestamp': datetime.now().isoformat(),
            'run_type': run_type,
            'paper_balance': self.paper_balance['USDC'],
            'total_trades': len(trades),
            'trades': trades,
        }
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
            
        self.logger.info(f"Saved {len(trades)} trade records to {filename}")
        
    def _save_final_report(self):
        self.logger.info("Generating final report...")
        
        total_trades = len(self.trade_history)
        buy_up = sum(1 for t in self.trade_history if t.get('side') == 'BUY_UP')
        buy_down = sum(1 for t in self.trade_history if t.get('side') == 'BUY_DOWN')
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'paper_trading_summary': {
                'starting_balance': 1000.0,
                'current_balance': self.paper_balance['USDC'],
                'pnl': self.paper_balance['USDC'] - 1000.0,
                'total_trades': total_trades,
                'buy_up_count': buy_up,
                'buy_down_count': buy_down,
                'positions': self.paper_balance['positions'],
            },
            'all_trades': self.trade_history,
        }
        
        filename = f'data/paper_trades/final_report_{datetime.now().strftime("%Y%m%d")}.json'
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
            
        self.logger.info(f"Final report saved to {filename}")


def main():
    parser = argparse.ArgumentParser(description='Polymarket Paper Trading Bot')
    parser.add_argument('--single', action='store_true', help='Run single market trade')
    parser.add_argument('--market', type=str, default=None, help='Target market slug')
    parser.add_argument('--monitor', action='store_true', help='Run continuous monitor')
    parser.add_argument('--interval', type=int, default=300, help='Monitoring interval in seconds')
    parser.add_argument('--max-order', type=float, default=10.0, help='Max order size USDC')
    parser.add_argument('--daily-loss', type=float, default=20.0, help='Daily loss limit USDC')
    
    args = parser.parse_args()
    
    setup_logging()
    
    pipeline = PaperTradingPipeline(
        max_order_size=args.max_order,
        daily_loss_limit=args.daily_loss,
    )
    
    if args.monitor:
        pipeline.run_monitor_loop(interval_seconds=args.interval)
    elif args.single:
        pipeline.run_single_market(market_slug=args.market)
    else:
        pipeline.run_single_market()


if __name__ == '__main__':
    main()
