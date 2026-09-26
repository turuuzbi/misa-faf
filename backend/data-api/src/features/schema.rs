use anyhow::Result;
use sqlx::PgPool;

pub async fn registers(pool: &PgPool) -> Result<()> {
    for statement in [
        "CREATE TABLE IF NOT EXISTS feature_rates (
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            scope VARCHAR(48) NOT NULL,
            key VARCHAR(64) NOT NULL,
            win_start TIMESTAMPTZ NOT NULL,
            count INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (user_id, scope, key)
        )",
        "CREATE TABLE IF NOT EXISTS feature_aux (
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            feature VARCHAR(48) NOT NULL,
            state JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, feature)
        )",
        "CREATE TABLE IF NOT EXISTS feature_guestbook (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            display_name TEXT NOT NULL,
            message TEXT NOT NULL,
            pinned BOOLEAN NOT NULL DEFAULT FALSE,
            public_id VARCHAR(32),
            order_idx INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            approved_at TIMESTAMPTZ,
            removed_at TIMESTAMPTZ
        )",
        "CREATE INDEX IF NOT EXISTS feature_guestbook_user_status_idx ON feature_guestbook (user_id, status, approved_at)",
        "CREATE INDEX IF NOT EXISTS feature_guestbook_user_pinned_idx ON feature_guestbook (user_id) WHERE pinned",
        "CREATE TABLE IF NOT EXISTS feature_asks (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            question TEXT NOT NULL,
            answer TEXT,
            contact TEXT,
            public_id VARCHAR(32),
            order_idx INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            published_at TIMESTAMPTZ
        )",
        "CREATE INDEX IF NOT EXISTS feature_asks_user_status_idx ON feature_asks (user_id, status, order_idx)",
        "CREATE TABLE IF NOT EXISTS feature_drawings (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            public_id VARCHAR(32),
            strokes JSONB NOT NULL DEFAULT '[]'::jsonb,
            description TEXT,
            pinned BOOLEAN NOT NULL DEFAULT FALSE,
            ord INTEGER NOT NULL DEFAULT 0,
            payload_size INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            moderated_at TIMESTAMPTZ
        )",
        "CREATE INDEX IF NOT EXISTS feature_drawings_user_status_idx ON feature_drawings (user_id, status, created_at)",
        "CREATE INDEX IF NOT EXISTS feature_drawings_user_pinned_idx ON feature_drawings (user_id) WHERE pinned",
        "CREATE TABLE IF NOT EXISTS feature_neighbours (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            from_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            to_username VARCHAR(32) NOT NULL,
            to_user_id UUID REFERENCES users(id) ON DELETE CASCADE,
            ord INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (from_user_id, to_username)
        )",
        "ALTER TABLE feature_neighbours ADD COLUMN IF NOT EXISTS id UUID NOT NULL DEFAULT gen_random_uuid()",
        "ALTER TABLE feature_neighbours ADD COLUMN IF NOT EXISTS to_user_id UUID REFERENCES users(id) ON DELETE CASCADE",
        "CREATE INDEX IF NOT EXISTS feature_neighbours_to_idx ON feature_neighbours (to_username)",
        "CREATE INDEX IF NOT EXISTS feature_neighbours_to_user_idx ON feature_neighbours (to_user_id)",
        "CREATE TABLE IF NOT EXISTS feature_leases (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token VARCHAR(128) NOT NULL,
            first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL
        )",
        "CREATE UNIQUE INDEX IF NOT EXISTS feature_leases_user_token_idx ON feature_leases (user_id, token)",
        "CREATE INDEX IF NOT EXISTS feature_leases_user_idx ON feature_leases (user_id)",
        "CREATE TABLE IF NOT EXISTS feature_hits (
            user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            count BIGINT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )",
        "CREATE TABLE IF NOT EXISTS feature_hit_dedup (
            key VARCHAR(64) PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )",
        "CREATE INDEX IF NOT EXISTS feature_hit_dedup_user_idx ON feature_hit_dedup (user_id, at)",
        "CREATE TABLE IF NOT EXISTS feature_secret_grants (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL
        )",
        "CREATE INDEX IF NOT EXISTS feature_secret_grants_user_idx ON feature_secret_grants (user_id, expires_at)",
        "CREATE TABLE IF NOT EXISTS feature_tally_polls (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            revision INTEGER NOT NULL DEFAULT 1,
            poll JSONB NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'open',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at TIMESTAMPTZ
        )",
        "CREATE INDEX IF NOT EXISTS feature_tally_polls_user_idx ON feature_tally_polls (user_id, published_at DESC)",
        "CREATE TABLE IF NOT EXISTS feature_tally_votes (
            id UUID PRIMARY KEY,
            poll_id UUID NOT NULL REFERENCES feature_tally_polls(id) ON DELETE CASCADE,
            key VARCHAR(64) NOT NULL,
            option_id VARCHAR(16),
            idem VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )",
        "CREATE UNIQUE INDEX IF NOT EXISTS feature_tally_votes_poll_key_idx ON feature_tally_votes (poll_id, key)",
        "CREATE UNIQUE INDEX IF NOT EXISTS feature_tally_votes_poll_idem_idx ON feature_tally_votes (poll_id, idem)",
        "CREATE TABLE IF NOT EXISTS feature_archive (
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,
            snapshot JSONB NOT NULL,
            head_hash VARCHAR(96),
            reason TEXT,
            actor UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, seq)
        )",
        "CREATE INDEX IF NOT EXISTS feature_archive_user_idx ON feature_archive (user_id, seq)",
    ] {
        sqlx::query(statement).execute(pool).await?;
    }
    // Admin-panel switches for every feature group. Seeded ON so an upgrade does
    // not change live behaviour; a missing row fails closed (see helpers::global_enabled).
    for (key, description) in FEATURE_SWITCHES {
        sqlx::query(
            "INSERT INTO feature_flags (key, enabled, description) VALUES ($1, TRUE, $2) ON CONFLICT (key) DO NOTHING",
        )
        .bind(key)
        .bind(description)
        .execute(pool)
        .await?;
    }
    Ok(())
}

/// Keep in sync with `FEATURE_FLAG_CATALOG` in backend/app/core/feature_flags.py.
pub const FEATURE_SWITCHES: [(&str, &str); 16] = [
    ("feature.ask_anything", "Ask me anything (global switch)"),
    ("feature.other_side", "The other side / card back (global switch)"),
    ("feature.night_shift", "The night shift (global switch)"),
    ("feature.daily_draw", "The draw (global switch)"),
    ("feature.time_capsule", "Time capsule (global switch)"),
    ("feature.archive", "The archive (global switch)"),
    ("feature.moon", "The moon (global switch)"),
    ("feature.guestbook", "Guestbook (global switch)"),
    ("feature.neighbours", "Neighbours (global switch)"),
    ("feature.alive", "Alive parent switch (presence, clock, hit counter)"),
    ("feature.alive.presence", "Alive: live visitor count"),
    ("feature.alive.clock", "Alive: owner clock"),
    ("feature.alive.hits", "Alive: retro hit counter"),
    ("feature.secret_word", "Secret word (global switch)"),
    ("feature.chalkboard", "A chalkboard (global switch)"),
    ("feature.tally", "The tally (global switch)"),
];