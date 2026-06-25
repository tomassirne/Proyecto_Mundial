"""
scraper_5_ligas.py
==================
Descarga goles, asistencias, minutos jugados y posición de todos los jugadores
de las 5 grandes ligas (Premier League, La Liga, Serie A, Bundesliga, Ligue 1)
más Cristiano Ronaldo y Lionel Messi desde FBref.

Temporada por defecto: 2024-2025 (la más reciente completa en FBref).
Para cambiar la temporada, modificá SEASON_SUFFIX abajo.

Requisitos:
    pip install requests beautifulsoup4 pandas lxml

Uso:
    python scraper_5_ligas.py

Salida:
    stats_jugadores_5_ligas.csv
"""

import time
import re
import requests
import pandas as pd
from bs4 import BeautifulSoup
from io import StringIO

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────

# Sufijo de temporada en FBref. Ejemplos: "2425" = 2024-25, "2324" = 2023-24
SEASON_SUFFIX = "2425"

# Delay entre requests (segundos). No bajar de 4 para evitar ban.
REQUEST_DELAY = 5

# Archivo de salida
OUTPUT_FILE = "stats_jugadores_5_ligas.csv"

# ──────────────────────────────────────────────
# MAPEO DE POSICIONES (FBref → español)
# ──────────────────────────────────────────────
POSITION_MAP = {
    # Arqueros
    "GK": "Arquero",
    # Defensores
    "DF": "Defensor",
    "LB": "Defensor",
    "RB": "Defensor",
    "CB": "Defensor",
    "WB": "Defensor",
    # Mediocampistas
    "MF": "Mediocampista",
    "DM": "Mediocampista",
    "CM": "Mediocampista",
    "AM": "Mediocampista",
    "LM": "Mediocampista",
    "RM": "Mediocampista",
    # Delanteros
    "FW": "Delantero",
    "LW": "Delantero",
    "RW": "Delantero",
    "CF": "Delantero",
    "SS": "Delantero",
}

# Ligas en FBref: (nombre legible, comp_id)
LIGAS = {
    "Premier League": "9",
    "La Liga":        "12",
    "Serie A":        "11",
    "Bundesliga":     "20",
    "Ligue 1":        "13",
}

# ──────────────────────────────────────────────
# HEADERS HTTP
# ──────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ──────────────────────────────────────────────
# FUNCIONES
# ──────────────────────────────────────────────

def get_page(url: str, retries: int = 3) -> BeautifulSoup | None:
    """Descarga una página con reintentos y devuelve BeautifulSoup."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "lxml")
            elif resp.status_code == 429:
                wait = 60 * attempt
                print(f"  ⚠ Rate limit (429). Esperando {wait}s...")
                time.sleep(wait)
            else:
                print(f"  ✗ HTTP {resp.status_code} en {url}")
                return None
        except requests.RequestException as e:
            print(f"  ✗ Error de red (intento {attempt}/{retries}): {e}")
            time.sleep(10 * attempt)
    return None


def map_position(raw_pos: str) -> str:
    """Convierte posición FBref a español. Toma la primera posición si hay varias."""
    if not raw_pos or pd.isna(raw_pos):
        return "Desconocido"
    # FBref a veces pone "DF,MF" — tomamos la primera
    first = str(raw_pos).split(",")[0].strip()
    return POSITION_MAP.get(first, f"Otro ({first})")


def scrape_league(liga_name: str, comp_id: str) -> pd.DataFrame:
    """
    Scrapea la tabla de estadísticas estándar de FBref para una liga.
    Retorna DataFrame con columnas: jugador, equipo, liga, posicion, goles, asistencias, minutos.
    """
    url = (
        f"https://fbref.com/en/comps/{comp_id}/stats/players/"
        f"{SEASON_SUFFIX}/players-standard-stats-{SEASON_SUFFIX}"
    )

    # FBref también usa URLs sin el sufijo de temporada para la más reciente:
    # Intentamos con sufijo primero, si falla usamos la URL canónica
    print(f"\n📥 Descargando {liga_name}...")
    print(f"   URL: {url}")

    soup = get_page(url)

    # Fallback a URL sin temporada (liga actual)
    if soup is None:
        url_fallback = f"https://fbref.com/en/comps/{comp_id}/stats"
        print(f"   Reintentando con URL sin temporada: {url_fallback}")
        soup = get_page(url_fallback)

    if soup is None:
        print(f"   ✗ No se pudo obtener {liga_name}")
        return pd.DataFrame()

    # Buscamos la tabla con id que contiene "stats_standard"
    table = soup.find("table", {"id": re.compile(r"stats_standard")})
    if table is None:
        # A veces FBref oculta la tabla en un comentario HTML
        comments = soup.find_all(string=lambda text: isinstance(text, str) and "stats_standard" in text)
        for comment in comments:
            inner = BeautifulSoup(str(comment), "lxml")
            table = inner.find("table", {"id": re.compile(r"stats_standard")})
            if table:
                break

    if table is None:
        print(f"   ✗ Tabla no encontrada en {liga_name}")
        return pd.DataFrame()

    # Leer con pandas
    try:
        df_list = pd.read_html(StringIO(str(table)), header=[0, 1])
        df = df_list[0]
    except Exception as e:
        print(f"   ✗ Error parseando tabla: {e}")
        return pd.DataFrame()

    # FBref usa MultiIndex de columnas — aplanamos
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            " ".join(str(c).strip() for c in col if "Unnamed" not in str(c)).strip()
            for col in df.columns.values
        ]

    # Renombrar columnas clave (FBref puede cambiarlas levemente entre temporadas)
    col_aliases = {
        "Player":    ["Player", "Jugador"],
        "Squad":     ["Squad", "Club", "Team"],
        "Pos":       ["Pos", "Position"],
        "Goals":     ["Goals", "Gls", "Performance Gls", "Gls.1"],
        "Assists":   ["Assists", "Ast", "Performance Ast", "Ast.1"],
        "Minutes":   ["Minutes", "Min", "Playing Time Min", "90s"],
    }

    rename_map = {}
    for target, candidates in col_aliases.items():
        for c in candidates:
            if c in df.columns:
                rename_map[c] = target
                break

    df = df.rename(columns=rename_map)

    # Filtrar filas de cabecera repetidas (FBref inserta "Player" cada N filas)
    if "Player" in df.columns:
        df = df[df["Player"] != "Player"]
        df = df[df["Player"].notna()]
        df = df[df["Player"].str.strip() != ""]

    # Seleccionar y limpiar columnas
    cols_needed = ["Player", "Squad", "Pos", "Goals", "Assists", "Minutes"]
    missing = [c for c in cols_needed if c not in df.columns]
    if missing:
        print(f"   ⚠ Columnas faltantes: {missing}. Columnas disponibles: {list(df.columns)[:15]}")
        # Intentamos continuar con lo que tenemos
        cols_needed = [c for c in cols_needed if c in df.columns]

    df = df[cols_needed].copy()

    # Limpiar tipos
    for col in ["Goals", "Assists", "Minutes"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # Agregar liga y posición traducida
    df["Liga"] = liga_name
    if "Pos" in df.columns:
        df["Posicion"] = df["Pos"].apply(map_position)
    else:
        df["Posicion"] = "Desconocido"

    # Renombrar a español
    rename_es = {
        "Player":  "Jugador",
        "Squad":   "Equipo",
        "Goals":   "Goles",
        "Assists": "Asistencias",
        "Minutes": "Minutos",
        "Pos":     "Pos_original",
    }
    df = df.rename(columns=rename_es)

    # Orden final
    final_cols = ["Jugador", "Equipo", "Liga", "Posicion", "Goles", "Asistencias", "Minutos"]
    df = df[[c for c in final_cols if c in df.columns]]

    print(f"   ✓ {len(df)} jugadores encontrados")
    time.sleep(REQUEST_DELAY)
    return df


def scrape_player_search(player_name: str, expected_name: str) -> pd.DataFrame | None:
    """
    Busca un jugador específico en FBref por nombre y retorna sus stats de la temporada.
    Útil para Messi (Inter Miami → no está en las 5 grandes ligas) y CR7 (Al Nassr).
    """
    print(f"\n🔍 Buscando stats de {expected_name}...")

    # Búsqueda en FBref
    search_url = f"https://fbref.com/search/search.fcgi?search={requests.utils.quote(player_name)}"
    soup = get_page(search_url)
    time.sleep(REQUEST_DELAY)

    if soup is None:
        return None

    # Buscar link al jugador en resultados
    player_link = None
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/players/" in href and "/en/players/" in href:
            player_link = "https://fbref.com" + href
            break

    if player_link is None:
        print(f"   ✗ No se encontró perfil para {expected_name}")
        return None

    print(f"   Perfil: {player_link}")
    player_soup = get_page(player_link)
    time.sleep(REQUEST_DELAY)

    if player_soup is None:
        return None

    # Buscar tabla de stats estándar por temporada
    table = player_soup.find("table", {"id": "stats_standard_dom_lg"})
    if table is None:
        table = player_soup.find("table", {"id": re.compile(r"stats_standard")})

    if table is None:
        print(f"   ✗ Tabla de stats no encontrada para {expected_name}")
        return None

    try:
        df = pd.read_html(StringIO(str(table)))[0]
    except Exception as e:
        print(f"   ✗ Error parseando tabla de {expected_name}: {e}")
        return None

    # Aplanar MultiIndex si existe
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            " ".join(str(c).strip() for c in col if "Unnamed" not in str(c)).strip()
            for col in df.columns.values
        ]

    # Filtrar por temporada 2024-2025
    season_col = next((c for c in df.columns if "Season" in str(c) or "season" in str(c).lower()), None)
    if season_col:
        df_season = df[df[season_col].astype(str).str.contains("2024-25", na=False)]
        if df_season.empty:
            # Tomar la última fila disponible (temporada más reciente)
            df_season = df[~df[season_col].astype(str).str.contains("Career|career", na=False)].tail(1)
    else:
        df_season = df.tail(2)  # últimas filas

    if df_season.empty:
        print(f"   ✗ Sin datos de temporada 2024-25 para {expected_name}")
        return None

    # Extraer posición del perfil
    pos_tag = player_soup.find("p")
    pos_raw = ""
    if pos_tag:
        pos_text = pos_tag.get_text()
        pos_match = re.search(r"Position:\s*([A-Z,\s]+)", pos_text)
        if pos_match:
            pos_raw = pos_match.group(1).strip()

    # Columnas de interés
    col_aliases = {
        "Squad":   ["Squad", "Club", "Team"],
        "Goals":   ["Gls", "Goals", "Performance Gls"],
        "Assists": ["Ast", "Assists", "Performance Ast"],
        "Minutes": ["Min", "Minutes", "Playing Time Min"],
        "Comp":    ["Comp", "Competition", "League"],
    }
    row = df_season.iloc[0] if not df_season.empty else None

    if row is None:
        return None

    def get_val(aliases):
        for a in aliases:
            if a in row.index:
                return row[a]
        return None

    # Intentar agregarlos todos por cada temporada (sumamos si hay varias filas)
    goals = pd.to_numeric(df_season.get(next((a for a in col_aliases["Goals"] if a in df_season.columns), ""), pd.Series([0])), errors="coerce").fillna(0).sum()
    assists = pd.to_numeric(df_season.get(next((a for a in col_aliases["Assists"] if a in df_season.columns), ""), pd.Series([0])), errors="coerce").fillna(0).sum()
    minutes = pd.to_numeric(df_season.get(next((a for a in col_aliases["Minutes"] if a in df_season.columns), ""), pd.Series([0])), errors="coerce").fillna(0).sum()
    squad = str(get_val(col_aliases["Squad"]) or "N/D")
    comp = str(get_val(col_aliases["Comp"]) or "N/D")

    pos_translated = map_position(pos_raw) if pos_raw else "Delantero"  # default para estos dos

    result = pd.DataFrame([{
        "Jugador":       expected_name,
        "Equipo":        squad,
        "Liga":          comp,
        "Posicion":      pos_translated,
        "Goles":         int(goals),
        "Asistencias":   int(assists),
        "Minutos":       int(minutes),
    }])
    print(f"   ✓ {expected_name}: {int(goals)} goles, {int(assists)} asistencias, {int(minutes)} minutos")
    return result


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Scraper FBref — 5 Grandes Ligas + Messi & CR7")
    print(f"  Temporada: {SEASON_SUFFIX[:2]}20{SEASON_SUFFIX[2:]}-{SEASON_SUFFIX[:2]}20{SEASON_SUFFIX[2:][0]}5")
    print("=" * 60)

    all_dfs = []

    # 1. Scrapear las 5 ligas
    for liga_name, comp_id in LIGAS.items():
        df = scrape_league(liga_name, comp_id)
        if not df.empty:
            all_dfs.append(df)

    # 2. Agregar Messi y CR7 (juegan fuera de las 5 grandes ligas)
    for player_query, display_name in [
        ("Lionel Messi", "Lionel Messi"),
        ("Cristiano Ronaldo", "Cristiano Ronaldo"),
    ]:
        df_player = scrape_player_search(player_query, display_name)
        if df_player is not None and not df_player.empty:
            all_dfs.append(df_player)

    if not all_dfs:
        print("\n✗ No se pudo obtener ningún dato. Verificá tu conexión a internet.")
        return

    # 3. Combinar y exportar
    final_df = pd.concat(all_dfs, ignore_index=True)

    # Eliminar duplicados (si algún jugador figura en más de una liga por préstamo)
    final_df = final_df.drop_duplicates(subset=["Jugador", "Equipo", "Liga"])

    # Ordenar por goles descendente
    final_df = final_df.sort_values(["Liga", "Goles"], ascending=[True, False])

    final_df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 60)
    print(f"  ✅ CSV guardado: {OUTPUT_FILE}")
    print(f"  📊 Total jugadores: {len(final_df)}")
    print(f"  📋 Columnas: {', '.join(final_df.columns.tolist())}")
    print("\n  Distribución por liga:")
    for liga, count in final_df["Liga"].value_counts().items():
        print(f"    {liga}: {count} jugadores")
    print("\n  Top 5 goleadores del dataset:")
    print(final_df.nlargest(5, "Goles")[["Jugador", "Equipo", "Liga", "Goles", "Asistencias"]].to_string(index=False))
    print("=" * 60)


if __name__ == "__main__":
    main()