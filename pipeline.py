"""
Mundial 2026 · Pipeline de datos diario
========================================
Fuente única: API-Football (plan pago)
  - fixtures, match stats, lineups, player stats, standings, top scorers

Corre una vez por día vía GitHub Actions.
Dependencias: pip install requests psycopg2-binary python-dotenv
"""

import os
import logging
import requests
import psycopg2
import psycopg2.extras
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

# ── CONFIG ───────────────────────────────────────────────────
API_FOOTBALL_KEY = os.environ["API_FOOTBALL_KEY"]
DB_URL           = os.environ["SUPABASE_DB_URL"]

AF_BASE    = "https://v3.football.api-sports.io"
AF_HEADERS = {"x-apisports-key": API_FOOTBALL_KEY}

LEAGUE_ID = 1
SEASON    = 2026

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)


# ── HELPERS ──────────────────────────────────────────────────

def af_get(endpoint: str, params: dict) -> dict:
    """GET a API-Football."""
    resp = requests.get(f"{AF_BASE}/{endpoint}", headers=AF_HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
    log.info(f"AF /{endpoint} → {data.get('results', 0)} resultados | restantes hoy: {remaining}")
    if data.get("errors"):
        log.warning(f"  Errors: {data['errors']}")
    return data

def get_conn():
    return psycopg2.connect(DB_URL)

def safe_int(val, default=None):
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default

def safe_float(val, default=None):
    try:
        if isinstance(val, str):
            val = val.replace("%", "").strip()
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default

def upsert(conn, table: str, rows: list, conflict_cols: list):
    if not rows:
        log.info(f"  → {table}: sin filas para insertar")
        return
    cursor = conn.cursor()
    cols        = list(rows[0].keys())
    update_cols = [c for c in cols if c not in conflict_cols + ["inserted_at"]]
    placeholders = ",".join(["%s"] * len(cols))
    col_names    = ",".join(cols)
    conflict     = ",".join(conflict_cols)
    updates      = ",".join([f"{c} = EXCLUDED.{c}" for c in update_cols])
    sql = f"""
        INSERT INTO {table} ({col_names})
        VALUES ({placeholders})
        ON CONFLICT ({conflict}) DO UPDATE SET {updates}
    """
    values = [tuple(r[c] for c in cols) for r in rows]
    psycopg2.extras.execute_batch(cursor, sql, values, page_size=100)
    conn.commit()
    log.info(f"  → {table}: {len(rows)} filas procesadas")


# ── FETCH: MATCHES ───────────────────────────────────────────

def fetch_finished_matches(target_date: date) -> list:
    """Partidos terminados en la fecha indicada (UTC)."""
    data = af_get("fixtures", {
        "league":  LEAGUE_ID,
        "season":  SEASON,
        "date":    target_date.isoformat(),
        "status":  "FT-AET-PEN",
    })
    rows = []
    for f in data.get("response", []):
        fixture = f["fixture"]
        teams   = f["teams"]
        goals   = f["goals"]
        score   = f["score"]
        league  = f["league"]

        rows.append({
            "match_id":       fixture["id"],
            "date":           fixture["date"],
            "stage":          league["round"],
            "group_name":     league["round"].replace("Group Stage - ", "")
                              if "Group Stage" in league.get("round", "") else None,
            "home_team_id":   teams["home"]["id"],
            "home_team_name": teams["home"]["name"],
            "away_team_id":   teams["away"]["id"],
            "away_team_name": teams["away"]["name"],
            "home_score":     safe_int(goals.get("home")),
            "away_score":     safe_int(goals.get("away")),
            "home_ht_score":  safe_int(score["halftime"]["home"]),
            "away_ht_score":  safe_int(score["halftime"]["away"]),
            "status":         fixture["status"]["short"],
            "venue":          fixture["venue"]["name"],
            "referee":        fixture.get("referee"),
        })

    log.info(f"Partidos terminados el {target_date}: {len(rows)}")
    return rows


# ── FETCH: MATCH STATS ───────────────────────────────────────

def fetch_match_stats(match_id: int, home_id: int, home_name: str,
                      away_id: int, away_name: str) -> list:
    data = af_get("fixtures/statistics", {"fixture": match_id})
    rows = []

    team_meta = {
        home_id: {"name": home_name, "is_home": True},
        away_id: {"name": away_name, "is_home": False},
    }

    for team_data in data.get("response", []):
        tid  = team_data["team"]["id"]
        meta = team_meta.get(tid, {
            "name": team_data["team"]["name"], "is_home": False
        })
        stats = {s["type"]: s["value"] for s in team_data.get("statistics", [])}

        rows.append({
            "match_id":         match_id,
            "team_id":          tid,
            "team_name":        meta["name"],
            "is_home":          meta["is_home"],
            "possession_pct":   safe_float(stats.get("Ball Possession")),
            "passes_total":     safe_int(stats.get("Total passes")),
            "passes_accurate":  safe_int(stats.get("Passes accurate")),
            "passes_pct":       safe_float(stats.get("Passes %")),
            "shots_total":      safe_int(stats.get("Total Shots")),
            "shots_on_target":  safe_int(stats.get("Shots on Goal")),
            "shots_off_target": safe_int(stats.get("Shots off Goal")),
            "shots_blocked":    safe_int(stats.get("Blocked Shots")),
            "shots_insidebox":  safe_int(stats.get("Shots insidebox")),
            "shots_outsidebox": safe_int(stats.get("Shots outsidebox")),
            "fouls":            safe_int(stats.get("Fouls")),
            "yellow_cards":     safe_int(stats.get("Yellow Cards")),
            "red_cards":        safe_int(stats.get("Red Cards")),
            "offsides":         safe_int(stats.get("Offsides")),
            "corners":          safe_int(stats.get("Corner Kicks")),
            "goalkeeper_saves": safe_int(stats.get("Goalkeeper Saves")),
            "xg":               safe_float(stats.get("expected_goals")),
            "goals_prevented":  safe_float(stats.get("goals_prevented")),
        })

    return rows


# ── FETCH: LINEUPS + PLAYER STATS ────────────────────────────

def fetch_lineups(match_id: int) -> list:
    data = af_get("fixtures/lineups", {"fixture": match_id})
    rows = []

    for team_data in data.get("response", []):
        tid      = team_data["team"]["id"]
        tname    = team_data["team"]["name"]
        formation = team_data.get("formation")

        for p in team_data.get("startXI", []):
            pl = p["player"]
            rows.append({
                "match_id":      match_id,
                "team_id":       tid,
                "team_name":     tname,
                "player_id":     pl["id"],
                "player_name":   pl["name"],
                "shirt_number":  pl.get("number"),
                "position":      pl.get("pos"),
                "grid":          pl.get("grid"),
                "formation":     formation,
                "is_starter":    True,
            })

        for p in team_data.get("substitutes", []):
            pl = p["player"]
            rows.append({
                "match_id":      match_id,
                "team_id":       tid,
                "team_name":     tname,
                "player_id":     pl["id"],
                "player_name":   pl["name"],
                "shirt_number":  pl.get("number"),
                "position":      pl.get("pos"),
                "grid":          None,
                "formation":     formation,
                "is_starter":    False,
            })

    return rows


def fetch_player_stats(match_id: int) -> list:
    data = af_get("fixtures/players", {"fixture": match_id})
    rows = []

    for team_data in data.get("response", []):
        tid   = team_data["team"]["id"]
        tname = team_data["team"]["name"]

        for p in team_data.get("players", []):
            info  = p["player"]
            stats = p["statistics"][0] if p.get("statistics") else {}

            def sv(path, cast=None, default=None):
                try:
                    val = stats
                    for part in path.split("."):
                        val = val[part]
                    if val is None:
                        return default
                    return cast(val) if cast else val
                except (KeyError, TypeError, ValueError):
                    return default

            rows.append({
                "match_id":          match_id,
                "team_id":           tid,
                "team_name":         tname,
                "player_id":         info["id"],
                "player_name":       info["name"],
                "minutes_played":    sv("games.minutes", int, 0),
                "position":          sv("games.position"),
                "shirt_number":      sv("games.number", int),
                "rating":            sv("games.rating", float),
                "is_captain":        sv("games.captain", bool, False),
                "is_substitute":     sv("games.substitute", bool, False),
                "goals":             sv("goals.total", int, 0),
                "goals_conceded":    sv("goals.conceded", int, 0),
                "assists":           sv("goals.assists", int, 0),
                "saves":             sv("goals.saves", int, 0),
                "shots_total":       sv("shots.total", int, 0),
                "shots_on_target":   sv("shots.on", int, 0),
                "passes_total":      sv("passes.total", int, 0),
                "passes_accurate":   sv("passes.accuracy", int, 0),
                "passes_key":        sv("passes.key", int, 0),
                "tackles_total":     sv("tackles.total", int, 0),
                "tackles_blocks":    sv("tackles.blocks", int, 0),
                "interceptions":     sv("tackles.interceptions", int, 0),
                "duels_total":       sv("duels.total", int, 0),
                "duels_won":         sv("duels.won", int, 0),
                "dribbles_attempts": sv("dribbles.attempts", int, 0),
                "dribbles_success":  sv("dribbles.success", int, 0),
                "fouls_committed":   sv("fouls.committed", int, 0),
                "fouls_drawn":       sv("fouls.drawn", int, 0),
                "yellow_cards":      sv("cards.yellow", int, 0),
                "red_cards":         sv("cards.red", int, 0),
                "offsides":          sv("offsides", int, 0),
                "penalty_scored":    sv("penalty.scored", int, 0),
                "penalty_missed":    sv("penalty.missed", int, 0),
                "penalty_saved":     sv("penalty.saved", int, 0),
            })

    return rows


# ── FETCH: STANDINGS (API-Football) ─────────────────────────

def fetch_standings(today: date) -> list:
    data = af_get("standings", {"league": LEAGUE_ID, "season": SEASON})
    rows = []

    for league_data in data.get("response", []):
        for group in league_data.get("league", {}).get("standings", []):
            for entry in group:
                team = entry["team"]
                rows.append({
                    "snapshot_date": today.isoformat(),
                    "group_name":    entry.get("group", "").replace("Group ", ""),
                    "rank":          entry["rank"],
                    "team_id":       team["id"],
                    "team_name":     team["name"],
                    "played":        entry["all"]["played"],
                    "won":           entry["all"]["win"],
                    "drawn":         entry["all"]["draw"],
                    "lost":          entry["all"]["lose"],
                    "goals_for":     entry["all"]["goals"]["for"],
                    "goals_against": entry["all"]["goals"]["against"],
                    "goal_diff":     entry["goalsDiff"],
                    "points":        entry["points"],
                    "form":          entry.get("form"),
                })

    log.info(f"Standings: {len(rows)} equipos")
    return rows


# ── FETCH: TOP SCORERS (API-Football) ────────────────────────

def fetch_top_scorers(today: date) -> list:
    data = af_get("players/topscorers", {"league": LEAGUE_ID, "season": SEASON})
    rows = []

    for rank, item in enumerate(data.get("response", []), start=1):
        player = item["player"]
        stats  = item["statistics"][0] if item.get("statistics") else {}
        team   = stats.get("team", {})

        rows.append({
            "snapshot_date":    today.isoformat(),
            "rank":             rank,
            "player_id":        player["id"],
            "player_name":      player["name"],
            "team_id":          team.get("id"),
            "team_name":        team.get("name"),
            "goals":            safe_int(stats.get("goals", {}).get("total"), 0),
            "assists":          safe_int(stats.get("goals", {}).get("assists"), 0),
            "penalties_scored": safe_int(stats.get("penalty", {}).get("scored"), 0),
            "minutes_played":   safe_int(stats.get("games", {}).get("minutes"), 0),
            "rating":           safe_float(stats.get("games", {}).get("rating")),
        })

    log.info(f"Top scorers: {len(rows)} jugadores")
    return rows


# ── MAIN ─────────────────────────────────────────────────────

def run():
    today       = date.today()
    target_date = today - timedelta(days=1)

    log.info(f"══ Pipeline Mundial 2026 · procesando {target_date} ══")

    conn = get_conn()
    try:
        # 1. Partidos terminados ayer
        matches = fetch_finished_matches(target_date)
        if matches:
            upsert(conn, "matches", matches, ["match_id"])

        # 2. Por cada partido: stats, lineups, player stats
        for m in matches:
            mid = m["match_id"]
            log.info(f"Procesando {m['home_team_name']} vs {m['away_team_name']} (id: {mid})")

            stats = fetch_match_stats(
                mid,
                m["home_team_id"], m["home_team_name"],
                m["away_team_id"], m["away_team_name"],
            )
            upsert(conn, "match_stats", stats, ["match_id", "team_id"])

            lineups = fetch_lineups(mid)
            upsert(conn, "lineups", lineups, ["match_id", "player_id"])

            player_stats = fetch_player_stats(mid)
            upsert(conn, "player_stats", player_stats, ["match_id", "player_id"])

        # 3. Standings (snapshot diario)
        standings = fetch_standings(today)
        upsert(conn, "standings", standings, ["snapshot_date", "team_id"])

        # 4. Top scorers (snapshot diario)
        top_scorers = fetch_top_scorers(today)
        upsert(conn, "top_scorers", top_scorers, ["snapshot_date", "player_id"])

        log.info("══ Pipeline completado sin errores ══")

    except Exception as e:
        log.error(f"Error en el pipeline: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run()