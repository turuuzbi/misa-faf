use super::helpers::*;
use axum::extract::{Json, Path, State};
use axum::http::StatusCode;
use serde::Deserialize;
use serde_json::{json, Value};
use sqlx::PgPool;
use uuid::Uuid;

pub const SLOTS_MAX: i64 = 5;
pub const NAME_MAX: usize = 40;

#[derive(Deserialize)]
pub struct Nominate {
    to_username: Option<String>,
}

async fn enabled(pool: &PgPool, user_id: &Uuid) -> bool {
    feature_on(pool, user_id, "neighbours").await.0
}

fn clean_handle(raw: &str) -> String {
    raw.trim().trim_start_matches('@').to_string()
}

/// Case-insensitive lookup; returns the id and the current canonical handle.
async fn user_of(pool: &PgPool, username: &str) -> Option<(Uuid, String)> {
    sqlx::query_as("SELECT id, username FROM users WHERE LOWER(username) = LOWER($1)")
        .bind(username)
        .fetch_optional(pool)
        .await
        .ok()
        .flatten()
}

/// One nominated page as the owner sees it, with its *current* handle
/// (a renamed page keeps the relationship because edges are keyed by user id).
struct Edge {
    to_id: Option<Uuid>,
    handle: String,
}

async fn edges_from(pool: &PgPool, user_id: &Uuid) -> Result<Vec<Edge>, (StatusCode, Json<Value>)> {
    let rows: Vec<(Option<Uuid>, String, Option<String>)> = sqlx::query_as(
        "SELECT COALESCE(n.to_user_id, u.id), n.to_username, u.username
         FROM feature_neighbours n
         LEFT JOIN users u ON u.id = n.to_user_id OR (n.to_user_id IS NULL AND LOWER(u.username) = LOWER(n.to_username))
         WHERE n.from_user_id = $1
         ORDER BY n.ord ASC, n.created_at ASC",
    )
    .bind(user_id)
    .fetch_all(pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    Ok(rows
        .into_iter()
        .map(|(to_id, stored, current)| Edge { to_id, handle: current.unwrap_or(stored) })
        .collect())
}

/// Reciprocal edge that is allowed to show publicly: the other page named us back,
/// still exists, is not suspended, and has the feature switched on (spec 09).
async fn is_public_mutual(pool: &PgPool, user_id: &Uuid, to_id: &Uuid) -> bool {
    let named_back: bool = sqlx::query_scalar(
        "SELECT EXISTS(
            SELECT 1 FROM feature_neighbours n
            JOIN users me ON me.id = $2
            WHERE n.from_user_id = $1
              AND (n.to_user_id = $2 OR (n.to_user_id IS NULL AND LOWER(n.to_username) = LOWER(me.username)))
        ) AND EXISTS(
            SELECT 1 FROM users t WHERE t.id = $1
              AND (t.suspended_at IS NULL OR (t.suspended_until IS NOT NULL AND t.suspended_until < NOW()))
        )",
    )
    .bind(to_id)
    .bind(user_id)
    .fetch_one(pool)
    .await
    .unwrap_or(false);
    named_back && enabled(pool, to_id).await
}

fn accent_of(settings: &Value) -> Option<String> {
    let raw = settings.get("accentColor")?.as_str()?;
    let hex = raw.strip_prefix('#')?;
    (hex.len() == 6 && hex.chars().all(|c| c.is_ascii_hexdigit())).then(|| format!("#{hex}"))
}

pub async fn nominate(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
    Json(body): Json<Nominate>,
) -> ApiResult {
    if !enabled(&pool, &user_id).await {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    let to = clean_handle(&body.to_username.unwrap_or_default());
    if to.is_empty() || to.chars().count() > NAME_MAX {
        return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "invalid_name", "Invalid neighbour username."));
    }
    let Some((to_id, canonical)) = user_of(&pool, &to).await else {
        return Err(err_reason(StatusCode::NOT_FOUND, "user_not_found", "That profile does not exist."));
    };
    if to_id == user_id {
        return Err(err_reason(StatusCode::CONFLICT, "self_nomination", "You cannot nominate yourself."));
    }

    // Serialise nominations per owner so concurrent adds cannot exceed five slots
    // or insert the same page twice under different letter case (spec 09.2).
    let mut tx = pool.begin().await.map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    sqlx::query("SELECT pg_advisory_xact_lock(hashtextextended($1::text, 7309))")
        .bind(user_id)
        .execute(&mut *tx)
        .await
        .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    let (count, dup): (i64, bool) = sqlx::query_as(
        "SELECT COUNT(*),
                COALESCE(BOOL_OR(to_user_id = $2 OR LOWER(to_username) = LOWER($3)), FALSE)
         FROM feature_neighbours WHERE from_user_id = $1",
    )
    .bind(user_id)
    .bind(to_id)
    .bind(&canonical)
    .fetch_one(&mut *tx)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    if dup {
        return Err(err_reason(StatusCode::CONFLICT, "duplicate", "Already nominated."));
    }
    if count >= SLOTS_MAX {
        return Err(err_reason(StatusCode::CONFLICT, "slots_full", "Neighbour slots are full."));
    }
    sqlx::query(
        "INSERT INTO feature_neighbours (id, from_user_id, to_username, to_user_id, ord)
         VALUES ($1,$2,$3,$4,$5)",
    )
    .bind(new_uuid())
    .bind(user_id)
    .bind(&canonical)
    .bind(to_id)
    .bind(count as i32)
    .execute(&mut *tx)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    tx.commit().await.map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    let mutual = is_public_mutual(&pool, &user_id, &to_id).await;
    ok(json!({ "ok": true, "username": canonical, "mutual": mutual }))
}

pub async fn remove(
    State(pool): State<PgPool>,
    Path((user_id, to_username)): Path<(Uuid, String)>,
) -> ApiResult {
    let handle = clean_handle(&to_username);
    let target = user_of(&pool, &handle).await.map(|(id, _)| id);
    let affected = sqlx::query(
        "DELETE FROM feature_neighbours
         WHERE from_user_id = $1 AND (LOWER(to_username) = LOWER($2) OR ($3::uuid IS NOT NULL AND to_user_id = $3))",
    )
    .bind(user_id)
    .bind(&handle)
    .bind(target)
    .execute(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    if affected.rows_affected() == 0 {
        return Err(err(StatusCode::NOT_FOUND, "neighbour_not_found"));
    }
    ok(json!({ "ok": true, "username": handle }))
}

pub async fn owner_view(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    let edges = edges_from(&pool, &user_id).await?;
    let mut nominees: Vec<Value> = Vec::with_capacity(edges.len());
    for edge in &edges {
        let mutual = match edge.to_id {
            Some(to_id) => is_public_mutual(&pool, &user_id, &to_id).await,
            None => false,
        };
        let state = if edge.to_id.is_none() { "missing" } else if mutual { "mutual" } else { "waiting" };
        nominees.push(json!({ "username": edge.handle, "mutual": mutual, "state": state }));
    }
    // Free slots; a pending nomination still uses one (spec 09).
    let slots = (SLOTS_MAX - edges.len() as i64).max(0);
    ok(json!({ "slots": slots, "max": SLOTS_MAX, "neighbours": nominees }))
}

pub async fn public_view(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    if !enabled(&pool, &user_id).await {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    let edges = edges_from(&pool, &user_id).await?;
    let mut neighbours: Vec<Value> = Vec::new();
    for edge in edges {
        let Some(to_id) = edge.to_id else { continue };
        if !is_public_mutual(&pool, &user_id, &to_id).await {
            continue;
        }
        let settings = settings_of(read_config(&pool, &to_id).await.as_ref());
        neighbours.push(json!({ "username": edge.handle, "mutual": true, "color": accent_of(&settings) }));
    }
    ok(json!({ "neighbours": neighbours }))
}
