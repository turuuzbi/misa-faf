"use client";

import { useEffect, useMemo, useRef } from "react";
import { useFeatureFlags } from "@/lib/feature-flags";
import { featuresPayload } from "@/lib/profile-features";
import type { ProfileConfig } from "@/lib/types";

const STYLESHEET = "/dashboard/profile-features.css?v=20260926";
const MODULE = "/dashboard/profile-features.mjs?v=20260926";

type FeaturesModule = { mountFeatures: (host: HTMLElement, data: unknown) => () => void };

/**
 * Living-profile features (guestbook, AMA, tally, moon, ...). The same client
 * module powers the server-rendered username page; here it is mounted into the
 * React card. In `preview` (the dashboard) it is read-only: no heartbeats, no
 * hit counting and no submissions.
 */
export function ProfileFeatures({ config, preview }: { config: ProfileConfig; preview: boolean }) {
  const ref = useRef<HTMLElement>(null);
  const { enabled } = useFeatureFlags();
  const payload = useMemo(() => featuresPayload(config, enabled, preview), [config, enabled, preview]);
  const key = payload ? JSON.stringify(payload) : "";

  useEffect(() => {
    if (!key || !ref.current) return;
    if (!document.querySelector(`link[data-misa-features-css]`)) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = STYLESHEET;
      link.dataset.misaFeaturesCss = "";
      document.head.append(link);
    }
    let disposed = false;
    let cleanup: (() => void) | undefined;
    void import(/* webpackIgnore: true */ MODULE).then((module: FeaturesModule) => {
      if (!disposed && ref.current) cleanup = module.mountFeatures(ref.current, JSON.parse(key));
    }).catch(() => undefined);
    return () => { disposed = true; cleanup?.(); };
  }, [key]);

  if (!payload) return null;
  return <section ref={ref} className="misa-features" aria-label="On this page" />;
}
