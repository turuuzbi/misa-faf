"use client";

import { elementBox, updateElementLayout, type LayoutViewport } from "@/lib/element-layout";
import { motion } from "framer-motion";
import { SiDiscord } from "react-icons/si";
import { AlignCenter, AlignLeft, AlignRight, AppWindow, Brush, CalendarDays, Check, CircleDot, Crop, Eye, Image as ImageIcon, Laptop, Layers, LayoutTemplate, Maximize2, Move, MousePointer2, Palette, PanelLeftClose, PanelLeftOpen, RotateCcw, Share2, Shield, SlidersHorizontal, Sparkles, Trash2, Type, Upload, UsersRound, Volume2, WandSparkles, X, ZoomIn, ZoomOut, type LucideIcon } from "lucide-react";
import { PortfolioPanel } from "@/components/customization/PortfolioPanel";
import { WidgetsPanel } from "@/components/customization/WidgetsPanel";
import { useEffect, useRef, useState, type CSSProperties, type ElementType } from "react";
import { EffectColors } from "./EffectColors";
import { ImageCropModal } from "@/components/customization/ImageCropModal";
import { AudioCropModal } from "@/components/customization/AudioCropModal";
import { PlaylistEditor } from "@/components/customization/PlaylistEditor";
import { DraftPreviewBoundary, useDraftPreview } from "@/lib/draft-preview";
import { ProfilePreviewButton } from "@/components/profile/ProfilePreviewButton";
import { ProfileRenderer } from "@/components/profile/ProfileRenderer";
import { BackgroundEffectLayer } from "@/components/profile/BackgroundEffectLayer";
import { BACKGROUND_EFFECTS } from "@/lib/background-effects";
import { SharingAppearance } from "@/components/sharing/SharingAppearance";
import { sharePageCopy } from "@/lib/share";
import { Button, FieldLabel, PageHeader, RangeControl, SelectBox, SectionTitle, TextArea, TextInput, Toggle } from "@/components/ui";
import { canCropAsset, IMAGE_ACCEPT, isAnimatedAsset, prepareCursorAsset } from "@/lib/image-edit";
import { syncPlaylist } from "@/lib/audio";
import { PreviewPlayerProvider } from "@/lib/preview-player";
import { assetFromFile, dataUrlToFile, mimeTypeForFile, uploadProfileAsset, useProfile } from "@/lib/profile-store";
import type { AudioTrack, BackgroundEffect, ButtonStyle, PageEnter, ProfileAsset, ProfileFont, ProfileShape, SocialAlign, UsernameEffect } from "@/lib/types";
import { useT } from "@/lib/i18n";
import { useDefaultFonts } from "@/lib/default-fonts";
import { useFeatureFlags } from "@/lib/feature-flags";
import { FONT_ACCEPT, PAGE_ENTERS, USERNAME_EFFECTS, usernameEffectClass } from "@/lib/typography";

const tabRows = [
  [
    { id: "assets", label: "Assets", icon: ImageIcon },
    { id: "layout", label: "Layout", icon: LayoutTemplate },
    { id: "widgets", label: "Widgets", icon: AppWindow },
    { id: "portfolio", label: "Portfolio", icon: Layers },
  ],
  [
    { id: "general", label: "General", icon: SlidersHorizontal },
    { id: "colors", label: "Colors", icon: Palette },
    { id: "effects", label: "Effects", icon: WandSparkles },
    { id: "sharing", label: "Sharing appearance", icon: Share2 },
  ],
] as const;
const tabs = tabRows.flat();
type Tab = (typeof tabs)[number]["id"];
type CropKey = "avatar" | "background" | "banner" | "ogImage" | "favicon";
const cropSpec: Record<CropKey, { title: string; aspect: number; width: number; height: number; mime: string }> = {
  avatar: { title: "Crop avatar", aspect: 1, width: 512, height: 512, mime: "image/jpeg" },
  background: { title: "Crop background", aspect: 16 / 9, width: 1280, height: 720, mime: "image/jpeg" },
  banner: { title: "Crop banner", aspect: 3, width: 1200, height: 400, mime: "image/jpeg" },
  ogImage: { title: "Crop share image", aspect: 1200 / 630, width: 1200, height: 630, mime: "image/jpeg" },
  favicon: { title: "Crop favicon", aspect: 1, width: 128, height: 128, mime: "image/png" },
};

export function CustomizationWorkspace() {
  return <DraftPreviewBoundary><CustomizationContent /></DraftPreviewBoundary>;
}

function CustomizationContent() {
  const { active: previewTabOpen } = useDraftPreview();
  const t = useT();
  const { config, updateConfig, resetConfig, saveProfile, saveState, profileReady } = useProfile();
  const { enabled } = useFeatureFlags();
  const [tab, setTab] = useState<Tab>("assets");
  const [crop, setCrop] = useState<{ key: CropKey; asset: ProfileAsset } | null>(null);
  const [audioCrop, setAudioCrop] = useState<ProfileAsset | null>(null);
  const [layoutViewport, setLayoutViewport] = useState<LayoutViewport>("desktop");
  const [manualMove, setManualMove] = useState(false);
  const [fullPreview, setFullPreview] = useState(false);
  const [controlsCollapsed, setControlsCollapsed] = useState(false);
  const shareCopy = sharePageCopy(config);
  const tabIcon = config.assets.favicon?.url || config.assets.avatar?.url || "";
  const setSettings = (patch: Partial<typeof config.settings>) => updateConfig((current) => {
    const { profileFrameWidth, profileFrameHeight, profileFrameScale, profileFrameX, profileFrameY, cardAlign, ...rest } = patch;
    const hasFrameChange = [profileFrameWidth, profileFrameHeight, profileFrameScale, profileFrameX, profileFrameY, cardAlign].some((value) => value !== undefined);
    if (!hasFrameChange) return { ...current, settings: { ...current.settings, ...patch } };
    const frame = elementBox(current.settings, "frame", layoutViewport);
    const next = { ...frame,
      ...(profileFrameWidth !== undefined ? { width: profileFrameWidth } : {}),
      ...(profileFrameHeight !== undefined ? { height: profileFrameHeight } : {}),
      ...(profileFrameScale !== undefined ? { width: Math.min(1040, (layoutViewport === "mobile" ? 358 : 880) * profileFrameScale / 100) } : {}),
      ...(profileFrameX !== undefined ? { x: profileFrameX * 2 } : {}),
      ...(profileFrameY !== undefined ? { y: Math.max(0, profileFrameY * 4) } : {}),
      ...(cardAlign !== undefined ? { x: cardAlign === "left" ? -100 : cardAlign === "right" ? 100 : 0 } : {}),
    };
    return { ...current, settings: { ...current.settings, ...rest, elementLayouts: updateElementLayout(current.settings, layoutViewport, "frame", next) } };
  });
  const setProfile = (patch: Partial<typeof config.profile>) => updateConfig((current) => ({ ...current, profile: { ...current.profile, ...patch } }));
  const uploadRevision = useRef<Record<string, number>>({});
  const setAsset = (key: keyof typeof config.assets, asset: ProfileAsset | boolean | number | string) => { uploadRevision.current[key === "background" || key === "backgroundVideo" ? "backgroundMedia" : key] = (uploadRevision.current[key === "background" || key === "backgroundVideo" ? "backgroundMedia" : key] || 0) + 1; updateConfig((current) => ({ ...current, assets: { ...current.assets, [key]: asset } })); };
  const currentFrame = elementBox(config.settings, "frame", layoutViewport);
  const layoutConfig = { ...config, settings: { ...config.settings, profileFrameWidth: currentFrame.width || 358, profileFrameHeight: currentFrame.height, profileFrameX: currentFrame.x / 2, profileFrameY: currentFrame.y / 4, profileFrameScale: Math.round((currentFrame.width || 358) / (layoutViewport === "mobile" ? 358 : 880) * 100), cardAlign: (currentFrame.x < 0 ? "left" : currentFrame.x > 0 ? "right" : "center") as SocialAlign } };
  const openManualMove = () => { setManualMove(true); setFullPreview(true); };
  const resetFramePosition = () => setSettings({ elementLayouts: updateElementLayout(config.settings, layoutViewport, "frame", { x: 0, y: 0, width: layoutViewport === "desktop" ? 880 : 0, height: 0 }) });
  const adjustFrameScale = (delta: number) => { const frame = elementBox(config.settings, "frame", layoutViewport); setSettings({ elementLayouts: updateElementLayout(config.settings, layoutViewport, "frame", { ...frame, width: Math.min(1040, Math.max(260, (frame.width || 358) + delta * 4)) }) }); };
  const uploadAsset = async (key: keyof typeof config.assets, file: File) => {
    const revision = uploadRevision.current[key === "background" || key === "backgroundVideo" ? "backgroundMedia" : key] = (uploadRevision.current[key === "background" || key === "backgroundVideo" ? "backgroundMedia" : key] || 0) + 1;
    const maxBytes = key === "backgroundVideo" || key === "backgroundEffectVideo" ? 110_000_000 : key === "audio" ? 40_000_000 : key === "clickSound" ? 2_000_000 : key === "customFont" ? 5_000_000 : key === "cursor" ? 5_000_000 : 25_000_000;
    const type = mimeTypeForFile(file).toLowerCase();
    const imageKeys = new Set(["avatar", "background", "banner", "ogImage", "favicon"]);
    if (!file || file.size <= 0) { window.alert("That file is empty. Please choose it again."); return; }
    if (file.size > maxBytes) { window.alert(t("customize.fileTooLarge", { mb: Math.round(maxBytes / 1_000_000) })); return; }
    if (imageKeys.has(String(key)) && !type.startsWith("image/")) { window.alert("Please choose a PNG, JPEG, WebP, or GIF image."); return; }
    try {
      const source = await assetFromFile(file);
      let uploadFile = file;
      if (key === "cursor") {
        const prepared = await prepareCursorAsset(source);
        if (prepared.url?.startsWith("data:")) uploadFile = await dataUrlToFile(prepared.url, "cursor.png", "image/png");
      }
      const uploaded = await uploadProfileAsset(String(key), uploadFile);
      if (uploadRevision.current[key === "background" || key === "backgroundVideo" ? "backgroundMedia" : key] !== revision) return;
      updateConfig((current) => ({
        ...current,
        assets: {
          ...current.assets,
          [key]: uploaded,
          ...(key === "backgroundVideo" ? { background: { url: null, remove: true }, audioSource: current.assets.audioSource === "standalone" || current.assets.audioSource === "tracks" ? current.assets.audioSource : "video" } : key === "background" ? { backgroundVideo: { url: null, remove: true }, audioSource: current.assets.tracks?.length ? "tracks" : "standalone", audioEnabled: current.assets.audioEnabled && Boolean(current.assets.tracks?.length || current.assets.audio?.url) } : {}),
          ...(key === "audio" ? { audioSource: "standalone", tracks: [] } : {}),
        },
      }));
    } catch (error) {
      console.error("Asset upload failed", error);
      window.alert(error instanceof Error ? error.message : "The file could not be uploaded. Please try again.");
    }
  };  const tabLabel: Record<Tab, string> = { assets: t("customize.tabAssets"), layout: t("customize.tabLayout"), widgets: t("customize.tabWidgets"), portfolio: t("customize.tabPortfolio"), general: t("customize.tabGeneral"), colors: t("customize.tabColors"), effects: t("customize.tabEffects"), sharing: t("customize.sharingTitle") };
  const visibleTabRows = tabRows.map((row) => row.filter(({ id }) => enabled(id === "assets" ? "customize.assets" : id === "layout" ? "customize.layout" : id === "widgets" ? "customize.widgets" : id === "portfolio" ? "customize.portfolio" : id === "effects" ? "customize.effects" : id === "sharing" ? "customize.sharing" : "customize.general"))).filter((row) => row.length);
  return <PreviewPlayerProvider><main className="mx-auto min-h-screen max-w-[1500px] px-5 py-8 sm:px-8 sm:py-10 xl:px-10"><PageHeader eyebrow={t("customize.eyebrow")} title={t("customize.title")} description={t("customize.description")} action={<div className="flex flex-wrap justify-end gap-2"><Button variant="ghost" onClick={() => setControlsCollapsed((collapsed) => !collapsed)} >{controlsCollapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}<span className="hidden lg:inline">{controlsCollapsed ? t("customize.showControls", undefined, "Show controls") : t("customize.hideControls", undefined, "Hide controls")}</span></Button><Button variant="ghost" onClick={resetConfig}><RotateCcw size={15} />{t("common.reset")}</Button><Button variant="accent" onClick={() => void saveProfile()} disabled={saveState === "saving" || !profileReady}>{saveState === "saving" ? t("common.saving") : saveState === "saved" ? <><Check size={15} />{t("common.savedCheck")}</> : <><Check size={15} />{t("common.save")}</>}</Button></div>} /><div className={`grid items-start gap-6 ${controlsCollapsed ? "md:grid-cols-[56px_minmax(0,1fr)]" : "md:grid-cols-[minmax(0,.9fr)_minmax(0,1.1fr)]"}`}><section className={`min-w-0 rounded-2xl border border-white/[.07] bg-[#0d0d12] ${controlsCollapsed ? "p-2 md:w-14" : "p-4 sm:p-5 md:max-h-[calc(100vh-7rem)] md:overflow-y-auto"}`}>{controlsCollapsed ? <div className="flex min-h-[120px] flex-col items-center justify-center gap-3"><button type="button" aria-label={t("customize.showControls", undefined, "Show controls")} title={t("customize.showControls", undefined, "Show controls")} onClick={() => setControlsCollapsed(false)} className="flex h-10 w-10 items-center justify-center rounded-xl text-zinc-400 transition hover:bg-white/[.08] hover:text-white"><PanelLeftOpen size={17} /></button><span className="sr-only">{t("customize.showControls", undefined, "Show controls")}</span></div> : <div className="min-w-0"><div className="mb-6 space-y-1 rounded-2xl bg-white/[.035] p-1.5">{visibleTabRows.map((row, index) => <div key={index} className={`grid gap-1 ${index === 0 ? "grid-cols-4" : "grid-cols-4"}`}>{row.map(({ id, icon: Icon }) => <button key={id} type="button" onClick={() => setTab(id)} className={`flex min-w-0 items-center justify-center gap-1.5 rounded-xl px-2 py-2.5 text-xs font-medium transition ${tab === id ? "bg-white/[.12] text-white shadow-sm" : "text-zinc-500 hover:bg-white/[.04] hover:text-zinc-200"}`}><Icon size={14} className="shrink-0" /><span className="truncate">{tabLabel[id]}</span></button>)}</div>)}</div><motion.div key={tab} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: .2 }}>{tab === "assets" && <AssetsPanel config={config} setAsset={setAsset} onUpload={uploadAsset} onCrop={setCrop} onAudioCrop={setAudioCrop} onTracks={(tracks) => updateConfig((current) => ({ ...current, assets: { ...current.assets, ...syncPlaylist(tracks), audioSource: tracks.length ? "tracks" : current.assets.audio?.url ? "standalone" : "video", audioEnabled: tracks.length ? false : current.assets.audioEnabled } }))} />}{tab === "layout" && <LayoutsPanel config={layoutConfig} setSettings={setSettings} onManualMove={openManualMove} onResetFrame={resetFramePosition} />}{tab === "widgets" && <WidgetsPanel />}{tab === "portfolio" && <PortfolioPanel />}{tab === "general" && <GeneralPanel config={config} setSettings={setSettings} setProfile={setProfile} />}{tab === "sharing" && <SharingAppearance config={config} setSettings={setSettings} setAsset={(key, asset) => setAsset(key, asset)} onUpload={uploadAsset} onCrop={setCrop} />}{tab === "colors" && <ColorsPanel config={config} setSettings={setSettings} />}{tab === "effects" && <><EffectsPanel config={config} setSettings={setSettings} setAsset={setAsset} onUpload={uploadAsset} /><EffectColors /></>}</motion.div></div>}</section><section className="min-w-0 md:sticky md:top-4 md:self-start"><div><div className="mb-3 flex items-center justify-between gap-3 px-1"><div className="flex items-center gap-2 text-sm font-medium"><span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#e11d48]/10 text-[#fecdd3]"><Laptop size={14} /></span>{t("customize.preview")}</div><div className="flex items-center gap-2"><span className="hidden items-center gap-2 text-[11px] text-zinc-600 sm:flex"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />{t("customize.instant")}</span><ProfilePreviewButton /></div></div><div className="overflow-hidden rounded-2xl border border-white/[.1] bg-[#08080d] shadow-2xl shadow-black/30"><div className="flex h-9 items-center gap-1.5 border-b border-white/[.06] bg-white/[.025] px-3"><span className="h-2.5 w-2.5 rounded-full bg-[#ff6f70]/70" /><span className="h-2.5 w-2.5 rounded-full bg-[#ffcb70]/70" /><span className="h-2.5 w-2.5 rounded-full bg-[#70d69a]/70" /><div className="mx-auto flex h-5 max-w-[260px] flex-1 items-center justify-center gap-1.5 rounded-md bg-black/20 px-2 text-[9px] text-zinc-600">{tabIcon ? <img src={tabIcon} alt="" className="h-3 w-3 rounded-[3px] object-cover" /> : null}<span className="truncate">{shareCopy.title}</span></div></div><div className="h-[580px] overflow-auto sm:h-[650px]" dir="ltr">{previewTabOpen && !fullPreview ? <div className="flex h-full items-center justify-center p-6 text-sm text-zinc-400">Your live preview is open in its own tab.</div> : !fullPreview && <ProfileRenderer config={config} preview fitViewport layoutViewport={layoutViewport} manualPositioning={manualMove} onLayoutChange={setSettings} />}</div></div></div></section></div>{saveState === "saved" && <div role="status" className="fixed bottom-6 end-6 z-40 rounded-xl border border-emerald-400/20 bg-[#12191a] px-4 py-3 text-sm text-emerald-300 shadow-xl">{t("customize.savedToast")}</div>}
    {fullPreview && <div className="fixed inset-0 z-[100] flex flex-col bg-[#07070a]">
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-white/[.06] bg-[#0b0b10]/90 px-3 sm:px-4">
        <div className="flex items-center gap-2 text-sm font-medium text-white"><Maximize2 size={15} className="text-[#fecdd3]" />{t("customize.fullView", undefined, "Full view")}</div>
        <button type="button" aria-label="Close full view" onClick={() => { setFullPreview(false); setManualMove(false); }} className="flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 hover:bg-white/[.06] hover:text-white"><X size={18} aria-hidden="true" /></button>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-white/10 p-3">
        {(["desktop", "mobile"] as const).map((viewport) => <Button key={viewport} variant={layoutViewport === viewport ? "accent" : "ghost"} aria-pressed={layoutViewport === viewport} onClick={() => setLayoutViewport(viewport)}>{viewport === "desktop" ? "Desktop layout" : "Mobile layout"}</Button>)}
        <span className="text-xs text-zinc-400">{manualMove ? "Select frame, Discord, a widget or audio using its handle. Drag to move; use the corner to resize. Arrow keys also work." : "Layouts save separately for desktop and mobile."}</span>
      </div>
      <div className="relative min-h-0 flex-1 overflow-auto" dir="ltr">
        <div className="mx-auto h-full" style={{ width: layoutViewport === "mobile" ? "min(100%, 390px)" : "100%" }}><ProfileRenderer config={config} preview fitViewport layoutViewport={layoutViewport} manualPositioning={manualMove} onLayoutChange={setSettings} /></div>
        </div>
      {manualMove ? <div className="z-20 flex shrink-0 flex-wrap items-center justify-center gap-2 rounded-2xl border border-white/[.1] bg-[#0b0b10]/90 p-2 shadow-2xl backdrop-blur-sm"><Button variant="ghost" className="h-9 min-h-0 px-3 text-xs" onClick={resetFramePosition}><RotateCcw size={13} />{t("common.reset")}</Button><Button variant="ghost" aria-label="Zoom out" className="h-9 min-h-0 w-9 min-w-0 px-0" onClick={() => adjustFrameScale(-10)} ><ZoomOut size={15} /></Button><span className="min-w-12 text-center font-mono text-xs text-zinc-300">{currentFrame.width ? `${currentFrame.width}px` : "Auto"}</span><Button variant="ghost" aria-label="Zoom in" className="h-9 min-h-0 w-9 min-w-0 px-0" onClick={() => adjustFrameScale(10)} ><ZoomIn size={15} /></Button><Button variant="accent" className="h-9 min-h-0 px-4 text-xs" onClick={() => setManualMove(false)}>{t("customize.exitMove", undefined, "Exit move mode")}</Button></div> : null}
    </div>}
    <AudioCropModal
      open={Boolean(audioCrop)}
      src={audioCrop?.url || ""}
      onCancel={() => setAudioCrop(null)}
      onApply={async (url, mime) => {
        try {
          const uploaded = await uploadProfileAsset("audio", await dataUrlToFile(url, "video-audio.webm", mime));
          updateConfig((current) => ({
            ...current,
            assets: {
              ...current.assets,
              audio: uploaded,
              audioTitle: "Video audio",
              audioSource: "standalone",
              tracks: [],
              audioEnabled: false,
            },
          }));
        } catch (error) {
          window.alert(error instanceof Error ? error.message : "The cropped audio could not be uploaded.");
        } finally {
          setAudioCrop(null);
        }
      }}
    />
    <ImageCropModal
      open={Boolean(crop)}
      title={crop ? cropSpec[crop.key].title : "Crop image"}
      src={crop?.asset.url || ""}
      aspect={crop ? cropSpec[crop.key].aspect : 1}
      outputWidth={crop ? cropSpec[crop.key].width : 512}
      outputHeight={crop ? cropSpec[crop.key].height : 512}
      mime={crop ? cropSpec[crop.key].mime : "image/jpeg"}
      onCancel={() => setCrop(null)}
      onApply={async (url) => {
        const currentCrop = crop;
        if (!currentCrop) return;
        try {
          const spec = cropSpec[currentCrop.key];
          const uploaded = await uploadProfileAsset(currentCrop.key, await dataUrlToFile(url, "cropped-" + currentCrop.key + ".jpg", spec.mime));
          setAsset(currentCrop.key, uploaded);
        } catch (error) {
          window.alert(error instanceof Error ? error.message : "The cropped image could not be uploaded.");
        } finally {
          setCrop(null);
        }
      }}
    />
  </main></PreviewPlayerProvider>;
}

export function ConstellationProfileControls({
  backgroundEffect = "None",
  onBackgroundEffectChange,
}: {
  backgroundEffect?: BackgroundEffect;
  onBackgroundEffectChange?: (effect: BackgroundEffect) => void;
}) {
  const t = useT();
  const { config, updateConfig, resetConfig, saveProfile, saveState, profileReady } = useProfile();
  const [tab, setTab] = useState<Tab>("assets");
  const [crop, setCrop] = useState<{ key: CropKey; asset: ProfileAsset } | null>(null);
  const setSettings = (patch: Partial<typeof config.settings>) => updateConfig((current) => ({ ...current, settings: { ...current.settings, ...patch } }));
  const setProfile = (patch: Partial<typeof config.profile>) => updateConfig((current) => ({ ...current, profile: { ...current.profile, ...patch } }));
  const uploadRevision = useRef<Record<string, number>>({});
  const setAsset = (key: keyof typeof config.assets, asset: ProfileAsset | boolean | number | string) => { uploadRevision.current[key === "background" || key === "backgroundVideo" ? "backgroundMedia" : key] = (uploadRevision.current[key === "background" || key === "backgroundVideo" ? "backgroundMedia" : key] || 0) + 1; updateConfig((current) => ({ ...current, assets: { ...current.assets, [key]: asset } })); };
  const uploadAsset = async (key: keyof typeof config.assets, file: File) => {
    const revision = uploadRevision.current[key === "background" || key === "backgroundVideo" ? "backgroundMedia" : key] = (uploadRevision.current[key === "background" || key === "backgroundVideo" ? "backgroundMedia" : key] || 0) + 1;
    const maxBytes = key === "backgroundVideo" || key === "backgroundEffectVideo" ? 110_000_000 : key === "audio" ? 40_000_000 : key === "clickSound" ? 2_000_000 : key === "customFont" ? 5_000_000 : key === "cursor" ? 5_000_000 : 25_000_000;
    const type = mimeTypeForFile(file).toLowerCase();
    const imageKeys = new Set(["avatar", "banner", "ogImage", "favicon"]);
    if (!file || file.size <= 0) { window.alert("That file is empty. Please choose it again."); return; }
    if (file.size > maxBytes) { window.alert(t("customize.fileTooLarge", { mb: Math.round(maxBytes / 1_000_000) })); return; }
    if (imageKeys.has(String(key)) && !type.startsWith("image/")) { window.alert("Please choose a PNG, JPEG, WebP, or GIF image."); return; }
    try {
      const source = await assetFromFile(file);
      const uploaded = await uploadProfileAsset(String(key), file);
      if (uploadRevision.current[key === "background" || key === "backgroundVideo" ? "backgroundMedia" : key] !== revision) return;
      setAsset(key, uploaded);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "The file could not be uploaded. Please try again.");
    }
  };
  const labels: Record<Tab, string> = { assets: t("customize.tabAssets"), layout: t("customize.tabLayout"), widgets: t("customize.tabWidgets"), portfolio: t("customize.tabPortfolio"), general: t("customize.tabGeneral"), colors: t("customize.tabColors"), effects: t("customize.tabEffects"), sharing: t("customize.sharingTitle") };
  const personalAssets: Array<{ key: keyof typeof config.assets; title: string; description: string; icon: typeof ImageIcon; accept: string }> = [
    { key: "avatar", title: t("customize.avatar"), description: t("customize.avatarDesc"), icon: CircleDot, accept: IMAGE_ACCEPT },
    { key: "banner", title: t("customize.banner"), description: t("customize.bannerDesc"), icon: ImageIcon, accept: IMAGE_ACCEPT },
  ];
  return <div className="mt-2 w-full min-w-0 max-w-full overflow-hidden border-t border-white/[.07] pt-5">
    <SectionTitle title="Your profile design" description="These controls save a separate Constellation design and never change your normal Customize profile. Background, cursor, and audio are shared by the whole Constellation." />
    <div className="mb-5 grid grid-cols-2 gap-1 rounded-2xl bg-white/[.035] p-1.5 sm:grid-cols-4">{tabs.map(({ id, icon: Icon }) => <button key={id} type="button" onClick={() => setTab(id)} className={`flex min-w-0 items-center justify-center gap-1.5 rounded-xl px-2 py-2.5 text-xs font-medium transition ${tab === id ? "bg-white/[.12] text-white" : "text-zinc-500 hover:bg-white/[.04] hover:text-zinc-200"}`}><Icon size={14} className="shrink-0" /><span className="truncate">{labels[id]}</span></button>)}</div>
    <motion.div key={tab} className="w-full min-w-0 max-w-full overflow-hidden" initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: .2 }}>
      {tab === "assets" && <div><SectionTitle icon={Brush} title={t("customize.assetsTitle")} description="Avatar and banner stay personal. Use Shared for the common background, cursor, and audio." /><div className="space-y-3">{personalAssets.map((item) => <AssetRow key={item.key} item={item} asset={(config.assets[item.key] as ProfileAsset) || { url: null }} setAsset={setAsset} onUpload={uploadAsset} onCrop={setCrop} />)}</div></div>}
      {tab === "layout" && <LayoutsPanel config={config} setSettings={setSettings} onManualMove={() => window.alert("Use Move profiles in the Constellation preview to reposition your profile.")} onResetFrame={() => setSettings({ profileFrameScale: 100, profileFrameWidth: 430, profileFrameHeight: 0, profileFrameX: 0, profileFrameY: 0 })} />}
      {tab === "widgets" && <WidgetsPanel />}
      {tab === "portfolio" && <PortfolioPanel />}
      {tab === "general" && <GeneralPanel config={config} setSettings={setSettings} setProfile={setProfile} />}
      {tab === "sharing" && <SharingAppearance config={config} setSettings={setSettings} setAsset={(key, asset) => setAsset(key, asset)} onUpload={uploadAsset} onCrop={setCrop} />}
      {tab === "colors" && <ColorsPanel config={config} setSettings={setSettings} />}
      {tab === "effects" && <EffectsPanel config={config} setSettings={setSettings} setAsset={setAsset} onUpload={uploadAsset} backgroundEffectValue={backgroundEffect} onBackgroundEffectChange={onBackgroundEffectChange} />}
    </motion.div>
    <div className="mt-5 flex flex-wrap justify-end gap-2"><Button variant="ghost" onClick={resetConfig}><RotateCcw size={14} />Reset design draft</Button><Button variant="accent" disabled={!profileReady || saveState === "saving"} onClick={() => void saveProfile()}><Check size={14} />{saveState === "saving" ? "Saving…" : saveState === "saved" ? "Design saved" : "Save design"}</Button></div>
    <ImageCropModal open={Boolean(crop)} title={crop ? cropSpec[crop.key].title : "Crop image"} src={crop?.asset.url || ""} aspect={crop ? cropSpec[crop.key].aspect : 1} outputWidth={crop ? cropSpec[crop.key].width : 512} outputHeight={crop ? cropSpec[crop.key].height : 512} mime={crop ? cropSpec[crop.key].mime : "image/jpeg"} onCancel={() => setCrop(null)} onApply={async (url) => { const current = crop; if (!current) return; try { const spec = cropSpec[current.key]; setAsset(current.key, await uploadProfileAsset(current.key, await dataUrlToFile(url, "cropped-" + current.key + ".jpg", spec.mime))); } catch (error) { window.alert(error instanceof Error ? error.message : "The cropped image could not be uploaded."); } finally { setCrop(null); } }} />
  </div>;
}
function AssetsPanel({ config, setAsset, onUpload, onCrop, onAudioCrop, onTracks }: { config: ReturnType<typeof import("@/lib/mock-data").cloneMockProfile>; setAsset: (key: keyof typeof config.assets, asset: ProfileAsset | boolean | number | string) => void; onUpload: (key: keyof typeof config.assets, file: File) => Promise<void>; onCrop: (next: { key: CropKey; asset: ProfileAsset }) => void; onAudioCrop: (asset: ProfileAsset) => void; onTracks: (tracks: AudioTrack[]) => void }) {
  const t = useT();
  const { enabled } = useFeatureFlags();
  const items: Array<{ key: keyof typeof config.assets; title: string; description: string; icon: typeof ImageIcon; accept: string }> = [
    { key: "banner", title: t("customize.banner"), description: t("customize.bannerDesc"), icon: ImageIcon, accept: IMAGE_ACCEPT },
    { key: "avatar", title: t("customize.avatar"), description: t("customize.avatarDesc"), icon: CircleDot, accept: IMAGE_ACCEPT },
    { key: "cursor", title: t("customize.cursor"), description: t("customize.cursorDesc"), icon: MousePointer2, accept: "image/png,image/gif,image/x-icon" },
  ];
  const hasBackgroundVideo = Boolean(config.assets.backgroundVideo?.url);
  return <div>
    <SectionTitle icon={Brush} title={t("customize.assetsTitle")} description={t("customize.assetsDesc")} />
    <div className="space-y-3">
      <BackgroundAssetRow config={config} setAsset={setAsset} onUpload={onUpload} onCrop={onCrop} />
      {items.map((item) => <AssetRow key={item.key} item={item} asset={(config.assets[item.key] as ProfileAsset) || { url: null }} setAsset={setAsset} onUpload={onUpload} onCrop={onCrop} />)}
      <PlaylistEditor config={config} onChange={onTracks} />
    </div>
    {hasBackgroundVideo ? <div className="mt-4 space-y-1 divide-y divide-white/[.06] rounded-2xl border border-white/[.07] bg-white/[.02] px-4">
      <ToggleRow label="Use background video audio" checked={config.assets.audioEnabled && config.assets.audioSource === "video"} onChange={(checked) => { setAsset("audioEnabled", checked); setAsset("audioSource", checked ? "video" : config.assets.tracks?.length ? "tracks" : config.assets.audio?.url ? "standalone" : "video"); }} onReset={() => { setAsset("audioEnabled", false); setAsset("audioSource", config.assets.tracks?.length ? "tracks" : config.assets.audio?.url ? "standalone" : "video"); }} />
      <div className="py-3"><RangeControl label="Default volume" value={config.assets.volume} min={0} max={100} suffix="%" onChange={(value) => setAsset("volume", value)} onReset={() => setAsset("volume", 65)} /></div>
    </div> : null}
    {enabled("customize.assets.audioCrop") && hasBackgroundVideo ? <Button variant="subtle" className="mt-3 w-full text-xs" onClick={() => onAudioCrop(config.assets.backgroundVideo)}>Extract and crop audio from video</Button> : null}
  </div>;
}

function BackgroundAssetRow({ config, setAsset, onUpload }: { config: ReturnType<typeof import("@/lib/mock-data").cloneMockProfile>; setAsset: (key: keyof typeof config.assets, asset: ProfileAsset | boolean | number | string) => void; onUpload: (key: keyof typeof config.assets, file: File) => Promise<void>; onCrop: (next: { key: CropKey; asset: ProfileAsset }) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const video = config.assets.backgroundVideo;
  const image = config.assets.background;
  const hasBackground = Boolean(video?.url || image?.url);
  const upload = async (file: File) => {
    const type = mimeTypeForFile(file).toLowerCase();
    const nextIsVideo = type.startsWith("video/") || /\.(mp4|webm|mov)$/i.test(file.name);
    if (!nextIsVideo && !type.startsWith("image/")) { window.alert("Choose an image, GIF, MP4, WebM, or MOV file."); return; }
    await onUpload(nextIsVideo ? "backgroundVideo" : "background", file);

  };
  const removeBackground = () => {
    setAsset("backgroundVideo", { url: null, remove: true });
    setAsset("background", { url: null, remove: true });
    setAsset("audioEnabled", false);
    setAsset("audioSource", config.assets.tracks?.length ? "tracks" : config.assets.audio?.url ? "standalone" : "video");
  };
  return <div className="relative isolate flex h-[220px] flex-col items-center justify-center overflow-hidden rounded-2xl border border-white/[.08] bg-white/[.025] px-5 text-center sm:h-[250px] sm:px-8">
    {hasBackground ? <div className="absolute inset-0 -z-10">{video?.url ? <video src={video.url} className="h-full w-full object-cover" muted loop autoPlay playsInline preload="metadata" /> : image?.url ? <img src={image.url} alt="Current background" className="h-full w-full object-cover" /> : null}<div className="absolute inset-0 bg-black/50" /></div> : null}
    <p className="text-xl font-medium text-white drop-shadow-lg">Background</p>
    <input ref={input} className="hidden" type="file" accept="image/png,image/jpeg,image/webp,image/gif,video/mp4,video/webm,video/quicktime,.mov" onClick={(event) => { event.currentTarget.value = ""; }} onChange={(event) => { const element = event.currentTarget; const file = element.files?.[0]; if (file) void upload(file).finally(() => { element.value = ""; }); }} />
    <div className="mt-5 flex items-center justify-center gap-2"><Button variant="subtle" className="h-11 min-h-0 px-6 backdrop-blur-md" onClick={() => input.current?.click()}><Upload size={16} />{hasBackground ? "Replace" : "Upload"}</Button>{hasBackground ? <Button variant="subtle" className="h-11 min-h-0 px-4 backdrop-blur-md" onClick={removeBackground}><Trash2 size={15} />Remove</Button> : null}</div>
    {hasBackground ? <p className="absolute inset-x-4 bottom-3 truncate text-[11px] text-white/55">{video?.name || image?.name || "Current background"}</p> : null}
  </div>;
}
function AssetRow({ item, asset, setAsset, onUpload, onCrop }: { item: { key: keyof ReturnType<typeof import("@/lib/mock-data").cloneMockProfile>["assets"]; title: string; description: string; icon: typeof ImageIcon; accept: string }; asset: ProfileAsset; setAsset: (key: keyof ReturnType<typeof import("@/lib/mock-data").cloneMockProfile>["assets"], asset: ProfileAsset | boolean | number | string) => void; onUpload: (key: keyof ReturnType<typeof import("@/lib/mock-data").cloneMockProfile>["assets"], file: File) => Promise<void>; onCrop: (next: { key: CropKey; asset: ProfileAsset }) => void }) {
  const t = useT();
  const input = useRef<HTMLInputElement>(null);
  const isImage = item.key === "avatar" || item.key === "background" || item.key === "banner";
  const croppable = isImage && canCropAsset(asset);
  const hasAsset = Boolean(asset?.url);
  const previewClass = item.key === "cursor" ? "h-full w-full object-contain p-10 sm:p-12" : "h-full w-full object-cover";
  return <div className="relative isolate flex h-[220px] flex-col items-center justify-center overflow-hidden rounded-2xl border border-white/[.08] bg-white/[.025] px-5 text-center sm:h-[250px] sm:px-8">
    {hasAsset ? <div className="absolute inset-0 -z-10"><img src={asset.url!} alt="" className={previewClass} /><div className="absolute inset-0 bg-black/50" /></div> : <item.icon size={34} className="mb-3 text-zinc-500" />}
    <p className="text-xl font-medium text-white drop-shadow-lg">{item.title}</p>
    {!hasAsset ? <p className="mt-2 text-xs text-zinc-500">{item.description}</p> : null}
    <input ref={input} className="hidden" type="file" accept={item.accept} onClick={(event) => { event.currentTarget.value = ""; }} onChange={(event) => { const inputElement = event.currentTarget; const file = inputElement.files?.[0]; if (file) void onUpload(item.key, file).finally(() => { inputElement.value = ""; }); }} />
    <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
      <Button variant="subtle" className="h-11 min-h-0 shrink-0 whitespace-nowrap px-5 backdrop-blur-md" onClick={() => input.current?.click()}><Upload size={15} />{hasAsset ? t("common.replace") : t("common.upload")}</Button>
      {croppable && <Button variant="subtle" className="h-11 min-h-0 shrink-0 whitespace-nowrap px-4 backdrop-blur-md" onClick={() => onCrop({ key: item.key as CropKey, asset })}><Crop size={15} />{t("common.crop")}</Button>}
      {hasAsset && <Button variant="subtle" className="h-11 min-h-0 shrink-0 whitespace-nowrap px-4 backdrop-blur-md" onClick={() => setAsset(item.key, { url: null, remove: true })}><Trash2 size={15} />{t("common.remove")}</Button>}
    </div>
    {hasAsset ? <p className="absolute inset-x-4 bottom-3 truncate text-[11px] text-white/55">{isAnimatedAsset(asset) ? t("customize.animated") : asset.name || t("customize.uploaded")}</p> : null}
  </div>;
}
function LayoutsPanel({ config, setSettings, onManualMove, onResetFrame }: { config: ReturnType<typeof import("@/lib/mock-data").cloneMockProfile>; setSettings: (patch: Partial<typeof config.settings>) => void; onManualMove: () => void; onResetFrame: () => void }) {
  const t = useT();
  return (
    <div>
      <SectionTitle icon={LayoutTemplate} title={t("customize.layoutsTitle")} description={t("customize.layoutsDesc")} />
      <div className="space-y-5 rounded-2xl border border-white/[.07] bg-white/[.02] p-4"><RangeControl label={t("customize.opacity")} value={config.settings.profileOpacity} min={0} max={80} suffix="%" onChange={(value) => setSettings({ profileOpacity: value })} onReset={() => setSettings({ profileOpacity: 10 })} /><RangeControl label={t("customize.bgOpacity")} value={config.settings.backgroundOpacity} min={20} max={100} suffix="%" onChange={(value) => setSettings({ backgroundOpacity: value })} onReset={() => setSettings({ backgroundOpacity: 88 })} /><RangeControl label={t("customize.blur")} value={config.settings.profileBlur} min={0} max={40} suffix="px" onChange={(value) => setSettings({ profileBlur: value })} onReset={() => setSettings({ profileBlur: 24 })} /><RangeControl label={t("customize.radius")} value={config.settings.profileRadius} min={0} max={40} suffix="px" onChange={(value) => setSettings({ profileRadius: value })} onReset={() => setSettings({ profileRadius: 24 })} /><RangeControl label={t("customize.frameOpacity")} value={config.settings.profileFrameOpacity ?? 100} min={0} max={100} suffix="%" onChange={(value) => setSettings({ profileFrameOpacity: value })} onReset={() => setSettings({ profileFrameOpacity: 100 })} /></div>
      <div className="mt-6 space-y-5 rounded-2xl border border-white/[.07] bg-white/[.02] p-4">
        <div className="grid grid-cols-2 gap-3">
          <div>
          <FieldLabel>{t("customize.avatarShape")}</FieldLabel>
          <SelectBox value={config.settings.avatarShape || "circle"} options={["circle", "rounded", "square"]} onChange={(value) => setSettings({ avatarShape: value as ProfileShape })} onReset={() => setSettings({ avatarShape: "circle" })} />
        </div>
        <div>
          <FieldLabel>{t("customize.buttonStyle")}</FieldLabel>
          <SelectBox value={config.settings.buttonStyle || "glass"} options={["glass", "solid", "outline"]} onChange={(value) => setSettings({ buttonStyle: value as ButtonStyle })} onReset={() => setSettings({ buttonStyle: "glass" })} />
        </div>
        </div>
        <div>
          <FieldLabel>{t("customize.cardAlign")}</FieldLabel>
          <div className="grid grid-cols-3 gap-2">{([{ id: "left", label: t("common.left"), icon: AlignLeft }, { id: "center", label: t("common.center"), icon: AlignCenter }, { id: "right", label: t("common.right"), icon: AlignRight }] as Array<{ id: SocialAlign; label: string; icon: typeof AlignLeft }>).map(({ id, label, icon: Icon }) => <button key={id} type="button" onClick={() => setSettings({ cardAlign: id })} className={`flex items-center justify-center gap-2 rounded-xl border px-3 py-2.5 text-xs ${(config.settings.cardAlign || "center") === id ? "border-[#e11d48]/50 bg-[#e11d48]/10 text-white" : "border-white/[.08] text-zinc-500"}`}><Icon size={14} />{label}</button>)}</div>
        </div>
        <div className="mt-2 flex justify-end"><ResetButton label={t("customize.cardAlign")} onClick={() => setSettings({ cardAlign: "center" })} /></div><div className="space-y-1 divide-y divide-white/[.06] rounded-2xl border border-white/[.07] bg-white/[.02] px-4">
          <ToggleRow label={t("customize.showFrame")} checked={config.settings.showProfileFrame !== false} onChange={(checked) => setSettings({ showProfileFrame: checked })} onReset={() => setSettings({ showProfileFrame: true })} />
          <ToggleRow label={t("customize.showAvatar")} checked={config.settings.showAvatar !== false} onChange={(checked) => setSettings({ showAvatar: checked })} onReset={() => setSettings({ showAvatar: true })} />
          <ToggleRow label={t("customize.showAvatarBorder")} checked={config.settings.showAvatarBorder !== false} onChange={(checked) => setSettings({ showAvatarBorder: checked })} onReset={() => setSettings({ showAvatarBorder: true })} />
          <ToggleRow label={t("customize.showDisplayName")} checked={config.settings.showDisplayName !== false} onChange={(checked) => setSettings({ showDisplayName: checked })} onReset={() => setSettings({ showDisplayName: true })} />
        </div>
        <button type="button" onClick={onManualMove} className="flex w-full items-center gap-4 rounded-2xl border border-white/[.07] bg-white/[.035] p-4 text-left transition hover:border-[#e11d48]/40 hover:bg-[#e11d48]/[.08]">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#e11d48]/10 text-[#fecdd3]"><Move size={24} /></span>
        <span className="min-w-0 flex-1"><span className="block text-base font-medium text-white">{t("customize.manualMove", undefined, "Move manually")}</span><span className="mt-1 block text-xs text-zinc-500">{t("customize.manualMoveHint", undefined, "Move and resize the frame, Discord status and audio independently.")}</span></span>
        <span className="text-2xl text-zinc-400" aria-hidden="true">&gt;</span>
      </button>
      <div className="space-y-5 rounded-2xl border border-white/[.07] bg-white/[.02] p-4">
          <p className="text-xs leading-5 text-zinc-500">{t("customize.frameHint")}</p>
          <RangeControl label={t("customize.frameSize")} value={config.settings.profileFrameScale ?? 100} min={50} max={150} suffix="%" onChange={(value) => setSettings({ profileFrameScale: value })} onReset={() => setSettings({ profileFrameScale: 100 })} />
          <RangeControl label={t("customize.frameWidth", undefined, "Frame width")} value={config.settings.profileFrameWidth ?? 430} min={260} max={1040} suffix="px" onChange={(value) => setSettings({ profileFrameWidth: value })} onReset={() => setSettings({ profileFrameWidth: 430 })} />
          <RangeControl label={t("customize.frameHeight", undefined, "Frame height")} value={config.settings.profileFrameHeight || 420} min={200} max={1000} suffix="px" onChange={(value) => setSettings({ profileFrameHeight: value })} onReset={() => setSettings({ profileFrameHeight: 0 })} />
          <RangeControl label={t("customize.frameHorizontal")} value={config.settings.profileFrameX ?? 0} min={-45} max={45} suffix="%" onChange={(value) => setSettings({ profileFrameX: value })} onReset={() => setSettings({ profileFrameX: 0 })} />
          <RangeControl label={t("customize.frameVertical")} value={config.settings.profileFrameY ?? 0} min={0} max={45} suffix="%" onChange={(value) => setSettings({ profileFrameY: value })} onReset={() => setSettings({ profileFrameY: 0 })} />
          <div className="flex justify-end"><Button variant="ghost" className="h-9 min-h-0 px-3 text-xs" onClick={onResetFrame}><RotateCcw size={13} />{t("common.reset")}</Button></div>
        </div>
        <RangeControl label={t("customize.borderWidth")} value={config.settings.borderWidth ?? 1} min={0} max={8} suffix="px" onChange={(value) => setSettings({ borderWidth: value })} onReset={() => setSettings({ borderWidth: 1 })} />
        <div>
          <FieldLabel>{t("customize.borderColor")}</FieldLabel>
          <div className="flex items-center gap-2"><input aria-label="Border color" type="color" value={config.settings.borderColor || "#ffffff"} onChange={(event) => setSettings({ borderColor: event.target.value })} className="h-11 w-12 cursor-pointer rounded-xl border-0 bg-transparent p-0" /><TextInput value={config.settings.borderColor || "#ffffff"} onChange={(value) => setSettings({ borderColor: value })} /><ResetButton label={t("customize.borderColor")} onClick={() => setSettings({ borderColor: "#ffffff" })} /></div>
        </div>
      </div>
    </div>
  );
}

function GeneralPanel({ config, setSettings, setProfile }: { config: ReturnType<typeof import("@/lib/mock-data").cloneMockProfile>; setSettings: (patch: Partial<typeof config.settings>) => void; setProfile: (patch: Partial<typeof config.profile>) => void }) {
  const t = useT();
  return <div><SectionTitle icon={SlidersHorizontal} title={t("customize.generalTitle")} description={t("customize.generalDesc")} /><div className="space-y-6"><div className="grid gap-3 sm:grid-cols-2"><div><FieldLabel>{t("customize.displayName")}</FieldLabel><TextInput value={config.profile.displayName} onChange={(value) => setProfile({ displayName: value })} /></div><div><FieldLabel>{t("customize.username")}</FieldLabel><TextInput value={`@${config.profile.username}`} onChange={() => undefined} disabled /></div></div><p className="-mt-3 text-xs text-zinc-600">{t("customize.usernameHint")}</p><div><FieldLabel>{t("customize.fieldDesc")}</FieldLabel><TextArea value={config.profile.description} onChange={(value) => setProfile({ description: value })} placeholder={t("customize.descriptionPh")} /><p className="mt-1 text-[11px] text-zinc-600">{t("customize.descriptionHint")}</p></div><div><FieldLabel>{t("customize.location")}</FieldLabel><TextInput value={config.profile.location} onChange={(value) => setProfile({ location: value })} placeholder={t("customize.locationPh")} /></div><div className="space-y-1 divide-y divide-white/[.06] rounded-2xl border border-white/[.07] bg-white/[.02] px-4"><ToggleRow icon={CircleDot} label={t("customize.gradient")} checked={config.settings.profileGradient} onChange={(checked) => setSettings({ profileGradient: checked })} onReset={() => setSettings({ profileGradient: true })} /><ToggleRow icon={Eye} label={t("customize.showViews")} checked={config.settings.showViews} onChange={(checked) => setSettings({ showViews: checked })} onReset={() => setSettings({ showViews: true })} /><ToggleRow icon={CalendarDays} label={t("customize.showJoin")} checked={Boolean(config.settings.showJoinDate)} onChange={(checked) => setSettings({ showJoinDate: checked })} onReset={() => setSettings({ showJoinDate: false })} /><ToggleRow icon={Shield} label={t("customize.showBadges")} checked={config.settings.showBadges} onChange={(checked) => setSettings({ showBadges: checked })} onReset={() => setSettings({ showBadges: true })} /><ToggleRow icon={UsersRound} label={t("customize.showSocials")} checked={config.settings.showSocials} onChange={(checked) => setSettings({ showSocials: checked })} onReset={() => setSettings({ showSocials: true })} /><ToggleRow icon={Eye} label="Show username" checked={config.settings.showUsername !== false} onChange={(checked) => setSettings({ showUsername: checked })} onReset={() => setSettings({ showUsername: true })} /><ToggleRow icon={SiDiscord} label={t("customize.showDiscordStatus", undefined, "Show Discord status")} checked={config.settings.showDiscordStatus !== false} onChange={(checked) => setSettings({ showDiscordStatus: checked })} onReset={() => setSettings({ showDiscordStatus: true })} /><ToggleRow icon={Laptop} label={t("customize.entryScreen")} checked={config.settings.entryScreen} onChange={(checked) => setSettings({ entryScreen: checked })} onReset={() => setSettings({ entryScreen: true })} /></div><div><FieldLabel>{t("customize.iconAlign")}</FieldLabel><div className="grid grid-cols-3 gap-2">{([{ id: "left", label: t("common.left"), icon: AlignLeft }, { id: "center", label: t("common.center"), icon: AlignCenter }, { id: "right", label: t("common.right"), icon: AlignRight }] as Array<{ id: SocialAlign; label: string; icon: typeof AlignLeft }>).map(({ id, label, icon: Icon }) => <button key={id} type="button" onClick={() => setSettings({ socialAlign: id })} className={`flex items-center justify-center gap-2 rounded-xl border px-3 py-2.5 text-xs ${(config.settings.socialAlign || "center") === id ? "border-[#e11d48]/50 bg-[#e11d48]/10 text-white" : "border-white/[.08] text-zinc-500"}`}><Icon size={14} />{label}</button>)}</div></div><div className="flex justify-end"><ResetButton label={t("customize.iconAlign")} onClick={() => setSettings({ socialAlign: "center" })} /></div><div><FieldLabel>{t("customize.entryText")}</FieldLabel><TextInput value={config.settings.entryText} onChange={(value) => setSettings({ entryText: value })} /><p className="mt-1 text-[11px] text-zinc-600">{t("customize.entryHint")}</p></div></div></div>;
}

function ColorsPanel({ config, setSettings }: { config: ReturnType<typeof import("@/lib/mock-data").cloneMockProfile>; setSettings: (patch: Partial<typeof config.settings>) => void }) {
  const t = useT();
  const colors: Array<{ label: string; key: "accentColor" | "textColor" | "backgroundColor" | "iconColor" }> = [{ label: t("customize.accent"), key: "accentColor" }, { label: t("customize.textColor"), key: "textColor" }, { label: t("customize.bgColor"), key: "backgroundColor" }, { label: t("customize.iconColor"), key: "iconColor" }];
  const colorDefaults = { accentColor: "#9b87f5", textColor: "#ffffff", backgroundColor: "#08080d", iconColor: "#d8d3ff" } as const;
  return (
    <div>
      <SectionTitle icon={Palette} title={t("customize.colorsTitle")} description={t("customize.colorsDesc")} />
      <div className="grid gap-3 sm:grid-cols-2">{colors.map(({ label, key }) => <div key={key} className="rounded-2xl border border-white/[.07] bg-white/[.02] p-4"><FieldLabel>{label}</FieldLabel><div className="flex items-center gap-2"><input aria-label={label} type="color" value={config.settings[key]} onChange={(e) => setSettings({ [key]: e.target.value })} className="h-11 w-12 cursor-pointer rounded-xl border-0 bg-transparent p-0" /><TextInput value={config.settings[key]} onChange={(value) => setSettings({ [key]: value })} /><ResetButton label={label} onClick={() => setSettings({ [key]: colorDefaults[key] })} /></div></div>)}</div>
      <div className="mt-4 space-y-1 divide-y divide-white/[.06] rounded-2xl border border-white/[.07] bg-white/[.02] px-4">
        <ToggleRow label={t("customize.mono")} checked={Boolean(config.settings.monochromeIcons)} onChange={(checked) => setSettings({ monochromeIcons: checked })} onReset={() => setSettings({ monochromeIcons: false })} />
        <ToggleRow label={t("customize.swap")} checked={Boolean(config.settings.widgetColorSwap)} onChange={(checked) => setSettings({ widgetColorSwap: checked })} onReset={() => setSettings({ widgetColorSwap: false })} />
      </div>
    </div>
  );
}


function UsernameEffectPreview({ effect, name, usernameColor, effectColor, large = false }: { effect: UsernameEffect; name: string; usernameColor: string; effectColor: string; large?: boolean }) {
  const gradient = effect === "Gradient" || effect === "Shimmer" || effect === "Rainbow";
  const style = {
    color: gradient ? undefined : usernameColor,
    textShadow: effect === "Glow" ? "0 0 18px " + effectColor + "aa" : undefined,
    ["--username-color" as string]: usernameColor,
    ["--effect-color" as string]: effectColor,
    ...(effect === "Rainbow" ? { backgroundImage: "linear-gradient(90deg, #ff3b6b, #ffcf4a, #61e294, #55b8ff, #b887ff, #ff3b6b)", backgroundSize: "200% 100%" } : {}),
  } as CSSProperties;
  return <span className={(large ? "text-2xl sm:text-3xl" : "text-sm") + " font-semibold " + usernameEffectClass(effect)} style={style}>{name}</span>;
}

function UsernameEffectPicker({ label, value, onChange, name, usernameColor, effectColor, onReset }: { label: string; value: UsernameEffect; onChange: (value: UsernameEffect) => void; name: string; usernameColor: string; effectColor: string; onReset?: () => void }) {
  return (
    <div>
      <div className="flex items-center justify-between"><FieldLabel>{label}</FieldLabel>{onReset && <ResetButton label={label} onClick={onReset} />}</div>
      <div className="w-full min-w-0 max-w-full rounded-2xl border border-white/[.07] bg-white/[.02] p-3">
        <div className="flex min-h-20 items-center justify-center overflow-hidden rounded-xl border border-white/[.06] bg-black/20 px-4 py-5">
          <UsernameEffectPreview effect={value} name={name} usernameColor={usernameColor} effectColor={effectColor} large />
        </div>
        <div className="mt-3 grid w-full min-w-0 gap-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 150px), 1fr))" }}>
          {USERNAME_EFFECTS.map((effect) => (
            <button key={effect} type="button" onClick={() => onChange(effect)} aria-pressed={value === effect} className={"flex min-h-20 min-w-0 flex-col items-center justify-center gap-2 overflow-hidden rounded-xl border px-2 py-3 transition " + (value === effect ? "border-[#e11d48]/60 bg-[#e11d48]/10" : "border-white/[.07] bg-white/[.02] hover:border-white/20 hover:bg-white/[.05]")}>
              <UsernameEffectPreview effect={effect} name={name} usernameColor={usernameColor} effectColor={effectColor} />
              <span className={"text-[10px] uppercase tracking-[.12em] " + (value === effect ? "text-[#fecdd3]" : "text-zinc-600")}>{effect}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function BackgroundEffectPicker({ value, onChange }: { value: BackgroundEffect; onChange: (value: BackgroundEffect) => void }) {
  const selected = BACKGROUND_EFFECTS.find((item) => item.value === value) || BACKGROUND_EFFECTS[0];
  return <div>
    <FieldLabel>Background effect</FieldLabel>
    <div className="relative z-20 rounded-2xl border border-white/[.07] bg-white/[.02]">
      <div className="relative isolate h-32 overflow-hidden bg-[radial-gradient(circle_at_30%_20%,rgba(225,29,72,.16),transparent_42%),#09090d]">
        <BackgroundEffectLayer effect={value} className="z-0" />
        <div className="absolute inset-x-0 bottom-0 z-10 bg-gradient-to-t from-black/70 to-transparent px-4 pb-3 pt-8">
          <strong className="text-sm text-white">{selected.label}</strong>
          <p className="mt-1 text-xs text-zinc-400">{selected.description}</p>
        </div>
      </div>
      <div className="p-3">
        <SelectBox value={value} options={BACKGROUND_EFFECTS.map((item) => item.value)} onChange={(next) => onChange(next as BackgroundEffect)} onReset={() => onChange("None")} />
      </div>
    </div>
  </div>;
}
function EffectsPanel({ config, setSettings, setAsset, onUpload, showBackgroundEffect = true, backgroundEffectValue, onBackgroundEffectChange }: { config: ReturnType<typeof import("@/lib/mock-data").cloneMockProfile>; setSettings: (patch: Partial<typeof config.settings>) => void; setAsset: (key: keyof typeof config.assets, asset: ProfileAsset | boolean | number | string) => void; onUpload: (key: keyof typeof config.assets, file: File) => Promise<void>; showBackgroundEffect?: boolean; backgroundEffectValue?: BackgroundEffect; onBackgroundEffectChange?: (value: BackgroundEffect) => void }) {
  const t = useT();
  const defaultFonts = useDefaultFonts();
  const { enabled } = useFeatureFlags();
  const fontInput = useRef<HTMLInputElement>(null);
  const soundInput = useRef<HTMLInputElement>(null);
  const customFont = config.assets.customFont || { url: null };
  const clickFile = config.assets.clickSound || { url: null };
  const selectedFont = defaultFonts.find((font) => font.id === (config.settings.profileFont || "Inter")) || defaultFonts[0];
  return (
    <div>
      <SectionTitle icon={Sparkles} title={t("customize.effectsTitle")} description={t("customize.effectsDesc")} />
      <div className="space-y-6">
        <div className="grid w-full min-w-0 gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 150px), 1fr))" }}>
        {showBackgroundEffect ? <div className="col-span-full min-w-0"><BackgroundEffectPicker value={backgroundEffectValue ?? config.settings.backgroundEffect ?? "None"} onChange={onBackgroundEffectChange ?? ((value) => setSettings({ backgroundEffect: value }))} /></div> : null}
        <div className="col-span-full min-w-0"><UsernameEffectPicker label={t("customize.nameEffect")} value={config.settings.usernameEffect} onChange={(value) => setSettings({ usernameEffect: value })} name={config.profile.displayName || "yourname"} usernameColor={config.settings.usernameColor || config.settings.textColor || "#ffffff"} effectColor={config.settings.usernameEffectColor || config.settings.accentColor || "#e11d48"} onReset={() => setSettings({ usernameEffect: "Glow" })} /></div>
        <div className="min-w-0"><FieldLabel>{t("customize.pageEnter")}</FieldLabel><SelectBox value={config.settings.pageEnter || "Fade"} options={[...PAGE_ENTERS]} onChange={(value) => setSettings({ pageEnter: value as PageEnter })} onReset={() => setSettings({ pageEnter: "Fade" })} /></div>
        <div className="min-w-0"><FieldLabel>{t("customize.font")}</FieldLabel><SelectBox value={selectedFont?.name || "Inter"} options={defaultFonts.map((font) => font.name)} onChange={(value) => { const next = defaultFonts.find((font) => font.name === value); if (next) setSettings({ profileFont: next.id }); }} onReset={() => setSettings({ profileFont: "Inter" })} /></div>

        </div>
        {config.settings.usernameEffect !== "Rainbow" && <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
          <div><FieldLabel>{t("customize.usernameColor", undefined, "Username color")}</FieldLabel><div className="flex gap-2"><input aria-label="Username color" type="color" value={config.settings.usernameColor || "#ffffff"} onChange={(event) => setSettings({ usernameColor: event.target.value })} className="h-10 w-11 cursor-pointer rounded-xl border-0 bg-transparent p-0" /><TextInput value={config.settings.usernameColor || "#ffffff"} onChange={(value) => setSettings({ usernameColor: value })} /></div></div>
          <div><FieldLabel>{t("customize.usernameEffectColor", undefined, "Effect color")}</FieldLabel><div className="flex gap-2"><input aria-label="Username effect color" type="color" value={config.settings.usernameEffectColor || config.settings.accentColor || "#e11d48"} onChange={(event) => setSettings({ usernameEffectColor: event.target.value })} className="h-10 w-11 cursor-pointer rounded-xl border-0 bg-transparent p-0" /><TextInput value={config.settings.usernameEffectColor || config.settings.accentColor || "#e11d48"} onChange={(value) => setSettings({ usernameEffectColor: value })} /></div></div>
        </div>}
        <div className="rounded-2xl border border-white/[.07] bg-white/[.02] p-3.5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/[.06] text-zinc-500"><Type size={17} /></div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-zinc-200">{t("customize.customFont")}</p>
              <p className="mt-1 truncate text-xs text-zinc-600">{customFont.url ? customFont.name || t("customize.uploadedFont") : t("customize.customFontHint")}</p>
            </div>
            <input ref={fontInput} className="hidden" type="file" accept={FONT_ACCEPT} onChange={(event) => { const file = event.target.files?.[0]; if (file) void onUpload("customFont", file); event.target.value = ""; }} />
            <Button variant="subtle" className="h-9 min-h-0 px-3 text-xs" onClick={() => fontInput.current?.click()}>{customFont.url ? t("common.replace") : <><Upload size={13} />{t("common.upload")}</>}</Button>
            {customFont.url ? <Button variant="ghost" className="h-9 min-h-0 px-3 text-xs" onClick={() => setAsset("customFont", { url: null, remove: true })}>{t("common.remove")}</Button> : null}
          </div>
        </div>
        <div className="space-y-5 rounded-2xl border border-white/[.07] bg-white/[.02] p-4">
          <RangeControl label={t("customize.textSize")} value={config.settings.fontSize ?? 16} min={12} max={22} suffix="px" onChange={(value) => setSettings({ fontSize: value })} onReset={() => setSettings({ fontSize: 16 })} />
          <RangeControl label={t("customize.tracking")} value={config.settings.letterSpacing ?? 0} min={-2} max={8} suffix="px" onChange={(value) => setSettings({ letterSpacing: value })} onReset={() => setSettings({ letterSpacing: 0 })} />
        </div>
        <div className="space-y-1 divide-y divide-white/[.06] rounded-2xl border border-white/[.07] bg-white/[.02] px-4">
          <ToggleRow label={t("customize.nameGlow")} checked={config.settings.usernameGlow} onChange={(checked) => setSettings({ usernameGlow: checked })} onReset={() => setSettings({ usernameGlow: true })} />
          <ToggleRow label={t("customize.socialGlow")} checked={config.settings.socialGlow} onChange={(checked) => setSettings({ socialGlow: checked })} onReset={() => setSettings({ socialGlow: true })} />
          <ToggleRow label={t("customize.badgeGlow")} checked={config.settings.badgeGlow} onChange={(checked) => setSettings({ badgeGlow: checked })} onReset={() => setSettings({ badgeGlow: true })} />
          <ToggleRow label={t("customize.tilt")} checked={Boolean(config.settings.cardTilt)} onChange={(checked) => setSettings({ cardTilt: checked })} onReset={() => setSettings({ cardTilt: false })} />
          <ToggleRow label={t("customize.clickSound")} checked={Boolean(config.settings.clickSound)} onChange={(checked) => setSettings({ clickSound: checked })} onReset={() => setSettings({ clickSound: false })} />
          <ToggleRow label={t("customize.typewriter")} checked={Boolean(config.settings.bioTypewriter)} onChange={(checked) => setSettings({ bioTypewriter: checked })} onReset={() => setSettings({ bioTypewriter: false })} />
          <ToggleRow label={t("customize.tabAnimate")} checked={Boolean(config.settings.tabTitleAnimate)} onChange={(checked) => setSettings({ tabTitleAnimate: checked })} onReset={() => setSettings({ tabTitleAnimate: false })} />
        </div>
        {config.settings.clickSound && (
          <div className="rounded-2xl border border-white/[.07] bg-white/[.02] p-3.5">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/[.06] text-zinc-500"><Volume2 size={17} /></div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-zinc-200">{t("customize.clickFile")}</p>
                <p className="mt-1 truncate text-xs text-zinc-600">{clickFile.url ? clickFile.name || t("customize.uploadedClick") : t("customize.clickFileHint")}</p>
              </div>
              <input ref={soundInput} className="hidden" type="file" accept="audio/mpeg,audio/wav,audio/mp3,.mp3,.wav" onChange={(event) => { const file = event.target.files?.[0]; if (file) void onUpload("clickSound", file); event.target.value = ""; }} />
              <Button variant="subtle" className="h-9 min-h-0 px-3 text-xs" onClick={() => soundInput.current?.click()}>{clickFile.url ? t("common.replace") : <><Upload size={13} />{t("common.upload")}</>}</Button>
              {clickFile.url ? <Button variant="ghost" className="h-9 min-h-0 px-3 text-xs" onClick={() => setAsset("clickSound", { url: null, remove: true })}>{t("common.remove")}</Button> : null}
            </div>
          </div>
        )}
        {config.settings.bioTypewriter && (
          <div className="space-y-5 rounded-2xl border border-white/[.07] bg-white/[.02] p-4">
            <RangeControl label={t("customize.typeSpeed")} value={config.settings.bioTypeMs ?? 55} min={20} max={160} suffix="ms" onChange={(value) => setSettings({ bioTypeMs: value })} onReset={() => setSettings({ bioTypeMs: 55 })} />
            <RangeControl label={t("customize.deleteSpeed")} value={config.settings.bioDeleteMs ?? 35} min={20} max={160} suffix="ms" onChange={(value) => setSettings({ bioDeleteMs: value })} onReset={() => setSettings({ bioDeleteMs: 35 })} />
            <RangeControl label={t("customize.pauseSpeed")} value={config.settings.bioPauseMs ?? 1200} min={400} max={4000} suffix="ms" onChange={(value) => setSettings({ bioPauseMs: value })} onReset={() => setSettings({ bioPauseMs: 1200 })} />
          </div>
        )}
        <div className="rounded-2xl border border-[#e11d48]/15 bg-[#e11d48]/[.05] p-4"><div className="flex gap-3"><WandSparkles size={17} className="mt-0.5 shrink-0 text-[#fecdd3]" /><p className="text-xs leading-5 text-zinc-400">{t("customize.tabNote")}</p></div></div>
      </div>
    </div>
  );
}

function ToggleRow({ icon: Icon, label, checked, onChange, onReset }: { icon?: ElementType; label: string; checked: boolean; onChange: (value: boolean) => void; onReset?: () => void }) {
  return <div className="flex items-center justify-between gap-3 py-3.5"><div className="flex min-w-0 flex-1 items-start gap-3 sm:items-center">{Icon && <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#e11d48]/[.08] text-[#fda4af]"><Icon size={17} strokeWidth={1.8} /></span>}<span className="text-sm text-zinc-300">{label}</span></div><div className="flex items-center gap-2">{onReset && <button type="button" onClick={onReset} aria-label={"Reset " + label} title={"Reset " + label} className="rounded-md p-1 text-zinc-600 transition hover:bg-white/[.06] hover:text-zinc-200"><RotateCcw size={12} /></button>}<Toggle label={label} checked={checked} onChange={onChange} /></div></div>;
}

function ResetButton({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} aria-label={"Reset " + label} title={"Reset " + label} className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-zinc-600 transition hover:bg-white/[.06] hover:text-zinc-200"><RotateCcw size={12} />Reset</button>;
}
