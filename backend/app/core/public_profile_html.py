from app.core.element_layout import element_style

import hashlib
import json
from html import escape

from fastapi import Request

from app.core.discord_live import safe_discord_img
from app.core.og_card import share_copy
from app.core.public_origin import public_origin_for
from app.core.markdown import render_safe_markdown
from app.core.profile_features import features_markup, public_features_payload
from app.core.profile_sanitize import PAGE_ENTERS, PROFILE_FONTS, USERNAME_EFFECTS, css_hex_color, has_public_asset, is_safe_social_icon, public_playlist, public_social_href, sanitize_profile_config
from app.core.sections import visible_sections, project_configured
from app.core.widgets import safe_widget_url
from app.core.social_icons import social_icon_markup
from app.core.social_prefixes import DEFAULT_ICON_COLOR, resolve_icon_color


def _color_with_alpha(value: str, alpha: float) -> str:
    raw = (value or "#ffffff").lstrip("#")
    if len(raw) == 3:
        raw = "".join(part * 2 for part in raw)
    raw = raw[:6]
    if len(raw) != 6 or any(character not in "0123456789abcdefABCDEF" for character in raw):
        return f"rgba(255,255,255,{max(0.0, min(1.0, alpha)):.3f})"
    red = int(raw[0:2], 16)
    green = int(raw[2:4], 16)
    blue = int(raw[4:6], 16)
    return f"rgba({red},{green},{blue},{max(0.0, min(1.0, alpha)):.3f})"


PUBLIC_ANALYTICS_SCRIPT = """<script>
(() => {
  const username = document.body.dataset.profileUser || "";
  if (!username) return;
  const device = /iPad|Tablet/i.test(navigator.userAgent) ? "tablet" : /Mobi|Android/i.test(navigator.userAgent) ? "mobile" : "desktop";
  const send = (kind, socialId, socialLabel) => {
    const body = JSON.stringify({
      username,
      kind,
      socialId: socialId || "",
      socialLabel: socialLabel || "",
      referrer: document.referrer || "",
      device,
    });
    fetch("/api/v1/analytics/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
      credentials: "same-origin",
    }).catch(() => {});
  };
  send("view");
  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-social-id]");
    if (!target) return;
    send("click", target.getAttribute("data-social-id") || "", target.getAttribute("data-social-platform") || "");
  });
})();
</script>
"""

PUBLIC_BADGE_SCRIPT = """<script>
(() => {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  document.querySelectorAll("img[data-animated-badge]").forEach((image) => {
    const preview = image.getAttribute("src") || "";
    const animated = image.getAttribute("data-animated-badge") || "";
    if (!preview || !animated) return;
    const start = () => image.setAttribute("src", animated);
    const stop = () => image.setAttribute("src", preview);
    image.addEventListener("pointerenter", start);
    image.addEventListener("pointerleave", stop);
    image.addEventListener("pointerdown", start);
    image.addEventListener("pointerup", stop);
    image.addEventListener("pointercancel", stop);
  });
})();
</script>
"""

PUBLIC_COPY_SCRIPT = """<div id="copy-toast" hidden>Copied</div>
<script>
(() => {
  const toast = document.getElementById("copy-toast");
  const audio = document.getElementById("profile-audio");
  const player = document.getElementById("profile-player");
  const playBtn = document.getElementById("audio-play");
  const muteBtn = document.getElementById("audio-mute");
  const prevBtn = document.getElementById("audio-prev");
  const nextBtn = document.getElementById("audio-next");
  const shuffleBtn = document.getElementById("audio-shuffle");
  const repeatBtn = document.getElementById("audio-repeat");
  const seek = document.getElementById("audio-seek");
  const volumeInput = document.getElementById("audio-volume");
  const titleEl = document.getElementById("audio-title");
  const countEl = document.getElementById("audio-count");
  const artEl = document.getElementById("audio-art");
  const nowEl = document.getElementById("audio-now");
  const durEl = document.getElementById("audio-dur");
  const video = document.querySelector(".bg-video");
  const enabled = document.body.dataset.audioEnabled === "1";
  const volume = Math.min(1, Math.max(0, Number(document.body.dataset.volume || "0.65")));
  let tracks = [];
  try { tracks = JSON.parse(document.getElementById("playlist-data")?.textContent || "[]"); } catch {}
  let index = 0;
  let shuffle = false;
  let repeat = "all";
  let order = tracks.map((_, i) => i);
  const keepOnCard = (event) => { event.stopPropagation(); };
  const bindClick = (event) => { event.preventDefault(); event.stopPropagation(); };
  const fmt = (value) => {
    if (!Number.isFinite(value) || value <= 0) return "0:00";
    const m = Math.floor(value / 60);
    const s = Math.floor(value % 60);
    return m + ":" + String(s).padStart(2, "0");
  };
  const paint = (i) => {
    const track = tracks[i];
    if (!track) return;
    if (audio) audio.dataset.trackInfo = JSON.stringify({ ...track, src: track.audio, count: tracks.length });
    if (titleEl) titleEl.textContent = track.title || "Track";
    if (countEl) countEl.textContent = (i + 1) + " / " + tracks.length;
    if (artEl && track.artwork && artEl.getAttribute("src") !== track.artwork) artEl.src = track.artwork;
  };
  const load = (i, play) => {
    if (!audio || !tracks[i] || !tracks[i].audio) return;
    index = i;
    paint(i);
    const next = tracks[i].audio;
    const current = audio.getAttribute("data-track-src") || "";
    if (current === next) {
      audio.currentTime = 0;
    } else {
      audio.setAttribute("data-track-src", next);
      audio.preload = "metadata";
      audio.src = next;
    }
    if (play) audio.play().catch(() => {});
  };
  const step = (dir) => {
    if (!tracks.length) return;
    const pos = order.indexOf(index);
    load(order[(pos + dir + order.length) % order.length], true);
  };
  if (audio) audio.volume = volume;
  const videoToggle = document.getElementById("video-audio-toggle");
  const videoVolume = document.getElementById("video-volume");
  if (video) {
    video.volume = volume;
    const syncVideo = () => {
      if (videoToggle) { videoToggle.textContent = video.muted ? "Enable audio" : "Mute audio"; videoToggle.setAttribute("aria-pressed", String(!video.muted)); }
    };
    video.addEventListener("volumechange", syncVideo);
    videoToggle?.addEventListener("click", () => { video.muted = !video.muted; video.play().catch(() => {}); });
    videoVolume?.addEventListener("input", () => { video.volume = Number(videoVolume.value) / 100; });
    syncVideo();
  }
  const startMedia = () => {
    if (video) video.play().catch(() => {});
    if (audio && enabled && tracks[0]) load(0, true);
  };

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy]");
    if (!button || (player && player.contains(button))) return;
    event.preventDefault();
    event.stopPropagation();
    const value = button.getAttribute("data-copy") || "";
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const field = document.createElement("textarea");
      field.value = value;
      document.body.appendChild(field);
      field.select();
      document.execCommand("copy");
      field.remove();
    }
    if (!toast) return;
    toast.hidden = false;
    window.setTimeout(() => { toast.hidden = true; }, 1600);
  });

  const entry = document.getElementById("entry");
  const card = document.getElementById("profile-card");
  const mediaDock = document.querySelector(".media-dock");
  const profileMeta = document.querySelector(".meta");

  if (player) {
    player.addEventListener("click", keepOnCard);
    player.addEventListener("pointerdown", keepOnCard);
  }
  const bind = (el, handler) => {
    if (!el) return;
    el.addEventListener("click", (event) => { bindClick(event); handler(event); });
  };
  const togglePlay = () => {
    if (!audio) return;
    if (!audio.getAttribute("data-track-src") && tracks[0]) load(0, true);
    else if (audio.paused) audio.play().catch(() => {});
    else audio.pause();
  };
  if (playBtn && audio) {
    bind(playBtn, togglePlay);
    audio.addEventListener("play", () => {
      playBtn.dataset.playing = "1";
      playBtn.setAttribute("aria-label", "Pause");
      playBtn.setAttribute("aria-pressed", "true");
    });
    audio.addEventListener("pause", () => {
      playBtn.dataset.playing = "0";
      playBtn.setAttribute("aria-label", "Play");
      playBtn.setAttribute("aria-pressed", "false");
    });
    audio.addEventListener("timeupdate", () => {
      if (seek && audio.duration) seek.value = String(Math.floor(audio.currentTime));
      if (nowEl) nowEl.textContent = fmt(audio.currentTime);
    });
    audio.addEventListener("loadedmetadata", () => {
      if (seek) seek.max = String(Math.floor(audio.duration || 1));
      if (durEl) durEl.textContent = fmt(audio.duration);
    });
    audio.addEventListener("ended", () => {
      if (repeat === "one") { audio.currentTime = 0; audio.play().catch(() => {}); return; }
      const last = order.indexOf(index) === order.length - 1;
      if (last && repeat === "off") return;
      step(1);
    });
  }
  bind(prevBtn, () => step(-1));
  bind(nextBtn, () => step(1));
  bind(shuffleBtn, () => {
    shuffle = !shuffle;
    if (shuffleBtn) {
      shuffleBtn.dataset.on = shuffle ? "1" : "0";
      shuffleBtn.setAttribute("aria-label", shuffle ? "Disable shuffle" : "Shuffle");
      shuffleBtn.setAttribute("aria-pressed", shuffle ? "true" : "false");
    }
    order = tracks.map((_, i) => i);
    if (shuffle) order = order.map((v, i) => [v, (i * 17 + 11) % order.length]).sort((a, b) => a[1] - b[1]).map((x) => x[0]);
  });
  bind(repeatBtn, () => {
    repeat = repeat === "off" ? "all" : repeat === "all" ? "one" : "off";
    if (repeatBtn) {
      repeatBtn.dataset.mode = repeat;
      repeatBtn.setAttribute("aria-label", repeat === "one" ? "Repeat one" : repeat === "all" ? "Repeat all" : "Repeat off");
    }
  });
  bind(muteBtn, () => {
    if (!audio) return;
    audio.muted = !audio.muted;
    if (muteBtn) {
      muteBtn.dataset.muted = audio.muted ? "1" : "0";
      muteBtn.setAttribute("aria-label", audio.muted ? "Unmute" : "Mute");
      muteBtn.setAttribute("aria-pressed", audio.muted ? "true" : "false");
    }
  });
  if (volumeInput && audio) {
    volumeInput.addEventListener("input", (event) => {
      event.stopPropagation();
      audio.volume = Math.min(1, Math.max(0, Number(volumeInput.value || "0") / 100));
    });
  }
  if (seek && audio) {
    seek.addEventListener("input", (event) => {
      event.stopPropagation();
      audio.currentTime = Number(seek.value || "0");
    });
  }
  if (tracks[0]) paint(0);

  const cursorSrc = document.body.dataset.cursor || "";
  if (cursorSrc) {
    const apply = (url) => {
      document.documentElement.style.setProperty("--cursor", `url("${url}") 16 16, auto`);
    };
    apply(cursorSrc);
    const image = new Image();
    image.onload = () => {
      if (image.naturalWidth <= 128 && image.naturalHeight <= 128) return;
      const canvas = document.createElement("canvas");
      canvas.width = 32;
      canvas.height = 32;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(image, 0, 0, 32, 32);
      apply(canvas.toDataURL("image/png"));
    };
    image.src = cursorSrc;
  }

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const pageEnter = document.body.dataset.pageEnter || "Fade";
  const playClick = () => {
    if (document.body.dataset.clickSound !== "1" || document.body.dataset.clickPreset === "None") return;
    const preset = document.body.dataset.clickPreset || "Crisp Click";
    const src = (!document.body.dataset.clickPreset || preset === "Custom") ? document.body.dataset.clickSrc || "" : "";
    if (src) {
      const tap = new Audio(src);
      tap.volume = 0.35;
      tap.play().catch(() => {});
      return;
    }
    if (preset === "Custom") return;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = preset === "Pixel Click" ? "square" : preset === "Mouse Click" ? "triangle" : "sine";
    osc.frequency.value = preset === "Bass Tick" ? 140 : preset === "Pixel Click" ? 1200 : preset === "Mouse Click" ? 1800 : 880;
    gain.gain.value = 0.05;
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.08);
    osc.stop(ctx.currentTime + 0.09);
    osc.onended = () => { osc.disconnect(); gain.disconnect(); ctx.close(); };
  };
  const reveal = () => {
    if (!card) return;
    card.hidden = false;
    if (mediaDock) mediaDock.hidden = false;
    if (profileMeta) profileMeta.hidden = false;
    if (document.body.dataset.profileKind !== "Portfolio" && !reduced && pageEnter !== "None") card.classList.add("enter-" + pageEnter.toLowerCase());
    startMedia();
  };
  if (entry && card) {
    card.hidden = true;
    if (mediaDock) mediaDock.hidden = true;
    if (profileMeta) profileMeta.hidden = true;
    let entryUsed = false;
    entry.addEventListener("click", (event) => {
      event.stopPropagation();
      if (entryUsed) return;
      entryUsed = true;
      entry.classList.add("is-leaving");
      window.setTimeout(() => { entry.hidden = true; }, reduced ? 0 : 500);
      if (video && videoToggle && enabled) video.muted = false;
      reveal();
    });
  } else {
    reveal();
  }
  document.addEventListener("click", (event) => {
    const hit = event.target.closest(".social, #entry, [data-copy], .audio-btn");
    if (hit) playClick();
  });
  const tiltCard = document.body.dataset.profileKind === "Portfolio" ? document.querySelector(".portfolio-identity") : card;
  if (tiltCard && document.body.dataset.tilt === "1" && !reduced) {
    tiltCard.addEventListener("pointermove", (event) => {
      const box = tiltCard.getBoundingClientRect();
      const x = (event.clientX - box.left) / box.width - 0.5;
      const y = (event.clientY - box.top) / box.height - 0.5;
      tiltCard.style.transform = "rotateX(" + (-y * 7).toFixed(2) + "deg) rotateY(" + (x * 9).toFixed(2) + "deg)";
    });
    tiltCard.addEventListener("pointerleave", () => { tiltCard.style.transform = ""; });
  }
  const nameEl = document.getElementById("display-name");
  const nameEffect = document.body.dataset.nameEffect || "";
  if (nameEl && nameEffect === "Shuffle") {
    const full = nameEl.textContent || "";
    const glyphs = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    let step = 0;
    const timer = window.setInterval(() => {
      step += 1;
      nameEl.textContent = full.split("").map((ch, index) => {
        if (ch === " " || index < Math.floor(step / 2)) return full[index] || "";
        return glyphs[Math.floor(Math.random() * glyphs.length)];
      }).join("");
      if (step > full.length * 2 + 4) window.clearInterval(timer);
    }, 40);
  }
  const bioEl = document.getElementById("profile-bio");
  const bioNode = document.getElementById("bio-lines");
  if (bioEl && bioNode && !reduced) {
    let lines = [];
    try { lines = JSON.parse(bioNode.textContent || "[]"); } catch (error) { lines = []; }
    if (lines.length) {
      let line = 0;
      let index = 0;
      let deleting = false;
      const typeSpeed = Math.max(20, Math.min(160, Number(document.body.dataset.bioTypeMs || "55")));
      const deleteSpeed = Math.max(20, Math.min(160, Number(document.body.dataset.bioDeleteMs || "35")));
      const pause = Math.max(400, Math.min(4000, Number(document.body.dataset.bioPauseMs || "1200")));
      const tick = () => {
        const current = lines[line] || "";
        if (!deleting) {
          index += 1;
          bioEl.textContent = current.slice(0, index);
          if (index >= current.length) {
            deleting = lines.length > 1;
            window.setTimeout(tick, lines.length > 1 ? pause : 999999);
            return;
          }
          window.setTimeout(tick, typeSpeed);
          return;
        }
        index -= 1;
        bioEl.textContent = current.slice(0, Math.max(0, index));
        if (index <= 0) {
          deleting = false;
          line = (line + 1) % lines.length;
          window.setTimeout(tick, typeSpeed);
          return;
        }
        window.setTimeout(tick, deleteSpeed);
      };
      tick();
    }
  }
  if (document.body.dataset.tabTitle === "1" && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const titleNode = document.getElementById("page-title-data");
    let base = document.title;
    try { base = JSON.parse(titleNode && titleNode.textContent ? titleNode.textContent : JSON.stringify(document.title)); } catch (error) {}
    const pad = base + "   ";
    let offset = 0;
    window.setInterval(() => {
      document.title = pad.slice(offset) + pad.slice(0, offset);
      offset = (offset + 1) % pad.length;
    }, 180);
  }
})();
</script>"""


PUBLIC_MEDIA_LAYOUT_SCRIPT = """<script>
(() => {
  const slot = document.querySelector(".profile-audio-slot");
  if (!slot) return;
  const mobile = document.querySelector("[data-profile-mobile-audio]");
  const row = document.querySelector("[data-profile-media-row]");
  const viewport = window.matchMedia("(min-width:900px)");
  const place = () => {
    const target = viewport.matches ? row : mobile;
    if (!target || slot.parentElement === target) return;
    const audio = slot.querySelector("audio");
    const playing = audio && !audio.paused;
    if (target.moveBefore && slot.isConnected) target.moveBefore(slot, null);
    else target.appendChild(slot);
    if (playing && audio.paused) audio.play().catch(() => {});
  };
  place();
  viewport.addEventListener("change", place);
})();
</script>"""

PUBLIC_WIDGET_SCRIPT = """<script>
(() => {
  const cards = document.querySelectorAll("[data-timezone]");
  if (!cards.length) return;
  const tick = () => {
    cards.forEach((el) => {
      const zone = el.getAttribute("data-timezone");
      const title = el.querySelector("strong");
      if (!zone || !title) return;
      try {
        title.textContent = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: zone }).format(new Date());
      } catch (error) {}
    });
  };
  tick();
  setInterval(tick, 15000);
})();
</script>"""

PUBLIC_DISCORD_STATUS_SCRIPT = """<script>
(() => {
  const dots = document.querySelectorAll("[data-discord-status]");
  const labels = document.querySelectorAll("[data-discord-status-label]");
  const username = document.body.dataset.profileUser || "";
  if ((!dots.length && !labels.length) || !username) return;
  const allowed = { online: "Online", idle: "Idle", dnd: "Do Not Disturb", offline: "Offline" };
  const paint = (status) => {
    const label = allowed[status];
    if (!label) return;
    dots.forEach((dot) => {
      dot.className = "status-dot status-" + status;
      dot.setAttribute("data-discord-status", status);
      dot.setAttribute("aria-label", "Discord " + status);
    });
    labels.forEach((el) => { el.textContent = label; });
  };
  const pull = () => {
    fetch("/api/v1/profile/" + encodeURIComponent(username) + "/discord-status", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : null)
      .then((data) => { if (data && data.status) paint(data.status); })
      .catch(() => {});
  };
  setInterval(pull, 15000);
})();
</script>
"""

# Discord web-client status masks (`svg-mask-status-*`).
DISCORD_STATUS_ICON_SVG = """<svg viewBox="0 0 16 16" aria-hidden="true">
  <circle cx="8" cy="8" r="8" fill="#15151d"/>
  <g transform="translate(8 8) scale(0.72) translate(-8 -8)">
    <g class="icon-online"><circle cx="8" cy="8" r="8" fill="#23a55a"/></g>
    <g class="icon-idle"><circle cx="8" cy="8" r="8" fill="#f0b232"/><circle cx="4" cy="4" r="6" fill="#15151d"/></g>
    <g class="icon-dnd"><circle cx="8" cy="8" r="8" fill="#f23f43"/><rect x="2" y="6" width="12" height="4" rx="2" fill="#15151d"/></g>
    <g class="icon-offline"><circle cx="8" cy="8" r="8" fill="#80848e"/><circle cx="8" cy="8" r="4" fill="#15151d"/></g>
  </g>
</svg>"""


def _audio_icon(body: str, class_name: str = "") -> str:
    classes = f"audio-icon {class_name}".strip()
    return (
        f'<svg class="{classes}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{body}</svg>'
    )


AUDIO_ICON_SHUFFLE = _audio_icon(
    '<path d="m18 14 4 4-4 4"/><path d="m18 2 4 4-4 4"/>'
    '<path d="M2 18h1.5c2.8 0 5.2-1.6 6.5-4"/><path d="M2 6h1.5c2.8 0 5.2 1.6 6.5 4"/>'
    '<path d="M22 6h-1.5c-2.8 0-5.2 1.6-6.5 4"/><path d="M22 18h-1.5c-2.8 0-5.2-1.6-6.5-4"/>'
)
AUDIO_ICON_PREVIOUS = _audio_icon('<path d="m19 20-9-8 9-8v16Z"/><path d="M5 19V5"/>')
AUDIO_ICON_PLAY = _audio_icon('<path d="m6 3 14 9-14 9V3Z" fill="currentColor"/>', "audio-icon-play")
AUDIO_ICON_PAUSE = _audio_icon('<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>', "audio-icon-pause")
AUDIO_ICON_NEXT = _audio_icon('<path d="m5 4 9 8-9 8V4Z"/><path d="M19 5v14"/>')
AUDIO_ICON_REPEAT = _audio_icon('<path d="m17 2 4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h18"/><path d="m7 22-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/>')
AUDIO_ICON_VOLUME = _audio_icon('<path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/>', "audio-icon-volume")
AUDIO_ICON_VOLUME_X = _audio_icon('<path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="m22 9-6 6"/><path d="m16 9 6 6"/>', "audio-icon-volume-x")

PUBLIC_EMPTY_SCRIPT = """<script type="module">
import { mountEmpty } from '/dashboard/profile-empty.mjs';
const emptyCleanup = [...document.querySelectorAll('[data-empty-face]')].map(mountEmpty);
addEventListener('pagehide', () => emptyCleanup.forEach(cleanup => cleanup()), { once: true });
</script>"""

PUBLIC_LYRICS_SCRIPT = """<script type="module">
import { mountLyrics } from '/dashboard/profile-lyrics.mjs';
document.querySelectorAll('[data-lyrics-body]').forEach(host => mountLyrics(host, document.body));
</script>"""


PUBLIC_BACKGROUND_EFFECT_SCRIPT = """<script>
(()=>{const c=document.getElementById("bg-particles");if(!c)return;const e=c.dataset.effect||"None",rgb=c.dataset.color||(e==="Fireflies"?"252,210,113":"255,255,255"),x=c.getContext("2d"),reduce=matchMedia("(prefers-reduced-motion:reduce)").matches;let w=1,h=1,t=0,raf=0,wind=0,p=[];
if(e==="Rain"){c.style.backdropFilter="blur(1.4px) saturate(.88) brightness(.93)";c.style.background="rgba(130,175,198,.035)"}
const make=(random=true)=>({x:Math.random()*w,y:random?Math.random()*h:-30,s:e==="Rain"?2.5+Math.pow(Math.random(),3.1)*18:e==="Fireflies"?.45+Math.pow(Math.random(),2.2)*1.35:e==="Sakura"?10+Math.random()*4:e==="Snow"?.8+Math.random()*2.4:1.4+Math.random()*(e==="Snowflakes"?4:2.6),v:e==="Rain"?.025+Math.random()*.22:e==="Snow"?.2+Math.random()*1.8:.25+Math.random()*1.1,d:(Math.random()-.5)*(e==="Fireflies"?.7:e==="Sakura"?.9:e==="Snow"?2.2:.35),q:Math.random()*Math.PI*2,a:.35+Math.random()*.55});
const resize=()=>{const r=c.getBoundingClientRect(),d=Math.min(devicePixelRatio||1,e==="Rain"?1.5:1.75);w=Math.max(1,r.width);h=Math.max(1,r.height);c.width=Math.round(w*d);c.height=Math.round(h*d);x.setTransform(d,0,0,d,0,0);const n=e==="Fireflies"?Math.max(60,Math.min(200,Math.round(w*h/6000))):e==="Sakura"?Math.max(10,Math.min(28,Math.round(w/80))):e==="Snow"?Math.max(24,Math.min(64,Math.round(w*h/14500))):Math.max(12,Math.min(e==="Rain"?140:48,Math.round(e==="Rain"?w*h/5200:w/28)));p=Array.from({length:reduce?Math.min(22,n):n},()=>make())};
const flake=o=>{x.save();x.translate(o.x,o.y);x.strokeStyle="rgba("+rgb+","+o.a+")";x.lineWidth=Math.max(.7,o.s/5);for(let i=0;i<3;i++){x.rotate(Math.PI/3);x.beginPath();x.moveTo(-o.s,0);x.lineTo(o.s,0);x.stroke()}x.restore()};
const rain=o=>{const r=o.s,z=1+Math.max(0,r-7)*.035;if(r>8){const l=x.createLinearGradient(o.x,o.y-r*3.2,o.x,o.y);l.addColorStop(0,"rgba(210,235,246,0)");l.addColorStop(1,"rgba(210,235,246,"+o.a*.16+")");x.strokeStyle=l;x.lineWidth=Math.max(1,r*.18);x.beginPath();x.moveTo(o.x,o.y-r*3.2);x.lineTo(o.x,o.y-r*.7);x.stroke()}const g=x.createRadialGradient(o.x-r*.32,o.y-r*.4,r*.08,o.x,o.y,r*1.15);g.addColorStop(0,"rgba(255,255,255,.68)");g.addColorStop(.2,"rgba(210,235,246,.13)");g.addColorStop(.68,"rgba(120,155,176,.08)");g.addColorStop(1,"rgba(5,18,28,.48)");x.shadowColor="rgba(0,10,20,.62)";x.shadowBlur=Math.max(2,r*.45);x.shadowOffsetY=Math.max(1,r*.12);x.fillStyle=g;x.beginPath();x.ellipse(o.x,o.y,r*.72,r*z,0,0,Math.PI*2);x.fill();x.shadowColor="transparent";x.strokeStyle="rgba(235,249,255,"+Math.min(.7,o.a*.75)+")";x.lineWidth=Math.max(.45,r*.055);x.stroke();x.strokeStyle="rgba(255,255,255,"+o.a*.5+")";x.lineWidth=Math.max(.5,r*.08);x.beginPath();x.arc(o.x-r*.08,o.y-r*.13,r*.48,Math.PI*1.05,Math.PI*1.68);x.stroke()};
const draw=(move=true)=>{x.clearRect(0,0,w,h);t+=move?1:0;for(const o of p){if(move){if(e==="Fireflies"){o.x+=(o.q>Math.PI?-1:1)*(.12+o.v*.12);o.y+=Math.sin(t/95+o.q)*.06}else if(e==="Rain"){o.y+=o.v*Math.max(1,o.s/5);o.x+=Math.sin(t/130+o.q)*.018}else if(e==="Snow"){o.y+=o.v;o.x+=o.d+wind}else{o.y+=o.v;o.x+=o.d+Math.sin(t/70+o.q)*.16}if(e==="Fireflies"){if(o.x>w+30){o.x=-30;o.y=Math.random()*h}else if(o.x< -30){o.x=w+30;o.y=Math.random()*h}}else if(o.y>h+30||o.x< -30||o.x>w+30)Object.assign(o,make(false))}x.save();x.globalAlpha=e==="Fireflies"?o.a*Math.pow(Math.max(0,Math.sin(t/(72+o.q*8)+o.q)),5):o.a;if(e==="Rain")rain(o);else if(e==="Sakura"){const pw=o.s*.78,ph=o.s;x.globalAlpha*=.9-Math.min(.7,o.y/Math.max(1,h)*.7);x.translate(o.x,o.y);x.rotate(Math.sin(t/34+o.q)*.48+o.q);if(Math.sin(t/42+o.q)<0)x.scale(-1,1);const g=x.createLinearGradient(-pw/2,-ph/2,pw/2,ph/2);g.addColorStop(0,"rgba(255,183,197,.92)");g.addColorStop(1,"rgba(255,197,208,.9)");x.fillStyle=g;x.beginPath();x.moveTo(-pw*.52,0);x.bezierCurveTo(-pw*.35,-ph*.48,pw*.32,-ph*.55,pw*.52,0);x.bezierCurveTo(pw*.3,ph*.42,-pw*.25,ph*.55,-pw*.52,0);x.closePath();x.fill()}else if(e==="Snowflakes")flake(o);else if(e==="Fireflies"){const g=x.createRadialGradient(o.x,o.y,0,o.x,o.y,o.s*3.2);g.addColorStop(0,"rgba("+rgb+",1)");g.addColorStop(.24,"rgba("+rgb+",.7)");g.addColorStop(1,"rgba("+rgb+",0)");x.fillStyle=g;x.beginPath();x.arc(o.x,o.y,o.s*3.2,0,Math.PI*2);x.fill()}else{x.fillStyle="rgba("+rgb+",.82)";x.beginPath();x.arc(o.x,o.y,o.s,0,Math.PI*2);x.fill()}x.restore()}};
const tick=()=>{draw(true);raf=requestAnimationFrame(tick)};new ResizeObserver(()=>{resize();if(reduce)draw(false)}).observe(c);if(e==="Snow")addEventListener("pointermove",a=>{wind=(a.clientX/Math.max(1,innerWidth)-.5)*1.4},{passive:true});resize();reduce?draw(false):tick();document.addEventListener("visibilitychange",()=>{cancelAnimationFrame(raf);if(!reduce&&!document.hidden)tick()})})();
</script>"""

PUBLIC_SAKURA_EFFECT = """<style>
.misa-sakura-petal{pointer-events:none;position:absolute;top:0}
@keyframes misa-sakura-fall{0%{opacity:.9;top:0}100%{opacity:.2;top:100%}}
@keyframes misa-sakura-blow-soft-left{0%{margin-left:0}100%{margin-left:-50%}}
@keyframes misa-sakura-blow-medium-left{0%{margin-left:0}100%{margin-left:-100%}}
@keyframes misa-sakura-blow-soft-right{0%{margin-left:0}100%{margin-left:50%}}
@keyframes misa-sakura-blow-medium-right{0%{margin-left:0}100%{margin-left:100%}}
@keyframes misa-sakura-sway-0{0%{transform:rotate(-5deg)}40%{transform:rotate(28deg)}100%{transform:rotate(3deg)}}
@keyframes misa-sakura-sway-1{0%{transform:rotate(10deg)}40%{transform:rotate(43deg)}100%{transform:rotate(15deg)}}
@keyframes misa-sakura-sway-2{0%{transform:rotate(15deg)}40%{transform:rotate(56deg)}100%{transform:rotate(22deg)}}
@keyframes misa-sakura-sway-3{0%{transform:rotate(25deg)}40%{transform:rotate(74deg)}100%{transform:rotate(37deg)}}
@keyframes misa-sakura-sway-4{0%{transform:rotate(40deg)}40%{transform:rotate(68deg)}100%{transform:rotate(25deg)}}
@keyframes misa-sakura-sway-5{0%{transform:rotate(50deg)}40%{transform:rotate(78deg)}100%{transform:rotate(40deg)}}
@keyframes misa-sakura-sway-6{0%{transform:rotate(65deg)}40%{transform:rotate(92deg)}100%{transform:rotate(58deg)}}
@keyframes misa-sakura-sway-7{0%{transform:rotate(72deg)}40%{transform:rotate(118deg)}100%{transform:rotate(68deg)}}
@keyframes misa-sakura-sway-8{0%{transform:rotate(94deg)}40%{transform:rotate(136deg)}100%{transform:rotate(82deg)}}
</style><script>
/* Adapted from Sakura.js, copyright (c) 2019 Jeroen Hammann, MIT License. */
(()=>{const l=document.getElementById("sakura-effect");if(!l||matchMedia("(prefers-reduced-motion:reduce)").matches)return;
const ri=(a,b)=>Math.floor(Math.random()*(b-a+1))+a,bl=["soft-left","medium-left","soft-right","medium-right"],sw=Array.from({length:9},(_,i)=>"sway-"+i);
const create=()=>{setTimeout(()=>requestAnimationFrame(create),300);const ft=innerHeight*.007+Math.round(Math.random()*5),b=bl[ri(0,bl.length-1)],s=sw[ri(0,sw.length-1)],h=ri(10,14),w=h-Math.floor(ri(0,10)/3),p=document.createElement("span");
p.className="misa-sakura-petal";p.style.animation="misa-sakura-fall "+ft+"s linear 0s 1, misa-sakura-blow-"+b+" "+(Math.max(ft,30)-20+ri(0,20))+"s linear 0s infinite, misa-sakura-"+s+" "+ri(2,4)+"s linear 0s infinite";
p.style.background=l.dataset.color?"linear-gradient(120deg,rgba("+l.dataset.color+",.9),rgba("+l.dataset.color+",.9))":"linear-gradient(120deg,rgba(255,183,197,.9),rgba(255,197,208,.9))";p.style.borderRadius=ri(14,14+Math.floor(Math.random()*10))+"px "+ri(1,Math.max(1,Math.floor(w/4)))+"px";p.style.height=h+"px";p.style.left=Math.random()*l.clientWidth-100+"px";p.style.marginTop=-(Math.floor(Math.random()*20)+15)+"px";p.style.width=w+"px";p.addEventListener("animationend",()=>p.remove(),{once:true});l.appendChild(p)};requestAnimationFrame(create)})();
</script>"""

def render_public_profile(config: dict, request: Request | None = None, widgets: list | None = None, default_fonts: list[dict] | None = None, feature_flags: dict[str, bool] | None = None) -> str:
    incoming = config if isinstance(config, dict) else {}
    discord_live = incoming.get("discord") if isinstance(incoming.get("discord"), dict) else {}
    rank = incoming.get("rank") if isinstance(incoming.get("rank"), dict) else None
    config = sanitize_profile_config(incoming)
    if discord_live:
        config["discord"] = discord_live
    if rank:
        config["rank"] = rank
    profile = config.get("profile") or {}
    settings = config.get("settings") or {}
    premium = settings.get("premium") or {}
    assets = config.get("assets") or {}
    username_raw = str(profile.get("username") or "user")
    username = escape(username_raw)
    display_name = escape(str(profile.get("displayName") or username))
    share = share_copy(profile, settings, username_raw)
    page_title = escape(share["title"])
    share_description = escape(share["description"])
    public_origin = public_origin_for(request)
    page_url = escape(f"{public_origin}/{username_raw}", quote=True)
    og_image_url = escape(f"{public_origin}/api/v1/profile/{username_raw}/og.jpg?v={_share_version(config)}", quote=True)
    favicon_url = escape(f"{public_origin}/api/v1/profile/{username_raw}/assets/favicon", quote=True)
    asset_src = lambda kind: f"/api/v1/profile/{escape(username_raw, quote=True)}/assets/{kind}"
    raw_description = str(profile.get("description") or "")
    description = escape(raw_description)
    bio_lines = premium.get("typewriterTexts") or [line.strip() for line in raw_description.splitlines() if line.strip()][:8]
    location = escape(str(profile.get("location") or ""))
    accent = css_hex_color(settings.get("accentColor"), "#9b87f5")
    username_color = css_hex_color(settings.get("usernameColor"), "#ffffff")
    username_effect_color = css_hex_color(settings.get("usernameEffectColor"), accent)
    text_color = css_hex_color(settings.get("textColor"), "#ffffff")
    background = css_hex_color(settings.get("backgroundColor"), "#08080d")
    icon_color = css_hex_color(settings.get("iconColor"), DEFAULT_ICON_COLOR)
    profile_opacity = _clamp(settings.get("profileOpacity"), 10, 0, 80) / 100
    background_opacity = _clamp(settings.get("backgroundOpacity"), 88, 20, 100) / 100
    profile_blur = _clamp(settings.get("profileBlur"), 24, 0, 40)
    profile_radius = _clamp(settings.get("profileRadius"), 24, 0, 80)
    profile_frame_opacity = _clamp(settings.get("profileFrameOpacity"), 100, 0, 100) / 100
    username_effect = settings.get("usernameEffect") if settings.get("usernameEffect") in USERNAME_EFFECTS else "Glow"
    layout = settings.get("layout") if settings.get("layout") in {"Default", "Modern", "Simplistic", "Sleek", "Portfolio"} else "Modern"
    avatar_shape = settings.get("avatarShape") if settings.get("avatarShape") in {"circle", "rounded", "square"} else "circle"
    banner_shape = settings.get("bannerShape") if settings.get("bannerShape") in {"rounded", "square", "pill"} else "rounded"
    button_style = settings.get("buttonStyle") if settings.get("buttonStyle") in {"glass", "solid", "outline"} else "glass"
    profile_font = settings.get("profileFont") if settings.get("profileFont") in PROFILE_FONTS else "Inter"
    profile_font_scope = "all" if settings.get("profileFontScope") == "all" else "name"
    font_size = _clamp(settings.get("fontSize"), 16, 12, 22)
    letter_spacing = _clamp(settings.get("letterSpacing"), 0, -2, 8)
    bio_typewriter = bool(settings.get("bioTypewriter")) and bool(bio_lines)
    tab_title_on = 1 if settings.get("tabTitleAnimate") else 0
    bio_type_ms = _clamp(settings.get("bioTypeMs"), 55, 20, 160)
    bio_delete_ms = _clamp(settings.get("bioDeleteMs"), 35, 20, 160)
    bio_pause_ms = _clamp(settings.get("bioPauseMs"), 1200, 400, 4000)
    card_align = settings.get("cardAlign") if settings.get("cardAlign") in {"left", "center", "right"} else "center"
    show_frame = bool(settings.get("showProfileFrame", True))
    frame_visible = show_frame and profile_frame_opacity > 0
    show_avatar = bool(settings.get("showAvatar", True))
    show_avatar_border = bool(settings.get("showAvatarBorder", True))
    show_display_name = bool(settings.get("showDisplayName", True))
    show_username = bool(settings.get("showUsername", True))
    border_color = css_hex_color(settings.get("borderColor"), "#ffffff")
    border_width = _clamp(settings.get("borderWidth"), 1, 0, 8) if premium.get("borderEnabled", True) else 0
    widget_swap = bool(settings.get("widgetColorSwap"))
    card_tilt = 1 if settings.get("cardTilt") else 0
    page_enter = settings.get("pageEnter") if settings.get("pageEnter") in PAGE_ENTERS else "Fade"
    click_sound_on = 1 if settings.get("clickSound") else 0
    has_click = has_public_asset(assets, "clickSound", "audio")
    entry_on = bool(settings.get("entryScreen"))
    entry_text = escape(str(settings.get("entryText") or "Click anywhere to enter"))
    if entry_text == "click to enter...":
        entry_text = "Click anywhere to enter"
    entry_subtitle = escape(premium.get("entrySubtitle") or "")
    entry_icon = f'<img src="{asset_src("entryIcon")}" alt="" class="profile-entry-icon">' if has_public_asset(assets, "entryIcon", "image") else ""
    runtime_options = json.dumps({"video": str(assets.get("audioSource") or ("tracks" if assets.get("tracks") else "standalone" if (assets.get("audio") or {}).get("url") else "video")) == "video", "background": settings.get("backgroundColor", "#08080d"), "image": asset_src("background") if (assets.get("background") or {}).get("url") else None, "volume": _clamp(assets.get("volume"), 65, 0, 100) / 100}).replace("<", "\\u003c")
    volume_runtime = '<script type="module">import {mountVolume} from "/dashboard/profile-volume.mjs";mountVolume(document.body,' + runtime_options + ');</script>' if assets.get("tracks") or (assets.get("audio") or {}).get("url") or ((assets.get("backgroundVideo") or {}).get("url") and assets.get("audioEnabled", True)) else ""
    cursor_module = {"Cursor Cat": "cat", "Snowflakes": "snowflakes", "Ghost Cursor": "ghost", "Following Dot": "dot", "Bubbles": "bubbles"}.get(premium.get("cursorEffect"))
    cursor_runtime = '<script type="module">if(matchMedia("(pointer:fine)").matches&&!matchMedia("(prefers-reduced-motion:reduce)").matches){const {mount}=await import("/dashboard/premium-cursors/' + cursor_module + '.mjs");mount(document.body,' + json.dumps(premium.get("cursorColor", "#ffffff")) + ');}</script>' if cursor_module else ""
    avatar_radius = {"square": "12px", "rounded": "22px"}.get(avatar_shape, "50%")
    banner_radius = {"square": "0", "pill": "999px"}.get(banner_shape, "18px")
    content_align = settings.get("socialAlign") if settings.get("socialAlign") in {"left", "center", "right"} else "center"
    managed_font = next((item for item in (default_fonts or []) if isinstance(item, dict) and item.get("id") == profile_font), None)
    managed_font_url = str(managed_font.get("url") or "") if managed_font else ""
    font_stack = "MisaDefaultFont,Inter,system-ui,sans-serif" if managed_font_url.startswith("data:") else "Inter,system-ui,sans-serif"
    has_font = has_public_asset(assets, "customFont", "font")
    if has_font:
        font_stack = f"MisaProfile,{font_stack}"
    page_font_stack = font_stack if profile_font_scope == "all" else "Inter,system-ui,sans-serif"
    page_place = {"left": "flex-start", "right": "flex-end"}.get(card_align, "center")
    has_banner = has_public_asset(assets, "banner", "image")
    username_glow = bool(settings.get("usernameGlow")) or username_effect == "Glow"
    name_class = "name"
    if username_effect == "Gradient":
        name_class += " name-gradient"
    elif username_effect == "Shimmer":
        name_class += " name-shimmer"
    elif username_effect == "Rainbow":
        name_class += " name-rainbow"
    elif username_effect == "Fuzzy":
        name_class += " name-fuzzy"
    elif username_effect == "Sparkle":
        name_class += " name-sparkle"
    elif username_effect == "Glitch":
        name_class += " name-glitch"
    elif username_effect == "Pulse":
        name_class += " name-pulse"



    elif username_effect == "Wave":
        name_class += " name-wave"
    elif username_effect == "Shadow":
        name_class += " name-shadow"
    name_style = f"font-size:var(--profile-name-size,{font_size + 8}px);letter-spacing:{letter_spacing}px;color:{username_color};"
    name_style += f"font-family:{font_stack};"
    if username_effect in {"Gradient", "Shimmer"}:
        name_style += f"background:linear-gradient(90deg,{username_color},{username_effect_color},{username_color});-webkit-background-clip:text;background-clip:text;color:transparent;"


    if username_glow:
        name_style += f"text-shadow:0 0 24px {username_effect_color}aa;"
    else:
        name_style += "text-shadow:none;"
    has_avatar = has_public_asset(assets, "avatar", "image")
    has_background = has_public_asset(assets, "background", "image")
    has_video = has_public_asset(assets, "backgroundVideo", "video")
    has_effect_video = has_public_asset(assets, "backgroundEffectVideo", "video")
    background_effect = str(settings.get("backgroundEffect") or "None")
    has_cursor = has_public_asset(assets, "cursor", "image")
    audio_source = str(assets.get("audioSource") or "").strip().lower()
    if audio_source not in {"video", "standalone", "tracks"}:
        audio_source = "tracks" if assets.get("tracks") else "standalone" if (assets.get("audio") or {}).get("url") else "video"
    audio_enabled = audio_source in {"standalone", "tracks"} or bool(assets.get("audioEnabled", True)) and audio_source == "video"
    volume = _clamp(assets.get("volume"), 65, 0, 100)
    volume_ratio = volume / 100
    audio_title = escape(str(assets.get("audioTitle") or "").strip() or str((assets.get("audio") or {}).get("name") or "").rsplit(".", 1)[0] or "Profile audio")
    discord = config.get("discord") if isinstance(config.get("discord"), dict) else {}
    discord_avatar = safe_discord_img(discord.get("avatar"))
    discord_deco = safe_discord_img(discord.get("decoration"))
    guild = discord.get("guildTag") if isinstance(discord.get("guildTag"), dict) else {}
    guild_badge = safe_discord_img(guild.get("badge"))
    guild_tag_text = escape(str(guild.get("tag") or "")[:4])
    discord_status = str(discord.get("status") or "").strip().lower()
    if discord_status not in {"online", "idle", "dnd", "offline"}:
        discord_status = ""
    avatar_face = (
        f'<img class="avatar" src="{discord_avatar or asset_src("avatar")}" alt="{display_name}">'
        if discord_avatar or has_avatar
        else f'<div class="avatar avatar-placeholder">{escape((str(profile.get("displayName") or username)[:1]) or "*")}</div>'
    )
    deco_tag = f'<img class="avatar-deco" src="{discord_deco}" alt="" onerror="this.remove()">' if discord_deco else ""
    status_tag = (
        f'<span class="status-dot status-{discord_status}" data-discord-status="{discord_status}" aria-label="Discord {discord_status}">{DISCORD_STATUS_ICON_SVG}</span>'
        if discord_status
        else ""
    )
    avatar_border_class = "" if show_avatar_border else " no-border"
    avatar_tag = f'<div class="avatar-ring{avatar_border_class}"><div class="avatar-inner{avatar_border_class}">{avatar_face}</div>{deco_tag}{status_tag}</div>' if show_avatar else ""
    guild_img = f'<img src="{guild_badge}" alt="" onerror="this.remove()">' if guild_badge else ""
    guild_tag = f'<span class="guild-tag">{guild_img}{guild_tag_text}</span>' if guild_tag_text else ""
    video_muted = " muted"
    video_tag = (
        f'<video class="bg-video" autoplay{video_muted} loop playsinline src="{asset_src("backgroundVideo")}"></video>'
        if has_video
        else ""
    )
    effect_video_tag = (
        f'<video class="bg-effect" autoplay muted loop playsinline src="{asset_src("backgroundEffectVideo")}"></video>'
        if has_effect_video
        else ""
    )
    effect_color = (premium.get("effectColors") or {}).get(background_effect, "")
    effect_rgb = ",".join(str(int(effect_color[i:i+2], 16)) for i in (1,3,5)) if effect_color else ""
    sakura_effect_tag = f'<div id="sakura-effect" class="bg-effect" data-color="{effect_rgb}" aria-hidden="true"></div>' if background_effect == "Sakura" else ""
    rain_effect_tag = '<iframe class="bg-effect codrops-rain-effect" src="/dashboard/vendor/rain-effect/profile.html#slide-2" title="Codrops rain effect" aria-hidden="true" tabindex="-1"></iframe>' if background_effect == "Rain" else ""
    effect_canvas_tag = f'<canvas id="bg-particles" class="bg-effect" data-color="{effect_rgb}" data-effect="{escape(background_effect, quote=True)}" aria-hidden="true"></canvas>' if background_effect not in {"None", "Sakura", "Rain"} else ""
    playlist = public_playlist(username_raw, assets) if audio_source == "tracks" else []
    if audio_source == "standalone" and asset_src("audio"):
        playlist = [{
            "id": "standalone",
            "title": audio_title,
            "audio": asset_src("audio"),
            "artwork": asset_src("audioArtwork") or (asset_src("avatar") if has_avatar else ""),
        }]
    first = playlist[0] if playlist else None
    art_src = (first or {}).get("artwork") or (asset_src("avatar") if has_avatar else "")
    art_tag = f'<img id="audio-art" class="player-art" src="{escape(art_src, quote=True)}" alt="" width="56" height="56">' if art_src else '<img id="audio-art" class="player-art player-art-empty" alt="" width="56" height="56">'
    audio_tag = '<audio id="profile-audio" preload="none"></audio>' if playlist else ""
    playlist_data = (
        f'<script type="application/json" id="playlist-data">{json.dumps(playlist, separators=(",", ":")).replace("<", "\\u003c")}</script>'
        if playlist
        else ""
    )
    audio_controls = (
        f'<div class="player" id="profile-player">'
        f'<div class="player-layout">{art_tag}<div class="player-meta">'
        f'<strong id="audio-title">{escape((first or {}).get("title") or audio_title)}</strong>'
        f'<div class="player-progress"><span id="audio-now">0:00</span>'
        f'<input id="audio-seek" type="range" min="0" max="1" value="0" aria-label="Seek">'
        f'<span id="audio-dur">0:00</span></div></div>'
        f'<div class="player-controls">'
        f'<button type="button" id="audio-prev" class="audio-btn" aria-label="Previous track">{AUDIO_ICON_PREVIOUS}</button>'
        f'<button type="button" id="audio-play" class="audio-btn play" data-playing="0" aria-label="Play" aria-pressed="false">{AUDIO_ICON_PLAY}{AUDIO_ICON_PAUSE}</button>'
        f'<button type="button" id="audio-next" class="audio-btn" aria-label="Next track">{AUDIO_ICON_NEXT}</button>'
        f'</div></div>'
        f"</div>"
        if playlist
        else ""
    )
    if has_video and audio_source == "video" and audio_enabled:
        audio_controls = f'<div class="player"><div class="player-layout"><span class="player-meta">Background video</span><button id="video-audio-toggle" type="button" class="audio-btn" aria-pressed="false" style="width:auto;padding:8px">Enable audio</button><input id="video-volume" type="range" min="0" max="100" value="{round(volume_ratio * 100)}" aria-label="Video volume" style="min-width:0;max-width:100%"></div></div>'
    presence_pfp = safe_discord_img(discord.get("accountAvatar") or discord.get("avatar"))
    presence_face = (
        f'<img class="discord-presence-image" src="{presence_pfp}" alt="" width="44" height="44">'
        if presence_pfp
        else f'<div class="discord-presence-fallback">{escape((str(profile.get("displayName") or username)[:1]) or "*")}</div>'
    )
    presence_status = (
        f'<span class="status-dot status-{discord_status}" data-discord-status="{discord_status}" aria-label="Discord {discord_status}">{DISCORD_STATUS_ICON_SVG}</span>'
        if discord_status
        else ""
    )
    discord_handle = escape(str(discord.get("globalName") or discord.get("username") or "").strip()[:32])
    status_label = {"online": "Online", "idle": "Idle", "dnd": "Do Not Disturb", "offline": "Offline"}.get(discord_status, "")
    presence_name = f'<p class="discord-presence-name">{discord_handle}</p>' if discord_handle else ""
    presence_label = f'<p class="discord-presence-status" data-discord-status-label>{status_label}</p>' if status_label else ""
    discord_tile = (
        f'<div class="discord-presence">'
        f'<div class="discord-presence-body"><div class="discord-presence-avatar">{presence_face}{presence_status}</div>{presence_name}{presence_label}</div></div>'
        if settings.get("showDiscordStatus", True) and (presence_pfp or discord_status)
        else ""
    )

    wash_style = (
        f"background-image:radial-gradient(circle at 19% 10%,{accent}4d,transparent 28%),"
        f"radial-gradient(circle at 80% 75%,{accent}26,transparent 32%),"
        f"linear-gradient(135deg,{background},{background} 48%,#07070a);"
    )
    background_tag = (
        f'<img class="bg-image" src="{asset_src("background")}" alt="">'
        if has_background
        else f'<div class="bg-wash" style="{wash_style}"></div>'
    )
    cursor_attr = f' data-cursor="{asset_src("cursor")}"' if has_cursor else ""
    body_classes = [cls for cls in ("has-cursor" if has_cursor else "", "widget-swap" if widget_swap else "", f"align-{card_align}", f"content-{content_align}", f"layout-{layout.lower()}") if cls]
    body_class = f' class="{" ".join(body_classes)}"' if body_classes else ""
    cursor_css = f'html{{--cursor:url("{asset_src("cursor")}") 16 16, auto}}' if has_cursor else ""
    card_opacity = (min(profile_opacity + 0.08, 0.80) if layout == "Simplistic" else profile_opacity) * profile_frame_opacity
    card_blur = max(profile_blur - 10, 0) if layout == "Simplistic" else profile_blur
    use_gradient = bool(settings.get("profileGradient") is not False) and layout != "Simplistic"
    card_background = (
        f"linear-gradient(145deg,{_color_with_alpha(accent, 0.07 * profile_frame_opacity)},transparent 40%),rgba(8,8,13,{card_opacity})"
        if use_gradient
        else f"rgba(8,8,13,{card_opacity})"
    )
    border_css = _color_with_alpha(border_color, profile_frame_opacity * premium.get("borderOpacity", 100) / 100)
    card_shadow = (
        f"0 12px 40px rgba(0,0,0,{0.22 * profile_frame_opacity:.3f})"
        if layout == "Simplistic"
        else f"0 25px 90px rgba(0,0,0,{0.36 * profile_frame_opacity:.3f}),0 0 70px {_color_with_alpha(accent, 0.09 * profile_frame_opacity)}"
    )
    card_padding = "0" if layout == "Sleek" else ("24px 28px" if layout == "Simplistic" else "36px 28px")
    links, justify = _public_social_markup(config, icon_color)
    location_tag = (
        f'<p class="location"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg>{location}</p>'
        if location
        else ""
    )
    if bio_typewriter:
        description_tag = '<p class="description" id="profile-bio"></p>'
    elif raw_description.strip():
        description_tag = f'<p class="description">{"<br>".join(escape(line) for line in raw_description.splitlines())}</p>'
    else:
        description_tag = ""
    bio_data = (
        f'<script type="application/json" id="bio-lines">{json.dumps(bio_lines, separators=(",", ":")).replace("<", "\\u003c")}</script>'
        if bio_typewriter
        else ""
    )
    title_data = (
        f'<script type="application/json" id="page-title-data">{json.dumps(share["title"], separators=(",", ":")).replace("<", "\\u003c")}</script>'
        if tab_title_on
        else ""
    )
    font_face = f'@font-face{{font-family:MisaProfile;src:url("{asset_src("customFont")}");font-display:swap}}' if has_font else ""
    if managed_font_url.startswith("data:"):
        font_face += f'@font-face{{font-family:MisaDefaultFont;src:url("{managed_font_url}");font-display:swap}}'
    badges_tag = _public_badges(config, settings)
    views = _clamp((config.get("profile") or {}).get("views"), 0, 0, 1_000_000_000)
    views_tag = (
        f'<span class="views"><span class="eye" aria-hidden="true"></span>{views:,} profile view{"" if views == 1 else "s"}</span>'
        if settings.get("showViews")
        else ""
    )
    joined = _join_label(profile.get("joinedAt"))
    join_tag = f'<span class="views">{joined}</span>' if settings.get("showJoinDate") and joined else ""
    meta_tag = f'<div class="meta"{" hidden" if entry_on else ""}>{views_tag}{join_tag}</div>' if views_tag or join_tag else ""
    banner_tag = (
        f'<div class="banner"><img src="{asset_src("banner")}" alt=""></div>'
        if has_banner
        else ('<div class="banner banner-fallback"></div>' if layout == "Sleek" else "")
    )
    verified = (
        '<span class="verified" title="Verified"><svg viewBox="0 0 24 24" width="19" height="19" fill="currentColor" aria-hidden="true"><path d="M12 2 9.2 4.1 5.7 4.6 4.6 8 2.2 10.6 3.5 14l.1 3.6 3.3 1.4L9.2 22 12 20.7 14.8 22l2.3-2.9 3.3-1.4.1-3.6L21.8 10.6 19.4 8 18.3 4.6 14.8 4.1 12 2Zm-1.2 12.7-2.8-2.8 1.2-1.2 1.6 1.6 3.8-3.8 1.2 1.2-5 5Z"/></svg></span>'
        if any(isinstance(item, dict) and item.get("id") == "verified" and item.get("owned") for item in config.get("badges") or [])
        else ""
    )
    display_name_tag = f'<h1 id="display-name" class="{name_class}" style="{name_style}">{display_name}</h1>' if show_display_name else ""
    handle_tag = f'<p class="handle">@{username}</p>' if show_username else ""
    identity = f'<div class="profile-identity"><div class="name-row">{display_name_tag}{guild_tag}{verified}{badges_tag}</div>{handle_tag}{description_tag}{location_tag}</div>'
    discord_element = f'<div class="profile-media-slot"><div class="profile-element profile-element-discord" data-layout-element="discord" style="{element_style(settings, "discord")}">{discord_tile}</div></div>' if discord_tile else ""
    widget_markup = _public_widgets_markup([w for w in (widgets or []) if w.get("id") in {item.get("id") for item in config.get("widgets", [])}], settings)
    # Living-profile features (guestbook, AMA, tally, moon, ...): only those switched on by
    # both the owner and the admin panel get a container and a client module.
    features_container, features_assets = features_markup(public_features_payload(config, feature_flags))
    # Keep a single widget resolver / polling target; CSS places its cards beside presence.
    modules = f'<div class="profile-media-row" data-profile-media-row>{discord_element}{widget_markup}</div><div class="socials">{links}</div>{_public_sections_markup(config, username_raw)}{features_container}{meta_tag}'
    if layout == "Sleek":
        card_inner = f'<div class="sleek-hero">{banner_tag}{avatar_tag}</div><div class="sleek-body">{identity}{modules}</div>'
    else:
        card_inner = f'{banner_tag if layout == "Modern" else ""}<div class="card-body"><div class="profile-header" data-identity-align="{content_align}">{avatar_tag}{identity}</div>{modules}</div>'
    if layout == "Portfolio":
        hero_meta = f'<div class="portfolio-metadata">{views_tag}{location_tag}</div>' if views_tag or location_tag else ""
        sections = _public_sections_markup(config, username_raw)
        scroll = '<button type="button" class="portfolio-scroll" data-portfolio-next>Scroll for more<span aria-hidden="true">&#8595;</span></button>' if sections else ""
        hero = str(premium.get("hero") or "Classic").lower()
        identity_align = "center" if hero == "centered" else content_align
        first = f'<div class="profile-element profile-element-frame" data-layout-element="frame" style="{element_style(settings, "frame")}"><div class="card profile-glass portfolio-first-frame" style="background:{card_background if frame_visible else "transparent"};backdrop-filter:blur({card_blur if frame_visible else 0}px);box-shadow:{card_shadow if frame_visible else "none"}"><div class="profile-header" data-identity-align="{identity_align}">{avatar_tag}{identity}</div><div class="profile-media-row" data-profile-media-row>{discord_element}{widget_markup}</div><div class="socials">{links}</div>{features_container}{meta_tag}</div></div>'
        card_inner = f'<div class="portfolio-profile" data-hero="{hero}"><section class="portfolio-hero" data-portfolio-section="hero" aria-label="Profile">{first}<div class="profile-mobile-audio" data-profile-mobile-audio></div>{scroll}</section>{sections}</div>'
    media_dock = f'<div class="profile-media-slot profile-audio-slot"><div class="profile-element profile-element-audio" data-layout-element="audio" style="{element_style(settings, "audio")}"><div class="media-dock"{" hidden" if entry_on else ""}>{audio_controls}</div></div></div>' if audio_controls else ""
    if layout == "Portfolio":
        composition_markup = f'<div class="profile-composition"><main data-profile-variant="Portfolio" id="profile-card"{" hidden" if entry_on else ""}>{card_inner}</main><div class="profile-mobile-audio" data-profile-mobile-audio>{media_dock}</div></div>{hero_meta}'
    else:
        composition_markup = f'<div class="profile-composition"><div class="profile-element profile-element-frame" data-layout-element="frame" style="{element_style(settings, "frame")}"><div class="card-stage"><main data-profile-variant="{layout}" class="card profile-glass{' no-frame' if not frame_visible else ""}" id="profile-card"{" hidden" if entry_on else ""}>{card_inner}</main></div></div><div class="profile-mobile-audio" data-profile-mobile-audio>{media_dock}</div></div>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>{page_title}</title>
<meta name="description" content="{share_description}">
<meta name="theme-color" content="{accent}">
<link rel="canonical" href="{page_url}">
<link rel="icon" href="{favicon_url}">
<link rel="apple-touch-icon" href="{favicon_url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="misa.lol">
<meta property="og:title" content="{page_title}">
<meta property="og:description" content="{share_description}">
<meta property="og:url" content="{page_url}">
<meta property="og:image" content="{og_image_url}">
<meta property="og:image:type" content="image/jpeg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{page_title}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{page_title}">
<meta name="twitter:description" content="{share_description}">
<meta name="twitter:image" content="{og_image_url}">
<style>
{font_face}
*{{box-sizing:border-box}}html,body{{margin:0;min-height:100vh;min-height:100dvh;background:{background};color:{text_color};font-family:{page_font_stack};font-size:{font_size}px;scrollbar-width:none;-ms-overflow-style:none}}
html::-webkit-scrollbar,body::-webkit-scrollbar,.lyrics::-webkit-scrollbar{{display:none}}
{cursor_css}
.has-cursor,.has-cursor *{{cursor:var(--cursor, auto)}}
body{{position:relative;display:flex;align-items:center;justify-content:{page_place};padding:32px 16px;overflow:auto{";perspective:900px" if card_tilt else ""}}}
#profile-audio{{position:absolute;width:0;height:0;opacity:0;pointer-events:none}}
.bg-wash,.bg-image,.bg-video,.bg-effect,.backdrop{{position:fixed;inset:0;pointer-events:none}}
.bg-wash,.bg-image,.bg-video{{z-index:0}}
.bg-image,.bg-video,.bg-effect{{width:100%;height:100%;object-fit:cover}}
.backdrop{{z-index:1}}
.bg-effect{{z-index:2;background:transparent}}
.codrops-rain-effect{{border:0}}
.card{{position:relative;width:100%;min-height:inherit;margin:0;padding:{card_padding};border:{border_width}px {"dashed" if premium.get("borderType") == "Dashed" else "solid"} {border_css};border-radius:{profile_radius}px;background:{card_background};backdrop-filter:blur({card_blur}px);box-shadow:{card_shadow};text-align:{content_align};overflow:hidden;pointer-events:auto{";transform-style:preserve-3d" if card_tilt else ""}}}
.card.no-frame{{border-color:transparent;background:transparent;backdrop-filter:none;box-shadow:none}}
.card.no-frame::before{{display:none}}
.card-body.after-banner{{padding-top:20px}}
.layout-sleek .card{{overflow:hidden}}
.card::before{{content:"";position:absolute;inset:0 32px auto;height:1px;background:linear-gradient(90deg,transparent,{accent}aa,transparent)}}
.layout-simplistic .card::before,.layout-sleek .card::before{{display:none}}
.banner{{height:112px;overflow:hidden;border-radius:{banner_radius}}}
.layout-sleek .banner{{height:148px;border-radius:0}}
.layout-sleek .banner-fallback{{height:112px}}
.banner img,.banner-fallback{{width:100%;height:100%;object-fit:cover;display:block}}
.banner-fallback{{background:linear-gradient(135deg,{accent}55,transparent)}}
.sleek-hero{{position:relative}}
.sleek-body{{padding:48px 20px 24px}}
.avatar-ring{{position:relative;width:96px;height:96px;margin:0 auto 20px;padding:4px;border-radius:{avatar_radius};background:linear-gradient(135deg,{accent},#ffffff55,{accent}22)}}
.avatar-ring.no-border{{padding:0;background:transparent}}
.avatar-inner{{width:100%;height:100%;overflow:hidden;border-radius:{avatar_radius};border:4px solid #15151d;background:linear-gradient(135deg,#6358a3,#282442,#0d0d13)}}
.avatar-inner.no-border{{border:0;background:transparent}}
.avatar-ring .avatar{{width:100%;height:100%;object-fit:cover;border:0;border-radius:0;display:block;box-shadow:none}}
.avatar-deco{{position:absolute;left:-18%;top:-18%;width:136%;height:136%;pointer-events:none;z-index:3}}
.status-dot{{display:block;overflow:hidden;line-height:0}}
.status-dot svg{{display:block;width:100%;height:100%;max-width:100%;max-height:100%}}
.status-dot .icon-idle,.status-dot .icon-dnd,.status-dot .icon-offline{{display:none}}
.status-dot.status-idle .icon-online,.status-dot.status-dnd .icon-online,.status-dot.status-offline .icon-online{{display:none}}
.status-dot.status-idle .icon-idle,.status-dot.status-dnd .icon-dnd,.status-dot.status-offline .icon-offline{{display:block}}
.avatar-ring>.status-dot{{position:absolute;right:2px;bottom:2px;z-index:4;width:clamp(14px,22%,22px);height:clamp(14px,22%,22px);min-width:14px;min-height:14px;max-width:22px;max-height:22px;border-radius:999px}}
.layout-sleek .avatar-ring{{position:absolute;left:20px;bottom:-32px;width:72px;height:72px;margin:0;z-index:2}}
.layout-simplistic .avatar-ring{{width:80px;height:80px;margin-bottom:16px}}
.avatar-placeholder{{display:grid;place-items:center;color:#fff;font-size:28px;font-weight:600}}
.name-row{{display:flex;align-items:center;justify-content:center;gap:8px;flex-wrap:wrap}}
.content-left .name-row,.content-left .location{{justify-content:flex-start}}
.content-right .name-row,.content-right .location{{justify-content:flex-end}}
.content-center .location{{justify-content:center}}
.verified{{display:inline-flex;color:#a99bff}}
.verified svg{{display:block}}
.guild-tag{{display:inline-flex;align-items:center;gap:5px;padding:2px 6px;border-radius:6px;border:1px solid #ffffff26;background:#ffffff1a;color:#ffffffe6;font-size:11px;letter-spacing:.04em;font-weight:600}}
.guild-tag img{{width:16px;height:16px;border-radius:4px;object-fit:cover}}
h1{{margin:0;font-size:24px;font-weight:600;letter-spacing:-.04em;color:#fff}}
.name-gradient,.name-shimmer{{background:linear-gradient(90deg,#fff,#c5baff,#8d7df0);-webkit-background-clip:text;background-clip:text;color:transparent}}
.name-shimmer{{background-size:200% 100%;animation:shimmer 2.8s linear infinite}}
.name-rainbow{{background-image:linear-gradient(90deg,#ff5c7a,#ffd36a,#6dffb0,#6db7ff,#c58bff,#ff5c7a);background-size:200% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;animation:name-rainbow 2.4s linear infinite}}
.name-fuzzy{{animation:name-fuzzy 1.8s ease-in-out infinite}}
.name-sparkle{{animation:name-sparkle 1.4s ease-in-out infinite}}
.name-glitch{{animation:name-glitch .65s steps(2,end) infinite}}
.name-pulse{{animation:name-pulse 1.8s ease-in-out infinite}}


.name-wave{{animation:name-wave 1.4s ease-in-out infinite;transform-origin:center}}
.name-shadow{{animation:name-shadow 1.8s ease-in-out infinite}}
@keyframes name-rainbow{{0%{{background-position:0 50%}}100%{{background-position:200% 50%}}}}
@keyframes name-fuzzy{{0%,100%{{filter:blur(0)}}50%{{filter:blur(1.6px)}}}}
@keyframes name-sparkle{{0%,100%{{text-shadow:0 0 6px #fff8}}50%{{text-shadow:0 0 14px #fff,-10px -8px 0 #fff8,12px 4px 0 #ffe9}}}}
@keyframes name-glitch{{0%,100%{{transform:translate(0)}}20%{{transform:translate(-1px,1px)}}40%{{transform:translate(1px,-1px)}}60%{{transform:translate(-1px,0)}}80%{{transform:translate(1px,1px)}}}}
@keyframes name-pulse{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.72;transform:scale(1.035)}}}}
@keyframes name-wave{{0%,100%{{transform:skewX(0)}}50%{{transform:skewX(-5px) translateY(-2px)}}}}
@keyframes name-shadow{{0%,100%{{text-shadow:4px 4px 0 #0008}}50%{{text-shadow:8px 6px 0 #0008}}}}
.handle{{margin:4px 0 0;color:#ffffff;opacity:.35;font-size:12px}}
.description{{margin:12px 0 0;max-width:none;color:#ffffff;opacity:.65;font-size:14px;line-height:1.5}}
.location{{display:flex;align-items:center;justify-content:center;gap:6px;margin:12px 0 0;color:#ffffff;opacity:.4;font-size:12px}}
.location svg{{flex-shrink:0}}
.meta{{position:fixed;left:20px;bottom:20px;z-index:3;display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-start;gap:4px 12px;margin:0;pointer-events:none}}
.views{{display:inline-flex;align-items:center;gap:8px;margin:0;color:#ffffff;opacity:.35;font-size:12px}}
.eye{{position:relative;display:inline-flex;width:20px;height:14px;border:1px solid currentColor;border-radius:50%}}
.eye::after{{content:"";position:absolute;left:50%;top:50%;width:6px;height:6px;border-radius:50%;background:currentColor;transform:translate(-50%,-50%)}}
.badges{{display:inline-flex;flex-wrap:wrap;align-items:center;justify-content:{justify};gap:6px;margin:0}}
.badge{{display:grid;place-items:center;width:36px;height:36px;flex:0 0 36px;overflow:hidden;border-radius:11px;border:1px solid #ffffff1a;background:#ffffff12;color:inherit}}
.badge img{{display:block;width:24px;height:24px;object-fit:contain}}
.rank-badge{{display:inline-flex;width:auto;flex-basis:auto;gap:6px;padding:0 12px;border-radius:999px;font-size:11px;font-weight:600}}
.badge svg{{display:block;width:22px;height:22px}}
.rank-badge svg{{width:15px;height:15px}}
.socials{{display:flex;flex-wrap:wrap;justify-content:{justify};gap:10px;margin-top:28px;width:100%}}
.social{{display:grid;place-items:center;width:40px;height:40px;padding:0;border:1px solid #ffffff17;border-radius:12px;background:#ffffff0e;color:inherit;text-decoration:none;cursor:pointer;font:inherit}}
.social img{{width:18px;height:18px;object-fit:contain;border-radius:4px}}
.social-glyph{{display:block;width:18px;height:18px;background:currentColor;-webkit-mask:var(--glyph) center/contain no-repeat;mask:var(--glyph) center/contain no-repeat}}
.social svg{{display:block}}
.social svg:not([fill="none"]){{fill:currentColor}}
.social:hover{{border-color:{accent};background:{accent}22}}
.entry{{position:fixed;inset:0;z-index:4;display:grid;place-items:center;align-content:center;gap:14px;border:0;background:rgba(0,0,0,.6);color:#fff;cursor:pointer;font:inherit}}
.entry-play{{width:48px;height:48px;border-radius:16px;border:1px solid #ffffff29;background:#ffffff12}}
.entry small{{color:#ffffff66;font-size:12px}}
#copy-toast{{position:fixed;bottom:24px;left:50%;z-index:5;transform:translateX(-50%);padding:8px 12px;border-radius:999px;background:#111118ee;color:#fff;font-size:12px}}
#copy-toast[hidden],.card[hidden],.media-dock[hidden],.meta[hidden],.entry[hidden]{{display:none}}
.media-dock{{position:relative;z-index:4;width:100%;margin-top:24px;pointer-events:auto;container-type:inline-size}}
.discord-presence{{position:relative;display:flex;flex:0 0 42%;width:42%;min-width:0;min-height:80px;align-items:center;overflow:hidden;padding:12px;border:1px solid #ffffff1a;border-radius:18px;background:#00000040;text-align:left}}
.discord-presence-body{{display:grid;width:100%;min-width:0;grid-template-columns:44px minmax(0,1fr);grid-template-rows:auto auto;align-items:center;gap:2px 10px;overflow:hidden}}
.discord-presence-avatar{{position:relative;grid-row:1/3;width:44px;height:44px;flex:none;overflow:visible}}
.discord-presence-image,.discord-presence-fallback{{display:block;width:100%;height:100%;min-width:0;max-width:100%;overflow:hidden;border-radius:999px;object-fit:cover}}
.discord-presence-fallback{{display:grid;place-items:center;background:#ffffff14;color:#fff;font-size:14px;font-weight:600}}
.discord-presence-avatar .status-dot{{position:absolute;right:-2px;bottom:-2px;z-index:4;width:16px;height:16px;min-width:16px;min-height:16px;max-width:16px;max-height:16px;border-radius:999px}}
.discord-presence-name,.discord-presence-status{{width:100%;min-width:0;max-width:100%;margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.discord-presence-name{{color:#fff;font-size:13px;font-weight:600;line-height:1.2;text-align:left}}
.discord-presence-status{{color:#ffffff8c;font-size:10px;line-height:1.2;text-align:left}}
.player{{position:relative;z-index:5;width:100%;min-width:0;max-width:100%;margin-top:24px;padding:12px;overflow:hidden;border:1px solid #ffffff1a;border-radius:18px;background:#00000040;text-align:left;pointer-events:auto;isolation:isolate}}
.player-layout{{display:flex;min-width:0;align-items:center;gap:12px;overflow:hidden}}
.player-art{{display:block;width:clamp(48px,14vw,56px);height:clamp(48px,14vw,56px);min-width:48px;min-height:48px;max-width:56px;max-height:56px;flex:0 0 clamp(48px,14vw,56px);overflow:hidden;border-radius:12px;object-fit:cover;background:#ffffff10}}
.player-art-empty{{display:grid;place-items:center;color:#ffffff88}}
.player-meta{{min-width:0;max-width:100%;flex:1;overflow:hidden}}
.player-meta strong{{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}}
.player-progress{{display:flex;min-width:0;align-items:center;gap:8px;margin-top:8px;color:#ffffff66;font-size:10px;font-family:ui-monospace,monospace}}
.player-progress span{{display:block;flex:none;margin:0}}
#audio-seek{{width:100%;min-width:0;flex:1;accent-color:{accent};pointer-events:auto;cursor:pointer}}
.player-controls{{display:flex;flex:none;justify-content:flex-end;align-items:center;gap:2px}}
.audio-btn{{position:relative;z-index:1;display:inline-flex;width:28px;height:32px;flex:none;align-items:center;justify-content:center;overflow:hidden;border:0;border-radius:9px;background:transparent;color:#ffffff73;cursor:pointer;pointer-events:auto;-webkit-tap-highlight-color:transparent}}
.audio-btn:hover{{background:#ffffff0d;color:#fff}}
.audio-btn.play{{width:32px;height:36px;color:#ffffffcc}}
.audio-btn::before,.audio-btn::after{{display:none!important;content:none!important}}
.audio-icon{{display:block;width:16px;height:16px;flex:none;pointer-events:none}}
.audio-btn.play .audio-icon{{width:17px;height:17px}}
.audio-icon-pause,.audio-icon-volume-x{{display:none}}
#audio-play[data-playing="1"] .audio-icon-play{{display:none}}#audio-play[data-playing="1"] .audio-icon-pause{{display:block}}
#audio-mute[data-muted="1"] .audio-icon-volume{{display:none}}#audio-mute[data-muted="1"] .audio-icon-volume-x{{display:block}}
#audio-shuffle[data-on="1"]{{background:#9b87f533}}
#audio-repeat[data-mode="off"]{{opacity:.45}}
#audio-repeat[data-mode="one"]::after{{display:block!important;content:"1"!important;position:absolute;right:4px;top:2px;font-size:9px}}
.widget-swap .player{{background:{accent};color:{background};border-color:{background}33}}
.widget-swap .player-progress{{color:{background};opacity:.66}}
.widget-swap .player-art-empty{{background:{background}22;color:{background}}}
.widget-swap .audio-btn{{background:{background}22;color:{background}}}
.widget-swap .audio-btn.play,.widget-swap #audio-shuffle[data-on="1"]{{background:{background}33}}
.widget-swap #audio-seek{{accent-color:{background}}}
.widgets{{display:flex;flex-direction:column;gap:10px;margin-top:24px}}
.widget{{display:flex;width:100%;min-width:0;max-width:100%;align-items:center;gap:12px;overflow:hidden;padding:12px;border:1px solid #ffffff1a;border-radius:18px;background:#00000040;color:inherit;text-decoration:none}}
.widget-art{{display:block;width:clamp(48px,14vw,56px);height:clamp(48px,14vw,56px);min-width:48px;min-height:48px;max-width:56px;max-height:56px;flex:0 0 clamp(48px,14vw,56px);overflow:hidden;border-radius:12px;object-fit:cover;background:#ffffff10}}
.widget-art-empty{{display:grid;place-items:center;color:#ffffff66;font-size:10px;text-transform:uppercase;letter-spacing:.06em}}
.widget-meta{{min-width:0;max-width:100%;flex:1;overflow:hidden;text-align:left}}
.widget-meta strong{{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}}
.widget-meta span{{display:block;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#ffffff66;font-size:11px}}
.widget.is-error{{opacity:.85}}
.widget-swap .widget{{background:{accent};color:{background};border-color:{background}33}}
.widget-swap .widget-meta span{{color:{background};opacity:.66}}
.widget-swap .widget-art-empty{{background:{background}22;color:{background}}}
.sections{{display:flex;flex-direction:column;gap:10px;margin-top:24px}}
.section{{padding:12px;border:1px solid #ffffff1a;border-radius:18px;background:#00000040;text-align:left}}
.section h2,.section h3,.section h4{{margin:0 0 8px;font-size:13px;font-weight:600}}
.section p,.section li{{margin:0 0 8px;color:#ffffffa8;font-size:13px;line-height:1.5}}
.section ul,.section ol{{margin:0 0 8px;padding-left:18px}}
.section a,a.section{{color:inherit}}
a.section{{display:flex;text-decoration:none;transition:border-color .15s,background .15s}}
a.section:hover{{border-color:{accent}88;background:{accent}14}}
a.section:focus-visible{{outline:2px solid {accent};outline-offset:2px}}
.section-project .section-copy{{min-width:0;flex:1}}
.section-project .project-visit{{display:inline-flex;align-items:center;gap:4px;align-self:center;margin-left:auto;color:#ffffff80;font-size:12px}}
.section code{{padding:1px 5px;border-radius:6px;background:#ffffff14;font-size:12px}}
.section-project{{display:flex;gap:12px;align-items:flex-start}}
.section-cover{{width:64px;height:64px;border-radius:12px;object-fit:cover;background:#ffffff10;flex-shrink:0}}
.section-tags{{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}}
.section-tag{{padding:3px 8px;border-radius:999px;background:#ffffff14;color:#ffffffcc;font-size:10px}}
.lyrics{{max-height:160px;overflow:auto;margin-top:8px;scrollbar-width:none;-ms-overflow-style:none}}
.lyrics p{{margin:0;padding:3px 0;color:#ffffff66;font-size:13px}}
.lyrics p.is-active{{color:#fff;font-weight:600}}
.widget-swap .section{{background:{accent};color:{background};border-color:{background}33}}
.widget-swap .section p,.widget-swap .section li,.widget-swap .lyrics p{{color:{background};opacity:.7}}
.widget-swap .lyrics p.is-active{{color:{background};opacity:1}}
.widget-swap .section-tag,.widget-swap .section code{{background:{background}22;color:{background}}}
@keyframes drift{{0%,100%{{transform:translate3d(0,0,0)}}50%{{transform:translate3d(12px,-18px,0)}}}}
@keyframes shimmer{{0%{{background-position:0 50%}}100%{{background-position:100% 50%}}}}
@keyframes pulse{{0%,100%{{opacity:.42;transform:scale(1)}}50%{{opacity:.9;transform:scale(1.08)}}}}
@keyframes aurora{{0%,100%{{transform:translate3d(-6%,-3%,0) scale(1)}}50%{{transform:translate3d(7%,5%,0) scale(1.12)}}}}

@keyframes enter-fade{{from{{opacity:0}}to{{opacity:1}}}}
@keyframes enter-unfold{{from{{opacity:0;transform:scaleY(.12)}}to{{opacity:1;transform:none}}}}
@keyframes enter-pop{{from{{opacity:0;transform:scale(.86)}}to{{opacity:1;transform:none}}}}
.enter-fade{{animation:enter-fade .55s ease both}}
.enter-unfold{{transform-origin:top center;animation:enter-unfold .55s ease both}}
.enter-pop{{animation:enter-pop .45s cubic-bezier(.22,1,.36,1) both}}
@media (prefers-reduced-motion:reduce){{.enter-fade,.enter-unfold,.enter-pop{{animation:none}}.codrops-rain-effect{{display:none}}}}
</style><link rel="stylesheet" href="/dashboard/profile-layout.css?v=20260922-about-3"></head>
<body data-profile-layout data-profile-kind="{layout}" style="--misa-profile-font:{font_stack};--profile-text-size:{font_size}px;--portfolio-radius:{profile_radius}px;--portfolio-border:{border_width if frame_visible and premium.get("borderEnabled", True) else 0}px {"dashed" if premium.get("borderType") == "Dashed" else "solid"} {border_css}" data-premium-hero="{premium.get("hero", "Classic")}" data-premium-border="{premium.get("borderType", "Static")}"{body_class}{cursor_attr} data-profile-user="{username}" data-audio-enabled="{1 if audio_enabled else 0}" data-volume="{volume_ratio}" data-tilt="{card_tilt}" data-name-effect="{escape(username_effect, quote=True)}" data-tab-title="{tab_title_on}" data-bio-type-ms="{bio_type_ms}" data-bio-delete-ms="{bio_delete_ms}" data-bio-pause-ms="{bio_pause_ms}" data-page-enter="{escape(page_enter, quote=True)}" data-click-preset="{premium.get("clickPreset", "")}" data-click-sound="{click_sound_on}"{f' data-click-src="{asset_src("clickSound")}"' if has_click else ""}>
{background_tag}{video_tag}<div class="backdrop"></div>{effect_canvas_tag}{sakura_effect_tag}{rain_effect_tag}{effect_video_tag if background_effect == "None" else ""}
{f'<button type="button" id="entry" class="entry profile-entry"><span>{entry_icon}<strong>{entry_text}</strong><span class="profile-entry-subtitle">{entry_subtitle}</span></span></button>' if entry_on else ""}
{composition_markup}
{audio_tag}
{playlist_data}
{bio_data}
{title_data}
{PUBLIC_COPY_SCRIPT}
{PUBLIC_ANALYTICS_SCRIPT}
{PUBLIC_BACKGROUND_EFFECT_SCRIPT if effect_canvas_tag else ""}
{PUBLIC_SAKURA_EFFECT if sakura_effect_tag else ""}
{PUBLIC_BADGE_SCRIPT}
{PUBLIC_MEDIA_LAYOUT_SCRIPT}
{PUBLIC_WIDGET_SCRIPT}
{PUBLIC_DISCORD_STATUS_SCRIPT if status_tag else ""}
{PUBLIC_EMPTY_SCRIPT}
{PUBLIC_LYRICS_SCRIPT if any(s.get("enabled") and s.get("type") == "lyrics" for s in config.get("sections", [])) else ""}
{volume_runtime}{cursor_runtime}
{chr(60) + 'script type="module" src="/dashboard/portfolio-navigation.mjs?v=20260922-scroll"></script>' if layout == "Portfolio" else ""}
<script type="module" src="/dashboard/profile-widgets.mjs"></script>
{features_assets}
</body></html>"""


def _empty_content_markup(title: str | None = None, subtitle: str | None = None) -> str:
    heading = f"<h3>{escape(str(title))}</h3>" if title else ""
    description = f"<p>{escape(str(subtitle))}</p>" if subtitle else ""
    copy = f'<div class="profile-empty-copy">{heading}{description}</div>' if heading or description else ""
    return f'<div class="profile-empty" aria-label="No content configured"><div data-empty-face aria-hidden="true"></div>{copy}</div>'


def _public_sections_markup(config: dict, username: str) -> str:
    cards: list[str] = []
    portfolio = (config.get("settings") or {}).get("layout") == "Portfolio"
    rendered: list[tuple[dict, str]] = []
    def append(markup: str) -> None:
        rendered.append((item, markup))
        cards.append(markup)
    for item in visible_sections(config.get("sections") or []):
        kind = str(item.get("type") or "")
        title = escape(str(item.get("title") or "")[:80])
        heading = f"<h2>{title}</h2>" if title else ""
        if kind == "integration" and not item.get("body") and not any((item.get(side) or {}).get("enabled") for side in ("leftCard", "rightCard")):
            append(heading + _empty_content_markup(subtitle=item.get("subtitle")))
            continue
        if kind == "project" and not project_configured(item):
            append(_empty_content_markup(item.get("title"), item.get("subtitle")))
            continue
        if kind in {"about", "text", "integration"}:
            body = render_safe_markdown(str(item.get("body") or ""))
            if not body and not title and not item.get("subtitle") and not item.get("tags") and not any((item.get(side) or {}).get("enabled") for side in ("leftCard", "rightCard")):
                continue
            body = f'<div class="profile-rich-text profile-introduction-card">{body}</div>' if body else ""
            subtitle = escape(str(item.get("subtitle") or ""))
            subtitle_markup = f"<p>{subtitle}</p>" if subtitle else ""
            tags = "".join(f'<span class="section-tag">{escape(str(tag))}</span>' for tag in item.get("tags") or [])
            side_cards = []
            enabled_cards = [(side, suffix) for side, suffix in (("leftCard", "l"), ("rightCard", "r")) if (item.get(side) or {}).get("enabled")]
            configured_cards = [(side, suffix) for side, suffix in enabled_cards if item[side].get("type") == "presence" or str(item[side].get("value") or "").strip()]
            for side, suffix in configured_cards or enabled_cards[:1]:
                card = item.get(side)
                if not card or not card.get("enabled"):
                    continue
                if card.get("type") == "presence":
                    presence = config.get("discord") or {}
                    name = escape(str(presence.get("username") or "Discord"))
                    status = escape(str(presence.get("status") or "Unavailable"))
                    side_cards.append(f'<div class="widget"><div class="widget-meta"><strong>{name}</strong><span>{status}</span></div></div>')
                elif not str(card.get("value") or "").strip():
                    side_cards.append(_empty_content_markup())
                else:
                    side_cards.append(_public_widgets_markup([{**card, "id": str(item["id"])[:38] + "-" + suffix, "status": "empty", "title": card["type"], "subtitle": "Loading…"}]))
            append(f'<section class="section profile-introduction">{heading}{subtitle_markup}{body}<div class="profile-skills" aria-label="Skills">{tags}</div><div class="profile-section-cards">{"".join(side_cards)}</div></section>')
            continue
        if kind == "skills":
            tags = "".join(f'<span class="section-tag">{escape(str(tag)[:24])}</span>' for tag in item.get("tags") or [])
            if not tags:
                continue
            append(f'<div class="profile-skills" aria-label="Skills">{tags}</div>')
            continue
        if kind == "project":
            href = public_social_href(str(item.get("href") or ""), "Custom URL")
            cover = ""
            if (item.get("cover") or {}).get("url"):
                src = escape(f"/api/v1/profile/{username}/sections/{item.get('id')}/cover", quote=True)
                cover = f'<img class="section-cover" src="{src}" alt="">'
            body = render_safe_markdown(str(item.get("body") or ""))
            tags = "".join(f'<span class="section-tag">{escape(str(tag)[:24])}</span>' for tag in item.get("tags") or [])
            tag_row = f'<div class="section-tags">{tags}</div>' if tags else ""
            inner = f'{cover}<div class="section-copy">{heading}{body}{tag_row}</div>'
            if href:
                append(f'<a class="section section-project profile-project" href="{escape(href, quote=True)}" target="_blank" rel="noopener noreferrer">{inner}<span class="project-visit">visit <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17 17 7M7 7h10v10" /></svg></span></a>')
            else:
                append(f'<section class="section section-project profile-project">{inner}</section>')
            continue
        if kind == "lyrics":
            body = escape(str(item.get("body") or ""), quote=True)
            tracks = (config.get("assets") or {}).get("tracks") or []
            first_track = escape(str(tracks[0].get("id") or ""), quote=True) if tracks else "track-1"
            append(f'<section data-lyrics-body="{body}" data-lyrics-track="{first_track}" aria-label="Lyrics player"></section>')

    if not cards:
        return ""
    if portfolio:
        groups: list[list[tuple[dict, str]]] = []
        for record in rendered:
            if record[0].get("type") == "project" and groups and groups[-1][0][0].get("type") == "project":
                groups[-1].append(record)
            else:
                groups.append([record])
        cards = []
        for group in groups:
            first = group[0][0]
            identity = escape(str(first.get("id") or ""), quote=True)
            title = escape("Projects" if len(group) > 1 else str(first.get("title") or ""))
            content = "".join(markup for _, markup in group)
            if first.get("type") == "project":
                content = f'<h2>{title}</h2><div class="portfolio-showcase{' portfolio-feature' if len(group) == 1 else ""}">{content}</div>'
            cards.append(f'<section class="portfolio-section" data-portfolio-section="{identity}" data-section-title="{title}"><div class="portfolio-section-content">{content}</div></section>')
    classes = "portfolio-sections" if portfolio else "sections profile-sections"
    return f'<div class="{classes}">{"".join(cards)}</div>'


def _public_widgets_markup(widgets: list | None, settings: dict | None = None) -> str:
    cards: list[str] = []
    for item in widgets or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "empty")
        title = escape(str(item.get("title") or item.get("type") or "Widget")[:80])
        subtitle = escape(str(item.get("subtitle") or "")[:80])
        image = safe_widget_url(item.get("image"))
        href = safe_widget_url(item.get("href"))
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        zone = escape(str(meta.get("timezone") or ""), quote=True) if item.get("type") == "timezone" else ""
        kind = escape(str(item.get("type") or "widget")[:10])
        art = (
            f'<img class="widget-art" src="{escape(image, quote=True)}" alt="" width="56" height="56" loading="lazy">'
            if image
            else f'<div class="widget-art widget-art-empty">{kind}</div>'
        )
        inner = f'{art}<div class="widget-meta"><strong>{title}</strong><span>{subtitle}</span></div>'
        cls = "widget" + (" is-error" if status != "ok" else "")
        extra = f' data-timezone="{zone}"' if zone else ""
        if href and status == "ok":
            cards.append(f'<a class="{cls}" href="{escape(href, quote=True)}" target="_blank" rel="noopener noreferrer"{extra}>{inner}</a>')
        else:
            cards.append(f'<div class="{cls}"{extra}>{inner}</div>')
        element = "widget:" + str(item.get("id") or "")
        cards[-1] = f'<div class="profile-media-slot"><div class="profile-element profile-element-widget" data-widget-id="{escape(str(item.get("id") or ""), quote=True)}" data-layout-element="{escape(element, quote=True)}" style="{element_style(settings or {}, element)}">{cards[-1]}</div></div>'
    if not cards:
        return ""
    return "".join(cards)


def _public_social_markup(config: dict, global_icon_color: str) -> tuple[str, str]:
    settings = config.get("settings") or {}
    button_style = settings.get("buttonStyle") if settings.get("buttonStyle") in {"glass", "solid", "outline"} else "glass"
    if settings.get("showSocials") is False:
        return "", "center"
    align = settings.get("socialAlign") if settings.get("socialAlign") in {"left", "center", "right"} else "center"
    justify = {"left": "flex-start", "right": "flex-end"}.get(align, "center")
    monochrome = bool(settings.get("monochromeIcons"))
    buttons: list[str] = []
    for social in config.get("socials") or []:
        if not social.get("enabled"):
            continue
        social_id = escape(str(social.get("id") or ""), quote=True)
        label = escape(str(social.get("label") or social.get("platform") or "Link"), quote=True)
        value = str(social.get("value") or "")
        platform = str(social.get("platform") or "Custom URL")
        href = public_social_href(value, platform)
        action = social.get("action")
        if action not in {"open", "copy"}:
            action = "copy" if social.get("displayMode") == "text" else "open"
        icon = social.get("customIcon") or {}
        icon_url = str(icon.get("url") or "")
        if is_safe_social_icon(icon_url) and monochrome:
            inner = f'<span class="social-glyph" style="--glyph:url(&quot;{escape(icon_url, quote=True)}&quot;)"></span>'
        elif is_safe_social_icon(icon_url):
            inner = f'<img src="{escape(icon_url, quote=True)}" alt="">'
        else:
            inner = social_icon_markup(platform)
        color = resolve_icon_color(platform, social.get("iconColor"), global_icon_color, monochrome)
        glow = social.get("iconGlow") if isinstance(social.get("iconGlow"), bool) else bool(settings.get("socialGlow"))
        glow_style = f"filter:drop-shadow(0 0 6px {color}) drop-shadow(0 0 16px {color});" if glow else "filter:none;"
        if button_style == "solid":
            style = f"color:#0b0b10;fill:#0b0b10;background:{color};border:0;{glow_style}"
        elif button_style == "outline":
            style = f"color:{color};fill:{color};background:transparent;border:2px solid {color};{glow_style}"
        else:
            style = f"color:{color};fill:{color};{glow_style}"
        if action == "open" and href:
            buttons.append(
                f'<a class="social" href="{escape(href, quote=True)}" target="_blank" rel="noopener noreferrer" '
                f'data-social-id="{social_id}" data-social-platform="{escape(platform, quote=True)}" data-social-action="open" aria-label="Open {label}" title="{escape(value, quote=True)}" style="{style}">{inner}</a>'
            )
        else:
            buttons.append(
                f'<button type="button" class="social" data-social-id="{social_id}" data-social-platform="{escape(platform, quote=True)}" data-social-action="copy" '
                f'data-copy="{escape(value, quote=True)}" aria-label="Copy {label}" title="{escape(value, quote=True)}" style="{style}">{inner}</button>'
            )
    return "".join(buttons), justify


def _public_badges(config: dict, settings: dict) -> str:
    items: list[str] = []
    rank = config.get("rank") if isinstance(config.get("rank"), dict) else None
    if rank:
        color = css_hex_color(rank.get("color"), "#b6aaff")
        name = escape(str(rank.get("name") or "Rank"), quote=True)
        description = escape(str(rank.get("description") or name), quote=True)
        crown = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m3 6 4 4 5-7 5 7 4-4-2 13H5L3 6Z"/></svg>'
        items.append(f'<span class="badge rank-badge" title="{description}" style="color:{color};border-color:{color}55;background:{color}18">{crown}{name}</span>')
    if settings.get("showBadges") is not False:
        for badge in (config.get("badges") or [])[:5]:
            if not badge.get("owned") or not badge.get("enabled"):
                continue
            color = css_hex_color(settings.get("iconColor") if badge.get("monochrome") else badge.get("color"), "#d8d3ff")
            glow = f"box-shadow:0 0 18px {color}4d;" if settings.get("badgeGlow") else ""
            paint = f"color:{color};background:{color}22;border-color:{color}66;{glow}"
            name = escape(str(badge.get("name") or "Badge"), quote=True)
            icon_src = str(badge.get("icon") or "")
            animated_src = str(badge.get("assetUrl") or "") if badge.get("animated") else ""
            animated_attr = f' data-animated-badge="{escape(animated_src, quote=True)}"' if animated_src.startswith("https://") else ""
            mark = (
                f'<img src="{escape(icon_src, quote=True)}"{animated_attr} alt="" width="15" height="15" loading="lazy">'
                if icon_src.startswith("/api/v1/badges/") and icon_src.endswith("/icon")
                else _badge_icon_markup(str(badge.get("name") or ""))
            )
            items.append(f'<span class="badge" title="{name}" style="{paint}">{mark}</span>')
    return f'<div class="badges">{"".join(items)}</div>' if items else ""

def _badge_icon_markup(name: str) -> str:
    if name == "Premium":
        return '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M12 3 9.5 8.5 3 9.2l4.8 4.2L6.5 20 12 16.8 17.5 20l-1.3-6.6L21 9.2 14.5 8.5 12 3Z"/></svg>'
    if name == "OG":
        return '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M13 2 4 14h7l-1 8 10-14h-7l0-6Z"/></svg>'
    return '<svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" aria-hidden="true"><path d="M12 2 9.2 4.1 5.7 4.6 4.6 8 2.2 10.6 3.5 14l.1 3.6 3.3 1.4L9.2 22 12 20.7 14.8 22l2.3-2.9 3.3-1.4.1-3.6L21.8 10.6 19.4 8 18.3 4.6 14.8 4.1 12 2Zm-1.2 12.7-2.8-2.8 1.2-1.2 1.6 1.6 3.8-3.8 1.2 1.2-5 5Z"/></svg>'


def _join_label(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        from datetime import datetime
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return f"Joined {stamp.strftime('%b %Y')}"
    except ValueError:
        return ""


def _share_version(config: dict) -> str:
    settings = config.get("settings") if isinstance(config.get("settings"), dict) else {}
    assets = config.get("assets") if isinstance(config.get("assets"), dict) else {}
    parts: list[str] = []
    for key in ("ogTitle", "ogDescription", "ogOverlayAvatar", "ogOverlayName", "ogOverlayAddress", "accentColor", "backgroundColor"):
        parts.append(str(settings.get(key) or ""))
    for key in ("ogImage", "favicon", "avatar", "background"):
        item = assets.get(key)
        url = str((item or {}).get("url") or "") if isinstance(item, dict) else ""
        parts.append(f"{len(url)}:{url[:96]}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def _clamp(value: object, default: int, low: int, high: int) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))
