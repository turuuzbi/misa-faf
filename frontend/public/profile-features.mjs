// Living-profile features (spec v1.0) for the public profile card.
//
// Shared by the server-rendered username page (auto-mounts from
// #misa-features-data) and the React renderer (ProfileFeatures.tsx calls
// mountFeatures). Everything private stays on the server: this module only
// reads the public /api/v1/features/* endpoints, which already apply the
// owner switch, the admin switch and each feature's own rules.
//
// DOM is built with createElement/textContent only; nothing from the API is
// ever parsed as HTML.

const API = '/api/v1/features';
const HEARTBEAT_MS = 20_000;
const LEASE_S = 60;
const HIT_AFTER_MS = 5_000;
const SVG = 'http://www.w3.org/2000/svg';

const reduceMotion = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'style') for (const [prop, v] of Object.entries(value)) node.style.setProperty(prop, v);
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children.flat()) if (child != null && child !== false) node.append(child);
  return node;
}

function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) if (value != null) node.setAttribute(key, String(value));
  for (const child of children.flat()) if (child) node.append(child);
  return node;
}

const store = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* storage blocked: best effort */ } },
};

function randomId(bytes = 16) {
  const buf = new Uint8Array(bytes);
  (globalThis.crypto || window.crypto).getRandomValues(buf);
  return Array.from(buf, (b) => b.toString(16).padStart(2, '0')).join('');
}

/** Page-scoped browser token (one per page per browser, shared by its tabs). */
function pageToken(kind, user) {
  const key = `misa.${kind}.${user}`;
  let value = store.get(key);
  if (!value || !/^[a-f0-9]{16,64}$/.test(value)) { value = randomId(); store.set(key, value); }
  return value;
}

async function api(path, { method = 'GET', body, signal } = {}) {
  try {
    const response = await fetch(`${API}${path}`, {
      method,
      signal,
      credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store',
    });
    let data = null;
    try { data = await response.json(); } catch { /* empty body */ }
    return { ok: response.ok, status: response.status, data };
  } catch (error) {
    if (error?.name === 'AbortError') throw error;
    return { ok: false, status: 0, data: null };
  }
}

function safeHref(value) {
  try {
    const url = new URL(String(value || ''), location.origin);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch { return null; }
}

function fnv1a(text) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) { hash ^= text.charCodeAt(i); hash = Math.imul(hash, 0x01000193); }
  return hash >>> 0;
}

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

function localTime(date, timeZone, h24 = false) {
  try {
    return new Intl.DateTimeFormat('en-GB', { hour: 'numeric', minute: '2-digit', hour12: !h24, timeZone }).format(date).toLowerCase().replace(/\s/g, ' ');
  } catch { return null; }
}

function shortDate(iso, timeZone) {
  try { return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone }).format(new Date(iso)).toLowerCase(); } catch { return ''; }
}

/** Runs `fn` now and every `ms` while the page is visible; stops when hidden. */
function whileVisible(ms, fn, cleanups) {
  let timer = null;
  const tick = () => { if (!document.hidden) fn(); };
  const start = () => { stop(); tick(); timer = setInterval(tick, ms); };
  const stop = () => { if (timer) clearInterval(timer); timer = null; };
  const onVisibility = () => (document.hidden ? stop() : start());
  document.addEventListener('visibilitychange', onVisibility);
  start();
  cleanups.push(() => { stop(); document.removeEventListener('visibilitychange', onVisibility); });
}

function card(kind, label, ...children) {
  const id = `mf-${kind}-${Math.random().toString(36).slice(2, 8)}`;
  return el('section', { class: `mf-card mf-card--${kind}`, 'aria-labelledby': id },
    el('h3', { class: 'mf-label', id, text: label }), ...children);
}

function status(text = '') {
  return el('p', { class: 'mf-status', role: 'status', 'aria-live': 'polite', text });
}

function counter(input, max) {
  const out = el('span', { class: 'mf-count', 'aria-hidden': 'true', text: `0/${max}` });
  input.addEventListener('input', () => { out.textContent = `${input.value.length}/${max}`; });
  return out;
}

// ---------------------------------------------------------------- the moon

function moonIcon(lit, waxing, side, size = 22) {
  // Lit fraction -> terminator ellipse. Right-lit when `side === "right"`.
  const r = 10, cx = 12, cy = 12;
  const k = Math.max(0, Math.min(1, lit));
  const rx = Math.abs(1 - 2 * k) * r;
  const right = side === 'right';
  const outer = right ? 1 : 0;
  const inner = (k > 0.5) === right ? 1 : 0; // crescent: terminator bulges toward the lit limb
  const path = k <= 0.005 ? '' : k >= 0.995
    ? `M ${cx} ${cy - r} a ${r} ${r} 0 1 1 0 ${2 * r} a ${r} ${r} 0 1 1 0 ${-2 * r}`
    : `M ${cx} ${cy - r} A ${r} ${r} 0 0 ${outer} ${cx} ${cy + r} A ${rx} ${r} 0 0 ${inner} ${cx} ${cy - r} Z`;
  return svg('svg', { class: 'mf-moon', viewBox: '0 0 24 24', width: size, height: size, 'aria-hidden': 'true', focusable: 'false' },
    svg('circle', { cx, cy, r, class: 'mf-moon__dark' }),
    path ? svg('path', { d: path, class: 'mf-moon__lit' }) : null,
    svg('circle', { cx, cy, r, class: 'mf-moon__rim' }));
}

// ------------------------------------------------------------ tally marks

function tallyMarks(count) {
  const groups = Math.floor(count / 5), rest = count % 5, shown = Math.min(groups, 8);
  const width = (shown + (rest ? 1 : 0)) * 22 + 2;
  const node = svg('svg', { class: 'mf-marks', viewBox: `0 0 ${Math.max(width, 4)} 20`, width: Math.max(width, 4), height: 20, 'aria-hidden': 'true', focusable: 'false' });
  const stroke = (x1, y1, x2, y2) => node.append(svg('line', { x1, y1, x2, y2 }));
  for (let g = 0; g < shown; g++) {
    const x = g * 22 + 3;
    for (let i = 0; i < 4; i++) stroke(x + i * 4, 3 + (i % 2), x + i * 4 + 0.6, 17 - (i % 2));
    stroke(x - 2, 14, x + 15, 5);
  }
  for (let i = 0; i < rest; i++) { const x = shown * 22 + 3 + i * 4; stroke(x, 3 + (i % 2), x + 0.6, 17 - (i % 2)); }
  return node;
}

// ---------------------------------------------------------- chalk strokes

function drawingSvg(strokes, label) {
  const node = svg('svg', { class: 'mf-doodle', viewBox: '0 0 200 100', preserveAspectRatio: 'xMidYMid meet', role: 'img', 'aria-label': label || 'a visitor drawing' });
  for (const stroke of Array.isArray(strokes) ? strokes : []) {
    const pts = (stroke?.points || []).filter((p) => Array.isArray(p) && p.length >= 2 && Number.isFinite(+p[0]) && Number.isFinite(+p[1]));
    if (!pts.length) continue;
    const width = Math.max(1, Math.min(10, +stroke.width || 3));
    const points = pts.map((p) => `${(Math.max(0, Math.min(1, +p[0])) * 200).toFixed(1)},${(Math.max(0, Math.min(1, +p[1])) * 100).toFixed(1)}`).join(' ');
    node.append(svg('polyline', { points, 'stroke-width': (width * 0.7).toFixed(1) }));
  }
  return node;
}

// ================================================================== mount

export function mountFeatures(host, data) {
  if (!host || !data || !data.user) return () => {};
  const user = String(data.user);
  const name = String(data.name || user);
  const preview = !!data.preview;
  const cleanups = [];
  const aborter = new AbortController();
  cleanups.push(() => aborter.abort());
  const signal = aborter.signal;
  const get = (path) => api(path, { signal });
  const post = (path, body) => api(path, { method: 'POST', body, signal });
  const u = encodeURIComponent(user);

  host.replaceChildren();
  host.classList.add('misa-features');
  if (data.accent) host.style.setProperty('--mf-accent', data.accent);
  if (preview) host.dataset.preview = '';

  const strip = el('div', { class: 'mf-strip' });
  const notes = el('div', { class: 'mf-notes' });
  const grid = el('div', { class: 'mf-grid' });
  const footer = el('div', { class: 'mf-footer' });
  host.append(strip, notes, grid, footer);
  const sync = () => {
    strip.hidden = !strip.childElementCount;
    notes.hidden = !notes.childElementCount;
    grid.hidden = !grid.childElementCount;
    footer.hidden = !footer.childElementCount;
    host.hidden = !host.querySelector('.mf-chip,.mf-note,.mf-card,.mf-secret');
  };
  sync();
  // Async widgets arrive in any order; keep a fixed reading order by rank.
  const place = (parent, node, order) => {
    node.dataset.mfOrder = String(order);
    const after = [...parent.children].find((c) => Number(c.dataset.mfOrder) > order);
    parent.insertBefore(node, after || null);
    sync();
    return node;
  };
  const disabledNote = () => el('p', { class: 'mf-note mf-note--preview', text: 'visitors can use this on your live page.' });

  // ------------------------------------------------------------ presence
  if (data.presence) {
    const chip = place(strip, el('span', { class: 'mf-chip mf-chip--here' }, el('i', { class: 'mf-dot', 'aria-hidden': 'true' }), el('span', { text: '…' })), 1);
    const label = chip.lastChild;
    const show = (res) => {
      const n = res.ok ? Number(res.data?.active) : NaN;
      label.textContent = Number.isFinite(n) ? (n <= 1 ? (preview ? 'nobody here right now' : 'just you here right now') : `${n} people here right now`) : 'presence unavailable';
      chip.classList.toggle('is-off', !Number.isFinite(n));
    };
    if (preview) {
      get(`/alive/count/${u}`).then(show).catch(() => {});
    } else {
      const token = pageToken('presence', user);
      whileVisible(HEARTBEAT_MS, () => { post(`/alive/${u}`, { token, lease_seconds: LEASE_S }).then(show).catch(() => {}); }, cleanups);
    }
  }

  // --------------------------------------------------------------- clock
  if (data.clock?.tz) {
    const chip = place(strip, el('span', { class: 'mf-chip' }), 2);
    const where = String(data.clock.label || data.clock.tz.split('/').pop().replace(/_/g, ' ')).toLowerCase();
    const paint = () => {
      const time = localTime(new Date(), data.clock.tz, !!data.clock.h24);
      if (!time) { chip.remove(); sync(); return; }
      chip.replaceChildren('it’s ', el('b', { text: time }), ` in ${where}`);
    };
    whileVisible(15_000, paint, cleanups);
  }

  // ---------------------------------------------------------------- moon
  if (data.moon) {
    const chip = place(strip, el('span', { class: 'mf-chip mf-chip--moon' }), 3);
    const paint = async () => {
      const res = await get(`/moon/${u}`);
      const m = res.data?.moon;
      if (!res.ok || !m) { chip.remove(); sync(); return; }
      chip.replaceChildren(moonIcon(+m.illumination, !!m.waxing, m.side), el('span', { text: `${String(m.phase || '').toLowerCase()} · ${m.percent}% lit` }));
    };
    whileVisible(60 * 60_000, () => { paint().catch(() => {}); }, cleanups);
  }

  // ---------------------------------------------------------- hit counter
  if (data.hits) {
    const style = String(data.hits.style || 'odometer').toLowerCase();
    const digits = el('span', { class: `mf-odo mf-odo--${style.replace(/[^a-z]/g, '')}`, role: 'img', 'aria-label': 'visit counter loading' });
    place(strip, el('span', { class: 'mf-chip mf-chip--odo' }, digits), 4);
    const paint = (count, bump = false) => {
      const text = String(Math.max(0, Math.floor(count))).padStart(6, '0');
      digits.replaceChildren(...[...text].map((d, i) => el('b', { class: bump && i === text.length - 1 && !reduceMotion() ? 'is-rolling' : null, text: d })));
      digits.setAttribute('aria-label', `${plural(Math.floor(count), 'visit')} counted`);
    };
    get(`/hits/${u}`).then((res) => {
      if (!res.ok) { digits.closest('.mf-chip').remove(); sync(); return; }
      paint(+res.data?.count || 0);
      if (preview) return;
      // Qualified visit: counted once the page has been visible for five seconds.
      let visibleFor = 0, last = document.hidden ? null : Date.now(), done = false;
      const token = pageToken('hits', user);
      const check = () => {
        const now = Date.now();
        if (last != null) visibleFor += now - last;
        last = document.hidden ? null : now;
        if (!done && visibleFor >= HIT_AFTER_MS) {
          done = true;
          post(`/hits/${u}`, { token }).then((r) => { if (r.ok && r.data?.counted) paint(+r.data.count, true); }).catch(() => {});
        }
      };
      const timer = setInterval(check, 1000);
      document.addEventListener('visibilitychange', check);
      cleanups.push(() => { clearInterval(timer); document.removeEventListener('visibilitychange', check); });
    }).catch(() => {});
  }

  // --------------------------------------------------------- night shift
  if (data.night) {
    const note = el('p', { class: 'mf-note mf-note--night' });
    let timer = null;
    const check = async () => {
      const res = await get(`/night/${u}`);
      const night = res.data?.night;
      clearTimeout(timer);
      if (!res.ok || !night?.active) { note.remove(); sync(); }
      else {
        const time = localTime(new Date(), night.timezone) || '';
        note.replaceChildren(el('span', { class: 'mf-hand', text: `it’s ${time} where ${name} is. some of this is only here now.` }));
        if (!note.isConnected) place(notes, note, 1);
      }
      // Re-check at the next boundary (the client clock never grants access).
      const next = Date.parse(night?.next_transition_at || '');
      if (Number.isFinite(next)) timer = setTimeout(() => { check().catch(() => {}); }, Math.min(6 * 3600_000, Math.max(5_000, next - Date.now() + 1_000)));
    };
    check().catch(() => {});
    const onVisibility = () => { if (!document.hidden) check().catch(() => {}); };
    document.addEventListener('visibilitychange', onVisibility);
    cleanups.push(() => { clearTimeout(timer); document.removeEventListener('visibilitychange', onVisibility); });
  }

  // ------------------------------------------------------------ the draw
  if (data.draw) {
    get(`/draw/${u}`).then((res) => {
      const deck = res.data?.draw;
      const cards = Array.isArray(deck?.cards) ? deck.cards.filter((c) => typeof c === 'string' && c) : [];
      if (!res.ok || !cards.length) return;
      const day = String(deck.day || '');
      // Stable for this browser and the owner's calendar day; nothing is sent back.
      const key = `misa.draw.${user}`;
      let saved = null;
      try { saved = JSON.parse(store.get(key) || 'null'); } catch { saved = null; }
      if (!saved || saved.day !== day || typeof saved.seed !== 'string') { saved = { day, seed: randomId(8) }; store.set(key, JSON.stringify(saved)); }
      const line = cards[fnv1a(`${saved.seed}|${user}|${day}`) % cards.length];
      place(grid, card('draw', 'today’s card',
        el('p', { class: 'mf-drawcard mf-hand', text: line }),
        el('p', { class: 'mf-hint', text: 'yours for today. a new one after midnight where ' + name + ' is.' })), 1);
    }).catch(() => {});
  }

  // -------------------------------------------------------- time capsule
  if (data.capsule) {
    let timer = null;
    const box = card('capsule', data.capsule.label ? String(data.capsule.label).toLowerCase() : 'time capsule');
    const body = el('div', { class: 'mf-capsule' });
    box.append(body);
    const render = async () => {
      const res = await get(`/capsule/${u}`);
      clearInterval(timer);
      const c = res.data?.capsule;
      if (!res.ok || !c) { box.remove(); sync(); return; }
      if (!box.isConnected) place(grid, box, 2);
      if (c.state === 'open') {
        body.replaceChildren(
          el('p', { class: 'mf-hint', text: c.release_at ? `sealed until ${shortDate(c.release_at)}` : 'opened' }),
          el('p', { class: 'mf-hand mf-capsule__text', text: String(c.body || '') }));
        return;
      }
      const release = Date.parse(c.release_at || '');
      const offset = Date.parse(c.server_now || '') - Date.now();
      const count = el('span', { class: 'mf-capsule__count' });
      body.replaceChildren(
        el('span', { class: 'mf-seal', 'aria-hidden': 'true', text: '†' }),
        el('div', {},
          el('p', { class: 'mf-capsule__when', text: Number.isFinite(release) ? `opens ${shortDate(c.release_at)}` : 'sealed' }),
          count,
          el('p', { class: 'mf-hint', text: 'the words aren’t in this page. the server holds them until the day.' })));
      if (!Number.isFinite(release)) return;
      const tick = () => {
        const left = release - (Date.now() + (Number.isFinite(offset) ? offset : 0));
        if (left <= 0) { clearInterval(timer); render().catch(() => {}); return; }
        const days = Math.floor(left / 86_400_000), hours = Math.floor(left / 3_600_000) % 24, mins = Math.floor(left / 60_000) % 60;
        count.textContent = days > 0 ? `${plural(days, 'day')}, ${hours}h to go` : hours > 0 ? `${hours}h ${mins}m to go` : `${Math.max(1, mins)} min to go`;
      };
      tick();
      timer = setInterval(tick, 30_000);
    };
    render().catch(() => {});
    cleanups.push(() => clearInterval(timer));
  }

  // ------------------------------------------------------------ the tally
  if (data.tally) {
    const token = pageToken('tally', user);
    const box = card('tally', 'the tally');
    const body = el('div', { class: 'mf-tally' });
    box.append(body);
    const render = async () => {
      const res = await get(`/tally/${u}?voter=${encodeURIComponent(token)}`);
      const poll = res.data?.tally;
      if (!res.ok || !poll || !Array.isArray(poll.options)) { box.remove(); sync(); return; }
      if (!box.isConnected) place(grid, box, 3);
      const counts = res.data.counts && typeof res.data.counts === 'object' ? res.data.counts : null;
      const voted = res.data.voted || null;
      const closed = poll.status === 'closed';
      const question = el('p', { class: 'mf-tally__q', text: String(poll.q || '') });
      if (!closed && !voted) {
        const note = status();
        const buttons = poll.options.map((option) => el('button', {
          type: 'button', class: 'mf-btn mf-btn--option', disabled: preview, text: String(option),
          onclick: async (event) => {
            buttons.forEach((b) => { b.disabled = true; });
            event.currentTarget.setAttribute('aria-pressed', 'true');
            const vote = await post(`/tally/${u}/vote`, { token, option, idem: randomId(12), poll_id: poll.id });
            if (vote.ok || vote.status === 409) { await render(); return; }
            note.textContent = vote.status === 429 ? 'too many votes from here — try later.' : 'that didn’t go through. try again?';
            buttons.forEach((b) => { b.disabled = false; });
          },
        }));
        body.replaceChildren(...[question, el('div', { class: 'mf-options', role: 'group', 'aria-label': String(poll.q || 'poll') }, buttons), note, preview && disabledNote()].filter(Boolean));
        return;
      }
      if (!counts) {
        body.replaceChildren(question, el('p', { class: 'mf-hint', text: voted ? `you picked “${voted}”. the count shows when the poll closes.` : 'this poll is closed.' }));
        return;
      }
      const total = poll.options.reduce((sum, o) => sum + (+counts[o] || 0), 0);
      body.replaceChildren(question, el('ul', { class: 'mf-results' }, poll.options.map((option) => {
        const n = +counts[option] || 0;
        return el('li', { class: option === voted ? 'is-mine' : null, 'aria-label': `${option}: ${plural(n, 'vote')}` },
          el('span', { class: 'mf-results__label', 'aria-hidden': 'true', text: String(option) }),
          el('span', { class: 'mf-results__marks', 'aria-hidden': 'true' }, tallyMarks(n)),
          el('span', { class: 'mf-results__n', 'aria-hidden': 'true', text: String(n) }));
      })), el('p', { class: 'mf-hint', text: `${plural(total, 'vote')}${closed ? ' · closed' : ''}${voted ? ` · you picked “${voted}”` : ''}` }));
    };
    render().catch(() => {});
  }

  // ------------------------------------------------------ ask me anything
  if (data.asks) {
    const box = card('asks', 'ask me anything');
    const list = el('ul', { class: 'mf-qa' });
    const note = status();
    const input = el('textarea', { id: `mf-ask-${user}`, rows: 3, maxlength: 500, required: true, placeholder: data.asks.prompt || 'ask me something…' });
    const form = el('form', { class: 'mf-form', hidden: true, onsubmit: async (event) => {
      event.preventDefault();
      const question = input.value.trim();
      if (!question) { note.textContent = 'write a question first.'; input.focus(); return; }
      submit.disabled = true;
      const res = await post(`/asks/${u}`, { question });
      submit.disabled = false;
      if (res.ok) { input.value = ''; input.dispatchEvent(new Event('input')); note.textContent = `sent — only ${name} sees it. if they answer, it may go on the page.`; }
      else note.textContent = res.status === 429 ? 'you’ve asked a lot — try again later.' : res.status === 403 || res.status === 404 ? 'questions are closed right now.' : 'that didn’t send. your question is still here — try again.';
    } },
    el('label', { for: `mf-ask-${user}`, class: 'mf-field-label', text: `your question for ${name}` }), input,
    el('div', { class: 'mf-form__row' }, counter(input, 500), null));
    const submit = el('button', { type: 'submit', class: 'mf-btn mf-btn--primary', disabled: preview, text: 'send privately' });
    form.lastChild.append(submit);
    const open = el('button', { type: 'button', class: 'mf-btn', 'aria-expanded': 'false', text: 'ask something', onclick: () => {
      const show = form.hidden; form.hidden = !show; open.setAttribute('aria-expanded', String(show)); if (show) input.focus();
    } });
    box.append(...[list, open, form, note, preview && disabledNote()].filter(Boolean));
    get(`/asks/${u}`).then((res) => {
      if (!res.ok) return;
      const asks = Array.isArray(res.data?.asks) ? res.data.asks : [];
      const render = (all) => list.replaceChildren(...asks.slice(0, all ? asks.length : 2).map((a) => el('li', {},
        el('p', { class: 'mf-qa__q' }, el('span', { 'aria-hidden': 'true', text: '? ' }), String(a.question || '')),
        el('p', { class: 'mf-qa__a mf-hand', text: String(a.answer || '') }))));
      render(false);
      if (asks.length > 2) {
        const more = el('button', { type: 'button', class: 'mf-link', text: `show all ${asks.length}`, onclick: () => { render(true); more.remove(); } });
        list.after(more);
      }
      if (!asks.length) list.replaceWith(el('p', { class: 'mf-hint', text: 'nothing answered yet. ask the first one.' }));
      place(grid, box, 4);
    }).catch(() => {});
  }

  // ------------------------------------------------------------ guestbook
  if (data.guestbook) {
    const box = card('guestbook', data.guestbook.heading || 'guestbook');
    const list = el('ul', { class: 'mf-slips' });
    const note = status();
    const nameInput = el('input', { id: `mf-gb-name-${user}`, maxlength: 40, required: true, autocomplete: 'nickname' });
    const msgInput = el('textarea', { id: `mf-gb-msg-${user}`, rows: 2, maxlength: 200, required: true });
    const submit = el('button', { type: 'submit', class: 'mf-btn mf-btn--primary', disabled: preview, text: 'sign' });
    const form = el('form', { class: 'mf-form', hidden: true, onsubmit: async (event) => {
      event.preventDefault();
      const payload = { name: nameInput.value.trim(), message: msgInput.value.trim() };
      if (!payload.name || !payload.message) { note.textContent = 'a name and a line, please.'; (payload.name ? msgInput : nameInput).focus(); return; }
      submit.disabled = true;
      const res = await post(`/guestbook/${u}`, payload);
      submit.disabled = false;
      if (res.ok) { msgInput.value = ''; msgInput.dispatchEvent(new Event('input')); note.textContent = `thanks — it shows up here once ${name} approves it.`; }
      else note.textContent = res.status === 429 ? 'slow down a little — try again later.' : res.status === 403 || res.status === 404 ? 'the guestbook is closed right now.' : typeof res.data?.detail === 'string' && res.status === 422 ? res.data.detail.toLowerCase() : 'that didn’t go through — your words are still here.';
    } },
    el('label', { for: nameInput.id, class: 'mf-field-label', text: 'your name' }), nameInput,
    el('label', { for: msgInput.id, class: 'mf-field-label', text: 'one line' }), msgInput,
    el('div', { class: 'mf-form__row' }, counter(msgInput, 200), submit));
    const open = el('button', { type: 'button', class: 'mf-btn', 'aria-expanded': 'false', text: 'sign the guestbook', onclick: () => {
      const show = form.hidden; form.hidden = !show; open.setAttribute('aria-expanded', String(show)); if (show) nameInput.focus();
    } });
    box.append(...[list, open, form, note, preview && disabledNote()].filter(Boolean));
    get(`/guestbook/${u}`).then((res) => {
      if (!res.ok) return;
      const entries = Array.isArray(res.data?.guestbook) ? res.data.guestbook : [];
      const slip = (e, i) => el('li', { class: e.pinned ? 'is-pinned' : null, style: { '--r': `${[-1.4, 1.1, -0.6, 1.6, -1, 0.7][i % 6]}deg` } },
        el('span', { class: 'mf-hand', text: String(e.message || '') }),
        el('small', { text: `— ${String(e.display_name || 'someone')}` }));
      list.replaceChildren(...entries.slice(0, 3).map(slip));
      if (entries.length > 3) {
        const more = el('button', { type: 'button', class: 'mf-link', text: `read all ${entries.length}`, onclick: () => { list.replaceChildren(...entries.map(slip)); more.remove(); } });
        list.after(more);
      }
      if (!entries.length) list.replaceWith(el('p', { class: 'mf-hint', text: 'no signatures yet. be the first.' }));
      place(grid, box, 5);
    }).catch(() => {});
  }

  // ------------------------------------------------------------ chalkboard
  if (data.doodles) {
    const box = card('doodles', data.doodles.title || 'a chalkboard');
    const gallery = el('div', { class: 'mf-board' });
    const note = status();
    const panel = el('div', { class: 'mf-canvas', hidden: true });
    const open = el('button', { type: 'button', class: 'mf-btn', 'aria-expanded': 'false', text: 'draw something' });
    box.append(...[gallery, open, panel, note, preview && disabledNote()].filter(Boolean));
    let pad = null;
    open.addEventListener('click', () => {
      const show = panel.hidden;
      panel.hidden = !show; open.setAttribute('aria-expanded', String(show));
      if (show && !pad) pad = chalkPad(panel, { preview, onSend: async (strokes, description) => {
        const res = await post(`/drawings/${u}`, { strokes, description });
        if (res.ok) { note.textContent = `sent — ${name} decides what stays on the board.`; return true; }
        note.textContent = res.status === 429 ? 'the board needs a breather — try later.' : res.status === 403 || res.status === 404 ? 'the board is closed right now.' : 'that didn’t send — your drawing is still here.';
        return false;
      } });
      if (show) pad?.focus();
    });
    cleanups.push(() => pad?.destroy());
    get(`/drawings/${u}`).then((res) => {
      if (!res.ok) return;
      const drawings = Array.isArray(res.data?.drawings) ? res.data.drawings : [];
      gallery.replaceChildren(...drawings.slice(0, 6).map((d) => el('figure', { class: d.pinned ? 'is-pinned' : null }, drawingSvg(d.strokes, d.description ? String(d.description) : 'a visitor drawing'))));
      if (!drawings.length) gallery.replaceWith(el('p', { class: 'mf-hint', text: 'nothing kept on the board yet.' }));
      place(grid, box, 6);
    }).catch(() => {});
  }

  // ------------------------------------------------------------ neighbours
  if (data.neighbours) {
    get(`/neighbours/${u}`).then((res) => {
      const list = Array.isArray(res.data?.neighbours) ? res.data.neighbours : [];
      if (!res.ok || !list.length) return;
      const nav = el('nav', { class: 'mf-neighbours', 'aria-label': `${name}’s neighbours` },
        el('span', { class: 'mf-label mf-label--inline', text: 'neighbours' }),
        list.map((n) => {
          const handle = String(n.username || '');
          const color = /^#[0-9a-f]{6}$/i.test(n.color || '') ? n.color : null;
          return el('a', { class: 'mf-chip mf-chip--link', href: `/${encodeURIComponent(handle)}` }, el('i', { class: 'mf-dot', 'aria-hidden': 'true', style: color ? { background: color } : undefined }), handle);
        }));
      place(footer, nav, 1);
    }).catch(() => {});
  }

  // ----------------------------------------------------------- secret word
  if (data.secret) {
    const note = status();
    const found = el('span', { class: 'mf-found' });
    const input = el('input', { id: `mf-secret-${user}`, autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', maxlength: 64 });
    const reveal = (res) => {
      const href = safeHref(res.data?.url);
      if (!href) return;
      found.replaceChildren(el('a', { class: 'mf-chip mf-chip--secret', href, target: '_blank', rel: 'noopener noreferrer nofollow' }, String(res.data.label || 'the hidden link'), el('span', { 'aria-hidden': 'true', text: ' ↗' })));
      box.classList.add('is-found'); form.hidden = true; toggle.hidden = true;
      note.textContent = 'you found it.';
    };
    let busy = false, lastTry = '';
    const attempt = async (word, quiet) => {
      if (busy || preview || box.classList.contains('is-found')) return;
      const w = word.trim();
      if (w.length < 4 || w.length > 64 || w === lastTry) return;
      busy = true; lastTry = w;
      const res = await post(`/secret/${u}/attempt`, { word: w });
      busy = false;
      if (res.ok) reveal(res);
      else if (!quiet) note.textContent = res.status === 429 ? 'too many guesses — wait a bit.' : 'not it.';
    };
    const form = el('form', { class: 'mf-form mf-form--inline', hidden: true, onsubmit: (event) => { event.preventDefault(); lastTry = ''; attempt(input.value, false); } },
      el('label', { for: input.id, class: 'mf-field-label', text: 'the word' }), input,
      el('button', { type: 'submit', class: 'mf-btn mf-btn--primary', disabled: preview, text: 'try it' }));
    const toggle = el('button', { type: 'button', class: 'mf-link', 'aria-expanded': 'false', text: 'know the word?', onclick: () => {
      const show = form.hidden; form.hidden = !show; toggle.setAttribute('aria-expanded', String(show)); if (show) input.focus();
    } });
    const box = el('div', { class: 'mf-secret' }, found, toggle, form, note);
    place(footer, box, 2);
    // Desktop: the word can be typed anywhere on the page (never inside a field).
    if (!preview && typeof matchMedia === 'function' && matchMedia('(pointer: fine)').matches) {
      let buffer = '', timer = null;
      const onKey = (event) => {
        const t = event.target;
        if (event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return;
        if (t instanceof Element && (t.closest('input,textarea,select,[contenteditable=""],[contenteditable="true"]'))) return;
        if (event.key === 'Backspace') buffer = buffer.slice(0, -1);
        else if (event.key.length === 1) buffer = (buffer + event.key).slice(-64);
        else return;
        clearTimeout(timer);
        timer = setTimeout(() => { attempt(buffer, true); buffer = ''; }, 900);
      };
      document.addEventListener('keydown', onKey);
      cleanups.push(() => { clearTimeout(timer); document.removeEventListener('keydown', onKey); });
    }
  }

  // ------------------------------------------------------------ other side
  if (data.reverse && (data.reverse.title || data.reverse.text)) {
    const cardEl = host.closest('#profile-card, .profile-glass');
    if (cardEl) {
      if (data.accent) cardEl.style.setProperty('--mf-accent', data.accent);
      cleanups.push(otherSide(cardEl, data.reverse, name));
    }
  }

  return () => { for (const fn of cleanups.splice(0)) { try { fn(); } catch { /* ignore */ } } host.replaceChildren(); };
}

// ---------------------------------------------------------------- chalk pad

function chalkPad(panel, { preview, onSend }) {
  const canvas = el('canvas', { class: 'mf-canvas__board', role: 'img', 'aria-label': 'drawing area — draw with a finger, stylus or mouse' });
  const desc = el('input', { id: `mf-desc-${Math.random().toString(36).slice(2, 7)}`, maxlength: 280, placeholder: 'optional' });
  const undo = el('button', { type: 'button', class: 'mf-btn', text: 'undo', disabled: true });
  const clear = el('button', { type: 'button', class: 'mf-btn', text: 'clear', disabled: true });
  const send = el('button', { type: 'button', class: 'mf-btn mf-btn--primary', text: 'send drawing', disabled: true });
  panel.append(canvas,
    el('div', { class: 'mf-form__row mf-canvas__tools' }, undo, clear, send),
    el('label', { for: desc.id, class: 'mf-field-label', text: 'describe your drawing' }), desc);
  const ctx = canvas.getContext('2d');
  const strokes = [];
  let current = null, points = 0;
  const color = getComputedStyle(panel).color || '#f2f2f0';
  const size = () => {
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    const w = canvas.clientWidth || 300, h = Math.round(w / 2);
    canvas.style.height = `${h}px`;
    canvas.width = Math.round(w * ratio); canvas.height = Math.round(h * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    redraw();
  };
  const redraw = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    ctx.clearRect(0, 0, w, h);
    ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = color; ctx.lineWidth = 3;
    for (const s of strokes) {
      ctx.beginPath();
      s.forEach(([x, y], i) => (i ? ctx.lineTo(x * w, y * h) : ctx.moveTo(x * w, y * h)));
      if (s.length === 1) ctx.lineTo(s[0][0] * w + 0.1, s[0][1] * h);
      ctx.stroke();
    }
  };
  const buttons = () => { undo.disabled = clear.disabled = !strokes.length; send.disabled = preview || !strokes.length; };
  const at = (event) => {
    const box = canvas.getBoundingClientRect();
    return [Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)), Math.max(0, Math.min(1, (event.clientY - box.top) / box.height))];
  };
  const add = (p) => {
    const prev = current[current.length - 1];
    if (prev && Math.hypot(p[0] - prev[0], (p[1] - prev[1]) / 2) < 0.004) return;
    if (points >= 10_000) return;
    current.push([+p[0].toFixed(4), +p[1].toFixed(4)]); points++;
  };
  canvas.addEventListener('pointerdown', (event) => {
    if (strokes.length >= 100 || preview) return;
    canvas.setPointerCapture(event.pointerId);
    current = []; strokes.push(current); add(at(event)); redraw(); buttons();
  });
  canvas.addEventListener('pointermove', (event) => {
    if (!current) return;
    for (const e of event.getCoalescedEvents?.() || [event]) add(at(e));
    redraw();
  });
  const end = () => { current = null; };
  canvas.addEventListener('pointerup', end); canvas.addEventListener('pointercancel', end);
  undo.addEventListener('click', () => { const s = strokes.pop(); points -= s?.length || 0; redraw(); buttons(); });
  clear.addEventListener('click', () => { strokes.length = 0; points = 0; redraw(); buttons(); });
  send.addEventListener('click', async () => {
    send.disabled = true;
    const ok = await onSend(strokes.map((s) => ({ points: s, color: '#f2f2f0', width: 3 })), desc.value.trim() || undefined);
    if (ok) { strokes.length = 0; points = 0; desc.value = ''; redraw(); }
    buttons();
  });
  const observer = new ResizeObserver(size); observer.observe(canvas);
  return { focus: () => canvas.focus?.(), destroy: () => observer.disconnect() };
}

// --------------------------------------------------------------- the back

function otherSide(cardEl, reverse, name) {
  const backId = `mf-back-${Math.random().toString(36).slice(2, 8)}`;
  const heading = el('h2', { class: 'mf-back__title mf-hand', tabindex: '-1', text: String(reverse.title || 'the other side') });
  const toFront = el('button', { type: 'button', class: 'mf-btn', text: 'back to front' });
  const back = el('div', { class: 'mf-back', id: backId, hidden: true, role: 'region', 'aria-label': `the back of ${name}’s card` },
    heading, reverse.text ? el('p', { class: 'mf-back__text mf-hand', text: String(reverse.text) }) : null, toFront);
  const corner = el('button', { type: 'button', class: 'mf-corner', 'aria-controls': backId, 'aria-expanded': 'false', title: 'turn it over' }, el('span', { class: 'mf-sr', text: 'turn the card over' }));
  cardEl.classList.add('mf-has-back');
  cardEl.append(back, corner);
  const front = () => [...cardEl.children].filter((c) => c !== back && c !== corner);
  let flipped = false, busy = false;
  const flip = (toBack) => {
    if (busy || toBack === flipped) return;
    busy = true;
    const y = window.scrollY, h = cardEl.getBoundingClientRect().height;
    const swap = () => {
      flipped = toBack;
      cardEl.style.minHeight = `${h}px`; // no jump when the faces differ in height
      front().forEach((c) => { c.inert = toBack; c.toggleAttribute('data-mf-hidden', toBack); });
      back.hidden = !toBack; back.inert = !toBack;
      if (toBack) {
        // Place the back's words in the visible part of the (unchanged-height) card.
        const top = cardEl.getBoundingClientRect().top;
        const room = Math.max(0, h - back.offsetHeight - 48);
        back.style.marginTop = `${Math.round(Math.max(0, Math.min(room, 24 - top + window.innerHeight * 0.1)))}px`;
      } else {
        back.style.marginTop = '';
        cardEl.style.minHeight = '';
      }
      corner.setAttribute('aria-expanded', String(toBack));
      corner.hidden = toBack;
      window.scrollTo({ top: y });
      (toBack ? heading : corner).focus({ preventScroll: true });
    };
    if (reduceMotion()) { swap(); busy = false; return; }
    cardEl.classList.add('mf-turning');
    setTimeout(() => { swap(); cardEl.classList.remove('mf-turning'); cardEl.classList.add('mf-turned-in'); setTimeout(() => { cardEl.classList.remove('mf-turned-in'); busy = false; }, 260); }, 240);
  };
  corner.addEventListener('click', () => flip(true));
  toFront.addEventListener('click', () => flip(false));
  return () => { flip(false); back.remove(); corner.remove(); cardEl.classList.remove('mf-has-back'); cardEl.style.minHeight = ''; };
}

// ------------------------------------------------ server-rendered auto-mount

if (typeof document !== 'undefined') {
  const boot = () => {
    const payload = document.getElementById('misa-features-data');
    const host = document.querySelector('[data-misa-features]');
    if (!payload || !host || host.dataset.mounted) return;
    host.dataset.mounted = '1';
    try { mountFeatures(host, JSON.parse(payload.textContent || '{}')); } catch { host.hidden = true; }
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
}
