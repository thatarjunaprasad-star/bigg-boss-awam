/* ════════════════════════════════════════════════════════════════════
   BIGG BOSS AWAM — front-end application
   ════════════════════════════════════════════════════════════════════ */
"use strict";

/* ── session identity ─────────────────────────────────────────────── */
function getSessionKey() {
  let key = localStorage.getItem("awam_session");
  if (!key) {
    key = "web-" + (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now());
    localStorage.setItem("awam_session", key);
  }
  return key;
}
const SESSION_KEY = getSessionKey();

/* ── state ────────────────────────────────────────────────────────── */
const state = {
  contestants: [],
  votedToday: null,
  rated: {},
  activeTab: "chat",
  engineTimer: null,
  engineLoaded: false,
  selectedProfile: null,
  trivia: { current: null, locked: false },
  newsLoaded: false,
};

/* ── helpers ──────────────────────────────────────────────────────── */
const $ = (id) => document.getElementById(id);
const fmt = (n) => Number(n).toLocaleString("en-IN");

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderMarkdownLite(text) {
  let html = escapeHtml(text);
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
  html = html.replace(/\n/g, "<br>");
  return html;
}

function toast(message, type = "") {
  const root = $("toastRoot");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = message;
  root.appendChild(el);
  setTimeout(() => {
    el.classList.add("out");
    setTimeout(() => el.remove(), 350);
  }, 3400);
}

function timeAgo(isoTs) {
  const then = new Date(isoTs);
  if (isNaN(then)) return "";
  const secs = Math.max(1, (Date.now() - then.getTime()) / 1000);
  if (secs < 3600) return `${Math.max(1, Math.floor(secs / 60))}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

function hueForName(name) {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return 26 + (hash % 30); // amber-to-gold band keeps the palette classy
}

function monogramHtml(name, extraClass = "") {
  const initials = name.split(/\s+/).slice(0, 2).map((w) => w[0]).join("");
  return `<div class="monogram ${extraClass}" style="--h:${hueForName(name)}">${initials}</div>`;
}

function countUp(el, target, duration = 900) {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    el.textContent = fmt(target);
    return;
  }
  const start = Number(el.dataset.value || 0);
  const t0 = performance.now();
  function tick(now) {
    const p = Math.min((now - t0) / duration, 1);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(Math.round(start + (target - start) * eased));
    if (p < 1) requestAnimationFrame(tick);
    else el.dataset.value = target;
  }
  requestAnimationFrame(tick);
}

/* ── API client ───────────────────────────────────────────────────── */
async function api(path, options = {}) {
  const opts = {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Awam-Session": SESSION_KEY,
      ...(options.headers || {}),
    },
  };
  const response = await fetch(path, opts);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

/* ════════════════════════════════════════════════════════════════════
   TAB ROUTING
   ════════════════════════════════════════════════════════════════════ */
const TABS = ["chat", "vote", "leaderboard", "ratings", "news", "trivia", "engine"];

function switchTab(tab) {
  if (!TABS.includes(tab)) tab = "chat";
  state.activeTab = tab;
  for (const t of TABS) {
    document.querySelectorAll(`.nav-link[data-tab="${t}"]`).forEach((b) =>
      b.classList.toggle("active", t === tab)
    );
    $(`panel-${t}`).classList.toggle("active", t === tab);
  }
  history.replaceState(null, "", `#${tab}`);

  if (tab === "news" && !state.newsLoaded) loadNews();
  if (tab === "engine") startEnginePolling();
  else stopEnginePolling();
  if (tab === "trivia") refreshTriviaScore();
  if (tab === "vote" || tab === "leaderboard" || tab === "ratings") refreshContestants();
}

document.querySelectorAll(".nav-link, [data-tab], [data-tab-jump]").forEach((el) => {
  el.addEventListener("click", (e) => {
    e.preventDefault();
    switchTab(el.dataset.tab || el.dataset.tabJump);
  });
});

/* ════════════════════════════════════════════════════════════════════
   CONTESTANTS · VOTE · LEADERBOARD · RATINGS
   ════════════════════════════════════════════════════════════════════ */
async function refreshContestants() {
  const data = await api("/api/contestants");
  state.contestants = data.contestants;
  renderVoteGrid();
  renderLeaderboard();
  renderRatings();
  renderTicker();
  await refreshVoteStatus();
}

async function refreshVoteStatus() {
  try {
    const data = await api("/api/vote-status");
    state.votedToday = data.voted_today;
    state.rated = data.rated || {};
    const line = $("voteStatusLine");
    if (state.votedToday) {
      line.innerHTML = `You've cast your vote for <strong style="color:var(--gold-bright)">${escapeHtml(
        state.votedToday.name
      )}</strong> — the 24-hour lock is on. Ratings stay open, though.`;
    } else {
      line.innerHTML = `You haven't voted today. One vote per 24 hours — choose like a jury member.`;
    }
    renderVoteGrid();
    renderRatings();
  } catch { /* status is cosmetic */ }
}

function starWidgetHtml(contestant, size = "") {
  const yours = state.rated[contestant.id] || 0;
  const avg = Math.round(contestant.rating_avg);
  let stars = `<div class="stars" data-id="${contestant.id}">`;
  for (let s = 1; s <= 5; s++) {
    stars += `<button class="star ${s <= yours ? "lit" : ""}" data-stars="${s}" aria-label="Rate ${s} stars">★</button>`;
  }
  stars += `</div><div class="rating-note">avg ${contestant.rating_avg.toFixed(2)} · ${fmt(contestant.rating_count)} ratings${
    yours ? ` · you gave ${yours}★` : ""
  }</div>`;
  return stars;
}

function renderVoteGrid() {
  const grid = $("contestantGrid");
  grid.innerHTML = state.contestants
    .map(
      (c) => `
      <article class="contestant-card" data-id="${c.id}">
        <span class="rank-chip">#${c.rank}</span>
        ${monogramHtml(c.name)}
        <h3>${escapeHtml(c.name)}</h3>
        <p class="tagline">${escapeHtml(c.tagline)}</p>
        <p class="c-meta">${escapeHtml(c.season)} · ${escapeHtml(c.profession)}</p>
        <div class="vote-count"><b class="count" data-value="${c.votes}">0</b> votes · ${c.vote_share_pct}%</div>
        <div class="share-bar"><i style="width:${c.vote_share_pct}%"></i></div>
        ${starWidgetHtml(c)}
        <button class="btn-vote ${state.votedToday ? "voted" : ""}" data-vote-id="${c.id}"
          ${state.votedToday ? "disabled" : ""}>
          ${state.votedToday
            ? state.votedToday.id === c.id ? "Your Vote ✓" : "Vote Locked"
            : "Cast Vote"}
        </button>
      </article>`
    )
    .join("");
  grid.querySelectorAll(".count").forEach((el) => countUp(el, Number(el.dataset.value)));
  grid.querySelectorAll(".btn-vote").forEach((btn) =>
    btn.addEventListener("click", () => castVote(Number(btn.dataset.voteId)))
  );
  grid.querySelectorAll(".star").forEach((star) =>
    star.addEventListener("click", () => rateContestant(Number(star.parentElement.dataset.id), Number(star.dataset.stars)))
  );
}

async function castVote(contestantId) {
  if (state.votedToday) {
    toast(`Vote locked for ${state.votedToday.name} — back in 24 hours.`, "err");
    return;
  }
  try {
    const data = await api("/api/vote", {
      method: "POST",
      body: JSON.stringify({ contestant_id: contestantId }),
    });
    if (data.status === "cast") {
      toast(`🗳️ Vote recorded for <b>${escapeHtml(data.contestant.name)}</b>!`, "ok");
    } else if (data.status === "cooldown") {
      toast(`One vote per 24 hours — ${escapeHtml(data.detail)}`, "err");
    }
    await refreshContestants();
  } catch (err) {
    toast(err.message, "err");
  }
}

async function rateContestant(contestantId, stars) {
  try {
    const data = await api("/api/rate", {
      method: "POST",
      body: JSON.stringify({ contestant_id: contestantId, stars }),
    });
    state.rated[contestantId] = stars;
    const idx = state.contestants.findIndex((c) => c.id === contestantId);
    if (idx !== -1) state.contestants[idx] = { ...state.contestants[idx], ...data.contestant };
    toast(`⭐ ${escapeHtml(data.contestant.name)} — your ${stars}★ recorded. Avg now ${data.contestant.rating_avg.toFixed(2)}.`, "ok");
    renderVoteGrid();
    renderRatings();
    if (state.activeTab === "leaderboard") renderLeaderboard();
  } catch (err) {
    toast(err.message, "err");
  }
}

function renderLeaderboard() {
  const cs = state.contestants;
  const podium = $("podium");
  const medals = { 1: "🥈", 2: "👑", 3: "🥉" };
  const order = [1, 0, 2]; // 2nd, 1st, 3rd
  podium.innerHTML = order
    .map((idx) => {
      if (cs[idx] === undefined) return "<div class='podium-slot'></div>";
      const c = cs[idx];
      const place = c.rank;
      return `
        <div class="podium-slot ${place === 1 ? "first" : ""}">
          <div class="podium-card">
            ${place === 1 ? '<div class="podium-crown">👑</div>' : ""}
            <div class="podium-medal">${place === 1 ? "CHAMPION" : medals[place] + " RUNNER-UP"}</div>
            ${monogramHtml(c.name)}
            <h3>${escapeHtml(c.name)}</h3>
            <div class="podium-votes"><b class="count" data-value="${c.votes}">0</b> votes</div>
            <div class="podium-share">${c.vote_share_pct}% share · ⭐ ${c.rating_avg.toFixed(2)}</div>
          </div>
        </div>`;
    })
    .join("");
  podium.querySelectorAll(".count").forEach((el) => countUp(el, Number(el.dataset.value)));

  const rows = $("ladderRows");
  const topShare = cs.length ? cs[0].vote_share_pct : 1;
  rows.innerHTML = cs
    .slice(3)
    .map(
      (c) => `
      <div class="ladder-row">
        <div class="ladder-rank">#${c.rank}</div>
        ${monogramHtml(c.name)}
        <div class="ladder-name">${escapeHtml(c.name)}
          <small>${escapeHtml(c.season)}</small>
        </div>
        <div class="ladder-votes"><b class="count" data-value="${c.votes}">0</b> · ${c.vote_share_pct}%</div>
        <div class="ladder-bar-wrap"><div class="ladder-bar"><i style="width:${
          (c.vote_share_pct / topShare) * 100
        }%"></i></div></div>
      </div>`
    )
    .join("");
  rows.querySelectorAll(".count").forEach((el) => countUp(el, Number(el.dataset.value)));
}

function renderRatings() {
  const list = $("ratingsList");
  const sorted = [...state.contestants].sort((a, b) => b.rating_avg - a.rating_avg);
  list.innerHTML = sorted
    .map(
      (c) => `
      <div class="rating-row">
        ${monogramHtml(c.name)}
        <div class="rating-name">${escapeHtml(c.name)}
          <small>${escapeHtml(c.tagline)} · ${escapeHtml(c.season)}</small>
        </div>
        <div>
          <div class="rating-avg">${c.rating_avg.toFixed(2)}<small> / 5</small></div>
          <div class="rating-count">${fmt(c.rating_count)} ratings</div>
        </div>
        <div style="text-align:center">${starWidgetHtml(c)}</div>
      </div>`
    )
    .join("");
  list.querySelectorAll(".star").forEach((star) =>
    star.addEventListener("click", () => rateContestant(Number(star.parentElement.dataset.id), Number(star.dataset.stars)))
  );
}

/* ── ticker ───────────────────────────────────────────────────────── */
function renderTicker() {
  const track = $("tickerTrack");
  if (!state.contestants.length) return;
  const items = state.contestants.map(
    (c) => `<span>👁 <b>${escapeHtml(c.name)}</b> ${fmt(c.votes)} votes · ${c.vote_share_pct}%</span><span class="sep">✦</span>`
  );
  items.push(`<span>🗳 <b>${fmt(state.contestants.reduce((s, c) => s + c.votes, 0))}</b> total votes cast</span><span class="sep">✦</span>`);
  const content = items.join("");
  track.innerHTML = content + content; // duplicated for the seamless loop
}

/* ════════════════════════════════════════════════════════════════════
   CHAT
   ════════════════════════════════════════════════════════════════════ */
const chatMessages = $("chatMessages");
const chatScroll = $("chatScroll");

function scrollChat() {
  chatScroll.scrollTop = chatScroll.scrollHeight;
}

function appendUserBubble(text) {
  const el = document.createElement("div");
  el.className = "bubble user";
  el.innerHTML = `<div class="bubble-body"><div class="bubble-text">${escapeHtml(text)}</div></div>`;
  chatMessages.appendChild(el);
  scrollChat();
}

function appendTypingBubble() {
  const el = document.createElement("div");
  el.className = "bubble ai";
  el.id = "typingBubble";
  el.innerHTML = `
    <div class="bubble-avatar">
      <svg viewBox="0 0 64 40" class="bubble-eye"><path d="M4,20 C14,4 50,4 60,20 C50,36 14,36 4,20 Z" fill="none" stroke="#d4af37" stroke-width="3"/><circle cx="32" cy="20" r="7.5" fill="#d4af37"/><circle cx="32" cy="20" r="2.8" fill="#0a090d"/></svg>
    </div>
    <div class="bubble-body"><div class="typing"><i></i><i></i><i></i></div></div>`;
  chatMessages.appendChild(el);
  scrollChat();
}

function appendAiBubble(reply, meta) {
  const typing = $("typingBubble");
  if (typing) typing.remove();
  const el = document.createElement("div");
  el.className = "bubble ai";
  const metaLine = meta
    ? `<div class="bubble-meta">
         <span>intent <b>${escapeHtml(meta.intent)}</b></span>
         <span>engine <b>${escapeHtml(meta.engine)}</b></span>
         <span>${meta.latency_ms}ms · <b>${meta.tokens_per_sec}</b> tok/s</span>
         <span>kv hit <b>${meta.cache_hit_rate_pct}%</b></span>
         <span>ctx <b>${meta.context_tokens}</b> tok</span>
       </div>`
    : "";
  el.innerHTML = `
    <div class="bubble-avatar">
      <svg viewBox="0 0 64 40" class="bubble-eye"><path d="M4,20 C14,4 50,4 60,20 C50,36 14,36 4,20 Z" fill="none" stroke="#d4af37" stroke-width="3"/><circle cx="32" cy="20" r="7.5" fill="#d4af37"/><circle cx="32" cy="20" r="2.8" fill="#0a090d"/></svg>
    </div>
    <div class="bubble-body">
      <div class="bubble-text">${renderMarkdownLite(reply)}</div>
      ${metaLine}
    </div>`;
  chatMessages.appendChild(el);
  scrollChat();
}

async function sendChat(text) {
  appendUserBubble(text);
  appendTypingBubble();
  $("chatSend").disabled = true;
  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message: text }),
    });
    appendAiBubble(data.reply, { ...data.meta, intent: data.intent });
  } catch (err) {
    appendAiBubble(`The oracle stumbled: ${err.message}`, null);
  } finally {
    $("chatSend").disabled = false;
    $("chatInput").focus();
  }
}

$("chatForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("chatInput");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  sendChat(text);
});

document.querySelectorAll("#chatChips .chip").forEach((chip) =>
  chip.addEventListener("click", () => {
    $("chatInput").value = chip.dataset.fill;
    $("chatForm").requestSubmit();
  })
);

/* ════════════════════════════════════════════════════════════════════
   NEWS
   ════════════════════════════════════════════════════════════════════ */
async function loadNews() {
  try {
    const data = await api("/api/news?limit=20");
    $("newsGrid").innerHTML = data.news
      .map(
        (n) => `
        <article class="news-card">
          <div class="news-top">
            <span class="news-chip">${escapeHtml(n.category)}</span>
            <span class="news-time">${timeAgo(n.published_at)}</span>
          </div>
          <h3>${escapeHtml(n.title)}</h3>
          <p>${escapeHtml(n.body)}</p>
        </article>`
      )
      .join("");
    state.newsLoaded = true;
  } catch (err) {
    toast(err.message, "err");
  }
}

/* ════════════════════════════════════════════════════════════════════
   TRIVIA
   ════════════════════════════════════════════════════════════════════ */
function renderTriviaScore(score) {
  $("tsAnswered").textContent = score.answered;
  $("tsCorrect").textContent = score.correct;
  $("tsAccuracy").textContent = score.answered ? `${score.accuracy_pct}%` : "–";
}

async function refreshTriviaScore() {
  try {
    const data = await api("/api/trivia/next");
    renderTriviaScore(data.score);
  } catch { /* scoreboard is cosmetic */ }
}

async function loadTriviaQuestion() {
  const card = $("triviaCard");
  card.innerHTML = `<div class="trivia-placeholder"><p>Consulting the vault…</p></div>`;
  try {
    const data = await api("/api/trivia/next");
    const q = data.question;
    state.trivia.current = q;
    state.trivia.locked = false;
    renderTriviaScore(data.score);
    card.innerHTML = `
      <div class="trivia-meta">
        <span class="news-chip">${escapeHtml(q.category)}</span>
        <span class="news-chip">${escapeHtml(q.difficulty)}</span>
      </div>
      <div class="trivia-q">${escapeHtml(q.question)}</div>
      <div class="trivia-options">
        ${q.options
          .map(
            (opt, i) => `
          <button class="option-btn" data-idx="${i}">
            <span class="option-letter">${"ABCD"[i]}</span>${escapeHtml(opt)}
          </button>`
          )
          .join("")}
      </div>
      <div id="triviaFeedback"></div>
      <div class="trivia-actions" id="triviaActions"></div>`;
    card.querySelectorAll(".option-btn").forEach((btn) =>
      btn.addEventListener("click", () => answerTrivia(Number(btn.dataset.idx)))
    );
  } catch (err) {
    card.innerHTML = `<div class="trivia-placeholder"><p>${escapeHtml(err.message)}</p></div>`;
  }
}

async function answerTrivia(idx) {
  if (!state.trivia.current || state.trivia.locked) return;
  state.trivia.locked = true;
  const q = state.trivia.current;
  const card = $("triviaCard");
  card.querySelectorAll(".option-btn").forEach((btn) => {
    btn.disabled = true;
    const bIdx = Number(btn.dataset.idx);
    if (bIdx === idx) btn.classList.add("pending");
  });
  try {
    const data = await api("/api/trivia/answer", {
      method: "POST",
      body: JSON.stringify({ trivia_id: q.id, choice: "ABCD"[idx] }),
    });
    card.querySelectorAll(".option-btn").forEach((btn) => {
      const bIdx = Number(btn.dataset.idx);
      btn.classList.remove("pending");
      if (bIdx === "ABCD".indexOf(data.correct_letter)) btn.classList.add("correct");
      else if (bIdx === idx) btn.classList.add("wrong");
      else btn.classList.add("dimmed");
    });
    renderTriviaScore(data.score);
    const fb = $("triviaFeedback");
    fb.className = `trivia-feedback ${data.correct ? "ok" : "no"}`;
    fb.innerHTML = `
      <span class="verdict">${data.correct ? "✅ Sahi jawaab, Awam!" : "❌ Not this time."}</span>
      ${data.correct ? "" : `The answer was <strong>${escapeHtml(data.correct_letter)}) ${escapeHtml(data.correct_option)}</strong>.`}
      ${data.fun_fact ? `<div class="trivia-fact">💡 ${escapeHtml(data.fun_fact)}</div>` : ""}`;
    $("triviaActions").innerHTML = `<button class="btn btn-primary" id="triviaNext">Next Question</button>`;
    $("triviaNext").addEventListener("click", loadTriviaQuestion);
  } catch (err) {
    state.trivia.locked = false;
    card.querySelectorAll(".option-btn").forEach((b) => (b.disabled = false));
    toast(err.message, "err");
  }
}

$("triviaStart").addEventListener("click", loadTriviaQuestion);

/* ════════════════════════════════════════════════════════════════════
   ENGINE ROOM
   ════════════════════════════════════════════════════════════════════ */
function setGauge(id, valueId, pct) {
  $(id).style.setProperty("--p", pct);
  $(valueId).textContent = `${Math.round(pct)}%`;
}

function drawSparkline(series) {
  const canvas = $("sparkline");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 300;
  const h = 72;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  if (!series || series.length < 2) {
    ctx.fillStyle = "rgba(168,159,140,0.5)";
    ctx.font = "12px Manrope, sans-serif";
    ctx.fillText("awaiting traffic…", 12, 40);
    return;
  }
  const max = Math.max(...series, 1);
  const min = Math.min(...series, 0);
  const span = Math.max(max - min, 0.001);
  const step = w / (series.length - 1);
  const points = series.map((v, i) => [i * step, h - 8 - ((v - min) / span) * (h - 18)]);

  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, "rgba(212,175,55,0.35)");
  grad.addColorStop(1, "rgba(212,175,55,0)");
  ctx.beginPath();
  ctx.moveTo(points[0][0], h);
  points.forEach(([x, y]) => ctx.lineTo(x, y));
  ctx.lineTo(w, h);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  ctx.beginPath();
  points.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.strokeStyle = "#d4af37";
  ctx.lineWidth = 1.8;
  ctx.lineJoin = "round";
  ctx.stroke();

  const [lx, ly] = points[points.length - 1];
  ctx.beginPath();
  ctx.arc(lx, ly, 3, 0, Math.PI * 2);
  ctx.fillStyle = "#f2d57e";
  ctx.fill();
}

function renderDiagnostics(data) {
  const { device, engine, kv_cache: kv, telemetry: t, profiles } = data;

  // status pill + footer
  const pill = $("engineStatus");
  pill.classList.toggle("gpu", device.accelerator_available);
  $("engineStatusText").textContent = device.accelerator_available
    ? `GPU · ${device.vendor}`
    : "CPU MODE";
  $("footerMode").textContent = device.accelerator_available
    ? `${device.vendor} accelerator active`
    : "CPU precision mode";

  // device card
  const badge = $("deviceBadge");
  badge.classList.toggle("gpu", device.accelerator_available);
  $("deviceMode").textContent = device.accelerator_available ? `${device.vendor} GPU` : "CPU";
  $("deviceName").textContent = device.label;
  $("deviceNotes").innerHTML = device.notes.map((n) => `<li>${escapeHtml(n)}</li>`).join("");

  // profiles
  if (!state.selectedProfile) state.selectedProfile = data.profile.active;
  $("profileGrid").innerHTML = profiles
    .map(
      (p) => `
      <button class="profile-card ${p.key === state.selectedProfile ? "selected" : ""} ${p.active ? "active-now" : ""}"
              data-profile="${p.key}">
        <b>${escapeHtml(p.label)}${p.active ? " · live" : ""}</b>
        <span>${escapeHtml(p.description)}</span>
      </button>`
    )
    .join("");
  $("profileGrid").querySelectorAll(".profile-card").forEach((card) =>
    card.addEventListener("click", () => {
      state.selectedProfile = card.dataset.profile;
      $("applyProfile").disabled = false;
      renderDiagnostics(data);
    })
  );
  $("applyProfile").disabled = state.selectedProfile === data.profile.active;

  // KV cache
  setGauge("gaugeUtil", "gaugeUtilVal", Math.min(kv.utilization_pct, 100));
  setGauge("gaugeHit", "gaugeHitVal", Math.min(kv.hit_rate_pct, 100));
  const kvStats = [
    ["blocks", `${fmt(kv.used_blocks)} / ${fmt(kv.capacity_blocks)}`],
    ["block size", `${kv.block_size} tok`],
    ["tokens cached", fmt(kv.tokens_cached)],
    ["active sessions", fmt(kv.active_sessions)],
    ["sessions evicted", fmt(kv.evicted_sessions)],
    ["peak utilisation", `${kv.peak_utilization_pct}%`],
  ];
  $("kvStats").innerHTML = kvStats
    .map(([k, v]) => `<div class="kv-stat"><span>${k}</span><b>${v}</b></div>`)
    .join("");

  // latency
  const lat = t.latency_recent;
  $("latencyNums").innerHTML = `
    <div class="lat-num"><span>${lat.p50}</span><span>p50 ms</span></div>
    <div class="lat-num"><span>${lat.p95}</span><span>p95 ms</span></div>
    <div class="lat-num"><span>${lat.p99}</span><span>p99 ms</span></div>`;
  drawSparkline(data.latency_series);

  // throughput / service
  $("tpsNum").textContent = fmt(t.tokens_per_sec);
  const up = Math.floor(t.uptime_seconds);
  const uptime = up >= 3600 ? `${Math.floor(up / 3600)}h ${Math.floor((up % 3600) / 60)}m` : `${Math.floor(up / 60)}m ${up % 60}s`;
  const service = [
    ["requests served", fmt(t.requests)],
    ["tokens out", fmt(t.tokens_out)],
    ["chat messages", fmt(t.chat_messages)],
    ["votes cast", fmt(t.votes_cast)],
    ["trivia accuracy", `${t.trivia_accuracy_pct}%`],
    ["uptime", uptime],
  ];
  $("serviceStats").innerHTML = service
    .map(([k, v]) => `<div class="kv-stat"><span>${k}</span><b>${v}</b></div>`)
    .join("");

  state.engineLoaded = true;
}

async function fetchDiagnostics() {
  try {
    const data = await api("/api/diagnostics");
    renderDiagnostics(data);
  } catch { /* dashboard polls quietly */ }
}

function startEnginePolling() {
  fetchDiagnostics();
  if (!state.engineTimer) state.engineTimer = setInterval(fetchDiagnostics, 2500);
}
function stopEnginePolling() {
  if (state.engineTimer) {
    clearInterval(state.engineTimer);
    state.engineTimer = null;
  }
}

$("applyProfile").addEventListener("click", async () => {
  if (!state.selectedProfile) return;
  try {
    const data = await api("/api/diagnostics/profile", {
      method: "POST",
      body: JSON.stringify({ profile: state.selectedProfile }),
    });
    toast(`⚙️ Profile <b>${escapeHtml(data.label)}</b> applied to the engine.`, "ok");
    fetchDiagnostics();
  } catch (err) {
    toast(err.message, "err");
  }
});

$("runBenchmark").addEventListener("click", async () => {
  const btn = $("runBenchmark");
  const out = $("benchResult");
  btn.disabled = true;
  out.innerHTML = "Running kernels…";
  try {
    const data = await api("/api/diagnostics/benchmark", { method: "POST" });
    const b = data.benchmark;
    const modeNames = {
      gpu: "GPU · PyTorch kernels",
      cpu: "CPU · PyTorch kernels",
      cpu_calibration: "CPU · synthesis calibration",
      unavailable: "unavailable",
    };
    const rows = Object.entries(b.attention_ms || {})
      .map(([backend, ms]) => `<tr><td>${backend} attention</td><td><b>${ms ?? "n/a"}</b> ms</td></tr>`)
      .join("");
    out.innerHTML = `
      <div class="bench-mode">mode: ${escapeHtml(modeNames[b.mode] || b.mode)}</div>
      ${rows ? `<table><tr><th>kernel</th><th>result</th></tr>${rows}
        <tr><td>${escapeHtml(b.matmul_label || "matmul 1024²")}</td><td><b>${b.matmul_tflops}</b> TFLOPS (${b.matmul_ms} ms)</td></tr></table>` : ""}
      ${b.calibration_tokens_per_sec ? `<table><tr><th>calibration</th><th>result</th></tr>
        <tr><td>local synthesis</td><td><b>${fmt(b.calibration_tokens_per_sec)}</b> tokens/sec</td></tr></table>` : ""}
      ${b.notes.map((n) => `<div class="trivia-fact">${escapeHtml(n)}</div>`).join("")}`;
  } catch (err) {
    out.textContent = `Benchmark failed: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
});

/* ════════════════════════════════════════════════════════════════════
   BOOT
   ════════════════════════════════════════════════════════════════════ */
(async function init() {
  switchTab((location.hash || "#chat").slice(1));
  window.addEventListener("hashchange", () => {
    const tab = (location.hash || "#chat").slice(1);
    if (tab !== state.activeTab) switchTab(tab);
  });
  try {
    await refreshContestants();
  } catch (err) {
    toast(`Backend unreachable: ${err.message}`, "err");
  }
  fetchDiagnostics();
  $("chatInput").focus();
})();
