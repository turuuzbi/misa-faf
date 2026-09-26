"use client";

import { useEffect, useRef, useState, type CSSProperties, type RefObject, type PointerEvent } from "react";
import { createPortal } from "react-dom";
import { ArrowDown, Eye, MapPin } from "lucide-react";
import { ProfileLayoutElement } from "./ProfileLayoutElement";
import { ProfileAvatar, ProfileMeta, ProfileBio, ProfileDiscord, ProfileIdentity } from "./ProfileCardModules";
import { ProfileSections } from "./ProfileSections";
import { ProfileWidgets, WidgetResolutionProvider } from "./ProfileWidgets";
import { SocialLinks } from "../socials/SocialLinks";
import { ProfileFeatures } from "./ProfileFeatures";
import { portfolioPages } from "@/lib/portfolio";
import type { ProfileConfig } from "@/lib/types";

/** Uses the same draft, modules and media hosts as the compact profile layouts. */
export function PortfolioProfile({ config, preview, rootRef, frameStyle }: { config: ProfileConfig; preview: boolean; rootRef: RefObject<HTMLDivElement | null>; frameStyle: CSSProperties }) {
  const root = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState("hero");
  const [navigationHost, setNavigationHost] = useState<HTMLDivElement | null>(null);
  useEffect(() => { setNavigationHost(rootRef.current); }, [rootRef]);
  const sections = portfolioPages(config);
  const sectionKey = sections.map(page => page.items.map(item => item.id).join(",")).join("|");
  const centered = config.settings.premium?.hero === "Centered";
  const align = centered ? "center" : config.settings.socialAlign || "center";
  const navigate = (id: string) => {
    const target = Array.from(root.current?.querySelectorAll<HTMLElement>("[data-portfolio-section]") || []).find(node => node.dataset.portfolioSection === id);
    const scroller = (rootRef.current?.querySelector(".profile-composition") as HTMLElement | null) || rootRef.current;
    if (!target || !scroller) return;
    const behavior = matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth";
    // Scroll only the preview, never its containing dashboard.
    if (scroller.scrollHeight > scroller.clientHeight + 1 && getComputedStyle(scroller).overflowY === "auto") {
      scroller.scrollTo({ top: scroller.scrollTop + target.getBoundingClientRect().top - scroller.getBoundingClientRect().top, behavior });
    } else window.scrollTo({ top: window.scrollY + target.getBoundingClientRect().top, behavior });
  };
  const tilt = (event: PointerEvent<HTMLDivElement>) => {
    if (!config.settings.cardTilt || event.pointerType !== "mouse" || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const box = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - box.left) / box.width - .5, y = (event.clientY - box.top) / box.height - .5;
    event.currentTarget.style.transform = `perspective(900px) rotateX(${-y * 5}deg) rotateY(${x * 6}deg)`;
  };
  const animation = config.settings.pageEnter || "Fade";
  useEffect(() => {
    let disposed = false;
    let cleanup: (() => void) | undefined;
    const url = "/dashboard/portfolio-scene.mjs?v=20260922-scroll";
    void import(/* webpackIgnore: true */ url).then((module: { mountPortfolioScene: (root: HTMLElement, options: { animation: string; onActive: (id: string) => void }) => () => void }) => {
      if (!disposed && rootRef.current) cleanup = module.mountPortfolioScene(rootRef.current, { animation, onActive: setActive });
    });
    return () => { disposed = true; cleanup?.(); };
  }, [sectionKey, rootRef, animation]);
  return <WidgetResolutionProvider config={config} preview={preview}>
    <div ref={root} className="portfolio-profile" data-profile-variant="Portfolio" data-hero={centered ? "centered" : "classic"}>
      <section className="portfolio-hero" data-portfolio-section="hero" aria-label="Profile">
        <ProfileLayoutElement id="frame"><div className="profile-glass portfolio-first-frame p-7 sm:p-9" style={frameStyle} onPointerMove={tilt} onPointerLeave={event => { event.currentTarget.style.transform = ""; }}><div className="profile-header" data-identity-align={align}>
          {config.settings.showAvatar !== false && <ProfileAvatar config={config} />}
          <div className="profile-first-identity" style={{ textAlign: align }}><ProfileIdentity config={config} align={align} /><ProfileBio config={config} align={align} showLocation={false} /></div>
        </div><ProfileWidgets config={config} preview={preview} presence={<ProfileDiscord config={config} />} /><SocialLinks config={config} align={align} /><ProfileFeatures config={config} preview={preview} /><ProfileMeta config={config} align="left" /></div></ProfileLayoutElement>
        <div data-profile-mobile-audio className="profile-mobile-audio" />
        {!!sections.length && <button type="button" className="portfolio-scroll" onClick={() => navigate(sections[0].id)}>Scroll for more<ArrowDown size={18} /></button>}
      </section>

      <ProfileSections config={config} preview={preview} portfolio />
        {navigationHost && (config.settings.showViews || config.profile.location) && createPortal(<div className="portfolio-metadata">
          {config.settings.showViews && <span title="Profile Views"><Eye size={17} />{config.profile.views.toLocaleString()}</span>}
          {config.profile.location && <span title="Location"><MapPin size={17} />{config.profile.location}</span>}
        </div>, navigationHost)}
      {!!sections.length && navigationHost && createPortal(<nav className="portfolio-navigation" aria-label="Profile sections">{[{ id: "hero", title: "Profile" }, ...sections].map((section, index) => <button type="button" key={section.id} aria-label={`Go to ${section.title || `section ${index}`}`} aria-current={active === section.id ? "location" : undefined} onClick={() => navigate(section.id)}><span /></button>)}</nav>, navigationHost)}
    </div>
  </WidgetResolutionProvider>;
}
