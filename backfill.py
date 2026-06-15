"""
Mundial 2026 · Carga histórica
================================
Procesa un rango de fechas para cargar partidos anteriores al inicio
del pipeline diario.

Uso:
    python backfill.py                        # carga del 11/06 al 13/06 (default)
    python backfill.py 2026-06-11 2026-06-13  # rango personalizado

Dependencias: pip install requests psycopg2-binary python-dotenv
"""

import sys
import time
import logging
from datetime import date, timedelta

# Reutilizamos todo del pipeline principal
from pipeline import (
    fetch_finished_matches,
    fetch_match_stats,
    fetch_lineups,
    fetch_player_stats,
    fetch_events,
    fetch_standings,
    fetch_top_scorers,
    upsert,
    get_conn,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)


def daterange(start: date, end: date):
    """Genera fechas desde start hasta end inclusive."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def backfill(start_date: date, end_date: date):
    log.info(f"══ Backfill Mundial 2026 · {start_date} → {end_date} ══")

    conn = get_conn()
    total_matches = 0

    try:
        for target_date in daterange(start_date, end_date):
            log.info(f"── Procesando fecha: {target_date} ──")

            matches = fetch_finished_matches(target_date)
            if not matches:
                log.info(f"  Sin partidos terminados el {target_date}")
                continue

            upsert(conn, "matches", matches, ["match_id"])

            for m in matches:
                mid = m["match_id"]
                log.info(f"  Partido: {m['home_team_name']} vs {m['away_team_name']} (id: {mid})")

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

                events = fetch_events(mid)
                upsert(conn, "fixture_events", events, ["match_id", "elapsed", "elapsed_extra", "team_id", "player_id"])

                total_matches += 1

                # Pausa entre partidos para no saturar el rate limit
                time.sleep(1.5)

            # Pausa entre fechas
            time.sleep(2)

        # Standings y top scorers: un snapshot del día de hoy
        today = date.today()
        log.info("Cargando standings actuales...")
        standings = fetch_standings(today)
        upsert(conn, "standings", standings, ["snapshot_date", "team_id"])

        log.info("Cargando top scorers actuales...")
        top_scorers = fetch_top_scorers(today)
        upsert(conn, "top_scorers", top_scorers, ["snapshot_date", "player_id"])

        log.info(f"══ Backfill completado · {total_matches} partidos procesados ══")

    except Exception as e:
        log.error(f"Error en el backfill: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) == 3:
        start = date.fromisoformat(sys.argv[1])
        end   = date.fromisoformat(sys.argv[2])
    else:
        # Default: del 11/06 al 13/06
        start = date(2026, 6, 11)
        end   = date(2026, 6, 13)

    backfill(start, end)