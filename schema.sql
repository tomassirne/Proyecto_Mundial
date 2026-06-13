-- ============================================================
-- SCHEMA: Mundial 2026 · Pipeline de datos
-- Ejecutar en Supabase → SQL Editor
-- ============================================================

-- ── 1. MATCHES ──────────────────────────────────────────────
-- Un partido por fila. Se inserta al terminar el día.
CREATE TABLE IF NOT EXISTS matches (
    match_id          INTEGER PRIMARY KEY,  -- ID de API-Football
    date              TIMESTAMPTZ NOT NULL,
    stage             TEXT NOT NULL,        -- 'Group Stage', 'Round of 16', etc.
    group_name        TEXT,                 -- 'A', 'B', ... NULL en knockout
    home_team_id      INTEGER NOT NULL,
    home_team_name    TEXT NOT NULL,
    away_team_id      INTEGER NOT NULL,
    away_team_name    TEXT NOT NULL,
    home_score        INTEGER,              -- NULL si no terminó
    away_score        INTEGER,              -- NULL si no terminó
    status            TEXT NOT NULL,        -- 'FT', 'NS', 'LIVE', etc.
    venue             TEXT,
    referee           TEXT,
    inserted_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

-- ── 2. MATCH_STATS ──────────────────────────────────────────
-- Estadísticas por equipo por partido.
-- 2 filas por partido (home + away).
CREATE TABLE IF NOT EXISTS match_stats (
    id                BIGSERIAL PRIMARY KEY,
    match_id          INTEGER NOT NULL REFERENCES matches(match_id),
    team_id           INTEGER NOT NULL,
    team_name         TEXT NOT NULL,
    is_home           BOOLEAN NOT NULL,
    -- Posesión y pases
    possession_pct    NUMERIC(5,2),
    passes_total      INTEGER,
    passes_accurate   INTEGER,
    passes_pct        NUMERIC(5,2),
    -- Remates
    shots_total       INTEGER,
    shots_on_target   INTEGER,
    shots_off_target  INTEGER,
    shots_blocked     INTEGER,
    -- Defensa
    fouls             INTEGER,
    yellow_cards      INTEGER,
    red_cards         INTEGER,
    offsides          INTEGER,
    corners           INTEGER,
    -- Físico
    goalkeeper_saves  INTEGER,
    -- Control
    ball_safe         INTEGER,
    inserted_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (match_id, team_id)
);

-- ── 3. LINEUPS ───────────────────────────────────────────────
-- Un jugador por fila por partido.
-- ~22 filas por partido (11 titulares + suplentes que entraron).
CREATE TABLE IF NOT EXISTS lineups (
    id                BIGSERIAL PRIMARY KEY,
    match_id          INTEGER NOT NULL REFERENCES matches(match_id),
    team_id           INTEGER NOT NULL,
    team_name         TEXT NOT NULL,
    player_id         INTEGER NOT NULL,
    player_name       TEXT NOT NULL,
    shirt_number      INTEGER,
    position          TEXT,               -- 'Goalkeeper', 'Defender', etc.
    position_code     TEXT,               -- 'G', 'D', 'M', 'F'
    is_starter        BOOLEAN NOT NULL,
    minutes_played    INTEGER,
    rating            NUMERIC(4,2),       -- Rating de API-Football (0-10)
    inserted_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (match_id, player_id)
);

-- ── 4. PLAYER_STATS ─────────────────────────────────────────
-- Stats individuales por jugador por partido.
-- Complementa lineups con métricas de rendimiento.
CREATE TABLE IF NOT EXISTS player_stats (
    id                  BIGSERIAL PRIMARY KEY,
    match_id            INTEGER NOT NULL REFERENCES matches(match_id),
    team_id             INTEGER NOT NULL,
    team_name           TEXT NOT NULL,
    player_id           INTEGER NOT NULL,
    player_name         TEXT NOT NULL,
    -- Goles y asistencias
    goals               INTEGER DEFAULT 0,
    assists             INTEGER DEFAULT 0,
    -- Remates
    shots_total         INTEGER DEFAULT 0,
    shots_on_target     INTEGER DEFAULT 0,
    -- Pases
    passes_total        INTEGER DEFAULT 0,
    passes_accurate     INTEGER DEFAULT 0,
    passes_pct          NUMERIC(5,2),
    -- Dribles
    dribbles_attempts   INTEGER DEFAULT 0,
    dribbles_success    INTEGER DEFAULT 0,
    -- Duelos
    duels_total         INTEGER DEFAULT 0,
    duels_won           INTEGER DEFAULT 0,
    -- Defensa
    tackles             INTEGER DEFAULT 0,
    blocks              INTEGER DEFAULT 0,
    interceptions       INTEGER DEFAULT 0,
    -- Disciplina
    fouls_committed     INTEGER DEFAULT 0,
    fouls_drawn         INTEGER DEFAULT 0,
    yellow_cards        INTEGER DEFAULT 0,
    red_cards           INTEGER DEFAULT 0,
    -- Físico
    minutes_played      INTEGER DEFAULT 0,
    rating              NUMERIC(4,2),
    inserted_at         TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (match_id, player_id)
);

-- ── 5. STANDINGS ─────────────────────────────────────────────
-- Snapshot diario de la tabla de posiciones por grupo.
-- Múltiples snapshots en el tiempo → permite ver evolución.
CREATE TABLE IF NOT EXISTS standings (
    id                BIGSERIAL PRIMARY KEY,
    snapshot_date     DATE NOT NULL,
    group_name        TEXT NOT NULL,      -- 'A', 'B', ...
    rank              INTEGER NOT NULL,   -- Posición dentro del grupo
    team_id           INTEGER NOT NULL,
    team_name         TEXT NOT NULL,
    played            INTEGER DEFAULT 0,
    won               INTEGER DEFAULT 0,
    drawn             INTEGER DEFAULT 0,
    lost              INTEGER DEFAULT 0,
    goals_for         INTEGER DEFAULT 0,
    goals_against     INTEGER DEFAULT 0,
    goal_diff         INTEGER DEFAULT 0,
    points            INTEGER DEFAULT 0,
    form              TEXT,               -- Ej: 'WWDLW' (últimos 5)
    inserted_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (snapshot_date, team_id)
);

-- ── 6. TOP_SCORERS ───────────────────────────────────────────
-- Snapshot diario de la tabla de goleadores.
CREATE TABLE IF NOT EXISTS top_scorers (
    id                BIGSERIAL PRIMARY KEY,
    snapshot_date     DATE NOT NULL,
    rank              INTEGER NOT NULL,
    player_id         INTEGER NOT NULL,
    player_name       TEXT NOT NULL,
    team_id           INTEGER NOT NULL,
    team_name         TEXT NOT NULL,
    goals             INTEGER DEFAULT 0,
    assists           INTEGER DEFAULT 0,
    penalties_scored  INTEGER DEFAULT 0,
    minutes_played    INTEGER DEFAULT 0,
    rating            NUMERIC(4,2),
    inserted_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (snapshot_date, player_id)
);

-- ── ÍNDICES ──────────────────────────────────────────────────
-- Para acelerar las queries más comunes durante el análisis
CREATE INDEX IF NOT EXISTS idx_matches_date          ON matches(date);
CREATE INDEX IF NOT EXISTS idx_matches_status        ON matches(status);
CREATE INDEX IF NOT EXISTS idx_match_stats_match     ON match_stats(match_id);
CREATE INDEX IF NOT EXISTS idx_match_stats_team      ON match_stats(team_id);
CREATE INDEX IF NOT EXISTS idx_lineups_match         ON lineups(match_id);
CREATE INDEX IF NOT EXISTS idx_lineups_player        ON lineups(player_id);
CREATE INDEX IF NOT EXISTS idx_player_stats_match    ON player_stats(match_id);
CREATE INDEX IF NOT EXISTS idx_player_stats_player   ON player_stats(player_id);
CREATE INDEX IF NOT EXISTS idx_player_stats_team     ON player_stats(team_id);
CREATE INDEX IF NOT EXISTS idx_standings_date        ON standings(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_standings_team        ON standings(team_id);
CREATE INDEX IF NOT EXISTS idx_top_scorers_date      ON top_scorers(snapshot_date);

-- ── TRIGGER: updated_at automático en matches ────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_matches_updated_at
    BEFORE UPDATE ON matches
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
