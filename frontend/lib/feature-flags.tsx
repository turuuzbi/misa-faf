"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { dashboardRequest, peekDashboardCache } from "@/lib/dashboard-cache";

export const DEFAULT_FEATURE_FLAGS: Record<string, boolean> = {
  "nav.overview": true, "nav.analytics": true, "nav.badges": true, "nav.settings": true, "nav.security": true, "nav.constellations": true,
  "nav.customize": true, "nav.links": true, "nav.leaderboard": true, "nav.premium": true, "nav.templates": true,
  "customize.assets": true, "customize.assets.avatar": true, "customize.assets.background": true,
  "customize.assets.backgroundVideo": true, "customize.assets.audio": true, "customize.assets.audioCrop": true,
  "customize.layout": true, "customize.effects": true, "customize.effects.username": true,
  "customize.widgets": true, "customize.portfolio": true, "customize.sharing": true,
  "profile.frame": true, "profile.avatar": true, "profile.avatarBorder": true, "profile.displayName": true,
  "profile.socials": true, "profile.widgets": true, "profile.badges": true, "profile.audio": true,
  "profile.views": true, "profile.joinDate": true, "integrations.discord": true,
  "feature.usernameEffects.glitch": true, "feature.usernameEffects.pulse": true,
  "feature.usernameEffects.wave": true, "feature.usernameEffects.shadow": true,
  // Living-profile features: the data-api enforces these; the UI only skips dead widgets.
  "feature.ask_anything": true, "feature.other_side": true, "feature.night_shift": true, "feature.daily_draw": true,
  "feature.time_capsule": true, "feature.archive": true, "feature.moon": true, "feature.guestbook": true,
  "feature.neighbours": true, "feature.alive": true, "feature.alive.presence": true, "feature.alive.clock": true,
  "feature.alive.hits": true, "feature.secret_word": true, "feature.chalkboard": true, "feature.tally": true,
};

const FEATURE_FLAGS_KEY = "feature-flags";
const FeatureFlagsContext = createContext<Record<string, boolean>>(DEFAULT_FEATURE_FLAGS);

function loadFeatureFlags() {
  return dashboardRequest(FEATURE_FLAGS_KEY, async () => {
    const response = await fetch("/api/v1/feature-flags", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not load feature flags.");
    const payload = await response.json() as { flags?: Record<string, boolean> };
    return { ...DEFAULT_FEATURE_FLAGS, ...(payload.flags || {}) };
  }, { maxAge: 5 * 60_000 });
}

export function FeatureFlagsProvider({ children }: { children: React.ReactNode }) {
  const [flags, setFlags] = useState(() => peekDashboardCache<Record<string, boolean>>(FEATURE_FLAGS_KEY) || DEFAULT_FEATURE_FLAGS);
  useEffect(() => {
    let alive = true;
    void loadFeatureFlags().then((next) => { if (alive) setFlags(next); }).catch(() => undefined);
    return () => { alive = false; };
  }, []);
  const value = useMemo(() => flags, [flags]);
  return <FeatureFlagsContext.Provider value={value}>{children}</FeatureFlagsContext.Provider>;
}

export function useFeatureFlags() {
  const flags = useContext(FeatureFlagsContext);
  return { flags, enabled: (key: string) => flags[key] !== false };
}