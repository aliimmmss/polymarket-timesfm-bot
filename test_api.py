
import requests
import json

url = "https://clob.polymarket.com/markets?limit=5&active=true"
response = requests.get(url)
data = response.json()

print("Type of response:", type(data))
print("Keys in response:", list(data.keys()) if isinstance(data, dict) else "N/A")

if isinstance(data, dict):
    if 'results' in data:
        print("Results count:", len(data['results']))
        print("First result keys:", list(data['results'][0].keys()) if data['results'] else "empty")
    elif 'markets' in data:
        print("Markets count:", len(data['markets']))
    else:
        print("Full response (truncated):", json.dumps(data, indent=2)[:500])
else:
    print("Response (first 500 chars):", str(data)[:500])
