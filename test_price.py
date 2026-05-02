#!/usr/bin/env python3
import os
import requests
import certifi

# Force certifi CA bundle
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

print("SSL_CERT_FILE:", os.environ.get('SSL_CERT_FILE'))
print("Certifi bundle exists:", os.path.exists(certifi.where()))

try:
    r = requests.get(
        'https://api.binance.com/api/v3/ticker/price',
        params={'symbol': 'BTCUSDT'},
        timeout=10,
        verify=certifi.where()
    )
    print("Status:", r.status_code)
    print("Body:", r.text)
except Exception as e:
    print("EXCEPTION:", type(e).__name__, e)
