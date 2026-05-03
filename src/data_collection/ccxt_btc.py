"""CCXT-based BTC price fetcher with multi-exchange fallback.

Provides a single function: get_btc_price() -> float
Tries multiple exchanges and symbol formats; falls back to CoinGecko on failure.
"""

import time
import logging

logger = logging.getLogger(__name__)

# Exchange priority order with supported symbols
EXCHANGES = [
    ('binance', 'BTC/USDT'),
    ('coinbase', 'BTC/USD'),
    ('kraken', 'BTC/USD'),
    ('okx', 'BTC-USDT'),
    ('bybit', 'BTCUSDT'),
]

_cache = {'price': None, 'ts': 0}
CACHE_TTL = 10


def get_btc_price() -> float:
    """Fetch BTC price from first available CCXT exchange, fallback to CoinGecko."""
    global _cache

    if _cache['price'] and (time.time() - _cache['ts']) < CACHE_TTL:
        return _cache['price']

    import ccxt

    for exchange_name, symbol in EXCHANGES:
        try:
            exchange = getattr(ccxt, exchange_name)({
                'enableRateLimit': True,
                'timeout': 5000,
                'verify': False,
            })

            ticker = exchange.fetch_ticker(symbol)
            price = float(ticker['last'])

            if price and price > 0:
                logger.debug(f"BTC price from {exchange_name} ({symbol}): ${price:.2f}")
                _cache['price'] = price
                _cache['ts'] = time.time()
                exchange.close()
                return price

        except ccxt.BadSymbol as e:
            logger.debug(f"{exchange_name} symbol {symbol} not supported: {e}")
        except ccxt.RateLimitExceeded as e:
            logger.debug(f"{exchange_name} rate-limited: {e}")
        except ccxt.NetworkError as e:
            logger.debug(f"{exchange_name} network error: {e}")
        except ccxt.ExchangeError as e:
            logger.debug(f"{exchange_name} exchange error: {e}")
        except Exception as e:
            logger.debug(f"{exchange_name} failed ({symbol}): {e}")
        finally:
            try:
                exchange.close()
            except Exception:
                pass

    # Fallback to CoinGecko REST (works in WSL)
    logger.info("CCXT all failed — falling back to CoinGecko REST")
    try:
        import requests
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={'ids': 'bitcoin', 'vs_currencies': 'usd'},
            timeout=10,
            verify=False
        )
        if resp.status_code == 200:
            price = float(resp.json()['bitcoin']['usd'])
            logger.info(f"BTC price from CoinGecko fallback: ${price:.2f}")
            _cache['price'] = price
            _cache['ts'] = time.time()
            return price
    except Exception as e:
        logger.error(f"CoinGecko fallback failed: {e}")

    raise RuntimeError("All BTC price sources failed (CCXT + CoinGecko)")
