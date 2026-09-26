import type { ProfileConfig } from "./types";

/**
 * Which living-profile features a page shows, and the public data they need.
 * Mirrors backend/app/core/profile_features.py (the server-rendered page); the
 * data-api re-checks the owner and admin switches on every request anyway.
 */
export type FeaturesPayload = {
  user: string;
  name: string;
  accent?: string | null;
  preview: boolean;
  presence?: true;
  clock?: { tz: string; label: string; h24: boolean };
  hits?: { style: string };
  moon?: { hemisphere: "north" | "south" };
  night?: true;
  draw?: true;
  capsule?: { label: string };
  tally?: true;
  asks?: { prompt: string };
  guestbook?: { heading: string };
  doodles?: { title: string };
  neighbours?: true;
  secret?: true;
  reverse?: { title: string; text: string };
};

const FLAGS: Record<string, string[]> = {
  presence: ["feature.alive", "feature.alive.presence"],
  clock: ["feature.alive", "feature.alive.clock"],
  hits: ["feature.alive", "feature.alive.hits"],
  moon: ["feature.moon"],
  night: ["feature.night_shift"],
  draw: ["feature.daily_draw"],
  capsule: ["feature.time_capsule"],
  tally: ["feature.tally"],
  asks: ["feature.ask_anything"],
  guestbook: ["feature.guestbook"],
  doodles: ["feature.chalkboard"],
  neighbours: ["feature.neighbours"],
  secret: ["feature.secret_word"],
  reverse: ["feature.other_side"],
};

type Loose = Record<string, unknown>;
const obj = (value: unknown): Loose => (value && typeof value === "object" && !Array.isArray(value) ? (value as Loose) : {});
const text = (value: unknown, limit = 200) => (typeof value === "string" || typeof value === "number" ? String(value).trim().slice(0, limit) : "");

/** Same rule as the data-api's `feature_enabled` (helpers.rs). */
export function hasContent(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === "boolean") return value;
  if (typeof value === "string") return value.trim().length > 0;
  if (typeof value === "number") return value !== 0;
  if (Array.isArray(value)) return value.some((item) => item != null && !(typeof item === "string" && !item.trim()));
  if (typeof value === "object") {
    const o = value as Loose;
    if (typeof o.enabled === "boolean") return o.enabled;
    return Object.values(o).some((v) => typeof v !== "number" && hasContent(v));
  }
  return false;
}

export function featuresPayload(config: ProfileConfig, flagOn: (key: string) => boolean, preview: boolean): FeaturesPayload | null {
  const s = config.settings as unknown as Loose;
  const user = text(config.profile?.username, 32);
  if (!user) return null;
  const allowed = (key: string) => FLAGS[key].every(flagOn);
  const night = obj(s.night);
  const tz = text(s.timezone, 64) || text(night.tz, 64);
  const out: Omit<FeaturesPayload, "user" | "name" | "accent" | "preview"> = {};

  if (hasContent(s.presence) && allowed("presence")) out.presence = true;
  if (hasContent(s.clock) && tz && allowed("clock")) out.clock = { tz, label: text(s.clockLabel, 40), h24: Boolean(s.clock24) };
  const style = text(s.counterStyle, 16).toLowerCase();
  if ((s.hits === true || (style && style !== "plain" && style !== "off")) && allowed("hits")) out.hits = { style: style && style !== "plain" && style !== "off" ? style : "odometer" };
  if (hasContent(s.moon) && allowed("moon")) out.moon = { hemisphere: obj(s.moon).hemisphere === "south" ? "south" : "north" };
  if (hasContent(s.night) && allowed("night")) out.night = true;
  if (hasContent(s.draw) && allowed("draw")) out.draw = true;
  const capsule = obj(s.capsule);
  if ((capsule.sealed || text(capsule.text, 5000)) && allowed("capsule")) out.capsule = { label: text(capsule.label, 80) };
  const tally = obj(s.tally);
  if ((text(tally.q) || tally.enabled === true) && allowed("tally")) out.tally = true;
  if (hasContent(s.asks) && allowed("asks")) out.asks = { prompt: text(s.asksPrompt, 120) };
  if (hasContent(s.guestbook) && allowed("guestbook")) out.guestbook = { heading: text(s.guestbookHeading, 60) };
  if (hasContent(s.doodles) && allowed("doodles")) out.doodles = { title: text(s.doodlesTitle, 60) };
  if (hasContent(s.neighbours) && allowed("neighbours")) out.neighbours = true;
  const secret = obj(s.secret);
  if ((secret.configured || (secret.word && secret.url)) && allowed("secret")) out.secret = true;
  const reverse = obj(s.reverse);
  const backTitle = text(reverse.title, 80), backText = text(reverse.text, 1200);
  if ((backTitle || backText) && allowed("reverse")) out.reverse = { title: backTitle, text: backText };

  if (!Object.keys(out).length) return null;
  return { ...out, user, name: text(config.profile?.displayName, 64) || user, accent: typeof s.accentColor === "string" ? s.accentColor : null, preview };
}
