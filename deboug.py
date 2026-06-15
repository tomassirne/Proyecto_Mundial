import os
import requests
import json

API_KEY  = os.environ["API_FOOTBALL_KEY"]
BASE_URL = "https://v3.football.api-sports.io"
HEADERS  = {"x-apisports-key": API_KEY}

# Tomamos el partido terminado: Suecia vs Tunisia (id: 1539002)
match_id = 1539002

# Test 1: match stats por equipo
r1 = requests.get(f"{BASE_URL}/fixtures/statistics", headers=HEADERS, params={"fixture": match_id})
print("=== MATCH STATS ===")
print(json.dumps(r1.json(), indent=2)[:2000])

# Test 2: lineups
r2 = requests.get(f"{BASE_URL}/fixtures/lineups", headers=HEADERS, params={"fixture": match_id})
print("\n=== LINEUPS ===")
print(json.dumps(r2.json(), indent=2)[:2000])

# Test 3: player stats
r3 = requests.get(f"{BASE_URL}/fixtures/players", headers=HEADERS, params={"fixture": match_id})
print("\n=== PLAYER STATS ===")
print(json.dumps(r3.json(), indent=2)[:2000])