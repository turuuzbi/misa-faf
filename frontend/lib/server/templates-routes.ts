import "server-only";
import { randomUUID } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { AdminError } from "./admin-auth";
import { adminTransaction, adminUuid } from "./admin-operations";
import { publicTemplateCard } from "./admin-templates";
import { apiError } from "./http";
import { database, one } from "./postgres";
import { persistProfile, sanitizeProfilePayload, savedProfile } from "./profile-persistence";
import { withinLimit } from "./rate-limit";
import { nativeCoreEnabled } from "./rollout";
import { currentUser } from "./sessions";
import type { User } from "./users";

const json = (value: unknown, status = 200) =>
  NextResponse.json(value, { status, headers: { "Cache-Control": "no-store" } });

const TEMPLATE_ASSET_KEYS = [
  "banner", "background", "cursor", "backgroundVideo", "audio",
  "audioArtwork", "customFont", "clickSound", "entryIcon"
] as const;

const PERSONAL_SETTINGS = new Set([
  "ogTitle", "ogDescription", "ogOverlayAvatar", "ogOverlayName", "ogOverlayAddress",
  // Living-profile content/switches stay with their owner (see backend/app/core/templates.py).
  "capsule", "secret", "tally", "draw", "neighbours", "reverse", "night", "timezone", "clock", "clockLabel", "clock24", "guestbook", "guestbookHeading", "guestbookPaused", "guestbookPinning", "asks", "asksPrompt", "asksAcceptNew", "doodles", "doodlesTitle", "doodlesPaused", "moon", "presence", "hits", "vigil", "since", "replay", "remember", "archive"
]);

const VISIBILITIES = new Set(["public", "private", "unlisted"]);

export function slugify(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  return slug || `template-${randomUUID().slice(0, 8)}`;
}

export function uniqueSlugCandidate(name: string): string {
  return `${slugify(name)}-${randomUUID().slice(0, 6)}`;
}

export function cleanTags(values: unknown): string[] {
  let list: unknown[] = [];
  if (Array.isArray(values)) list = values;
  else if (typeof values === "string") list = values.split(",");
  const result: string[] = [];
  for (const item of list) {
    const tag = String(item || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9 _-]/g, "")
      .trim();
    if (tag && !result.includes(tag)) result.push(tag.slice(0, 24));
  }
  return result.slice(0, 8);
}

function cleanVisibility(value: unknown, fallback = "public"): string {
  const val = String(value || fallback).trim().toLowerCase();
  if (!VISIBILITIES.has(val)) throw new AdminError("Choose a valid template visibility.", 400);
  return val;
}

function cleanPreviewImage(value: unknown): string | null {
  const text = String(value || "").trim();
  if (!text) return null;
  const match = text.match(/^data:(image\/jpeg|image\/png|image\/webp);base64,[A-Za-z0-9+/=\s]+$/i);
  if (!match) throw new AdminError("Template preview must be a JPEG, PNG, or WebP image.", 400);
  if (text.length > 2_500_000) throw new AdminError("Template preview is too large.", 413);
  return text;
}

export function snapshotTemplateConfig(profile: Record<string, unknown>): Record<string, unknown> {
  const settings = { ...((profile.settings as Record<string, unknown>) || {}) };
  for (const key of PERSONAL_SETTINGS) delete settings[key];

  const assets = (profile.assets as Record<string, unknown>) || {};
  const snappedAssets: Record<string, unknown> = {};
  for (const key of TEMPLATE_ASSET_KEYS) {
    const item = assets[key];
    snappedAssets[key] = item && typeof item === "object" ? item : { url: null, name: "", type: "" };
  }

  const rawTracks = Array.isArray(assets.tracks) ? assets.tracks : [];
  snappedAssets.tracks = rawTracks.filter((t) => t && typeof t === "object");
  snappedAssets.audioTitle = String(assets.audioTitle || "").slice(0, 80);
  snappedAssets.audioEnabled = assets.audioEnabled !== undefined ? Boolean(assets.audioEnabled) : true;
  snappedAssets.audioSource = String(assets.audioSource || "").slice(0, 16);
  snappedAssets.volume = assets.volume !== undefined ? Number(assets.volume) : 65;

  return {
    settings,
    assets: snappedAssets,
    sections: Array.isArray(profile.sections) ? profile.sections : [],
  };
}

export function previewFromSnapshot(snapshot: Record<string, unknown>): Record<string, unknown> {
  const settings = (snapshot.settings as Record<string, unknown>) || {};
  const assets = (snapshot.assets as Record<string, unknown>) || {};
  const background = (assets.background as Record<string, unknown>) || {};
  const tracks = Array.isArray(assets.tracks) ? assets.tracks : [];
  const audio = (assets.audio as Record<string, unknown>) || {};
  const hasAudio =
    Boolean(audio.url) ||
    tracks.some((t) => {
      const item = t as Record<string, unknown> | null;
      const trackAudio = item?.audio as Record<string, unknown> | null;
      return Boolean(trackAudio?.url);
    });

  return {
    accentColor: String(settings.accentColor || "#9b87f5"),
    backgroundColor: String(settings.backgroundColor || "#08080d"),
    textColor: String(settings.textColor || "#ffffff"),
    layout: String(settings.layout || "Modern"),
    backgroundEffect: String(settings.backgroundEffect || "None"),
    profileFont: String(settings.profileFont || "Inter"),
    hasBackground: Boolean(background.url),
    hasAudio,
    trackCount: tracks.length,
  };
}

export function applyTemplateSnapshot(
  current: Record<string, unknown>,
  snapshot: Record<string, unknown>
): Record<string, unknown> {
  const currentSettings = { ...((current.settings as Record<string, unknown>) || {}) };
  const snapSettings = { ...((snapshot.settings as Record<string, unknown>) || {}) };
  for (const key of PERSONAL_SETTINGS) delete snapSettings[key];
  const mergedSettings = { ...currentSettings, ...snapSettings };
  for (const key of PERSONAL_SETTINGS) {
    if (key in currentSettings) mergedSettings[key] = currentSettings[key];
  }

  const currentAssets = { ...((current.assets as Record<string, unknown>) || {}) };
  const snapAssets = { ...((snapshot.assets as Record<string, unknown>) || {}) };
  for (const key of TEMPLATE_ASSET_KEYS) {
    if (key in snapAssets) currentAssets[key] = snapAssets[key];
  }

  const audio = (snapAssets.audio as Record<string, unknown>) || {};
  const tracks = Array.isArray(snapAssets.tracks) ? snapAssets.tracks : [];
  const hasAudio =
    Boolean(audio.url) ||
    tracks.some((t) => {
      const item = t as Record<string, unknown> | null;
      const trackAudio = item?.audio as Record<string, unknown> | null;
      return Boolean(trackAudio?.url);
    });

  if (hasAudio) {
    currentAssets.tracks = tracks;
    currentAssets.audioTitle = String(snapAssets.audioTitle || "").slice(0, 80);
    currentAssets.audioEnabled = Boolean(snapAssets.audioEnabled);
    if ("volume" in snapAssets) currentAssets.volume = snapAssets.volume;
  }

  return {
    ...current,
    settings: mergedSettings,
    assets: currentAssets,
    sections: Array.isArray(snapshot.sections) ? snapshot.sections : current.sections || [],
  };
}

async function isStaffAdmin(user: User): Promise<boolean> {
  if (user.is_admin) return true;
  const allow = (process.env.MISA_ADMIN_USER_IDS || "").split(",").map((v) => v.trim());
  if (allow.includes(user.id)) return true;
  const roleRow = await one<{ role: string }>(
    "SELECT role FROM user_roles WHERE user_id=$1 AND role IN ('owner', 'admin')",
    [user.id]
  );
  return Boolean(roleRow);
}

export async function canCreateTemplates(user: User): Promise<boolean> {
  if (await isStaffAdmin(user)) return true;
  const row = await one<{ role: string }>(
    "SELECT role FROM user_roles WHERE user_id=$1 AND role='template_creator'",
    [user.id]
  );
  return Boolean(row);
}

export async function templatesRoute(request: NextRequest, path: string[]) {
  if (!nativeCoreEnabled()) return apiError("Not found.", 404);

  try {
    const method = request.method;

    // GET /api/v1/templates: list published templates
    if (path.length === 0 && method === "GET") {
      const user = await currentUser(request);
      if (!user) return apiError("Not authenticated.", 401);

      const q = (request.nextUrl.searchParams.get("q") || "").trim().toLowerCase();
      const tag = (request.nextUrl.searchParams.get("tag") || "").trim().toLowerCase();
      const sortParam = (request.nextUrl.searchParams.get("sort") || "latest").trim().toLowerCase();
      const sortMap: Record<string, string> = {
        latest: "t.updated_at DESC, t.id DESC",
        popular: "favorite_count DESC, t.updated_at DESC, t.id DESC",
        week: "week_favorite_count DESC, t.updated_at DESC, t.id DESC",
        month: "month_favorite_count DESC, t.updated_at DESC, t.id DESC",
        all_time: "favorite_count DESC, t.created_at ASC, t.id ASC",
      };
      const orderBy = sortMap[sortParam] || sortMap.latest;

      const [templateRows, favoriteRows] = await Promise.all([
        database().query<Record<string, unknown>>(`
          SELECT t.id, t.slug, t.name, t.description, t.preview, t.preview_image_url, t.published,
                 t.visibility, t.tags, t.created_by, t.created_at, t.updated_at, u.username AS creator_username,
                 (SELECT COUNT(*) FROM template_favorites f WHERE f.template_id = t.id)::int AS favorite_count,
                 (SELECT COUNT(*) FROM template_favorites f WHERE f.template_id = t.id AND f.created_at >= NOW() - INTERVAL '7 days')::int AS week_favorite_count,
                 (SELECT COUNT(*) FROM template_favorites f WHERE f.template_id = t.id AND f.created_at >= NOW() - INTERVAL '30 days')::int AS month_favorite_count
          FROM profile_templates t
          LEFT JOIN users u ON u.id = t.created_by
          WHERE t.published = TRUE AND t.visibility = 'public'
          ORDER BY ${orderBy}
        `),
        database().query<{ template_id: string }>(
          "SELECT template_id FROM template_favorites WHERE user_id = $1",
          [user.id]
        ),
      ]);

      const favoriteIds = new Set(favoriteRows.rows.map((r) => r.template_id));
      const cards = [];

      for (const row of templateRows.rows) {
        const card = publicTemplateCard(row);
        card.is_favorite = favoriteIds.has(card.id);
        const preview = card.preview as Record<string, unknown>;
        const haystack = [
          card.name,
          card.description,
          ...card.tags,
          String(preview.layout || ""),
          String(preview.backgroundEffect || ""),
        ]
          .join(" ")
          .toLowerCase();

        if (q && !haystack.includes(q)) continue;
        if (tag && !card.tags.includes(tag)) continue;

        cards.push(card);
      }

      return json({ templates: cards });
    }

    // GET /api/v1/templates/me: my created templates
    if (path.length === 1 && path[0] === "me" && method === "GET") {
      const user = await currentUser(request);
      if (!user) return apiError("Not authenticated.", 401);
      if (!(await canCreateTemplates(user))) {
        throw new AdminError("Template creator access is required.", 403);
      }

      const rows = (await database().query<Record<string, unknown>>(`
        SELECT t.id, t.slug, t.name, t.description, t.preview, t.preview_image_url, t.published,
               t.visibility, t.tags, t.created_by, t.created_at, t.updated_at, u.username AS creator_username
        FROM profile_templates t
        LEFT JOIN users u ON u.id = t.created_by
        WHERE t.created_by = $1
        ORDER BY t.updated_at DESC
      `, [user.id])).rows;

      return json({ templates: rows.map(publicTemplateCard) });
    }

    // POST /api/v1/templates: publish new template
    if (path.length === 0 && method === "POST") {
      const user = await currentUser(request);
      if (!user) return apiError("Not authenticated.", 401);
      if (!(await canCreateTemplates(user))) {
        throw new AdminError("Template creator access is required.", 403);
      }

      const limited = await withinLimit(`rl:tpl-create:${user.id}`, 8, 3600).catch(() => false);
      if (!limited) throw new AdminError("Too many template creation requests.", 429);

      const count = Number((await one<{ count: string }>(
        "SELECT COUNT(*) FROM profile_templates WHERE created_by = $1",
        [user.id]
      ))?.count || 0);
      if (count >= 20) {
        throw new AdminError("You already have the maximum number of templates.", 400);
      }

      const body = await request.json().catch(() => null);
      if (!body) throw new AdminError("Invalid request.", 422);

      const name = String(body.name || "").trim();
      if (name.length < 2 || name.length > 48) {
        throw new AdminError("Give your template a name between 2 and 48 characters.", 400);
      }

      const description = String(body.description || "").trim().slice(0, 200);
      const tags = cleanTags(body.tags);
      const visibility = cleanVisibility(body.visibility);
      const previewImageUrl = cleanPreviewImage(body.preview_image_url);

      const profile = await savedProfile(user.id);
      if (!profile) {
        throw new AdminError("Save your look in Customize first, then publish it as a template.", 400);
      }

      const snapshot = snapshotTemplateConfig(profile as unknown as Record<string, unknown>);
      const preview = previewFromSnapshot(snapshot);
      const slug = slugify(name);
      const templateId = randomUUID();

      let row: Record<string, unknown>;
      try {
        row = (await database().query<Record<string, unknown>>(`
          INSERT INTO profile_templates (
            id, slug, name, description, config, preview, preview_image_url,
            published, visibility, tags, created_by
          ) VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, TRUE, $8, $9, $10)
          RETURNING id, slug, name, description, preview, preview_image_url, published,
                    visibility, tags, created_by, created_at, updated_at
        `, [
          templateId, slug, name, description, JSON.stringify(snapshot),
          JSON.stringify(preview), previewImageUrl, visibility, tags, user.id
        ])).rows[0];
      } catch (error) {
        if ((error as { code?: string }).code === "23505") {
          const altSlug = uniqueSlugCandidate(name);
          row = (await database().query<Record<string, unknown>>(`
            INSERT INTO profile_templates (
              id, slug, name, description, config, preview, preview_image_url,
              published, visibility, tags, created_by
            ) VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, TRUE, $8, $9, $10)
            RETURNING id, slug, name, description, preview, preview_image_url, published,
                      visibility, tags, created_by, created_at, updated_at
          `, [
            templateId, altSlug, name, description, JSON.stringify(snapshot),
            JSON.stringify(preview), previewImageUrl, visibility, tags, user.id
          ])).rows[0];
        } else {
          throw error;
        }
      }

      row.creator_username = user.username;
      return json({ template: publicTemplateCard(row) }, 201);
    }

    // POST /api/v1/templates/apply: apply template to user profile
    if (path.length === 1 && path[0] === "apply" && method === "POST") {
      const user = await currentUser(request);
      if (!user) return apiError("Not authenticated.", 401);
      if (!user.username) {
        throw new AdminError("Choose a username before applying a template.", 400);
      }

      const body = await request.json().catch(() => null);
      if (!body || !body.id) throw new AdminError("Template ID is required.", 422);

      const templateId = adminUuid(String(body.id));
      const limited = await withinLimit(`rl:tpl-apply:${user.id}`, 10, 60).catch(() => false);
      if (!limited) throw new AdminError("Too many template applications.", 429);

      const template = (await database().query<Record<string, unknown>>(`
        SELECT * FROM profile_templates WHERE id = $1
      `, [templateId])).rows[0];

      if (!template) throw new AdminError("Template not found.", 404);

      const owner = String(template.created_by) === user.id;
      const visible = Boolean(template.published) && ["public", "unlisted"].includes(String(template.visibility || "public"));
      const isStaff = await isStaffAdmin(user);

      if (!visible && !owner && !isStaff) {
        throw new AdminError("Template not found.", 404);
      }

      const snapshot = (template.config && typeof template.config === "object" ? template.config : {}) as Record<string, unknown>;
      const existing = (await savedProfile(user.id)) || null;
      const merged = applyTemplateSnapshot(existing as unknown as Record<string, unknown> || {}, snapshot);

      const sanitized = sanitizeProfilePayload(merged, user, existing);
      const saved = await persistProfile(user.id, sanitized);

      return json({ profile: saved });
    }

    // GET /api/v1/templates/slug/:slug: get template by slug
    if (path.length === 2 && path[0] === "slug" && method === "GET") {
      const slug = path[1].trim().toLowerCase();
      const user = await currentUser(request);

      const row = (await database().query<Record<string, unknown>>(`
        SELECT t.*, u.username AS creator_username
        FROM profile_templates t
        LEFT JOIN users u ON u.id = t.created_by
        WHERE lower(t.slug) = $1
      `, [slug])).rows[0];

      if (!row) throw new AdminError("Template not found.", 404);

      const owner = Boolean(user && String(row.created_by) === user.id);
      const visible = Boolean(row.published) && ["public", "unlisted"].includes(String(row.visibility || "public"));
      const isStaff = user ? await isStaffAdmin(user) : false;

      if (!visible && !owner && !isStaff) {
        throw new AdminError("Template not found.", 404);
      }

      let isFavorite = false;
      if (user) {
        const fav = await one(
          "SELECT 1 FROM template_favorites WHERE template_id = $1 AND user_id = $2",
          [row.id, user.id]
        );
        isFavorite = Boolean(fav);
      }

      const card = publicTemplateCard(row);
      card.is_favorite = isFavorite;
      return json({ template: card });
    }

    // POST /api/v1/templates/:template_id/favorite
    if (path.length === 2 && path[1] === "favorite" && method === "POST") {
      const user = await currentUser(request);
      if (!user) return apiError("Not authenticated.", 401);

      const templateId = adminUuid(path[0]);
      const body = await request.json().catch(() => ({}));
      const favorite = body?.favorite !== false;

      const template = (await database().query<Record<string, unknown>>(`
        SELECT id, published, visibility FROM profile_templates WHERE id = $1
      `, [templateId])).rows[0];

      if (!template || !template.published || String(template.visibility || "public") !== "public") {
        throw new AdminError("Template not found.", 404);
      }

      if (favorite) {
        await database().query(`
          INSERT INTO template_favorites (template_id, user_id)
          VALUES ($1, $2)
          ON CONFLICT (template_id, user_id) DO NOTHING
        `, [templateId, user.id]);
      } else {
        await database().query(
          "DELETE FROM template_favorites WHERE template_id = $1 AND user_id = $2",
          [templateId, user.id]
        );
      }

      return json({ favorite });
    }

    // POST /api/v1/templates/:template_id/refresh
    if (path.length === 2 && path[1] === "refresh" && method === "POST") {
      const user = await currentUser(request);
      if (!user) return apiError("Not authenticated.", 401);
      if (!(await canCreateTemplates(user))) {
        throw new AdminError("Template creator access is required.", 403);
      }

      const templateId = adminUuid(path[0]);
      const template = (await database().query<Record<string, unknown>>(
        "SELECT * FROM profile_templates WHERE id = $1",
        [templateId]
      )).rows[0];

      if (!template) throw new AdminError("Template not found.", 404);
      if (String(template.created_by) !== user.id && !(await isStaffAdmin(user))) {
        throw new AdminError("Template not found.", 404);
      }

      const limited = await withinLimit(`rl:tpl-refresh:${user.id}`, 8, 3600).catch(() => false);
      if (!limited) throw new AdminError("Too many refresh requests.", 429);

      const body = await request.json().catch(() => ({}));
      const previewImageUrl = cleanPreviewImage(body?.preview_image_url);

      const profile = await savedProfile(user.id);
      if (!profile) {
        throw new AdminError("Save your look in Customize first, then publish it as a template.", 400);
      }

      const snapshot = snapshotTemplateConfig(profile as unknown as Record<string, unknown>);
      const preview = previewFromSnapshot(snapshot);

      const updated = (await database().query<Record<string, unknown>>(`
        UPDATE profile_templates
        SET config = $2::jsonb, preview = $3::jsonb,
            preview_image_url = COALESCE($4, preview_image_url),
            updated_at = NOW()
        WHERE id = $1
        RETURNING *
      `, [templateId, JSON.stringify(snapshot), JSON.stringify(preview), previewImageUrl])).rows[0];

      if (!updated) throw new AdminError("Template not found.", 404);
      updated.creator_username = user.username;
      return json({ template: publicTemplateCard(updated) });
    }

    // PATCH /api/v1/templates/:template_id: update meta
    if (path.length === 1 && method === "PATCH") {
      const user = await currentUser(request);
      if (!user) return apiError("Not authenticated.", 401);
      if (!(await canCreateTemplates(user))) {
        throw new AdminError("Template creator access is required.", 403);
      }

      const templateId = adminUuid(path[0]);
      const template = (await database().query<Record<string, unknown>>(
        "SELECT * FROM profile_templates WHERE id = $1",
        [templateId]
      )).rows[0];

      if (!template) throw new AdminError("Template not found.", 404);
      if (String(template.created_by) !== user.id && !(await isStaffAdmin(user))) {
        throw new AdminError("Template not found.", 404);
      }

      const body = await request.json().catch(() => null);
      if (!body) throw new AdminError("Invalid request.", 422);

      const nextName = body.name ? String(body.name).trim() : template.name;
      const nextDesc = body.description !== undefined ? String(body.description || "").trim().slice(0, 200) : template.description;
      const nextPub = body.published !== undefined ? Boolean(body.published) : template.published;
      const nextSlug = body.name ? slugify(nextName as string) : template.slug;
      const nextTags = body.tags !== undefined ? cleanTags(body.tags) : template.tags;
      const nextVis = body.visibility !== undefined ? cleanVisibility(body.visibility) : template.visibility;

      let updated: Record<string, unknown>;
      try {
        updated = (await database().query<Record<string, unknown>>(`
          UPDATE profile_templates
          SET name = $2, description = $3, published = $4, slug = $5, tags = $6, visibility = $7, updated_at = NOW()
          WHERE id = $1
          RETURNING *
        `, [templateId, nextName, nextDesc, nextPub, nextSlug, nextTags, nextVis])).rows[0];
      } catch (error) {
        if ((error as { code?: string }).code === "23505") {
          const altSlug = uniqueSlugCandidate(nextName as string);
          updated = (await database().query<Record<string, unknown>>(`
            UPDATE profile_templates
            SET name = $2, description = $3, published = $4, slug = $5, tags = $6, visibility = $7, updated_at = NOW()
            WHERE id = $1
            RETURNING *
          `, [templateId, nextName, nextDesc, nextPub, altSlug, nextTags, nextVis])).rows[0];
        } else {
          throw error;
        }
      }

      if (!updated) throw new AdminError("Template not found.", 404);
      updated.creator_username = user.username;
      return json({ template: publicTemplateCard(updated) });
    }

    // DELETE /api/v1/templates/:template_id: remove template
    if (path.length === 1 && method === "DELETE") {
      const user = await currentUser(request);
      if (!user) return apiError("Not authenticated.", 401);
      if (!(await canCreateTemplates(user))) {
        throw new AdminError("Template creator access is required.", 403);
      }

      const templateId = adminUuid(path[0]);
      const template = (await database().query<Record<string, unknown>>(
        "SELECT * FROM profile_templates WHERE id = $1",
        [templateId]
      )).rows[0];

      if (!template) throw new AdminError("Template not found.", 404);
      if (String(template.created_by) !== user.id && !(await isStaffAdmin(user))) {
        throw new AdminError("Template not found.", 404);
      }

      await database().query("DELETE FROM profile_templates WHERE id = $1", [templateId]);
      return json({ ok: true });
    }

    return apiError("Not found.", 404);
  } catch (error) {
    return error instanceof AdminError
      ? apiError(error.message, error.status)
      : error instanceof SyntaxError
      ? apiError("Invalid request.", 422)
      : apiError("Templates service is temporarily unavailable.", 503);
  }
}
