import "server-only";

import { currentRankForUser } from "./achievements";
import { liveDiscordState } from "./discord";
import { database, one } from "./postgres";
import { hasActivePremium, publicProjection } from "./premium";
import { userByUsername } from "./users";

type StoredProfile = { config: unknown };

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? { ...(value as Record<string, unknown>) } : {};
}

export async function listUserBadgeGrants(userId: string) {
  const db = database();
  try {
    return (await db.query<Record<string, unknown>>(`
      SELECT b.id, b.name, b.description, b.color, b.preview_url, b.asset_url, b.animated, b.rarity,
             a.featured AS enabled, a.source, a.earned_at, a.display_order
      FROM badge_awards a
      JOIN badges b ON b.id = a.badge_id
      WHERE a.user_id = $1 AND a.revoked_at IS NULL AND (a.expires_at IS NULL OR a.expires_at > NOW()) AND b.active = TRUE
      ORDER BY a.featured DESC, a.display_order, b.display_order, b.name
    `, [userId])).rows;
  } catch {
    return [];
  }
}

/**
 * Public serializer for editor-owned feature settings. Mirrors
 * `public_feature_projection` in backend/app/core/feature_privacy.py: the sealed
 * capsule text, the secret word/link and one-way neighbour nominations must never
 * reach a visitor (they are served, when allowed, by /api/v1/features/*).
 */
export function publicFeatureProjection(config: Record<string, unknown>) {
  const settings = object(config.settings);
  if (!Object.keys(settings).length) return config;
  const capsule = settings.capsule;
  if (capsule && typeof capsule === "object" && !Array.isArray(capsule)) {
    const c = capsule as Record<string, unknown>;
    const safe: Record<string, unknown> = { sealed: Boolean(String(c.text ?? "").trim()) };
    for (const key of ["label", "at", "tz"]) if (key in c) safe[key] = c[key];
    settings.capsule = safe;
  }
  if ("secret" in settings) {
    const s = object(settings.secret);
    settings.secret = { configured: Boolean(s.configured || (s.word && s.url)) };
  }
  if (Array.isArray(settings.neighbours)) {
    settings.neighbours = settings.neighbours.some((name) => String(name ?? "").trim());
  }
  return { ...config, settings };
}

export async function publicProfile(username: string) {
  const user = await userByUsername(username.trim().toLowerCase());
  if (!user?.username) return null;

  const stored = await one<StoredProfile>("SELECT config FROM profiles WHERE user_id = $1", [user.id]);
  let config = stored?.config && typeof stored.config === "object" ? object(stored.config) : {};

  // If nested under config.config
  if (config.config && typeof config.config === "object") {
    config = object(config.config);
  }

  // Stamp identity
  const identity = object(config.profile);
  identity.username = user.username;
  identity.uid = user.id;
  identity.displayName = String(identity.displayName || user.display_name || user.username);
  identity.joinedAt = user.created_at || identity.joinedAt || "";
  config.profile = identity;

  // View count
  try {
    const stats = await one<{ views: number }>("SELECT views FROM profile_stats WHERE user_id = $1", [user.id]);
    identity.views = Number(stats?.views || 0);
  } catch {
    // Ignore stats table missing
  }

  // Apply premium projection
  const entitled = await hasActivePremium(user.id);
  config = publicProjection(config, entitled);
  config = publicFeatureProjection(config);

  // Authoritative active badges
  const grants = await listUserBadgeGrants(user.id);
  if (grants.length > 0) {
    const seen = new Set<string>();
    const badges = [];
    for (const item of grants) {
      const id = String(item.id || "");
      if (!id || seen.has(id)) continue;
      seen.add(id);
      badges.push({
        id,
        name: String(item.name || id).slice(0, 40),
        description: String(item.description || "").slice(0, 160),
        owned: true,
        enabled: Boolean(item.enabled),
        color: String(item.color || "#d8d3ff"),
        monochrome: false,
        icon: item.preview_url || `/api/v1/badges/${id}/icon`,
        previewUrl: `/api/v1/badges/${id}/icon`,
        assetUrl: String(item.asset_url || "").startsWith("https://") ? String(item.asset_url) : "",
        animated: Boolean(item.animated),
        rarity: String(item.rarity || "COMMON").slice(0, 32),
      });
      if (badges.length >= 10) break;
    }
    config.badges = badges;
  }

  // Current rank
  const rank = await currentRankForUser(user.id);
  if (rank) {
    config.rank = rank;
  } else {
    delete config.rank;
  }

  // Live Discord card
  if (user.discord_id) {
    try {
      const discordState = await liveDiscordState(user);
      if (discordState.connected && discordState.card) {
        const card: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(discordState.card)) {
          if (v != null) card[k] = v;
        }
        if (Object.keys(card).length > 0) {
          config.discord = card;
        }
      }
    } catch {
      delete config.discord;
    }
  } else {
    delete config.discord;
  }

  return config;
}

export function profileLimits() {
  const maxTracks = Math.max(1, Math.min(20, parseInt(process.env.MAX_PROFILE_TRACKS || "10", 10) || 10));
  const maxTrackBytes = Math.max(500_000, parseInt(process.env.MAX_TRACK_UPLOAD_BYTES || "40000000", 10) || 40_000_000);
  const maxArtworkBytes = 15_000_000;
  return {
    maxTracks,
    maxTrackBytes,
    maxArtworkBytes,
  };
}

export async function getPublicAssetUrl(username: string, kind: string): Promise<string | null> {
  const row = await one<{ url?: string }>(`
    SELECT CASE WHEN $2 = ANY(ARRAY['customFont','clickSound','entryIcon','ogImage','favicon'])
        AND COALESCE(config->'_premium_base', config->'config'->'_premium_base') IS NOT NULL
        AND NOT EXISTS(SELECT 1 FROM premium_entitlements pe WHERE pe.user_id=u.id AND pe.active=TRUE AND (pe.expires_at IS NULL OR pe.expires_at>NOW()))
        THEN COALESCE(config->'_premium_base'->'assets'->$2->>'url', config->'config'->'_premium_base'->'assets'->$2->>'url')
        ELSE COALESCE(config->'assets'->$2->>'url', config->'config'->'assets'->$2->>'url') END AS url
    FROM profiles p
    JOIN users u ON u.id = p.user_id
    WHERE lower(u.username) = $1 AND p.disabled_at IS NULL
  `, [username.toLowerCase(), kind]);
  const url = (row?.url || "").trim();
  return url || null;
}

export async function getPublicTrackAssetUrl(username: string, trackId: string, kind: string): Promise<string | null> {
  const row = await one<{ url?: string }>(`
    SELECT item->$3->>'url' AS url
    FROM profiles p
    JOIN users u ON u.id = p.user_id
    CROSS JOIN LATERAL jsonb_array_elements(
        COALESCE(
            config->'assets'->'tracks',
            config->'config'->'assets'->'tracks',
            '[]'::jsonb
        )
    ) AS item
    WHERE lower(u.username) = $1 AND p.disabled_at IS NULL AND item->>'id' = $2
    LIMIT 1
  `, [username.toLowerCase(), trackId, kind]);
  const url = (row?.url || "").trim();
  return url || null;
}

export async function getShareCardBits(username: string): Promise<Record<string, unknown> | null> {
  const row = await one<{
    username: string;
    display_name: string | null;
    premium_base: Record<string, unknown> | null;
    premium_active: boolean;
    settings: Record<string, unknown>;
    identity: Record<string, unknown>;
    og_image: string | null;
    favicon: string | null;
    avatar: string | null;
    background: string | null;
    version: string | number | null;
  }>(`
    SELECT
        u.username,
        u.display_name,
        COALESCE(pr.config->'_premium_base', pr.config->'config'->'_premium_base') AS premium_base,
        EXISTS(SELECT 1 FROM premium_entitlements pe WHERE pe.user_id=u.id AND pe.active=TRUE AND (pe.expires_at IS NULL OR pe.expires_at>NOW())) AS premium_active,
        COALESCE(
            pr.config->'settings',
            pr.config->'config'->'settings',
            '{}'::jsonb
        ) AS settings,
        COALESCE(
            pr.config->'profile',
            pr.config->'config'->'profile',
            '{}'::jsonb
        ) AS identity,
        COALESCE(
            pr.config->'assets'->'ogImage'->>'url',
            pr.config->'config'->'assets'->'ogImage'->>'url'
        ) AS og_image,
        COALESCE(
            pr.config->'assets'->'favicon'->>'url',
            pr.config->'config'->'assets'->'favicon'->>'url'
        ) AS favicon,
        COALESCE(
            pr.config->'assets'->'avatar'->>'url',
            pr.config->'config'->'assets'->'avatar'->>'url'
        ) AS avatar,
        COALESCE(
            pr.config->'assets'->'background'->>'url',
            pr.config->'config'->'assets'->'background'->>'url'
        ) AS background,
        EXTRACT(EPOCH FROM COALESCE(pr.updated_at, u.updated_at))::bigint AS version
    FROM users u
    LEFT JOIN profiles pr ON pr.user_id = u.id AND pr.disabled_at IS NULL
    WHERE lower(u.username) = $1
  `, [username.toLowerCase()]);

  if (!row) return null;
  const settings = object(row.settings);
  const identity = object(row.identity);
  if (!String(identity.displayName || "").trim()) {
    identity.displayName = String(row.display_name || row.username || username);
  }
  const projection = publicProjection(
    {
      settings,
      _premium_base: row.premium_base,
      assets: {
        ogImage: { url: row.og_image },
        favicon: { url: row.favicon },
      },
    },
    Boolean(row.premium_active)
  );
  return {
    username: String(row.username || username),
    settings: projection.settings || settings,
    identity,
    og_image: ((projection.assets as Record<string, unknown>)?.ogImage as { url?: string })?.url || null,
    favicon: ((projection.assets as Record<string, unknown>)?.favicon as { url?: string })?.url || null,
    avatar: row.avatar || null,
    background: row.background || null,
    version: row.version != null ? String(row.version) : "0",
  };
}
