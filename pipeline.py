"""
Mundial 2026 · Pipeline de datos diario
========================================
Corre una vez por día vía GitHub Actions.
Obtiene datos de API-Football y los guarda en Supabase.

Dependencias: pip install requests psycopg2-binary python-dotenv
"""

import os
import logging
import requests
import psycopg2
import psycopg2.extras
from datetime import date, datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

# ── CONFIG ───────────────────────────────────────────────────
API_KEY        = os.environ["API_FOOTBALL_KEY"]
DB_URL         = os.environ["SUPABASE_DB_URL"]
LEAGUE_ID      = 1      # FIFA World Cup en API-Football
SEASON         = 2026
BASE_URL       = "https://v3.football.api-sports.io"
HEADERS        = {"x-apisports-key": API_KEY}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)


# ── API CLIENT ───────────────────────────────────────────────

def api_get(endpoint: str, params: dict) -> dict:
    """Hace un GET a la API y devuelve el JSON. Lanza excepción si falla."""
    url = f"{BASE_URL}/{endpoint}"
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
    log.info(f"GET /{endpoint} → {len(data.get('response', []))} items | requests restantes hoy: {remaining}")
    return data


# ── DB CLIENT ────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DB_URL)


def upsert(conn, table: str, rows: list[dict], conflict_cols: list[str]):
    """
    Upsert genérico. Inserta filas y en caso de conflicto
    actualiza todas las columnas excepto inserted_at.
    """
    if not rows:
        return
    cursor = conn.cursor()
    cols = list(rows[0].keys())
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


# ── FETCH FUNCTIONS ──────────────────────────────────────────

def fetch_finished_matches(target_date: date) -> list[dict]:
    """
    Obtiene todos los partidos terminados del día anterior.
    API-Football usa la fecha en formato YYYY-MM-DD.
    """
    data = api_get("fixtures", {
        "league": LEAGUE_ID,
        "season": SEASON,
        "date":   target_date.isoformat(),
    })

    rows = []
    for f in data.get("response", []):
        fixture  = f["fixture"]
        teams    = f["teams"]
        goals    = f["goals"]
        league   = f["league"]

        # Solo procesar partidos terminados
        if fixture["status"]["short"] not in ("FT", "AET", "PEN"):
            continue

        rows.append({
            "match_id":       fixture["id"],
            "date":           fixture["date"],
            "stage":          league["round"],
            "group_name":     league.get("round", "").replace("Group Stage - ", "")
                              if "Group" in league.get("round", "") else None,
            "home_team_id":   teams["home"]["id"],
            "home_team_name": teams["home"]["name"],
            "away_team_id":   teams["away"]["id"],
            "away_team_name": teams["away"]["name"],
            "home_score":     goals["home"],
            "away_score":     goals["away"],
            "status":         fixture["status"]["short"],
            "venue":          fixture["venue"]["name"],
            "referee":        fixture.get("referee"),
        })

    log.info(f"Partidos terminados el {target_date}: {len(rows)}")
    return rows


def fetch_match_stats(match_id: int, home_team: dict, away_team: dict) -> list[dict]:
    """Estadísticas de equipo para un partido."""
    data = api_get("fixtures/statistics", {"fixture": match_id})
    rows = []

    team_meta = {
        home_team["id"]: {"name": home_team["name"], "is_home": True},
        away_team["id"]: {"name": away_team["name"], "is_home": False},
    }

    for team_data in data.get("response", []):
        tid  = team_data["team"]["id"]
        meta = team_meta.get(tid, {"name": team_data["team"]["name"], "is_home": False})

        # Convertir lista de stats a dict para acceso fácil
        stats = {s["type"]: s["value"] for s in team_data.get("statistics", [])}

        def safe_int(val):
            try:
                return int(val) if val is not None else None
            except (ValueError, TypeError):
                return None

        def safe_float(val):
            try:
                # Algunos valores vienen como "45%" → limpiar
                if isinstance(val, str):
                    val = val.replace("%", "").strip()
                return float(val) if val is not None else None
            except (ValueError, TypeError):
                return None

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
            "fouls":            safe_int(stats.get("Fouls")),
            "yellow_cards":     safe_int(stats.get("Yellow Cards")),
            "red_cards":        safe_int(stats.get("Red Cards")),
            "offsides":         safe_int(stats.get("Offsides")),
            "corners":          safe_int(stats.get("Corner Kicks")),
            "goalkeeper_saves": safe_int(stats.get("Goalkeeper Saves")),
            "ball_safe":        safe_int(stats.get("Ball Safe")),
        })

    return rows


def fetch_lineups_and_player_stats(match_id: int) -> tuple[list[dict], list[dict]]:
    """
    Obtiene lineups y stats individuales de jugadores para un partido.
    Dos requests: /fixtures/lineups y /fixtures/players
    """
    lineup_rows = []
    player_rows = []

    # ── Lineups ──
    data_lineups = api_get("fixtures/lineups", {"fixture": match_id})
    for team_data in data_lineups.get("response", []):
        tid       = team_data["team"]["id"]
        tname     = team_data["team"]["name"]

        for p in team_data.get("startXI", []):
            player = p["player"]
            lineup_rows.append({
                "match_id":     match_id,
                "team_id":      tid,
                "team_name":    tname,
                "player_id":    player["id"],
                "player_name":  player["name"],
                "shirt_number": player.get("number"),
                "position":     player.get("pos"),
                "position_code": player.get("pos"),
                "is_starter":   True,
                "minutes_played": 90,
                "rating":       None,
            })

        for p in team_data.get("substitutes", []):
            player = p["player"]
            lineup_rows.append({
                "match_id":     match_id,
                "team_id":      tid,
                "team_name":    tname,
                "player_id":    player["id"],
                "player_name":  player["name"],
                "shirt_number": player.get("number"),
                "position":     player.get("pos"),
                "position_code": player.get("pos"),
                "is_starter":   False,
                "minutes_played": 0,
                "rating":       None,
            })

    # ── Player stats ──
    data_players = api_get("fixtures/players", {"fixture": match_id})
    for team_data in data_players.get("response", []):
        tid   = team_data["team"]["id"]
        tname = team_data["team"]["name"]

        for p in team_data.get("players", []):
            info  = p["player"]
            stats = p["statistics"][0] if p.get("statistics") else {}

            def sv(path, cast=None, default=0):
                """Safe value: navega el dict de stats sin explotar."""
                try:
                    parts = path.split(".")
                    val = stats
                    for part in parts:
                        val = val[part]
                    if val is None:
                        return default
                    return cast(val) if cast else val
                except (KeyError, TypeError, ValueError):
                    return default

            minutes = sv("games.minutes", int, 0)

            # Actualizar minutos jugados en lineup_rows
            for lr in lineup_rows:
                if lr["player_id"] == info["id"] and lr["match_id"] == match_id:
                    lr["minutes_played"] = minutes
                    lr["rating"] = sv("games.rating", float, None) or None

            player_rows.append({
                "match_id":           match_id,
                "team_id":            tid,
                "team_name":          tname,
                "player_id":          info["id"],
                "player_name":        info["name"],
                "goals":              sv("goals.total", int, 0),
                "assists":            sv("goals.assists", int, 0),
                "shots_total":        sv("shots.total", int, 0),
                "shots_on_target":    sv("shots.on", int, 0),
                "passes_total":       sv("passes.total", int, 0),
                "passes_accurate":    sv("passes.accuracy", int, 0),
                "passes_pct":         sv("passes.accuracy", float, None) or None,
                "dribbles_attempts":  sv("dribbles.attempts", int, 0),
                "dribbles_success":   sv("dribbles.success", int, 0),
                "duels_total":        sv("duels.total", int, 0),
                "duels_won":          sv("duels.won", int, 0),
                "tackles":            sv("tackles.total", int, 0),
                "blocks":             sv("tackles.blocks", int, 0),
                "interceptions":      sv("tackles.interceptions", int, 0),
                "fouls_committed":    sv("fouls.committed", int, 0),
                "fouls_drawn":        sv("fouls.drawn", int, 0),
                "yellow_cards":       sv("cards.yellow", int, 0),
                "red_cards":          sv("cards.red", int, 0),
                "minutes_played":     minutes,
                "rating":             sv("games.rating", float, None) or None,
            })

    return lineup_rows, player_rows


def fetch_standings(today: date) -> list[dict]:
    """Snapshot de la tabla de posiciones de todos los grupos."""
    data = api_get("standings", {"league": LEAGUE_ID, "season": SEASON})
    rows = []

    for league_data in data.get("response", []):
        for group in league_data.get("league", {}).get("standings", []):
            for entry in group:
                team  = entry["team"]
                goals = entry["goalsDiff"]
                rows.append({
                    "snapshot_date":  today.isoformat(),
                    "group_name":     entry.get("group", "").replace("Group ", ""),
                    "rank":           entry["rank"],
                    "team_id":        team["id"],
                    "team_name":      team["name"],
                    "played":         entry["all"]["played"],
                    "won":            entry["all"]["win"],
                    "drawn":          entry["all"]["draw"],
                    "lost":           entry["all"]["lose"],
                    "goals_for":      entry["all"]["goals"]["for"],
                    "goals_against":  entry["all"]["goals"]["against"],
                    "goal_diff":      entry["goalsDiff"],
                    "points":         entry["points"],
                    "form":           entry.get("form"),
                })

    log.info(f"Standings: {len(rows)} equipos")
    return rows


def fetch_top_scorers(today: date) -> list[dict]:
    """Snapshot diario de la tabla de goleadores."""
    data = api_get("players/topscorers", {"league": LEAGUE_ID, "season": SEASON})
    rows = []

    for rank, item in enumerate(data.get("response", []), start=1):
        player = item["player"]
        stats  = item["statistics"][0] if item.get("statistics") else {}
        team   = stats.get("team", {})

        rows.append({
            "snapshot_date":   today.isoformat(),
            "rank":            rank,
            "player_id":       player["id"],
            "player_name":     player["name"],
            "team_id":         team.get("id"),
            "team_name":       team.get("name"),
            "goals":           stats.get("goals", {}).get("total", 0) or 0,
            "assists":         stats.get("goals", {}).get("assists", 0) or 0,
            "penalties_scored": stats.get("penalty", {}).get("scored", 0) or 0,
            "minutes_played":  stats.get("games", {}).get("minutes", 0) or 0,
            "rating":          float(stats["games"]["rating"]) if stats.get("games", {}).get("rating") else None,
        })

    log.info(f"Top scorers: {len(rows)} jugadores")
    return rows


# ── MAIN ─────────────────────────────────────────────────────

def run():
    # Por defecto procesamos el día anterior (partidos ya terminados)
    target_date = date.today() - timedelta(days=1)
    today       = date.today()

    log.info(f"══ Pipeline Mundial 2026 · procesando {target_date} ══")

    conn = get_conn()
    try:
        # 1. Partidos terminados ayer
        matches = fetch_finished_matches(target_date)
        if matches:
            upsert(conn, "matches", matches, ["match_id"])

        # 2. Stats + lineups + player stats por partido
        for m in matches:
            mid = m["match_id"]
            log.info(f"Procesando partido {mid}: {m['home_team_name']} vs {m['away_team_name']}")

            # Match stats (2 filas, una por equipo)
            stats = fetch_match_stats(
                mid,
                {"id": m["home_team_id"], "name": m["home_team_name"]},
                {"id": m["away_team_id"], "name": m["away_team_name"]},
            )
            if stats:
                upsert(conn, "match_stats", stats, ["match_id", "team_id"])

            # Lineups + player stats (2 requests)
            lineups, player_stats = fetch_lineups_and_player_stats(mid)
            if lineups:
                upsert(conn, "lineups", lineups, ["match_id", "player_id"])
            if player_stats:
                upsert(conn, "player_stats", player_stats, ["match_id", "player_id"])

        # 3. Standings (snapshot diario, independiente de si hubo partidos)
        standings = fetch_standings(today)
        if standings:
            upsert(conn, "standings", standings, ["snapshot_date", "team_id"])

        # 4. Top scorers (snapshot diario)
        top_scorers = fetch_top_scorers(today)
        if top_scorers:
            upsert(conn, "top_scorers", top_scorers, ["snapshot_date", "player_id"])

        log.info("══ Pipeline completado sin errores ══")

    except Exception as e:
        log.error(f"Error en el pipeline: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run()
