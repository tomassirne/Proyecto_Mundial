import os
import requests
import json

API_KEY  = os.environ["API_FOOTBALL_KEY"]
BASE_URL = "https://v3.football.api-sports.io"
HEADERS  = {"x-apisports-key": API_KEY}

match_id = 1539002  # Suecia 5-1 Tunisia

# Test 1: events
r1 = requests.get(f"{BASE_URL}/fixtures/events", headers=HEADERS, params={"fixture": match_id})
print("=== EVENTS ===")
print(json.dumps(r1.json(), indent=2)[:3000])

# Test 2: predictions
r2 = requests.get(f"{BASE_URL}/predictions", headers=HEADERS, params={"fixture": match_id})
print("\n=== PREDICTIONS ===")
print(json.dumps(r2.json(), indent=2)[:3000])