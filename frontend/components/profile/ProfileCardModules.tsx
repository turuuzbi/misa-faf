"use client";

import { ProfileFeatures } from "./ProfileFeatures";
import { ProfileLayoutElement } from "./ProfileLayoutElement";

import { BadgeCheck, Crown, MapPin, Sparkles, Zap } from "lucide-react";
import { useEffect, useLayoutEffect, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import type { LayoutViewport } from "@/lib/element-layout";
import { ProfileMusicPlayer, ProfileVideoAudioControl } from "@/components/profile/ProfileMusicPlayer";
import { BadgeArtwork } from "@/components/badges/BadgeArtwork";
import { ProfileSections } from "@/components/profile/ProfileSections";
import { WidgetResolutionProvider } from "./ProfileWidgets";
import { ProfileWidgets } from "@/components/profile/ProfileWidgets";
import { SocialLinks } from "@/components/socials/SocialLinks";
import { badgePaint, hasVerifiedBadge } from "@/lib/badges";
import { avatarRadius, formatJoinDate } from "@/lib/profile-layout";
import { useOptionalAuth } from "@/lib/auth-store";
import { usesBackgroundVideoAudio, usesUploadedProfileAudio } from "@/lib/audio";
import { DISCORD_STATUS_COLORS, DISCORD_STATUS_LABELS, DiscordStatusGlyph, type DiscordPresence, useDiscordLive } from "@/lib/discord-live";
import type { ProfileConfig } from "@/lib/types";
import { bioLines, nameTracking, typeMs, typeSize, usernameEffectClass } from "@/lib/typography";

function useCardDiscord(config: ProfileConfig) {
  const live = useDiscordLive();
  const username = useOptionalAuth()?.user?.username;
  const fromConfig = config.discord;
  if (fromConfig?.avatar || fromConfig?.accountAvatar || fromConfig?.decoration || fromConfig?.guildTag || fromConfig?.status || fromConfig?.username || fromConfig?.globalName) return fromConfig;
  if (username && username === config.profile.username && live?.state) {
    return {
      ...live.state.card,
      username: live.state.card.username || live.state.username,
      status: live.state.prefs.showStatus === false ? undefined : live.state.status,
    };
  }
  return undefined;
}
function DiscordStatusBadge({ status }: { status?: string | null }) {
  if (!status || !(status in DISCORD_STATUS_COLORS)) return null;
  return (
    <span
      className="absolute bottom-0.5 right-0.5 z-[4] h-[22%] w-[22%] min-h-3 min-w-3"
      title={`Discord ${status}`}
      aria-label={`Discord ${status}`}
    >
      <DiscordStatusGlyph status={status as DiscordPresence} className="block h-full w-full" />
    </span>
  );
}

export function ProfileAvatar({ config, className = "" }: { config: ProfileConfig; className?: string }) {
  const radius = avatarRadius(config.settings.avatarShape);
  const showBorder = config.settings.showAvatarBorder !== false;
  const discord = useCardDiscord(config);
  const src = discord?.avatar || config.assets.avatar.url;
  const outerClass = "relative mx-auto " + (showBorder ? "p-1 " : "p-0 ") + (className.includes("h-") ? className : "h-24 w-24 " + className);
  const innerClass = "flex h-full w-full items-center justify-center overflow-hidden " + (showBorder ? "border-4 border-[#15151d] bg-gradient-to-br from-[#6358a3] via-[#282442] to-[#0d0d13]" : "border-0 bg-transparent") + " text-3xl font-semibold text-white";
  return (
    <div className={outerClass} style={{ borderRadius: radius, background: showBorder ? "linear-gradient(135deg, " + config.settings.accentColor + ", #ffffff55, " + config.settings.accentColor + "22)" : "transparent" }}>
      <div className={innerClass} style={{ borderRadius: radius }}>
        {src ? <img src={src} alt="" className="h-full w-full object-cover" /> : config.profile.displayName.slice(0, 1)}
      </div>
      {discord?.decoration && <img src={discord.decoration} alt="" className="pointer-events-none absolute inset-[-18%] z-[3] h-[136%] w-[136%] max-w-none" />}
      <DiscordStatusBadge status={discord?.status} />
    </div>
  );
}
export function ProfileBanner({ config }: { config: ProfileConfig }) {
  const src = config.assets.banner?.url;
  if (!src) return null;
  const radius = config.settings.bannerShape === "square" ? "0px" : config.settings.bannerShape === "pill" ? "999px" : "18px";
  const height = profileLayoutIsSleek(config) ? 148 : 112;
  return <div className="overflow-hidden" style={{ borderRadius: radius, height }}><img src={src} alt="" className="h-full w-full object-cover" /></div>;
}

export function ProfileIdentity({ config, align = "center" }: { config: ProfileConfig; align?: "left" | "center" | "right" }) {
  const justify = align === "left" ? "justify-start" : align === "right" ? "justify-end" : "justify-center";
  const guild = useCardDiscord(config)?.guildTag;
  return (
    <div style={{ textAlign: align }}>
      <div className={`flex flex-wrap items-center gap-2 ${justify}`}>
        {config.settings.showDisplayName !== false && <ProfileDisplayName config={config} />}
        {guild?.tag && guild.badge && <span className="inline-flex items-center gap-1 rounded-md border border-white/15 bg-white/10 px-1.5 py-0.5 text-[11px] font-semibold tracking-wide text-white/90"><img src={guild.badge} alt="" className="h-4 w-4 rounded-sm object-cover" />{guild.tag}</span>}
        {hasVerifiedBadge(config.badges) && <span className="text-[#fb7185]" title="Verified"><BadgeCheck size={19} fill="currentColor" strokeWidth={1.4} /></span>}
        <ProfileBadges config={config} className="" />
      </div>
      {config.settings.showUsername !== false ? <p className="mt-1 text-xs text-white/35">@{config.profile.username}</p> : null}
    </div>
  );
}

export function ProfileDisplayName({ config }: { config: ProfileConfig }) {
  const s = config.settings;
  const name = config.profile.displayName;
  const effect = s.usernameEffect;
  const [typed, setTyped] = useState(effect === "Shuffle" ? "" : name);
  useEffect(() => {
    if (effect !== "Shuffle") { setTyped(name); return; }
    setTyped("");
    const glyphs = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    let step = 0;
    const timer = window.setInterval(() => {
      step += 1;
      setTyped(name.split("").map((ch, index) => {
        if (ch === " " || index < Math.floor(step / 2)) return name[index] || "";
        return glyphs[Math.floor(Math.random() * glyphs.length)];
      }).join(""));
      if (step > name.length * 2 + 4) window.clearInterval(timer);
    }, 40);
    return () => window.clearInterval(timer);
  }, [name, effect]);
  const usernameColor = s.usernameColor || s.textColor || "#ffffff";
  const effectColor = s.usernameEffectColor || s.accentColor || "#e11d48";
  const gradientEffect = effect === "Gradient" || effect === "Shimmer" || effect === "Rainbow";
  const effectClass = usernameEffectClass(effect);
  const rainbow = effect === "Rainbow" ? { backgroundImage: "linear-gradient(90deg, #ff3b6b, #ffcf4a, #61e294, #55b8ff, #b887ff, #ff3b6b)", backgroundSize: "200% 100%" } : {};
  return (
    <h1
      className={`font-semibold ${effectClass}`}
      style={{
        fontSize: "var(--profile-name-size, " + (typeSize(s.fontSize) + 8) + "px)",
        letterSpacing: nameTracking(s.letterSpacing),
        fontFamily: "var(--misa-profile-font)",
        color: gradientEffect ? undefined : usernameColor,
        textShadow: s.usernameGlow || effect === "Glow" ? "0 0 24px " + effectColor + "aa" : undefined,
        ["--username-color" as string]: usernameColor,
        ["--effect-color" as string]: effectColor,
        ...rainbow,
      }}
    >
      {typed || name}
    </h1>
  );
}

export function ProfileBio({ config, align = "center", showLocation = true }: { config: ProfileConfig; align?: "left" | "center" | "right"; showLocation?: boolean }) {
  const justify = align === "left" ? "justify-start" : align === "right" ? "justify-end" : "justify-center";
  const description = config.settings.premium?.typewriterTexts?.filter(Boolean).join("\n") || config.profile.description;
  const lines = bioLines(description);
  const [typed, setTyped] = useState(config.settings.bioTypewriter ? "" : config.profile.description);
  useEffect(() => {
    if (!config.settings.bioTypewriter || lines.length === 0 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setTyped(description);
      return;
    }
    let line = 0;
    let index = 0;
    let deleting = false;
    let timer = 0;
    const typeSpeed = typeMs(config.settings.bioTypeMs, 55);
    const deleteSpeed = typeMs(config.settings.bioDeleteMs, 35);
    const pause = Math.max(400, Math.min(4000, Number(config.settings.bioPauseMs) || 1200));
    const tick = () => {
      const current = lines[line] || "";
      if (!deleting) {
        index += 1;
        setTyped(current.slice(0, index));
        if (index >= current.length) {
          deleting = lines.length > 1;
          timer = window.setTimeout(tick, lines.length > 1 ? pause : 999999);
          return;
        }
        timer = window.setTimeout(tick, typeSpeed);
        return;
      }
      index -= 1;
      setTyped(current.slice(0, Math.max(0, index)));
      if (index <= 0) {
        deleting = false;
        line = (line + 1) % lines.length;
        timer = window.setTimeout(tick, typeSpeed);
        return;
      }
      timer = window.setTimeout(tick, deleteSpeed);
    };
    timer = window.setTimeout(tick, typeSpeed);
    return () => window.clearTimeout(timer);
  }, [description, config.settings.bioTypewriter, config.settings.bioTypeMs, config.settings.bioDeleteMs, config.settings.bioPauseMs]);
  return (
    <>
      {description && <p className="mt-3 min-h-6 whitespace-pre-line break-words text-sm leading-6 text-white/65">{config.settings.bioTypewriter ? typed : config.profile.description}</p>}
      {showLocation && config.profile.location && <p className={`mt-3 flex items-center gap-1.5 text-xs text-white/40 ${justify}`}><MapPin size={12} />{config.profile.location}</p>}
    </>
  );
}

export function ProfileBadges({ config, className = "" }: { config: ProfileConfig; className?: string }) {
  const visible = config.settings.showBadges !== false ? config.badges.filter((badge) => badge.owned && badge.enabled).slice(0, 5) : [];
  if (!config.rank && visible.length === 0) return null;
  const justify = config.settings.socialAlign === "left" ? "justify-start" : config.settings.socialAlign === "right" ? "justify-end" : "justify-center";
  return (
    <div className={`${className} inline-flex flex-wrap items-center gap-1.5 ${justify}`}>
      {config.rank && <span className="inline-flex h-9 items-center gap-1.5 rounded-full border border-white/10 bg-white/[.07] px-3 text-[11px] font-medium" style={{ color: config.rank.color }} title={config.rank.description || config.rank.name}><Crown size={15} />{config.rank.name}</span>}
      {visible.map((badge) => (
        <span
          key={badge.id}
          onMouseEnter={positionBadgeTooltip}
          onFocus={positionBadgeTooltip}
          tabIndex={0}
          aria-label={badge.name}
          className="profile-badge relative flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[.07] text-sm"
          style={badgePaint(badge, config.settings)}
        >
          <BadgeIcon badge={badge} /><span className="profile-badge-tooltip" aria-hidden="true">{badge.name}</span>
        </span>
      ))}
    </div>
  );
}

export function ProfileMeta({ config, align = "center", floating = false }: { config: ProfileConfig; align?: "left" | "center" | "right"; floating?: boolean }) {
  const joined = formatJoinDate(config.profile.joinedAt);
  const showViews = config.settings.showViews;
  const showJoin = config.settings.showJoinDate && joined;
  const justify = align === "left" ? "justify-start" : align === "right" ? "justify-end" : "justify-center";
  if (!showViews && !showJoin) return null;
  return (
    <div className={`${floating ? "pointer-events-none absolute bottom-5 left-5 z-10" : "mt-7"} flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-white/35 ${floating ? "justify-start" : justify}`}>
      {showViews && <span className="inline-flex items-center gap-2"><EyeIcon />{config.profile.views.toLocaleString()} profile {config.profile.views === 1 ? "view" : "views"}</span>}
      {showJoin && <span>{joined}</span>}
    </div>
  );
}

export function DiscordPresenceTile({ config }: { config: ProfileConfig }) {
  const discord = useCardDiscord(config);
  const src = discord?.accountAvatar || undefined;
  if (!src && !discord?.status) return null;
  const swap = Boolean(config.settings.widgetColorSwap);
  const ink = config.settings.backgroundColor;
  const accent = config.settings.accentColor;
  const status = discord?.status && discord.status in DISCORD_STATUS_COLORS ? discord.status as DiscordPresence : null;
  const discordName = (discord?.globalName || discord?.username || "").trim();
  const statusLabel = status ? DISCORD_STATUS_LABELS[status] : "";
  return (
    <div className={`relative flex min-h-[5rem] min-w-0 items-center gap-3 overflow-hidden rounded-2xl border px-3 py-3 sm:h-full flex-1 ${swap ? "" : "border-white/[.1] bg-black/25"}`} style={swap ? { backgroundColor: accent, color: ink, borderColor: `${ink}33` } : undefined}>
      <div className="relative h-12 w-12 shrink-0">
        {src ? <img src={src} alt="" className="h-full w-full rounded-full object-cover" /> : <div className={`flex h-full w-full items-center justify-center rounded-full text-sm font-semibold ${swap ? "" : "bg-white/[.08] text-white"}`} style={swap ? { backgroundColor: `${ink}1a` } : undefined}>{(discordName || config.profile.displayName).slice(0, 1)}</div>}
        {status ? <span className="absolute -bottom-0.5 -right-0.5 z-[4] h-4 w-4"><DiscordStatusGlyph status={status} className="block h-full w-full" /></span> : null}
      </div>
      <div className="min-w-0 flex-1 text-left">{discordName ? <p className={`truncate text-sm font-semibold ${swap ? "" : "text-white"}`}>{discordName}</p> : null}{statusLabel ? <p className={`mt-0.5 truncate text-[11px] ${swap ? "opacity-70" : "text-white/55"}`}>{statusLabel}</p> : null}</div>
    </div>
  );
}

export function ProfileAudioModule({ config, preview, rootRef, viewport, entered = true }: { config: ProfileConfig; preview: boolean; rootRef: RefObject<HTMLDivElement | null>; viewport: LayoutViewport; entered?: boolean }) {
  const hasVideoAudio = usesBackgroundVideoAudio(config.assets);
  const hasPlaylist = usesUploadedProfileAudio(config.assets);
  const [host, setHost] = useState<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    const slot = document.createElement("div");
    slot.className = "profile-media-slot profile-audio-slot";
    setHost(slot);
    return () => slot.remove();
  }, []);
  useLayoutEffect(() => {
    if (!host) return;
    const target = (entered ? rootRef.current?.querySelector(viewport === "desktop" ? "[data-profile-media-row]" : "[data-profile-mobile-audio]") : null) || rootRef.current?.querySelector("[data-profile-audio-waiting]");
    if ((hasPlaylist || hasVideoAudio) && target && host.parentElement !== target) {
      const audio = host.querySelector("audio");
      const playing = audio && !audio.paused;
      const parent = target as Element & { moveBefore?: (node: Node, child: Node | null) => void };
      if (parent.moveBefore && host.isConnected) parent.moveBefore(host, null);
      else parent.appendChild(host);
      if (playing && audio.paused) void audio.play().catch(() => undefined);
    } else if (!hasPlaylist && !hasVideoAudio) host.remove();
  }, [host, viewport, rootRef, config.settings.layout, hasPlaylist, hasVideoAudio, entered]);
  if (!hasPlaylist && !hasVideoAudio) return null;
  // The portal host moves, but the player and its media element stay mounted.
  return host ? createPortal(<ProfileLayoutElement id="audio"><div className="profile-audio-content">
    {hasVideoAudio && <ProfileVideoAudioControl config={config} />}
    {hasPlaylist && <ProfileMusicPlayer config={config} preview={preview} autoplay={!preview && entered} />}
  </div></ProfileLayoutElement>, host) : null;
}

export function ProfileDiscord({ config }: { config: ProfileConfig }) {
  const discord = useCardDiscord(config);
  if (config.settings.showDiscordStatus === false || (!discord?.accountAvatar && !discord?.status)) return null;
  return <div className="profile-media-slot"><ProfileLayoutElement id="discord"><DiscordPresenceTile config={config} /></ProfileLayoutElement></div>;
}

export function ProfileModules({ config, preview, align = "center" }: { config: ProfileConfig; preview: boolean; align?: "left" | "center" | "right" }) {
  return (
    <WidgetResolutionProvider config={config} preview={preview}><div style={{ textAlign: align }}>
      <ProfileWidgets config={config} preview={preview} presence={<ProfileDiscord config={config} />} />
      <SocialLinks config={config} />
      <ProfileSections config={config} preview={preview} />
      <ProfileFeatures config={config} preview={preview} />
    </div></WidgetResolutionProvider>
  );
}
function profileLayoutIsSleek(config: ProfileConfig) {
  return config.settings.layout === "Sleek";
}

function BadgeIcon({ badge }: { badge: ProfileConfig["badges"][number] }) {
  if (badge.previewUrl || badge.icon) return <BadgeArtwork badge={badge} className="h-6 w-6 object-contain" />;
  return badge.name === "Premium" ? <Sparkles size={22} fill="currentColor" /> : badge.name === "OG" ? <Zap size={22} fill="currentColor" /> : <BadgeCheck size={22} />;
}

function EyeIcon() {
  return <span className="relative flex h-3.5 w-5 items-center justify-center rounded-[50%] border border-current"><span className="h-1.5 w-1.5 rounded-full bg-current" /></span>;
}

function positionBadgeTooltip(event: React.SyntheticEvent<HTMLSpanElement>) {
  const badge = event.currentTarget;
  const tooltip = badge.querySelector<HTMLElement>(".profile-badge-tooltip");
  const root = badge.closest("[data-profile-layout]");
  if (!root || !tooltip) return;
  const bounds = root.getBoundingClientRect(), box = badge.getBoundingClientRect();
  const width = Math.min(160, bounds.width - 24);
  tooltip.style.width = `${width}px`;
  tooltip.style.left = `${Math.max(bounds.left + 12, Math.min(box.left + box.width / 2 - width / 2, bounds.right - width - 12)) - box.left}px`;
}
