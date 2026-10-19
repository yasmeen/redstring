const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const VERDICT_LABELS = {
  pursue: "Pitch",
  pursue_differentiated: "Pitch with a distinct angle",
  borderline: "Board call",
};
const VERDICT_HELP = {
  pursue: "Little audience overlap with signed clients.",
  pursue_differentiated: "Reaches the same people as a client; pitch only with a different creative angle.",
  borderline: "Partial overlap; the board decides.",
};
const STATUS_LABELS = { passed: "Passed", vetoed: "Vetoed" };
const status = (kind, text) => `<span class="status s-${esc(kind)}"><i></i>${esc(text)}</span>`;
const statusKind = (value) => {
  if (["flagged", "blocked", "vetoed"].includes(value)) return "red";
  if (["borderline", "pursue_differentiated", "conditional", "hypothesized"].includes(value)) return "amber";
  if (["pursue", "pitched", "signed", "cleared", "approved", "active", "ready"].includes(value)) return "green";
  return "ink";
};
const verdictStatus = (value, label) => status(statusKind(value), label || VERDICT_LABELS[value] || STATUS_LABELS[value] || String(value || "").replace(/_/g, " "));
const chip = (v, label) => {
  if (!(v || label)) return "";
  const verdict = label === undefined && Object.prototype.hasOwnProperty.call(VERDICT_LABELS, v);
  const title = verdict ? ` title="${esc(VERDICT_HELP[v])}"` : "";
  return `<span class="chip ${esc(v || "plain")}"${title}>${esc(label || VERDICT_LABELS[v] || STATUS_LABELS[v] || String(v).replace(/_/g, " "))}</span>`;
};
const VERDICT_TEXT = new RegExp(`\\b(${Object.keys(VERDICT_LABELS).join("|")})\\b`, "g");
const displayCopy = (text) => String(text ?? "")
  .replace(VERDICT_TEXT, (verdict) => VERDICT_LABELS[verdict])
  .replace(/\s*\(conflict [\d.]+\)/g, "")
  .replace(/[;,]?\s*similarity [\d.]+\s*[×x]\s*(?:audience )?overlap [\d.]+\s*=\s*risk [\d.]+(?:,?\s*(?:over|under) [\d.]+)?/gi, "")
  .replace(/The hackathon build sends nothing\./gi, "Nothing is sent from this workspace.");
const displayStudioCopy = (text) => displayCopy(text)
  .replace(/\binspired by (ref_[\w-]+(?:\s*,\s*ref_[\w-]+)*)/gi, (_, refs) => {
    const count = refs.split(/\s*,\s*/).length;
    return `inspired by ${count} ${count === 1 ? "reference" : "references"}`;
  });
const n = (x, d = 2) => (typeof x === "number" ? x.toFixed(d) : "");
const link = (u, label) => {
  if (!u) return `<span class="muted">no source URL</span>`;
  const hostname = (() => {
    try {
      return new URL(u, location.href).hostname.replace(/^www\./i, "") || "source";
    } catch {
      return "source";
    }
  })();
  const text = String(label ?? "").trim();
  const isUrl = /^(?:https?:\/\/|www\.)/i.test(text) || /^(?:[a-z0-9-]+\.)+[a-z]{2,}(?:[/?#:][^\s]*)?$/i.test(text);
  return `<a class="src" href="${esc(u)}" target="_blank" rel="noopener">${esc(text && !isUrl ? text : hostname)} <span aria-hidden="true">↗</span></a>`;
};
const hoodOf = (b) => b.neighborhood_name || b.neighborhood || "";
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const isSplit = () => false;
const intro = $("#intro");
const introButton = $("#intro-open");
const introKey = "rs-intro-dismissed";

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "content-type": "application/json" }, ...opts });
  if (!r.ok) {
    const error = new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    error.status = r.status;
    throw error;
  }
  return r.json();
}

// selected: the business currently shown in the dossier.
let state = { overview: null, techniques: [], selected: null, animating: false, analysis: null, dossierTab: "overview", pipelineStage: "", doubleTake: { pair: null, detail: null, version: 1, node: null, loading: 0 }, tryTab: "lead", mobileTryStep: 0 };

const viewLinks = [...document.querySelectorAll("[data-view-link]")];
const isAnalysisView = () => document.body.dataset.view === "analysis";
function syncViewFromLocation() {
  const view = location.pathname === "/analysis" ? "analysis" : "studio";
  document.body.dataset.view = view;
  $("#sidebar-view-label").textContent = view === "analysis" ? "Analysis" : "Studio";
  viewLinks.forEach((link) => {
    if (link.dataset.viewLink === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  return view;
}

const STUDIO_TABS = ["today", "pipeline", "double-take", "try", "log"];
function businessRouteFromLocation() {
  const parts = decodeURIComponent(location.hash.slice(1)).split("/");
  return parts[0] === "business" && parts[1]
    ? { slug: parts[1], section: parts[2] || "overview" }
    : null;
}
function studioTabFromHash() {
  const hash = decodeURIComponent(location.hash.slice(1));
  if (hash.startsWith("double-take/")) return "double-take";
  if (hash.startsWith("business/")) return "business";
  return STUDIO_TABS.includes(hash) ? hash : "today";
}
function syncStudioTab() {
  const tab = studioTabFromHash();
  document.body.dataset.tab = tab;
  const businessPage = $("#business-page");
  if (businessPage) businessPage.hidden = tab !== "business";
  document.querySelectorAll("[data-tab]").forEach((section) => {
    section.dataset.active = String(section.dataset.tab === tab);
  });
  document.querySelectorAll("[data-studio-tab]").forEach((link) => {
    if (link.dataset.studioTab === tab) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  return tab;
}

async function viewChanged() {
  const view = syncViewFromLocation();
  if (view === "analysis") {
    closeOverlay();
    if ($("#card").open) $("#card").close();
  } else endTour();
  if (view === "studio") syncStudioTab();
  if (!state.overview) await refresh();
  if (view === "analysis") await loadAnalysisFromLocation();
  else {
    const route = businessRouteFromLocation();
    if (route) {
      state.selected = route.slug;
      await openBusiness(route.slug, { quiet: true });
      scrollBusinessSection(route.section);
    } else if (state.selected && $("#drawer").classList.contains("open")) {
      await openBusiness(state.selected, { quiet: true });
    }
  }
}

syncViewFromLocation();
syncStudioTab();
viewLinks.forEach((link) => link.addEventListener("click", async (e) => {
  e.preventDefault();
  if (link.getAttribute("aria-current") === "page") return;
  history.pushState({}, "", link.href);
  await viewChanged();
}));
window.addEventListener("popstate", viewChanged);
document.querySelectorAll("[data-studio-tab]").forEach((link) => link.addEventListener("click", (e) => {
  e.preventDefault();
  history.pushState({}, "", `/#${link.dataset.studioTab}`);
  syncStudioTab();
  window.scrollTo({ top: 0, behavior: reduceMotion.matches ? "auto" : "smooth" });
}));
window.addEventListener("hashchange", async () => {
  if (isAnalysisView()) loadAnalysisFromLocation();
  else {
    const tab = syncStudioTab();
    if (tab === "double-take") loadDoubleTakeFromLocation();
    if (tab === "business") {
      const route = businessRouteFromLocation();
      if (route) {
        state.selected = route.slug;
        await openBusiness(route.slug, { quiet: true });
        scrollBusinessSection(route.section);
      }
    } else {
      window.scrollTo({ top: 0, behavior: reduceMotion.matches ? "auto" : "smooth" });
    }
  }
});
const icon = (name, cls = "") => ICON_PATHS[name]
  ? `<svg class="ic${cls ? ` ${cls}` : ""}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_PATHS[name]}</svg>`
  : "";
const AGENT_ICONS = { scout: "radar", researcher: "search", auditor: "clipboard-check", styledirector: "palette", strategist: "target", producer: "clapperboard", standards: "shield-check", accountmanager: "briefcase", board: "gavel", yaz: "gavel" };
const agentIcon = (name) => icon(AGENT_ICONS[String(name || "").toLowerCase().replace(/[\s_]/g, "")] || "user-round");
const who = (name) => `${agentIcon(name)}${esc(name)}`;
const CATEGORY_ICONS = { "Bookshop with storytime": "book-open", "Kids art": "brush", Yoga: "flower-2", Cafe: "coffee", "Climbing gym": "mountain", "Kids coding": "bot", "Kids gymnastics": "person-standing", "Pet grooming": "dog", "Swim lessons": "waves", Tutoring: "graduation-cap", Bakery: "croissant", "Music lessons": "music" };
const CATEGORY_HUE = { "Bookshop with storytime": "#7A4E2D", "Kids art": "#B5443B", Yoga: "#56703F", Cafe: "#6B4A3A", "Climbing gym": "#4F6170", "Kids coding": "#3F5C8C", "Kids gymnastics": "#8C4A7A", "Pet grooming": "#8A5E14", "Swim lessons": "#1F6A73", Tutoring: "#5A4A8C", Bakery: "#A0522D", "Music lessons": "#7A2E4A" };
const TECHNIQUE_ICONS = { hook: "zap", transition: "move", structure: "layout-template", pacing: "gauge", text: "type", color: "droplet", audio: "audio-lines", format: "film" };
const categoryIcon = (category) => icon(CATEGORY_ICONS[category] || "");
const avatar = (b, size = "") => {
  if (!b) return "";
  const logo = LOGOS[b.id];
  const fallback = ICON_PATHS[CATEGORY_ICONS[b.category]] || "";
  const mark = logo
    ? `<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${logo}</svg>`
    : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${fallback}</svg>`;
  return `<span class="avatar${size ? ` ${size}` : ""}" style="--av:${CATEGORY_HUE[b.category] || "#5C4A4D"}" aria-hidden="true">${mark}</span>`;
};
const bizByName = (name) => state.overview?.businesses.find((b) => b.name === name);
const bizById = (id) => state.overview?.businesses.find((b) => b.id === id);
function bizName(b, { link = true } = {}) {
  if (!b) return "";
  const id = b.id ? ` data-biz-card="${esc(b.id)}"` : "";
  const content = `${avatar(b, "sm")}<span>${esc(b.name || b.id)}</span>`;
  return link && b.id
    ? `<button type="button" class="biz-link" data-pick="${esc(b.id)}"${id}>${content}</button>`
    : `<span class="biz-name-inline"${id}>${content}</span>`;
}
const techChip = (name, kinds = {}) => `<button type="button" class="chip plain tech" data-tech-name="${esc(name)}" aria-haspopup="dialog"${kinds[name] ? ` title="${esc(kinds[name])}"` : ""}>${icon(TECHNIQUE_ICONS[kinds[name]] || "")}${esc(name)}</button>`;

let bizCardTimer = 0;
let activeBizTrigger = null;
let pinnedBizTrigger = null;
function hideBizCard() {
  clearTimeout(bizCardTimer);
  $("#biz-card").hidden = true;
  activeBizTrigger = null;
  pinnedBizTrigger = null;
}
function showBizCard(target) {
  clearTimeout(bizCardTimer);
  if (isAnalysisView()) return;
  const b = bizById(target.dataset.bizCard);
  if (!b) return;
  const client = state.overview?.clients?.find((c) => c.id === b.id);
  const meta = [b.category, hoodOf(b) || client?.neighborhood].filter(Boolean).join(" · ");
  const detail = b.status === "signed"
    ? client?.goals?.[0]?.text || ""
    : displayStudioCopy(b.reason || "").replace(/\s*\(conflict [^)]*\)/gi, "").trim();
  const stateTag = verdictStatus(b.verdict || b.status, b.status === "signed" ? "Signed" : undefined);
  const tip = $("#biz-card");
  tip.innerHTML = `<div class="biz-card-head">${avatar(b, "lg")}<span><div class="popover-head"><b>${esc(b.name)}</b><button type="button" class="popover-close" aria-label="Close business details">×</button></div>
    <span>${esc(meta)}</span>${stateTag}</span></div>${detail ? `<p>${esc(detail)}</p>` : ""}`;
  tip.hidden = false;
  activeBizTrigger = target;
  const rect = target.getBoundingClientRect();
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - tip.offsetWidth - 8));
  const top = Math.max(8, Math.min(rect.bottom, window.innerHeight - tip.offsetHeight - 8));
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
}
document.addEventListener("mouseover", (e) => {
  const target = e.target.closest("[data-biz-card]");
  if (target && !target.contains(e.relatedTarget) && window.matchMedia("(hover: hover)").matches) showBizCard(target);
  if (e.target.closest("#biz-card")) clearTimeout(bizCardTimer);
});
document.addEventListener("mouseout", (e) => {
  const target = e.target.closest("[data-biz-card]");
  if (target && !target.contains(e.relatedTarget) && !e.relatedTarget?.closest("#biz-card") && target !== pinnedBizTrigger) {
    bizCardTimer = window.setTimeout(hideBizCard, 250);
  }
  if (e.target.closest("#biz-card") && !e.relatedTarget?.closest("#biz-card") && !e.relatedTarget?.closest("[data-biz-card]") && !pinnedBizTrigger) {
    bizCardTimer = window.setTimeout(hideBizCard, 250);
  }
});
document.addEventListener("focusin", (e) => {
  const target = e.target.closest("[data-biz-card]") || e.target.closest("button, summary")?.querySelector("[data-biz-card]");
  if (target) showBizCard(target);
  if (e.target.closest("#biz-card")) clearTimeout(bizCardTimer);
});
document.addEventListener("focusout", (e) => {
  if ((e.target.closest("[data-biz-card]") || e.target.closest("button, summary")?.querySelector("[data-biz-card]"))
    && !e.relatedTarget?.closest("#biz-card") && !e.relatedTarget?.closest("[data-biz-card]") && !pinnedBizTrigger) {
    bizCardTimer = window.setTimeout(hideBizCard, 250);
  }
});
document.addEventListener("click", (e) => {
  const target = e.target.closest("[data-biz-card]");
  if (e.target.closest("#biz-card .popover-close")) { hideBizCard(); return; }
  if (target) {
    pinnedBizTrigger = pinnedBizTrigger === target ? null : target;
    if (pinnedBizTrigger) showBizCard(target);
    else hideBizCard();
  } else if (!e.target.closest("#biz-card")) hideBizCard();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideBizCard(); });
window.addEventListener("scroll", hideBizCard, true);

let activeTechTrigger = null;
let pinnedTechTrigger = null;
let techHideTimer = 0;
function techniquePopoverFor(target) {
  return target.closest("#card-body") ? $("#tech-card-sheet") : $("#tech-card");
}
function hideTechCard() {
  clearTimeout(techHideTimer);
  $("#tech-card").hidden = true;
  $("#tech-card-sheet").hidden = true;
  activeTechTrigger = null;
  pinnedTechTrigger = null;
}
async function showTechCard(target) {
  activeTechTrigger = target;
  let technique = state.techniques.find((item) => item.name === target.dataset.techName || item.id === target.dataset.techName);
  if (!technique) {
    state.techniques = await api("/api/techniques");
    technique = state.techniques.find((item) => item.name === target.dataset.techName || item.id === target.dataset.techName);
  }
  if (!technique || activeTechTrigger !== target) return;
  const card = techniquePopoverFor(target);
  const examples = technique.examples || [];
  const exampleHtml = examples.length
    ? examples.map((reference) => {
      const creator = String(reference.creator || "").replace(/^@/, "");
      return `<li><a href="${esc(reference.url)}" target="_blank" rel="noopener">${esc(`${creator ? `@${creator}` : "Reference"}${reference.category ? ` · ${reference.category}` : ""}`)}</a></li>`;
    }).join("")
    : `<li><a href="https://www.youtube.com/results?search_query=${encodeURIComponent(`${technique.name} video technique`)}" target="_blank" rel="noopener">Search examples on YouTube</a></li>`;
  card.innerHTML = `<div class="popover-head"><b>${esc(technique.name)}</b><button type="button" class="popover-close" aria-label="Close technique details">×</button></div>
    <p>${esc(technique.category)} · ${esc(technique.style)}</p><p>Rarity ${n(technique.rarity, 2)}</p>
    <p>${esc(technique.description || "No description available.")}</p><h4>Examples</h4><ul>${exampleHtml}</ul>`;
  card.hidden = false;
  activeTechTrigger = target;
  const rect = target.getBoundingClientRect();
  card.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - card.offsetWidth - 8))}px`;
  card.style.top = `${Math.max(8, Math.min(rect.bottom, window.innerHeight - card.offsetHeight - 8))}px`;
}
document.addEventListener("mouseover", (e) => {
  const target = e.target.closest("[data-tech-name]");
  if (target && !target.contains(e.relatedTarget)) {
    clearTimeout(techHideTimer);
    if (window.matchMedia("(hover: hover)").matches) showTechCard(target);
  }
  if (e.target.closest(".detail-popover")) clearTimeout(techHideTimer);
});
document.addEventListener("mouseout", (e) => {
  if (pinnedTechTrigger) return;
  if (e.target.closest("[data-tech-name]") && !e.relatedTarget?.closest(".detail-popover") && !e.relatedTarget?.closest("[data-tech-name]")) {
    techHideTimer = window.setTimeout(hideTechCard, 250);
  }
  const card = e.target.closest(".detail-popover");
  if (card && !card.contains(e.relatedTarget) && !e.relatedTarget?.closest("[data-tech-name]")) {
    techHideTimer = window.setTimeout(hideTechCard, 250);
  }
});
document.addEventListener("focusin", (e) => {
  const target = e.target.closest("[data-tech-name]");
  if (target) showTechCard(target);
  if (e.target.closest(".detail-popover")) clearTimeout(techHideTimer);
});
document.addEventListener("focusout", (e) => {
  if (!pinnedTechTrigger && !e.relatedTarget?.closest(".detail-popover") && !e.relatedTarget?.closest("[data-tech-name]")) {
    if (e.target.closest("[data-tech-name], .detail-popover")) techHideTimer = window.setTimeout(hideTechCard, 250);
  }
});
document.addEventListener("click", (e) => {
  if (e.target.closest("#tech-card .popover-close, #tech-card-sheet .popover-close")) {
    hideTechCard();
    return;
  }
  const target = e.target.closest("[data-tech-name]");
  if (target) {
    e.preventDefault();
    if (pinnedTechTrigger === target) hideTechCard();
    else {
      pinnedTechTrigger = target;
      showTechCard(target);
    }
    return;
  }
  if (!e.target.closest(".detail-popover")) hideTechCard();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTechCard(); });
window.addEventListener("scroll", hideTechCard, true);

function mediaOf(r) {
  const u = r.url || "";
  const yt = u.match(/youtube\.com\/(?:shorts\/|watch\?v=)([\w-]{6,})|youtu\.be\/([\w-]{6,})/);
  if (yt) {
    const id = yt[1] || yt[2];
    return { platform: "youtube", site: "YouTube", embed: `https://www.youtube-nocookie.com/embed/${id}?autoplay=1`, poster: `https://i.ytimg.com/vi/${id}/hqdefault.jpg` };
  }
  const ig = u.match(/instagram\.com\/(reel|p|tv)\/([\w-]+)/);
  if (ig) return { platform: "instagram", site: "Instagram", embed: `https://www.instagram.com/${ig[1]}/${ig[2]}/embed/` };
  return { platform: "", site: "" };
}

function refCard(r) {
  const m = mediaOf(r);
  const label = [r.creator, r.category].filter(Boolean).join(" · ") || "Reference";
  const inner = `${m.poster ? `<img src="${esc(m.poster)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<span class="ref-glyph">${categoryIcon(r.category) || icon("film")}</span>`}
    ${m.embed ? `<span class="ref-play">${icon("play")}</span>` : ""}${m.site ? `<span class="ref-site">${icon(m.platform)}${m.site}</span>` : ""}`;
  const poster = m.embed
    ? `<button type="button" class="ref-poster" data-embed="${esc(m.embed)}" data-title="${esc(label)}" aria-label="Play ${esc(label)} here" style="--av:${CATEGORY_HUE[r.category] || "#5C4A4D"}">${inner}</button>`
    : `<div class="ref-poster" style="--av:${CATEGORY_HUE[r.category] || "#5C4A4D"}">${inner}</div>`;
  return `<li class="ref">${poster}<div class="ref-body"><p class="ref-who">${link(r.url, label)}</p>${r.analysis ? `<p class="ref-how">${esc(r.analysis)}</p>` : ""}</div></li>`;
}

document.addEventListener("click", (e) => {
  const poster = e.target.closest("[data-embed]");
  if (!poster) return;
  const frame = document.createElement("iframe");
  frame.src = poster.dataset.embed;
  frame.title = poster.dataset.title;
  frame.allow = "autoplay; encrypted-media; picture-in-picture";
  frame.allowFullscreen = true;
  frame.className = "ref-frame";
  poster.closest(".ref").classList.add("playing");
  poster.replaceWith(frame);
});

document.addEventListener("click", async (e) => {
  const link = e.target.closest("a[data-analysis-link]");
  if (!link) return;
  e.preventDefault();
  history.pushState({}, "", link.href);
  await viewChanged();
});

function setIntroVisible(visible) {
  intro.hidden = !visible;
  introButton.hidden = visible;
  introButton.setAttribute("aria-expanded", String(visible));
}
const firstBlocked = () => {
  const blocked = (state.overview?.needs_you || []).filter((i) => i.type === "blocked");
  return blocked.find((i) => i.business_id === "tumble-town") || blocked[0];
};

function dismissIntro() {
  setIntroVisible(false);
  try { localStorage.setItem(introKey, "1"); } catch (_) { /* private mode */ }
}

const introPhone = window.matchMedia("(max-width: 599px)");
function syncIntroDefault() {
  setIntroVisible(false);
  introButton.textContent = introPhone.matches ? "New here? See how it works" : "New here? How it works";
}
syncIntroDefault();
introPhone.addEventListener("change", syncIntroDefault);
introButton.addEventListener("click", () => {
  setIntroVisible(true);
  intro.scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth", block: "center" });
  $("#intro-title").focus();
});
$("#intro-got-it").addEventListener("click", () => {
  dismissIntro();
  $("#board-h").focus();
});
$("#intro-see-draft").addEventListener("click", async () => {
  const hit = firstBlocked();
  if (!hit) return;
  selectDoubleTakePair(hit.business_id, hit.draft_id);
  dismissIntro();
});
$("#intro-see-pitch").addEventListener("click", async (e) => {
  const candidates = (state.overview?.businesses || [])
    .filter((business) => business.status === "pitched" || business.status === "signed");
  for (const business of candidates) {
    const dossier = await api(`/api/business/${business.id}`);
    const pitch = dossier.pitches?.[0];
    if (pitch) {
      await openPitch(business.id, pitch.id);
      return;
    }
  }
});

// Short names for the step knots. The full label from the server stays in the title, aria-label and "Next" line.
const STEP_SHORT = {
  reset: "Seed", screen: "Screen", research: "Research", spec: "Spec + Double Take", pitch: "Pitch",
  approve: "Approve", sign: "Sign", client_month: "Client month", retire_goal: "Retire goal",
};

const STAGES = [
  ["Lead", (b) => b.status === "lead" && !b.verdict, "Every lead has been screened."],
  ["Screened", (b) => b.status === "lead" && b.verdict, "Nothing screened yet. Step 1 runs Scout."],
  ["Passed", (b) => b.status === "passed", "No leads have been passed."],
  ["Pursued", (b) => b.status === "pursued", "No pursuits open."],
  ["Pitched", (b) => b.status === "pitched", "No pitches yet. The board approves every pitch, and nothing is ever sent."],
  ["Signed", (b) => b.status === "signed", "No clients yet."],
];

async function refresh() {
  const o = await api("/api/overview");
  state.overview = o;
  document.body.classList.toggle("readonly", !!o.readonly);
  $("#agency").textContent = o.agency;
  const hoods = (o.neighborhoods || []).map((h) => h.name).join(", ");
  $("#ws-meta").textContent = `${o.businesses.length} businesses${hoods ? ` in ${hoods}` : ""}`;
  $("#mode").textContent = `agents: ${o.mode}${o.readonly ? " · read-only" : ""}`;
  $("#meta").textContent = o.graphs.join(" · ");
  renderVideo(o.video_url);
  renderSteps(o);
  renderLog(o.log);
  renderBoard(o);
  renderAttention(o);
  renderAbout(o);
  renderPipelineRegister(o);
  renderDoubleTakePairs(o);
  $("#intro-see-draft").hidden = !firstBlocked();
  document.querySelectorAll(".readonly-form-note").forEach((note) => { note.hidden = !o.readonly; });

  const hoodSel = $("#lead-neighborhood");
  const keepHood = hoodSel.value || "n_flatiron";
  hoodSel.innerHTML = (o.neighborhoods || []).map((h) => `<option value="${esc(h.id)}">${esc(h.name)}</option>`).join("");
  hoodSel.value = keepHood;
  const sel = $("#draft-client");
  const keep = sel.value;
  sel.innerHTML = o.businesses.filter((b) => ["signed", "pursued", "pitched"].includes(b.status))
    .map((b) => `<option value="${esc(b.id)}">${esc(b.name)}</option>`).join("");
  if (keep) sel.value = keep;
  renderLeadAudienceControls();
  renderLeadPresets();
  feed();
  renderDays();
  if (studioTabFromHash() === "double-take") await loadDoubleTakeFromLocation();

  $("#follow").hidden = true;
  const businessRoute = businessRouteFromLocation();
  if (businessRoute) {
    state.selected = businessRoute.slug;
    await openBusiness(businessRoute.slug, { quiet: true });
    scrollBusinessSection(businessRoute.section);
  } else if (state.selected && $("#drawer").classList.contains("open")) {
    await openBusiness(state.selected, { quiet: true });
  }
  else drawString(false);
}

// Which business a log line is about: the one named first in it.
function subjectOf(line, list) {
  let best = null, at = Infinity;
  for (const b of list) {
    const k = Math.min(...[line.indexOf(b.id), line.indexOf(b.name)].filter((x) => x >= 0), Infinity);
    if (k < at) { at = k; best = b.id; }
  }
  return best;
}

// Follow the run: a Double Take block from the step that just ran, else the last business it touched,
// else the business the latest finished step is named for, else the last business in the log.
function followTarget(o) {
  const prevLast = state.prevLast;
  state.prevLast = o.log[o.log.length - 1];
  const latest = (lines) => {
    for (let i = lines.length - 1; i >= 0; i--) { const s = subjectOf(lines[i], o.businesses); if (s) return s; }
    return null;
  };
  if (prevLast !== undefined) {
    const p = o.log.lastIndexOf(prevLast);
    const fresh = p === -1 ? o.log : o.log.slice(p + 1);
    const hit = latest(fresh.filter((l) => /blocked/i.test(l))) || latest(fresh);
    if (hit) return hit;
  }
  const lastDone = [...o.steps].reverse().find((s) => s.done);
  const named = lastDone && o.businesses.find((b) => new RegExp(`\\b${b.name.split(" ")[0]}\\b`).test(lastDone.label));
  if (named) return named.id;
  return prevLast === undefined ? latest(o.log) : null;
}

function pickDefault(list) {
  return (list.find((b) => b.status === "pitched") || list.find((b) => b.status === "pursued")
    || list.find((b) => b.status === "signed") || list[0] || {}).id || null;
}

function renderSteps(o) {
  $("#steps").hidden = !!o.readonly;
  $("#runner-status").hidden = !!o.readonly;
  $("#readonly-note").hidden = !o.readonly;
  if (o.readonly) return;
  const next = o.steps.findIndex((s) => !s.done);
  $("#steps").innerHTML = o.steps.map((s, i) => {
    const cls = s.done ? "done" : i === next ? "next" : "pending";
    const said = s.done ? "done" : i === next ? "next" : "not run yet";
    const locked = i > 0 && !o.steps[i - 1].done;
    const finished = s.done && s.id !== "reset";
    const disabled = locked || finished;
    const title = finished ? "Already ran; reset first" : locked ? `Run step ${i - 1} first` : s.label;
    return `<li class="${cls}"><button type="button" data-step="${esc(s.id)}" ${disabled ? "disabled" : ""} title="${esc(title)}" aria-label="Step ${i}: ${esc(s.label)} (${said}${disabled ? `, ${esc(title)}` : ""})"><span class="knot-dot" aria-hidden="true">${i}</span><span class="step-name">${esc(STEP_SHORT[s.id] || s.label)}</span></button></li>`;
  }).join("");
  $("#step-next").innerHTML = next >= 0
    ? `<b>Next:</b> ${next}. ${esc(o.steps[next].label)}`
    : `<b>All ${o.steps.length} steps ran.</b> Step 0 resets the workspace.`;
}

function renderLog(lines) {
  const cls = (l) => (/blocked/i.test(l) ? "blocked" : l.startsWith("> ") ? "cmd" : "");
  $("#log").innerHTML = lines.map((l) => `<span class="ln ${cls(l)}">${esc(l)}</span>`).join("");
  $("#log").scrollTop = 1e6;
  const last = [...lines].reverse().find((l) => l.trim() && !l.startsWith("> ")) || "";
  $("#step-latest").textContent = last ? `Latest: ${last.replace(/\s{2,}/g, "  ")}` : "";
  $("#step-latest").classList.toggle("blocked", /blocked/i.test(last));
}

function bizCard(b) {
  const client = (state.overview?.clients || []).find((c) => c.id === b.id);
  const meta = [b.category, hoodOf(b) || client?.neighborhood].filter(Boolean).map(esc).join(" · ");
  const goal = client?.goals?.[0]?.text;
  const tags = b.status !== "signed" && b.verdict && b.verdict !== "pursue" ? verdictStatus(b.verdict) : "";
  return `<button type="button" class="biz" data-biz="${esc(b.id)}" data-status="${esc(b.status)}" aria-pressed="${b.id === state.selected}">
    <span class="biz-head">${bizName(b, { link: false })}<span class="biz-title">${meta ? `<span class="biz-meta">${categoryIcon(b.category)}${meta}</span>` : ""}</span></span>
    ${tags ? `<span class="biz-tags">${tags}</span>` : ""}${goal ? `<span class="biz-goal"><b>Goal:</b> ${esc(goal)}</span>` : ""}
    ${b.status === "signed" && client?.won_pitch ? `<span class="biz-goal"><b>Won with spec work</b></span>` : ""}</button>`;
}

const TIE = `<svg viewBox="0 0 44 12" aria-hidden="true"><circle cx="3" cy="6" r="3"/><path d="M3 6 C 15 13, 29 -1, 41 6"/><circle cx="41" cy="6" r="3"/></svg>`;

// Needs you holds decisions, most urgent first: the first one opens with its buttons, the rest are one line each.
function needsEntries(o) {
  const items = o.needs_you || [];
  const byId = Object.fromEntries((o.businesses || []).map((b) => [b.id, b]));
  const ro = !!o.readonly;
  const cta = (t) => `<span class="need-cta">${t} <span aria-hidden="true">→</span></span>`;
  const unit = (count, one, many) => `<span class="focus-n">${count} <small>${count === 1 ? one : many}</small></span>`;
  const entries = [];
  items.filter((i) => i.type === "borderline").forEach((i) => {
    const b = byId[i.business_id] || { name: i.business_id };
    const rawReason = i.reason || b.reason || "";
    const reason = displayStudioCopy(rawReason);
    const conflict = rawReason.match(/\(conflict\s+([\d.]+)\)/i)?.[1];
    const competitor = rawReason.match(/\b(?:with|against)\s+([^;,(]+?)(?=\s*(?:\(|;|$))/i)?.[1]?.trim();
    const cutoff = o.thresholds?.borderline ?? state.analysis?.thresholds?.borderline;
    const evidence = conflict && competitor && typeof cutoff === "number"
      ? `Partial overlap with ${esc(competitor)}: conflict <b class="metric">${n(Number(conflict))}</b>, above the <b class="metric">${n(cutoff)}</b> board-call line.`
      : `${esc(reason.replace(/\s*\(conflict [^)]*\)/i, "").replace(/;?\s*board call\.?$/i, "").trim())} `;
    entries.push({
      n: 1, kind: "Board call", icon: "gavel", biz: b,
      q: "Pursue this lead?",
      what: `${evidence} Pursue opens its research; Pass takes it off the pipeline for 90 days.`,
      actions: ro ? `<span class="focus-wait">Waiting on the board</span><button type="button" class="btn ghost big" data-pick="${esc(i.business_id)}" data-business-section="screening">See the screening</button>`
        : `<button type="button" class="btn primary big" data-lead-decision="pursue" data-slug="${esc(i.business_id)}">Pursue lead</button><button type="button" class="btn ghost big" data-lead-decision="pass" data-slug="${esc(i.business_id)}">Pass</button>`,
      more: ro ? "" : `<button type="button" class="text-button" data-pick="${esc(i.business_id)}" data-business-section="screening">See the screening first →</button>`,
      row: `<button type="button" class="focus-row" data-pick="${esc(i.business_id)}" data-business-section="screening"><span class="focus-item-kind">${icon("gavel")}New lead</span><span class="focus-row-text"><span class="focus-row-title">Pursue ${bizName(b, { link: false })}?</span><small>Partial overlap with a signed client · board call</small></span>${cta("Review")}</button>`,
    });
  });
  items.filter((i) => i.type === "pitch").forEach((i) => {
    const b = byId[i.business_id] || { name: i.business_id };
    const attrs = `data-pitch="${esc(i.pitch_id)}" data-slug="${esc(i.business_id)}"`;
    entries.push({
      n: 1, kind: "Pitch to approve", icon: "send", biz: b,
      q: "Approve this pitch?",
      what: "Account Manager assembled it from spec posts that cleared Double Take. Nothing is sent until you approve.",
      actions: `<button type="button" class="btn primary big" ${attrs}>Review and decide</button>`,
      row: `<button type="button" class="focus-row" ${attrs}><span class="focus-item-kind">${icon("send")}Pitch</span><span class="focus-row-text"><span class="focus-row-title">Approve ${bizName(b, { link: false })}'s pitch</span><small>Assembled from spec posts that cleared Double Take</small></span>${cta("Review")}</button>`,
    });
  });
  const posts = items.filter((i) => i.type === "approve_posts");
  if (posts.length) {
    const total = posts.reduce((a, i) => a + i.draft_ids.length, 0);
    const chips = posts.map((i) => `<button type="button" class="focus-chip" data-draft="${esc(i.draft_ids[0])}" data-slug="${esc(i.business_id)}">${bizName(byId[i.business_id] || { id: i.business_id, name: i.business }, { link: false })}<b>${i.draft_ids.length}</b></button>`).join("");
    entries.push({
      n: total, kind: "Posts to approve", icon: "circle-check",
      q: `Approve ${plural(total, "post", "posts")}?`,
      what: `All cleared Double Take. Pick a client to review ${posts.length === 1 ? "its" : "their"} posts.`,
      actions: `<span class="focus-chips">${chips}</span>`,
      row: `<div class="focus-row"><span class="focus-item-kind">${icon("circle-check")}Posts</span><div class="focus-row-middle"><button type="button" class="focus-row-text" data-draft="${esc(posts[0].draft_ids[0])}" data-slug="${esc(posts[0].business_id)}"><span class="focus-row-title">Approve ${plural(total, "post", "posts")}</span><small>All cleared by Double Take</small></button><span class="focus-chips">${chips}</span></div><span class="focus-row-right" aria-hidden="true"></span></div>`,
    });
  }
  const ready = items.find((i) => i.type === "ready");
  if (ready) {
    const k = ready.business_ids.length;
    entries.push({
      n: k, kind: "Cleared to pitch", icon: "sparkles",
      q: `${plural(k, "screened lead is", "screened leads are")} cleared to pitch`,
      what: "Scout found no clash with a signed client. Open one in the pipeline to pursue it.",
      actions: `<button type="button" class="btn primary big" data-reveal-lane="screened">See them in the pipeline</button>`,
      row: `<button type="button" class="focus-row" data-reveal-lane="screened"><span class="focus-item-kind">${icon("sparkles")}Leads</span><span class="focus-row-text">${plural(k, "lead is", "leads are")} cleared to pitch<small>Scout found no clash with a signed client</small></span>${cta("Review")}</button>`,
    });
  }
  const unscreened = items.filter((i) => i.type === "unscreened");
  if (unscreened.length) {
    const k = unscreened.length;
    entries.push({
      n: k, kind: "Leads to screen", icon: "radar",
      q: `${plural(k, "new lead is", "new leads are")} waiting for Scout`,
      what: "Run the next step and Scout screens them against every signed client.",
      actions: `<button type="button" class="btn primary big" data-reveal-lane="lead">See them in the pipeline</button>`,
      row: `<button type="button" class="focus-row" data-reveal-lane="lead"><span class="focus-item-kind">${icon("users")}Leads</span><span class="focus-row-text">${plural(k, "new lead is", "new leads are")} waiting for Scout<small>Run the next step to screen them</small></span>${cta("Review")}</button>`,
    });
  }
  return entries;
}

function renderAttention(o) {
  const byId = Object.fromEntries(o.businesses.map((b) => [b.id, b]));
  const entries = needsEntries(o);
  const [first, ...rest] = entries;
  const count = entries.length;
  const words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];
  const countWord = count < words.length ? words[count] : String(count);
  $("#today-kicker").textContent = `${count} ${count === 1 ? "decision" : "decisions"} today`;
  $("#today-title").textContent = count ? "Your call." : "All clear.";
  $("#today-summary").textContent = count === 0
    ? "The agents ran overnight. Nothing needs you right now."
    : count === 1
      ? "The agents ran overnight. This one needs your judgment before anything moves."
      : `The agents ran overnight. These ${countWord} need your judgment before anything moves.`;
  $("#needs-you-heading").textContent = count ? `${plural(count, "decision", "decisions")} waiting` : "All clear";
  const kindLabel = {
    "Board call": "New lead",
    "Pitch to approve": "Pitch",
    "Posts to approve": "Posts",
    "Cleared to pitch": "Leads",
    "Leads to screen": "Leads",
  };
  $("#needs-you").innerHTML = first
    ? `<div class="focus-item">
        <p class="focus-item-kind">${icon(first.icon)}${esc(kindLabel[first.kind] || first.kind)}</p>
        ${first.biz ? `<div class="focus-biz">${bizName(first.biz)}<span>${esc([first.biz.category, hoodOf(first.biz)].filter(Boolean).join(" · "))}</span></div>` : ""}
        <h3 class="focus-q">${esc(first.q)}</h3><p class="focus-what">${first.what}</p>
        <div class="focus-actions">${first.actions}</div>${first.more || ""}
      </div>${rest.length ? `<div class="focus-rows">${rest.map((entry) => entry.row).join("")}</div>` : ""}`
    : `<div class="needs-empty"><img class="needs-empty-image" src="/static/img/empty-all-clear.webp" width="720" height="720" alt="A tidy corkboard beside a cup of coffee." loading="lazy" decoding="async"><p>All clear: nothing needs you right now.</p></div>`;
  const blocked = (o.needs_you || []).filter((i) => i.type === "blocked").sort((a, z) => (z.risk || 0) - (a.risk || 0));
  $("#caught-count").textContent = String(blocked.length);
  const caughtRows = blocked.map((i) => `<button type="button" class="caught-row" data-draft="${esc(i.draft_id)}" data-slug="${esc(i.business_id)}">
      <span class="caught-who"><b>${bizName(byId[i.business_id] || { id: i.business_id, name: i.business }, { link: false })}</b>
        <span class="caught-lookalikes"><span>looked like</span>${[i.with_business, ...(i.also_like || [])].map((name, index) => `${index ? "<span>and</span>" : ""}<span class="caught-name">${bizName(bizByName(name), { link: false })}</span>`).join("")}</span>
      </span>
      ${typeof i.risk === "number" ? `<span class="risk-pill" title="Double Take risk">${n(i.risk)}</span>` : ""}
      <span class="caught-note">${i.shared?.length ? `Shared: ${i.shared.map(esc).join(", ")}` : "Shared techniques flagged by Double Take."}</span>
      <span class="caught-go" aria-hidden="true">→</span>
    </button>`).join("") || `<p class="empty-row">Nothing caught yet. Double Take checks every draft from step 3 on.</p>`;
  $("#caught").innerHTML = caughtRows;
  $("#tab-count-today").textContent = String(count);
  $("#tab-count-double-take").textContent = String(new Set(blocked.map((i) => i.draft_id)).size);
}

function renderAbout(o) {
  const clients = (o.businesses || []).filter((business) => business.status === "signed");
  const neighborhoods = [...new Set(clients.map(hoodOf).filter(Boolean))];
  const categories = [...new Set(clients.map((business) => business.category).filter(Boolean))];
  const meta = [
    plural(clients.length, "client", "clients"),
    neighborhoods.length ? plural(neighborhoods.length, "neighborhood", "neighborhoods") : "",
    categories.join(", "),
  ].filter(Boolean).join(" · ");
  $("#about-summary").textContent = `We make short-form video for local family businesses${meta ? ` · ${meta}` : ""}.`;
  const workflow = [
    ["user-round", "Leads"], ["search", "Research"], ["clapperboard", "Spec posts"],
    ["send", "Pitch"], ["circle-check", "Signed"], ["calendar-days", "Monthly posts"],
  ];
  $("#studio-workflow").innerHTML = workflow.map(([name, label]) =>
    `<li>${icon(name)}<span>${label}</span></li>`).join("");
  const pitchClient = (o.businesses || []).find((business) => business.status === "pitched" || business.status === "signed");
  const pitchButton = $("#intro-see-pitch");
  pitchButton.hidden = !pitchClient;
  pitchButton.dataset.slug = pitchClient?.id || "";
}

document.addEventListener("click", (e) => {
  const row = e.target.closest(".caught-row");
  if (!row) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  history.pushState({}, "", `/#double-take/${encodeURIComponent(row.dataset.slug)}/${encodeURIComponent(row.dataset.draft)}`);
  syncStudioTab();
  window.scrollTo({ top: 0, behavior: reduceMotion.matches ? "auto" : "smooth" });
});

function renderBoard(o) {
  $("#board").innerHTML = STAGES.map(([title, test, empty]) => {
    const items = o.businesses.filter(test);
    if ((title === "Passed" || title === "Lead") && !items.length) return "";
    let extra = 0;
    if (title === "Screened") {
      const order = { pursue: 0, pursue_differentiated: 1, borderline: 2 };
      items.sort((a, z) => (order[a.verdict] ?? 4) - (order[z.verdict] ?? 4) || a.name.localeCompare(z.name));
      const sel = items.findIndex((b) => b.id === state.selected);
      if (!state.showAllScreened && items.length > 5 && sel < 5) extra = items.length - 4;
    }
    const shown = extra ? items.slice(0, 4) : items;
    const won = (o.clients || []).filter((client) => client.won_pitch).map((client) => client.name);
    const emptyText = title === "Pitched" && won.length
      ? `No open pitches. Won and signed: ${won.join(", ")}.`
      : empty;
    return `<section class="stage" data-stage="${esc(title.toLowerCase())}" aria-label="${title}, ${items.length}"><h3>${title} <span class="count">${items.length}</span></h3>
      ${items.length ? `<div class="cards">${shown.map(bizCard).join("")}${extra ? `<button type="button" class="more-cards" data-more-stage="screened">Show ${extra} more</button>` : ""}</div>` : `<p class="empty-row">${esc(emptyText)}</p>`}</section>`;
  }).join("");
  $("#tab-count-pipeline").textContent = String(o.businesses.length);
}

function renderPipelineRegister(o) {
  const stageRows = STAGES.map(([title, test]) => ({ title, items: o.businesses.filter(test) })).filter((row) => row.items.length);
  $("#pipeline-kicker").textContent = `Pipeline · ${o.businesses.length} businesses`;
  $("#pipeline-stage-bar").style.gridTemplateColumns = stageRows.map((row) => `${row.items.length}fr`).join(" ") || "1fr";
  $("#pipeline-stage-bar").innerHTML = stageRows.map((row) => `<button type="button" class="pipeline-stage${state.pipelineStage === row.title.toLowerCase() ? " selected" : ""}" data-pipeline-stage="${esc(row.title.toLowerCase())}" aria-pressed="${state.pipelineStage === row.title.toLowerCase()}"><span class="pipeline-stage-count">${row.items.length}</span><span>${esc(row.title)}</span></button>`).join("");
  const screening = state.analysis?.screening || [];
  const visible = o.businesses.filter((b) => !state.pipelineStage || (STAGES.find(([title, test]) => test(b))?.[0].toLowerCase() === state.pipelineStage));
  $("#pipeline-register").innerHTML = `<div class="register-head label"><span>Business</span><span>Stage</span><span>Status</span><span>Overlap</span></div>${visible.map((b) => {
    const stage = STAGES.find(([title, test]) => test(b))?.[0] || b.status;
    const result = screening.find((row) => row.id === b.id);
    const overlap = b.max_conflict ?? result?.max_conflict;
    const statusLabel = b.verdict ? (VERDICT_LABELS[b.verdict] || b.verdict.replace(/_/g, " ")) : b.status === "signed" ? "Signed" : b.status.replace(/_/g, " ");
    return `<button type="button" class="register-row" data-biz="${esc(b.id)}">
      <span class="register-business">${bizName(b, { link: false })}<small>${esc([b.category, hoodOf(b)].filter(Boolean).join(" · "))}</small></span>
      <span class="register-stage">${esc(stage)}</span>
      <span class="register-status">${verdictStatus(b.verdict || b.status, statusLabel)}</span>
      <span class="register-overlap">${typeof overlap === "number" ? n(overlap) : "—"}<span class="register-chevron" aria-hidden="true">→</span></span>
    </button>`;
  }).join("") || `<p class="empty-row">No businesses in this stage.</p>`}`;
  if (!state.analysis && !state.pipelineAnalysisPromise) {
    state.pipelineAnalysisPromise = api("/api/analysis").then((analysis) => {
      state.analysis = analysis;
      state.pipelineAnalysisPromise = null;
      if (state.overview) renderPipelineRegister(state.overview);
    }).catch(() => { state.pipelineAnalysisPromise = null; });
  }
}

function blockedPairs(o = state.overview) {
  return (o?.needs_you || []).filter((item) => item.type === "blocked")
    .sort((a, b) => (b.risk || 0) - (a.risk || 0));
}

function doubleTakeRoute() {
  const parts = decodeURIComponent(location.hash.slice(1)).split("/");
  return parts[0] === "double-take" ? { slug: parts[1] || "", draft: parts[2] || "" } : { slug: "", draft: "" };
}

function renderDoubleTakePairs(o = state.overview) {
  if (!o || !$("#dt-pairs")) return;
  const pairs = blockedPairs(o);
  $("#doubletake-kicker").textContent = `${pairs.length} blocked drafts`;
  $("#tab-count-double-take").textContent = String(pairs.length);
  const route = doubleTakeRoute();
  $("#dt-pairs").innerHTML = pairs.map((pair, index) => {
    const selected = pair.business_id === route.slug && pair.draft_id === route.draft;
    return `<button type="button" class="dt-pair${selected ? " selected" : ""}" data-dt-slug="${esc(pair.business_id)}" data-dt-draft="${esc(pair.draft_id)}" aria-pressed="${selected}">
      <span class="label">${esc(pair.business || pair.business_id)} draft versus ${esc(pair.with_business || "another client")}</span>
      <span class="dt-pair-risk">${n(pair.risk)}</span>
    </button>`;
  }).join("") || `<p class="empty-row">No blocked drafts in this run.</p>`;
}

async function loadDoubleTakeFromLocation() {
  if (!state.overview || studioTabFromHash() !== "double-take") return;
  const pairs = blockedPairs();
  if (!pairs.length) {
    $("#dt-graph-box").innerHTML = `<p class="empty-row">No blocked drafts in this run.</p>`;
    $("#dt-inspector").innerHTML = "";
    return;
  }
  const route = doubleTakeRoute();
  const pair = pairs.find((item) => item.business_id === route.slug && item.draft_id === route.draft)
    || pairs[0];
  const href = `/#double-take/${encodeURIComponent(pair.business_id)}/${encodeURIComponent(pair.draft_id)}`;
  if (!route.slug || !route.draft || route.slug !== pair.business_id || route.draft !== pair.draft_id) history.replaceState({}, "", href);
  renderDoubleTakePairs();
  if (state.doubleTake.pair?.business_id === pair.business_id && state.doubleTake.pair?.draft_id === pair.draft_id && state.doubleTake.detail) {
    renderDoubleTakeGraph();
    return;
  }
  const load = ++state.doubleTake.loading;
  state.doubleTake.pair = pair;
  state.doubleTake.detail = null;
  state.doubleTake.version = 1;
  try {
    const detail = await api(`/api/doubletake/${encodeURIComponent(pair.business_id)}/${encodeURIComponent(pair.draft_id)}`);
    if (load !== state.doubleTake.loading) return;
    state.doubleTake.detail = detail;
    state.doubleTake.referenceCount = detail.reference_total;
    state.doubleTake.node = { type: "business", id: "business-0" };
    renderDoubleTakeGraph();
  } catch (error) {
    if (load === state.doubleTake.loading) $("#dt-graph-box").innerHTML = `<p class="empty-row">${esc(error.message)}</p>`;
  }
}

function selectDoubleTakePair(slug, draft) {
  history.pushState({}, "", `/#double-take/${encodeURIComponent(slug)}/${encodeURIComponent(draft)}`);
  syncStudioTab();
  loadDoubleTakeFromLocation();
}

function dtNodeMarkup(node, index, suffix = "") {
  const sub = node.hook ? `<span class="dt-node-hook">${esc(node.hook)}</span>` : "";
  const flagged = node.data?.flag ? " dt-node-flagged" : "";
  return `<button type="button" class="dt-node dt-node-${esc(node.type)}${flagged}" id="dt-node-${index}${suffix}" data-dt-node-index="${index}"${node.type === "technique" ? ` data-tech-name="${esc(node.name)}"` : ""} aria-pressed="${state.doubleTake.node?.id === node.id}">
    <span class="dt-node-type">${esc(node.label)}</span><b>${esc(node.name)}</b>${sub}
  </button>`;
}

function renderDoubleTakeGraph() {
  const detail = state.doubleTake.detail;
  const pair = state.doubleTake.pair;
  if (!detail || !pair) return;
  const v2 = state.doubleTake.version === 2 && detail.revision;
  const draft = v2 ? { ...detail.revision, version: 2 } : detail.draft;
  const flag = detail.flags.find((item) => item.business.id === pair.with_business_id) || detail.flags[0];
  const shared = flag?.shared || [];
  const sharedKey = shared.map((technique) => technique.id).sort().join("|");
  const sameTechFlags = detail.flags.filter((item) => item.shared.map((technique) => technique.id).sort().join("|") === sharedKey);
  const matches = sameTechFlags.length ? sameTechFlags : (flag ? [flag] : []);
  const targets = flag ? [flag, ...matches.filter((item) => item.business.id !== flag.business.id)] : matches;
  const graphTechniques = v2 ? draft.techniques : draft.techniques.filter((technique) => shared.some((item) => item.id === technique.id));
  const audienceRows = [...new Map((flag?.audiences || []).map((audience) => [audience.id, audience])).values()];
  const nodes = [];
  const add = (node) => { node.index = nodes.length; nodes.push(node); return node.index; };
  const draftIndex = add({ id: "draft", type: "draft", label: `Draft · v${draft.version}`, name: detail.business.name, hook: draft.hook, data: draft });
  const ownIndex = add({ id: "own-business", type: "business", label: `Business · ${detail.business.status}`, name: detail.business.name, data: { business: detail.business } });
  const techIndices = graphTechniques.map((technique, index) => {
    const matched = shared.find((item) => item.id === technique.id);
    return add({ id: `tech-${index}`, type: "technique", label: matched ? "Technique · rare" : "Technique", name: technique.name, data: { technique, shared: matched } });
  });
  const fingerprintIndex = add({
    id: "fingerprints", type: "fingerprint", label: "Fingerprints",
    name: v2 ? `No ${flag?.business.name || "business"} post uses these` : `${flag?.evidence.length || 0} of ${flag?.evidence_total_posts || 0} ${flag?.business.name || "business"} posts`,
    data: { flag, version: v2 ? 2 : 1 },
  });
  const businessIndices = targets.map((target, index) => add({
    id: `business-${index}`, type: "business", label: `Business · ${target.business.status}`, name: target.business.name,
    data: { business: target.business, flag: target },
  }));
  const audienceIndices = audienceRows.map((audience, index) => add({
    id: `audience-${index}`, type: "audience", label: "Audience", name: audience.name,
    data: { audience, flag },
  }));
  state.doubleTake.nodes = nodes;
  state.doubleTake.node = nodes.find((node) => node.id === state.doubleTake.node?.id) || nodes.find((node) => node.id === "business-0") || nodes[0];
  $("#dt-version-toggle").innerHTML = `<div class="segmented-control">${[
    { version: 1, label: "Draft v1 · blocked" },
    ...(detail.revision ? [{ version: 2, label: "Draft v2 · cleared" }] : []),
  ].map((item) => `<button type="button" data-dt-version="${item.version}" aria-pressed="${state.doubleTake.version === item.version}">${item.label}</button>`).join("")}</div>`;
  $("#dt-graph-box").dataset.version = v2 ? "2" : "1";
  $("#dt-graph-box").innerHTML = `<div class="dt-canvas">
    <svg class="dt-edge-svg" aria-hidden="true"></svg>
    <p class="label dt-label-top">What the draft reuses</p>
    <div class="dt-slot dt-slot-draft">${dtNodeMarkup(nodes[draftIndex], draftIndex)}</div>
    <div class="dt-slot dt-slot-tech">${techIndices.map((index) => dtNodeMarkup(nodes[index], index)).join("") || `<span class="muted">No techniques listed</span>`}</div>
    <div class="dt-slot dt-slot-proof">${dtNodeMarkup(nodes[fingerprintIndex], fingerprintIndex)}</div>
    <div class="dt-slot dt-slot-target">${businessIndices.map((index) => dtNodeMarkup(nodes[index], index)).join("")}</div>
    <p class="label dt-label-bottom">Who will see it</p>
    <div class="dt-slot dt-slot-own">${dtNodeMarkup(nodes[ownIndex], ownIndex)}</div>
    <div class="dt-slot dt-slot-audiences">${audienceIndices.map((index) => dtNodeMarkup(nodes[index], index)).join("") || `<span class="muted">No shared audiences returned</span>`}</div>
  </div>`;
  renderDoubleTakeInspector();
  renderDoubleTakeHistory();
  requestAnimationFrame(drawDoubleTakeEdges);
}

function dtFact(label, value, hint, className = "") {
  return `<div class="dt-fact${className ? ` ${className}` : ""}"><div class="dt-fact-copy"><span>${esc(label)}</span><small>${esc(hint)}</small></div><b class="mono">${esc(value)}</b></div>`;
}

function renderDoubleTakeInspector() {
  const node = state.doubleTake.nodes?.find((item) => item.id === state.doubleTake.node?.id);
  const detail = state.doubleTake.detail;
  if (!node || !detail) return;
  let facts = "";
  if (node.type === "technique") {
    const { technique, shared } = node.data;
    facts = [
      dtFact("Rarity", n(technique.rarity), "How strongly Double Take weighs this move as uncommon."),
      ...(shared ? [
        dtFact("Used in references", `${shared.ref_count} of ${state.doubleTake.referenceCount ?? "—"}`, "How many reference videos in the library show this move."),
        dtFact("Business signature share", shared.signature_share == null ? "—" : n(shared.signature_share), `How much of ${detail.business.name}'s signature uses this move.`),
      ] : []),
    ].join("");
  } else if (node.type === "fingerprint") {
    const items = node.data.version === 2 ? [] : node.data.flag?.evidence || [];
    const total = Math.max(items.length, Number(node.data.flag?.evidence_total_posts) || 0);
    facts = dtFact("Fingerprint evidence", `${items.length} of ${total} posts`, "Posts Double Take found that use these techniques.")
      + (items.length ? `<ul class="dt-evidence">${items.map((item) => `<li><span>${esc(item.hook)}</span>${item.views == null ? "" : `<small>Views: <b class="mono">${esc(item.views)}</b></small>`}</li>`).join("")}</ul>`
        : `<p class="muted">${node.data.version === 2 ? "No matching business post uses the revision's techniques." : "No evidence posts returned."}</p>`);
  } else if (node.type === "audience") {
    const audience = node.data.audience;
    const paths = audience.paths || [audience.path || []];
    const weight = (value) => value == null ? "—" : Number(value).toFixed(2);
    const names = detail.audience_names || {};
    const pathLabel = (path) => path.map((id, index) => `${index ? "overlaps with " : ""}${names[id] || "Audience"}`).join(" → ");
    facts = dtFact("Draft audience share", weight(audience.mine), `How much of ${detail.business.name}'s audience is this group: ${weight(audience.mine)} (0 = none, 1 = all).`)
      + dtFact("Other business audience share", weight(audience.theirs), `How much of ${node.data.flag.business.name}'s audience is this group: ${weight(audience.theirs)} (0 = none, 1 = all).`)
      + `<div class="dt-fact dt-audience-paths"><div class="dt-fact-copy"><span>Audience paths</span><small>How the two businesses' audience groups connect.</small></div><b>${paths.map((path) => `<span>${esc(pathLabel(path))}</span>`).join("")}</b></div>`;
  } else if (node.type === "business") {
    const { business, flag } = node.data;
    facts = dtFact("Status", business.status, "This business's current place in the agency pipeline.", "dt-fact-no-mono");
    if (flag) {
      facts += `<div class="dt-fact dt-risk-equation"><div class="dt-fact-copy"><span>Risk math</span><small>How Double Take combines the draft match and audience connection.</small></div>
        <div class="dt-risk-terms"><span><b>Similarity</b><b>${n(flag.similarity)}</b></span><span><b>Audience overlap</b><b>${n(flag.overlap)}</b></span>
        <span><b>Risk</b><b>${n(flag.risk)}</b></span><span><b>Block limit</b><b>${n(flag.limit)}</b></span></div></div>`;
    }
  } else {
    const draft = node.data;
    facts = dtFact("Version", draft.version, "Which version of the draft is shown.")
      + dtFact("Status", draft.status, "Whether Double Take blocked or cleared this version.", "dt-fact-no-mono")
      + `<div class="dt-fact dt-draft-hook"><div class="dt-fact-copy"><span>Hook</span><small>The opening line that frames this post.</small></div><b>${esc(draft.hook)}</b></div>`;
  }
  $("#dt-inspector").innerHTML = `<p class="label">${esc(node.label)}</p><h2>${esc(node.name)}</h2><div class="dt-facts">${facts}</div>
    <section class="dt-query"><p class="label">Found by the Double Take query</p><pre>${esc(detail.query?.cypher || "")}</pre></section>`;
}

function formatDecisionSentence(decision, business) {
  const text = String(decision.text || "");
  const name = business?.name || business?.id || "this business";
  const hook = (value) => String(value || "").trim().replace(/[.,!?;:…]+$/u, "");
  const producer = text.match(/^Draft v\d+: (.+)$/);
  if (producer) return `Producer wrote '${hook(producer[1])}'.`;
  const blocked = text.match(/^Double Take: blocked, resembles (.+)$/i);
  if (blocked) return `Double Take blocked a draft: it looked like ${blocked[1]}'s work.`;
  if (/^Double Take: cleared$/i.test(text)) return "Double Take cleared the draft.";
  const screened = text.match(/^Screened ([\w-]+): (.+)$/i);
  if (screened) return `Scout screened ${name}: ${screened[2]}.`;
  return `${decision.by || "Agent"}: ${text}`;
}

function renderDoubleTakeHistory() {
  const detail = state.doubleTake.detail;
  if (!detail) return;
  const decisions = (detail.next || []).map((item) => {
    return `<li class="dt-history-row"><span class="dt-history-icon">${agentIcon(item.by || "")}</span><span><span class="label">${esc(item.by || "Agent")}</span><span class="dt-history-sentence">${esc(formatDecisionSentence(item, detail.business))}</span>${item.rationale ? `<small>${esc(displayStudioCopy(item.rationale))}</small>` : ""}</span><time datetime="${esc(item.at || "")}" title="${esc(fullDateTime(item.at))}">${runDayLabel(item.day)}</time></li>`;
  }).join("");
  const later = (detail.later_blocks || []).map((item) => `<li><button type="button" class="dt-later-row" data-dt-slug="${esc(item.client_id)}" data-dt-draft="${esc(item.draft_id)}"><span class="label">Later</span><span>Later: ${esc(item.client)}'s draft was blocked against ${esc(detail.business.name)}${item.shared?.length ? ` (shared ${esc(item.shared.join(", "))}` : ""}${item.shared?.length && typeof item.risk === "number" ? ", " : ""}${typeof item.risk === "number" ? `risk ${n(item.risk)}` : ""}${item.shared?.length ? ")" : ""}.</span><b class="mono">${typeof item.risk === "number" ? n(item.risk) : ""}</b></button></li>`).join("");
  $("#dt-history").innerHTML = `<h2>What happened next</h2><ol class="dt-history-list">${decisions || `<li class="muted">No later decisions returned.</li>`}${later}</ol>`;
}

function drawDoubleTakeEdges() {
  const canvas = $("#dt-graph-box .dt-canvas");
  if (!canvas) return;
  const svg = canvas.querySelector(".dt-edge-svg");
  const nodes = state.doubleTake.nodes || [];
  const targets = nodes.filter((node) => node.type === "business" && node.id.startsWith("business-"));
  const techniques = nodes.filter((node) => node.type === "technique");
  const audiences = nodes.filter((node) => node.type === "audience");
  const fingerprint = nodes.find((node) => node.type === "fingerprint");
  const draft = nodes.find((node) => node.id === "draft");
  const own = nodes.find((node) => node.id === "own-business");
  const canvasRect = canvas.getBoundingClientRect();
  const paths = [];
  const rectOf = (node) => {
    const rect = document.getElementById(`dt-node-${node.index}`)?.getBoundingClientRect();
    return rect ? {
      left: rect.left - canvasRect.left,
      right: rect.right - canvasRect.left,
      top: rect.top - canvasRect.top,
      bottom: rect.bottom - canvasRect.top,
      centerX: rect.left + rect.width / 2 - canvasRect.left,
      centerY: rect.top + rect.height / 2 - canvasRect.top,
    } : null;
  };
  const path = (d) => paths.push(`<path class="dt-edge" d="${d}"/>`);
  const label = (text, x, y, anchor = "middle") => {
    paths.push(`<text class="dt-edge-label" text-anchor="${anchor}" x="${x}" y="${y}">${esc(text)}</text>`);
  };
  const fanOut = (source, destinations, caption = "", captionOffset = 0) => {
    const sourceRect = rectOf(source);
    const destinationRects = destinations.map(rectOf).filter(Boolean);
    if (!sourceRect || !destinationRects.length) return;
    const busX = (sourceRect.right + Math.min(...destinationRects.map((rect) => rect.left))) / 2;
    const ys = [sourceRect.centerY, ...destinationRects.map((rect) => rect.centerY)];
    let d = `M${sourceRect.right},${sourceRect.centerY} H${busX}`;
    if (Math.max(...ys) > Math.min(...ys)) d += ` M${busX},${Math.min(...ys)} V${Math.max(...ys)}`;
    destinationRects.forEach((rect) => { d += ` M${busX},${rect.centerY} H${rect.left}`; });
    path(d);
    if (caption) {
      const destinationY = destinationRects.reduce((sum, rect) => sum + rect.centerY, 0) / destinationRects.length;
      label(caption, busX, (sourceRect.centerY + destinationY) / 2);
    }
  };
  const fanIn = (sources, destination, caption = "", captionPosition = "top") => {
    const sourceRects = sources.map(rectOf).filter(Boolean);
    const destinationRect = rectOf(destination);
    if (!sourceRects.length || !destinationRect) return;
    const busX = (Math.max(...sourceRects.map((rect) => rect.right)) + destinationRect.left) / 2;
    const ys = [...sourceRects.map((rect) => rect.centerY), destinationRect.centerY];
    let d = `M${busX},${Math.min(...ys)} V${Math.max(...ys)}`;
    sourceRects.forEach((rect) => { d += ` M${rect.right},${rect.centerY} H${busX}`; });
    d += ` M${busX},${destinationRect.centerY} H${destinationRect.left}`;
    path(d);
    if (caption) label(caption, busX, (destinationRect.centerY + Math.min(...sourceRects.map((rect) => rect.centerY))) / 2);
  };
  if (draft && techniques.length && fingerprint) {
    fanOut(draft, techniques, "Uses");
    fanIn(techniques, fingerprint, "Evidence");
  }
  if (fingerprint && targets.length && $("#dt-graph-box").dataset.version === "1") fanOut(fingerprint, targets);
  if (draft && own) {
    const source = rectOf(draft);
    const destination = rectOf(own);
    if (source && destination) {
      path(`M${source.centerX},${source.bottom} V${destination.top}`);
      label("Of", source.centerX + 12, (source.bottom + destination.top) / 2, "start");
    }
  }
  if (own && audiences.length && targets.length) {
    fanOut(own, audiences, "Targets");
    fanIn(audiences, targets[0], "Overlap", "bottom");
  }
  svg.setAttribute("viewBox", `0 0 ${canvas.scrollWidth} ${canvas.scrollHeight}`);
  svg.innerHTML = paths.join("");
}

const dayDate = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
const runDayLabel = (day) => Number(day || 0) === 0 ? "First run" : `Day ${Number(day)}`;
const fullDateTime = (iso) => {
  const date = new Date(iso || "");
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString([], { dateStyle: "full", timeStyle: "long" });
};
const goalDueLabel = (value) => {
  if (!value) return "not set";
  const date = new Date(`${value}T12:00:00`);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
};

async function renderDays() {
  const a = await api("/api/activity");
  $("#dayloop").hidden = false;
  $("#next-day").hidden = !a.can_advance;
  $("#day-label").textContent = `${runDayLabel(a.day)} · ${dayDate(a.date)}`;
  const today = a.days.find((d) => d.day === a.day);
  const did = (today?.entries || []).filter((e) => e.agent !== "Board").length;
  const runActivityCount = (a.days || []).reduce((count, day) => count + day.entries.length, 0);
  $("#day-summary").textContent = !a.can_advance
    ? `Read-only copy: this is what the agents did in this run. ${plural(runActivityCount, "action", "actions")} recorded.`
    : a.day ? `Agents did ${plural(did, "thing", "things")} today on their own.` : "Press Next day and the agents start working.";
  const left = a.feed_left.length;
  $("#day-feed").textContent = left ? `${left} new ${left === 1 ? "lead" : "leads"} still to arrive.` : "";
  const byId = Object.fromEntries((state.overview?.businesses || []).map((b) => [b.id, b]));
  const days = a.days;
  $("#days").innerHTML = days.map((d) => `<li class="day"><h3 class="day-h">${runDayLabel(d.day)} <span class="muted">· ${esc(dayDate(d.date))}</span><span class="day-count">${d.entries.length} ${d.entries.length === 1 ? "action" : "actions"}</span></h3>
    <ul class="day-entries">${d.entries.slice().reverse().map((e) => {
      const blocked = /blocked/i.test(e.text || "");
      const board = e.agent === "Board";
      const kind = blocked ? "Double Take" : "Agent update";
      return `<li class="feed-entry${blocked ? " is-blocked" : ""}${board ? " is-board" : ""}">
        <span class="feed-icon" title="${esc(e.agent)}" aria-label="${esc(e.agent)}">${agentIcon(e.agent)}</span>
        <div class="feed-copy"><time class="feed-time" datetime="${esc(e.at || "")}" title="${esc(fullDateTime(e.at))}"></time><span class="label${blocked ? " blocked-kind" : ""}">${esc(e.agent)} · ${esc(kind)}</span>
          ${e.business_id ? `<span class="activity-business">${bizName(byId[e.business_id], { link: false })}</span>` : ""}
          <p>${esc(displayStudioCopy(e.text))}</p>${e.rationale ? `<small>${esc(displayStudioCopy(e.rationale))}</small>` : ""}
        </div>
      </li>`;
    }).join("")}</ul></li>`).join("")
    || `<li class="day empty muted">No agent activity yet.</li>`;
}

const LEAD_PRESETS = [
  { id: "dance", label: "Kids dance studio", category: "Kids gymnastics", neighborhood: "n_gramercy", targets: { A1: 0.9, A2: 0.5 } },
  { id: "coding", label: "Another coding club", category: "Kids coding", neighborhood: "n_flatiron", targets: { A2: 0.9, A4: 0.5 } },
  { id: "wine", label: "Wine bar", category: "Cafe", neighborhood: "n_nomad", targets: { A6: 0.9, A7: 0.5 } },
];

function renderLeadAudienceControls() {
  const fieldset = $("#aud-sliders");
  if (!fieldset || !state.overview) return;
  state.leadTargets ||= Object.fromEntries(state.overview.audiences.map((audience) => [audience.id, 0]));
  fieldset.innerHTML = `<legend>Customer groups</legend>${state.overview.audiences.map((audience) => {
    const selected = state.leadTargets[audience.id] ?? 0;
    const options = [["None", 0], ["Some", 0.5], ["Most", 0.9]];
    return `<div class="audience-choice"><span>${esc(audience.name)}</span><div class="audience-segments">${options.map(([label, value]) => `<label><input type="radio" name="aud-select-${esc(audience.id)}" value="${value}" data-audience="${esc(audience.id)}" ${Number(selected) === value ? "checked" : ""}><span>${label}</span></label>`).join("")}</div><input type="hidden" name="aud-${esc(audience.id)}" value="${esc(selected)}"></div>`;
  }).join("")}`;
}

function renderLeadPresets() {
  const host = $("#lead-presets");
  if (!host || !state.overview) return;
  if (!state.leadPreset) state.leadPreset = LEAD_PRESETS[0].id;
  host.innerHTML = `${LEAD_PRESETS.map((preset) => `<label class="lead-preset${state.leadPreset === preset.id ? " selected" : ""}"><input type="radio" name="lead-preset" value="${preset.id}" ${state.leadPreset === preset.id ? "checked" : ""}><span>${esc(preset.label)}</span></label>`).join("")}<label class="lead-preset${state.leadPreset === "own" ? " selected" : ""}"><input type="radio" name="lead-preset" value="own" ${state.leadPreset === "own" ? "checked" : ""}><span>Your own</span></label>`;
  if (state.leadPreset === "dance" && !state.leadPresetApplied) applyLeadPreset("dance");
}

function applyLeadPreset(id, schedule = true) {
  state.leadPreset = id;
  const ownFields = $("#lead-form .own-fields");
  ownFields.hidden = id !== "own";
  $("#lead-form [name=name]").required = id === "own";
  $("#lead-form [name=category]").required = id === "own";
  if (id !== "own") {
    const preset = LEAD_PRESETS.find((item) => item.id === id);
    if (preset) {
      $("#lead-form [name=name]").value = preset.label;
      $("#lead-form [name=category]").value = preset.category;
      $("#lead-neighborhood").value = preset.neighborhood;
      state.leadTargets = Object.fromEntries(state.overview.audiences.map((audience) => [audience.id, preset.targets[audience.id] || 0]));
    }
  }
  state.leadPresetApplied = true;
  renderLeadAudienceControls();
  $("#lead-presets").querySelectorAll(".lead-preset").forEach((label) => label.classList.toggle("selected", label.querySelector("input").value === id));
  if (schedule) scheduleLeadPreview();
}

let leadPreviewTimer;
function scheduleLeadPreview() {
  clearTimeout(leadPreviewTimer);
  leadPreviewTimer = setTimeout(runLeadPreview, 250);
}

function leadReadoutMarkup(result) {
  const verdict = result.verdict;
  const verdictLabel = VERDICT_LABELS[verdict] || String(verdict || "No verdict").replace(/_/g, " ");
  const thresholds = state.overview?.thresholds || {};
  const conflicts = (result.clients || []).map((client) => client.conflict).filter((value) => typeof value === "number");
  const max = Math.max(1, ...conflicts, thresholds.borderline || 0, thresholds.differentiate || 0);
  const marker = (value) => typeof value === "number" ? `left:${(value / max) * 100}%` : "";
  const tickLegend = [
    typeof thresholds.borderline === "number" ? `<span><i class="client-bar-swatch borderline"></i>Board-call line <b class="mono">${n(thresholds.borderline)}</b></span>` : "",
    typeof thresholds.differentiate === "number" ? `<span><i class="client-bar-swatch differentiate"></i>Distinct-angle line <b class="mono">${n(thresholds.differentiate)}</b></span>` : "",
  ].filter(Boolean).join("");
  return `<div class="lead-verdict"><h3><span class="status s-${statusKind(verdict)}" aria-hidden="true"><i></i></span>${esc(verdictLabel)}</h3></div>
    <p class="lead-reason">${esc(displayCopy(result.reason || ""))}</p>
    <div class="client-bars">${(result.clients || []).map((client) => `<div class="client-bar-row">
      <span>${esc(client.client)}</span><div class="client-bar" role="img" aria-label="${esc(client.client)} conflict ${n(client.conflict)}">
        <i class="client-bar-fill" style="width:${Math.max(0, Math.min(100, client.conflict / max * 100))}%"></i>
        ${typeof thresholds.borderline === "number" ? `<i class="client-bar-marker borderline" style="${marker(thresholds.borderline)}" title="Board-call line ${n(thresholds.borderline)}"></i>` : ""}
        ${typeof thresholds.differentiate === "number" ? `<i class="client-bar-marker differentiate" style="${marker(thresholds.differentiate)}" title="Differentiate line ${n(thresholds.differentiate)}"></i>` : ""}
      </div><b class="mono">${n(client.conflict)}</b></div>`).join("") || `<p class="muted">No client conflict returned.</p>`}
      <div class="client-bar-legend"><p>Each bar number is the conflict score with that client, using Scout's screening calculation.</p><div class="client-bar-legend-lines">${tickLegend}</div></div>
    </div>`;
}

let leadPreviewRequest = 0;
async function runLeadPreview(submitted = false) {
  const form = $("#lead-form");
  $("#lead-mobile-warning").hidden = true;
  const data = new FormData(form);
  const targets = {};
  for (const [key, value] of data.entries()) if (key.startsWith("aud-") && !key.startsWith("aud-select-") && Number(value) > 0) targets[key.slice(4)] = Number(value);
  if (state.leadPreset === "own" && (!String(data.get("name") || "").trim() || !String(data.get("category") || "").trim())) {
    $("#lead-result").innerHTML = `<p class="muted">Add a name and category, then Scout will check the client.</p>`;
    return;
  }
  if (!Object.keys(targets).length) {
    $("#lead-result").innerHTML = `<p class="muted">Choose at least one customer group to run the check.</p>`;
    if (submitted && window.matchMedia("(max-width: 760px)").matches) {
      $("#lead-mobile-warning").textContent = "Choose at least one customer group to run the check.";
      $("#lead-mobile-warning").hidden = false;
    }
    return;
  }
  const request = ++leadPreviewRequest;
  try {
    const result = await api("/api/try/lead", { method: "POST", body: JSON.stringify({
      name: data.get("name"), category: data.get("category"), neighborhood: data.get("neighborhood"), targets, preview: true,
    }) });
    if (request === leadPreviewRequest) {
      $("#lead-result").innerHTML = leadReadoutMarkup(result);
      if (submitted && window.matchMedia("(max-width: 760px)").matches && state.mobileTryStep === 2) {
        state.mobileTryStep = 3;
        updateTryMobileFlow();
      }
    }
  } catch (error) {
    if (request === leadPreviewRequest) {
      $("#lead-result").innerHTML = `<p class="muted">Scout could not finish this check: ${esc(error.message)}</p>`;
      if (submitted && window.matchMedia("(max-width: 760px)").matches && state.mobileTryStep === 2) {
        state.mobileTryStep = 3;
        updateTryMobileFlow();
      }
    }
  }
}

document.addEventListener("click", async (e) => {
  const b = e.target.closest("#next-day");
  if (!b) return;
  b.disabled = true;
  const label = b.innerHTML;
  b.textContent = "Agents are working…";
  let busy = false;
  try {
    await api("/api/next-day", { method: "POST" });
    await refresh();
  } catch (err) {
    if (err.status === 409 && err.message === "agents are busy") busy = true;
    else alert(err.message);
  } finally {
    b.disabled = false;
    b.innerHTML = label;
  }
  if (busy) $("#step-latest").textContent = "Agents are working…";
});

document.querySelectorAll(".fold-toggle").forEach((button) => button.addEventListener("click", () => {
  const target = document.getElementById(button.getAttribute("aria-controls"));
  const open = target.classList.toggle("folded") === false;
  button.setAttribute("aria-expanded", String(open));
  if (open) target.scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth", block: "nearest" });
}));

async function feed() {
  const ds = await api("/api/decisions");
  const businesses = state.overview?.businesses || [];
  const sorted = [...ds].sort((a, z) => Date.parse(z.at || 0) - Date.parse(a.at || 0));
  const groups = new Map();
  sorted.forEach((d) => {
    const slug = d.graph?.startsWith("client:") ? d.graph.slice(7) : "";
    const biz = businesses.find((b) => b.id === slug)
      || (d.graph === "agency" ? businesses.find((b) => b.id === subjectOf(d.text || "", businesses)) : null);
    const key = biz?.id || "agency";
    if (!groups.has(key)) groups.set(key, { biz, entries: [] });
    groups.get(key).entries.push(d);
  });
  const cleanHook = (hook) => String(hook || "").trim().replace(/[.,!?;:…]+$/u, "");
  const sentenceFor = (d, b) => {
    const text = String(d.text || "");
    const name = b?.name || b?.id || "this business";
    let m;
    if ((m = text.match(/^Screened ([\w-]+): (.+)$/i))) {
      const verdict = ({ borderline: "board call", pursue_differentiated: "pursue with a distinct angle", pursue: "cleared to pursue" })[m[2]] || m[2];
      return `Scout screened ${name}: ${verdict}.`;
    }
    if ((m = text.match(/^Draft v\d+: (.+)$/))) return `Producer wrote '${cleanHook(m[1])}'.`;
    if ((m = text.match(/^Double Take: blocked, resembles (.+)$/i))) return `Double Take blocked a draft: it looked like ${m[1]}'s work.`;
    if (/^Double Take: cleared$/i.test(text)) return "Double Take cleared the draft.";
    if (/^Board approve: Pitch$/i.test(text)) return "The board approved the pitch.";
    if (/^Status: signed$/i.test(text) || new RegExp(`\\b${b?.id || "____"} is now signed\\b`, "i").test(text)) return `The board signed ${name}.`;
    if (/^Status: pitched$/i.test(text) || new RegExp(`\\b${b?.id || "____"} is now pitched\\b`, "i").test(text)) return `Account Manager pitched ${name}.`;
    if (/^Status: pursued$/i.test(text) || new RegExp(`\\b${b?.id || "____"} is now pursued\\b`, "i").test(text)) return `Scout pursued ${name}.`;
    if (/^Pitch angle:/i.test(text)) return `Account Manager prepared a pitch for ${name}.`;
    if (/^Retired goal$/i.test(text)) return "The board retired a goal.";
    if (/^Goal \(hypothesized\):/i.test(text)) return "Researcher recorded a goal hypothesis.";
    if (/^Recorded (channel|competitor|audience) finding$/i.test(text)) return `Researcher recorded a ${text.match(/^Recorded (\w+)/i)[1]} finding.`;
    if (/^Audited \d+ posts$/i.test(text)) return `Auditor ${text.toLowerCase()}.`;
    if (/^Plan for /i.test(text)) return `Strategist prepared ${text.replace(/^Plan for /i, "a plan for ")}.`;
    if (/^Taste profile v\d+$/i.test(text)) return "Style Director created a taste profile.";
    return `${d.by || "Agent"}: ${text}`;
  };
  const renderGroup = ([key, group]) => {
    const entries = group.entries;
    const statements = [];
    for (let i = 0; i < entries.length; i++) {
      const d = entries[i], next = entries[i + 1];
      const clearPair = d.by === "Standards" && /^Double Take: cleared$/i.test(d.text || "")
        && next?.by === "Producer" && next.graph === d.graph
        && (d.affects || []).includes("Draft") && (next.affects || []).includes("Draft")
        && Date.parse(d.at || 0) - Date.parse(next.at || 0) < 5000;
      if (clearPair) {
        const hook = next.text.match(/^Draft v\d+: (.+)$/)?.[1];
        if (hook) {
          statements.push({ sentence: `Producer wrote '${cleanHook(hook)}', and Double Take cleared it.`, records: [d, next], by: next.by });
          i++;
          continue;
        }
      }
      statements.push({ sentence: sentenceFor(d, group.biz), records: [d], by: d.by });
    }
    const collapsed = [];
    statements.forEach((entry) => {
      const last = collapsed[collapsed.length - 1];
      if (last?.sentence === entry.sentence) {
        last.count++;
        last.records.push(...entry.records);
      } else collapsed.push({ ...entry, count: 1 });
    });
    const title = group.biz ? bizName(group.biz) : `<h3>Across the agency</h3>`;
    let previousDay = null;
    const list = collapsed.map((entry, i) => {
      const record = entry.records[0];
      const day = Number(record.day || 0);
      const newDay = day !== previousDay;
      previousDay = day;
      const blocked = entry.records.some((item) => /blocked/i.test(item.text || ""));
      const board = String(entry.by).toLowerCase() === "board";
      const kind = blocked ? "Double Take" : record.affects?.[0] || "Update";
      const rationale = [...new Set(entry.records.map((item) => item.rationale).filter(Boolean))][0];
      return `${newDay ? `<li class="feed-day-head${i >= 5 ? " feed-extra" : ""}"${i >= 5 ? " hidden" : ""}><span class="label">${runDayLabel(day)}</span></li>` : ""}
        <li class="feed-entry${i >= 5 ? " feed-extra" : ""}${blocked ? " is-blocked" : ""}${board ? " is-board" : ""}"${i >= 5 ? " hidden" : ""}>
          <span class="feed-icon">${agentIcon(entry.by || record.by || "")}</span>
          <div class="feed-copy"><time class="feed-time" datetime="${esc(record.at || "")}" title="${esc(fullDateTime(record.at))}"></time><span class="label${blocked ? " blocked-kind" : ""}">${esc(entry.by || record.by || "Agent")} · ${esc(kind)}</span>
            <p>${esc(entry.sentence)}${entry.count > 1 ? ` <span class="feed-count">×${entry.count}</span>` : ""}</p>
            ${rationale ? `<small>${esc(displayStudioCopy(rationale))}</small>` : ""}
          </div>
        </li>`;
    }).join("");
    return `<li class="feed-group"><div class="feed-group-head">${title}</div><ol class="feed-entries">${list}</ol>${collapsed.length > 5 ? `<button type="button" class="text-button feed-expand" aria-expanded="false">Show all ${entries.length}</button>` : ""}</li>`;
  };
  $("#feed").innerHTML = [...groups.entries()].map(renderGroup).join("")
    || `<li class="empty">No decisions yet. Run the steps above.</li>`;
}

$("#feed").addEventListener("click", (e) => {
  const button = e.target.closest(".feed-expand");
  if (!button) return;
  const open = button.getAttribute("aria-expanded") !== "true";
  button.setAttribute("aria-expanded", String(open));
  button.closest(".feed-group").querySelectorAll(".feed-extra").forEach((item) => { item.hidden = !open; });
  button.textContent = open ? "Show fewer" : `Show all ${button.closest(".feed-group").querySelectorAll(".feed-entries > li").length}`;
});

async function loadAnalysis() {
  const [analysis, decisions] = await Promise.all([api("/api/analysis"), api("/api/decisions")]);
  state.analysis = analysis;
  renderAnalysis(analysis, state.overview, decisions);
  lastNetW = $("#audience-net")?.clientWidth || 0;
}

async function loadAnalysisFromLocation() {
  const params = new URLSearchParams(location.search);
  const lead = params.get("lead");
  const draft = params.get("draft");
  if (lead) state.netLead = lead;
  await loadAnalysis();
  if (draft) {
    document.querySelectorAll(".dt-card.is-focused").forEach((card) => card.classList.remove("is-focused"));
    const card = document.querySelector(`.dt-card[data-draft="${CSS.escape(draft)}"]`);
    if (!card) return;
    card.classList.add("is-focused");
    card.tabIndex = -1;
    card.focus({ preventScroll: true });
    card.scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth", block: "center" });
  } else if (lead) {
    $("#ch-screening").scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth", block: "start" });
  }
}

// ---------------------------------------------------------------- analysis: a visual tour of the graph

const pretty = (id) => ({
  scout: "Scout", researcher: "Researcher", producer: "Producer", standards: "Standards",
  style_director: "Style director", strategist: "Strategist", account_manager: "Account manager",
  board: "Board", auditor: "Auditor",
}[String(id || "")] || String(id || "").replace(/_/g, " "));
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const SVGNS = "http://www.w3.org/2000/svg";

// Draw red strings between element pairs inside a positioned container.
function connect(container, svg, pairs, { bend = 0.5 } = {}) {
  const box = container.getBoundingClientRect();
  svg.setAttribute("viewBox", `0 0 ${box.width} ${box.height}`);
  svg.innerHTML = pairs.map(([a, b, opts = {}]) => {
    if (!a || !b) return "";
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    if (!ra.width || !rb.width) return "";
    const leftToRight = ra.left + ra.width / 2 <= rb.left + rb.width / 2;
    const x1 = (leftToRight ? ra.right : ra.left) - box.left, y1 = ra.top + ra.height / 2 - box.top;
    const x2 = (leftToRight ? rb.left : rb.right) - box.left, y2 = rb.top + rb.height / 2 - box.top;
    const dx = (x2 - x1) * bend;
    const w = opts.width ? ` style="stroke-width:${opts.width}"` : "";
    return `<path${w} d="M${x1.toFixed(1)} ${y1.toFixed(1)} C${(x1 + dx).toFixed(1)} ${y1.toFixed(1)} ${(x2 - dx).toFixed(1)} ${y2.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}"/>`
      + `<circle cx="${x1.toFixed(1)}" cy="${y1.toFixed(1)}" r="3.5"/><circle cx="${x2.toFixed(1)}" cy="${y2.toFixed(1)}" r="3.5"/>`;
  }).join("");
}

function renderAnalysis(analysis, overview, decisions) {
  const t = analysis.thresholds || {};
  renderArchitecture(analysis, overview);
  renderScreening(analysis, overview);
  renderDoubleTake(analysis);
  renderTerritory(analysis, overview);
  renderAccess(analysis);
  renderIntroProof(analysis, overview);
  renderFindings(analysis);

  // raw data
  $("#thresholds").innerHTML = [
    ["Rare technique", t.rare], ["Flag risk", t.flag_risk], ["Distinct angle at", t.differentiate], ["Board call at", t.borderline],
  ].map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${n(value)}</dd></div>`).join("");
  $("#raw-decisions").innerHTML = `<thead><tr><th scope="col">Agent</th><th scope="col">Graph</th><th scope="col">Text</th><th scope="col">Rationale</th></tr></thead>
    <tbody>${decisions.map((d) => `<tr><th scope="row">${esc(d.by)}</th><td class="mono">${esc(d.graph)}</td><td>${esc(d.text)}</td><td>${esc(d.rationale)}</td></tr>`).join("")
      || `<tr><td colspan="4" class="muted">No decisions yet.</td></tr>`}</tbody>`;
  const log = overview?.log || [];
  renderLog(log);
  const logEl = $("#log");
  const logNote = $("#run-log-note");
  logEl.hidden = log.length === 0;
  logNote.hidden = log.length > 0;
  if (!log.length) {
    logNote.textContent = overview?.readonly
      ? "This workspace started with the run already finished, so there is no live run log. The decisions table above is the full history."
      : "No steps run yet.";
  }
  requestAnimationFrame(redrawAnalysis);
}

// 1. architecture: private client graphs around the shared agency graph, joined by P1 projections
function renderArchitecture(analysis, overview) {
  const byId = Object.fromEntries((overview?.businesses || []).map((b) => [b.id, b]));
  const agency = analysis.graphs.find((g) => g.name === "agency") || { nodes: {}, edges: {} };
  const clients = analysis.graphs.filter((g) => g.name.startsWith("client:"));
  const count = (g, label) => (g.nodes || {})[label] || 0;
  const edge = (label) => (agency.edges || {})[label] || 0;
  const clientBox = (g) => {
    const slug = g.name.slice(7), b = byId[slug] || {};
    const parts = [["Post", "post", "posts"], ["Draft", "draft", "drafts"], ["Goal", "goal", "goals"], ["Decision", "decision", "decisions"]]
      .map(([label, one, many]) => [count(g, label), one, many]).filter(([c]) => c > 0);
    return `<article class="gbox client" data-slug="${esc(slug)}">
      <div class="gbox-head"><code>${esc(g.name)}</code>${b.status ? chip(b.status) : ""}</div>
      <p class="gname">${b.id ? bizName(b, { link: false }) : esc(slug)}</p>
      <p class="gbox-counts">${parts.map(([c, one, many]) => `<span><b>${c}</b> ${c === 1 ? one : many}</span>`).join("") || "<span>empty</span>"}</p>
      <p class="gbox-runs">Private. Q4 traces and Q5 stale-draft checks run here.</p>
    </article>`;
  };
  const group = (title, labels) => `<div><p class="grp">${title}</p><ul>${labels.map((l) => `<li><span>${l}</span><b>${count(agency, l)}</b></li>`).join("")}</ul></div>`;
  const half = Math.ceil(clients.length / 2);
  $("#graph-cards").innerHTML = `
    <svg class="arch-svg" id="arch-svg" aria-hidden="true"></svg>
    <div class="arch-col left">${clients.slice(0, half).map(clientBox).join("")}</div>
    <div class="arch-col center"><article class="gbox agency" id="agency-box">
      <div class="gbox-head"><code>agency</code><span class="label">shared graph</span></div>
      <div class="agency-groups">
        ${group("Who reaches whom", ["Business", "Audience", "Neighborhood"])}
        ${group("Creative vocabulary", ["Technique", "Style", "Reference"])}
        ${group("Projected from clients", ["Fingerprint"])}
        ${group("Accountability", ["Agent", "Decision"])}
      </div>
      <p class="gbox-counts"><span><b>${edge("TARGETS")}</b> audience targets</span><span><b>${edge("OVERLAPS")}</b> audience overlaps</span><span><b>${edge("SIGNATURE")}</b> signatures</span><span><b>${edge("USES")}</b> technique uses</span></p>
      <p class="gbox-runs">Cross-client checks run here: <span class="qtag">Q0</span><span class="qtag">Q1</span><span class="qtag">Q2</span><span class="qtag">Q3</span></p>
    </article></div>
    <div class="arch-col right">${clients.slice(half).map(clientBox).join("")}</div>`;
  $("#arch-legend").innerHTML = `${TIE}<span>Each red string is P1: a draft's Fingerprint projected into <code>agency</code>. It carries technique IDs only.</span>`;
}

function drawArchitecture() {
  const wrap = $("#graph-cards"), svg = $("#arch-svg"), hub = $("#agency-box");
  if (!wrap || !svg || !hub || getComputedStyle(svg).display === "none") return;
  const boxes = [...wrap.querySelectorAll(".gbox.client")];
  connect(wrap, svg, boxes.map((b) => [b, hub]), { bend: 0.55 });
}

// 2. screening: lead x client heat table + the audience graph Q1 walks for the selected lead
function bin(v) { return v < 0.25 ? 0 : v < 0.5 ? 1 : v < 0.9 ? 2 : v < 1.3 ? 3 : 4; }

function renderScreening(analysis, overview) {
  const t = analysis.thresholds || {};
  const clients = overview?.clients || [];
  const leads = analysis.screening || [];
  if (!state.netLead || !leads.some((r) => r.id === state.netLead)) {
    state.netLead = [...leads].sort((a, z) => (z.max_conflict || 0) - (a.max_conflict || 0))[0]?.id || null;
  }
  $("#lead-picker").innerHTML = [...leads].sort((a, z) => (z.max_conflict || 0) - (a.max_conflict || 0))
    .map((row) => `<button type="button" class="lead-chip" data-lead="${esc(row.id)}" aria-pressed="${row.id === state.netLead}"><span class="lead-chip-name">${bizName(bizById(row.id) || { id: row.id, name: row.name }, { link: false })}</span>${verdictStatus(row.verdict)}</button>`).join("");
  $("#screening-legend").textContent = `Conflict is the sum of path weights to one client. At ${n(t.borderline)} or more it is a board call; at ${n(t.differentiate)} or more Scout recommends a distinct content angle.`;
  $("#screening-table").innerHTML = `<caption class="sr-only">Conflict between each lead and each signed client</caption>
    <thead><tr><th scope="col">Lead</th>${clients.map((c) => `<th scope="col">${esc(c.name)}</th>`).join("")}<th scope="col">Verdict</th></tr></thead>
    <tbody>${leads.map((row) => {
      const cells = clients.map((c) => {
        const v = (row.clients || []).find((x) => x.client_id === c.id)?.conflict || 0;
        return `<td><span class="cell b${bin(v)}">${n(v)}</span></td>`;
      }).join("");
      const sel = row.id === state.netLead;
      return `<tr class="${sel ? "sel" : ""}"><th scope="row"><button type="button" class="lead-btn" data-lead="${esc(row.id)}" aria-pressed="${sel}">${esc(row.name)}<small>${esc(row.category)} · ${esc(row.neighborhood)}</small><span class="mobile-verdict">${verdictStatus(row.verdict)}</span></button></th>${cells}<td class="v">${verdictStatus(row.verdict)}</td></tr>`;
    }).join("") || `<tr><td colspan="${clients.length + 2}" class="muted">No leads to screen.</td></tr>`}</tbody>`;
  renderNet();
}

function renderNet() {
  const a = state.analysis, o = state.overview, host = $("#audience-net");
  if (!a || !o || !host || !a.audience_graph) return;
  const row = a.screening.find((r) => r.id === state.netLead);
  const ag = a.audience_graph, clients = o.clients || [], leads = a.screening;
  const fit = host.clientWidth - 8, W = Math.max(760, fit), rowH = 34, top = 34;
  const H = top + Math.max(leads.length, ag.audiences.length + 1, clients.length) * rowH + 12;
  const audName = Object.fromEntries(ag.audiences.map((x) => [x.name, x.id]));
  const ctx = (renderNet.ctx ||= document.createElement("canvas").getContext("2d"));
  ctx.font = `12.5px ${getComputedStyle(document.body).fontFamily}`;
  const pillW = (name) => Math.min(W - 2 * 180 - 110, ctx.measureText(name).width + 26);
  const xL = 180, xR = W - 180, xM = (xL + xR) / 2;
  const ys = (list, i) => top + 10 + (i + 0.5) * ((H - top - 20) / list.length);
  const P = {};
  leads.forEach((l, i) => (P["b:" + l.id] = { x: xL, y: ys(leads, i) }));
  clients.forEach((c, i) => (P["b:" + c.id] = { x: xR, y: ys(clients, i) }));
  ag.audiences.forEach((x, i) => { const w = pillW(x.name); P["a:" + x.id] = { x: xM, y: ys(ag.audiences, i), w }; });

  // heat on the edges the selected lead's paths actually use
  const hot = {}, add = (k, v) => (hot[k] = (hot[k] || 0) + v);
  const onA = new Set(), clientScore = {};
  (row?.clients || []).forEach((c) => {
    clientScore[c.client_id] = c.conflict;
    (c.paths || []).forEach((p) => {
      const parts = p.via.split(/(?: -> | → overlaps with )/).map((x) => audName[x] || x);
      if (parts.some((x) => !x)) return;
      const [first, last] = [parts[0], parts[parts.length - 1]];
      add(`t:${row.id}:${first}`, p.conflict); onA.add(first); onA.add(last);
      if (parts.length === 2) add(`o:${[first, last].sort().join(":")}`, p.conflict);
      add(`t:${c.client_id}:${last}`, p.conflict);
    });
  });
  const leadIds = new Set(leads.map((l) => l.id)), clientIds = new Set(clients.map((c) => c.id));
  const edgePath = (b, x) => {
    const pb = P["b:" + b], px = P["a:" + x];
    const left = pb.x < px.x, ex = left ? px.x - px.w / 2 : px.x + px.w / 2, sx = left ? pb.x + 6 : pb.x - 6;
    const dx = (ex - sx) * 0.5;
    return `M${sx} ${pb.y} C${sx + dx} ${pb.y} ${ex - dx} ${px.y} ${ex} ${px.y}`;
  };
  let edges = "";
  ag.targets.forEach((tg) => {
    const isLead = leadIds.has(tg.business_id), isClient = clientIds.has(tg.business_id);
    if (!isLead && !isClient) return;
    const k = `t:${tg.business_id}:${tg.audience_id}`, h = hot[k];
    if (isLead && tg.business_id !== state.netLead && !h) {
      edges += `<path class="e dim" d="${edgePath(tg.business_id, tg.audience_id)}" stroke-width="1"/>`;
    } else {
      edges += `<path class="e${h ? " hot" : ""}" d="${edgePath(tg.business_id, tg.audience_id)}" stroke-width="${h ? (1.5 + h * 7).toFixed(1) : (0.8 + tg.weight * 1.6).toFixed(1)}"><title>${esc(tg.business_id)} targets ${esc(tg.audience_id)} (weight ${n(tg.weight)})</title></path>`;
    }
  });
  ag.overlaps.forEach((ov) => {
    const pa = P["a:" + ov.a], pb = P["a:" + ov.b];
    if (!pa || !pb) return;
    const h = hot[`o:${[ov.a, ov.b].sort().join(":")}`];
    const x1 = pa.x + pa.w / 2, x2 = pb.x + pb.w / 2, bulge = 26 + Math.abs(pa.y - pb.y) * 0.35;
    const cx = Math.max(x1, x2) + bulge;
    edges += `<path class="e ov${h ? " hot" : ""}" d="M${x1} ${pa.y} C${cx} ${pa.y} ${cx} ${pb.y} ${x2} ${pb.y}" stroke-width="${h ? (1.5 + h * 7).toFixed(1) : 1.2}"><title>Audiences overlap (share ${n(ov.share)})</title></path>`;
  });
  const top1 = Object.entries(clientScore).sort((x, y) => y[1] - x[1])[0]?.[0];
  const nodes = [
    ...leads.map((l) => { const p = P["b:" + l.id], sel = l.id === state.netLead;
      return `<g class="n lead${sel ? " sel" : " dim"}"><circle cx="${p.x}" cy="${p.y}" r="${sel ? 7 : 5}"/><text x="${p.x - 14}" y="${p.y + 4}" text-anchor="end"${sel ? ' font-weight="700"' : ""}>${esc(l.name)}</text></g>`; }),
    ...ag.audiences.map((x) => { const p = P["a:" + x.id], on = onA.has(x.id);
      return `<g class="n aud${on ? " on" : " dim"}"><rect x="${p.x - p.w / 2}" y="${p.y - 12}" width="${p.w}" height="24" rx="12" fill="#FCFAF9" stroke="${on ? "#BE2A3A" : "#B8A9A6"}" stroke-width="${on ? 2.5 : 1.5}"/><text x="${p.x}" y="${p.y + 4}" text-anchor="middle">${esc(x.name)}</text></g>`; }),
    ...clients.map((c) => { const p = P["b:" + c.id], sc = clientScore[c.id];
      return `<g class="n client${c.id === top1 ? " on" : ""}"><circle cx="${p.x}" cy="${p.y}" r="7"/><text x="${p.x + 14}" y="${p.y + 4}">${esc(c.name)}</text>${sc ? `<text class="score" x="${p.x + 14}" y="${p.y + 20}">${n(sc)}</text>` : ""}</g>`; }),
  ].join("");
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}"${W > fit ? ` style="width:${W}px"` : ""} role="img" aria-label="Audience graph for ${esc(row?.name || "the selected lead")}: lead audiences, overlapping audiences and signed clients">
    <text class="col-label" x="${xL}" y="18" text-anchor="end">Leads</text>
    <text class="col-label" x="${xM}" y="18" text-anchor="middle">Audiences</text>
    <text class="col-label" x="${xR}" y="18">Signed clients</text>
    ${edges}${nodes}</svg>`;
  renderVerdictMath(row);
}

function renderVerdictMath(row) {
  const t = state.analysis?.thresholds || {};
  if (!row) { $("#verdict-math").innerHTML = `<p class="muted">Pick a lead.</p>`; return; }
  const cl = [...(row.clients || [])].sort((a, z) => z.conflict - a.conflict);
  const max = Math.max(2, (cl[0]?.conflict || 0) * 1.1);
  const pct = (v) => `${Math.min(100, (v / max) * 100).toFixed(1)}%`;
  $("#verdict-math").innerHTML = `<div class="vm-head"><b>${esc(row.name)}</b>${verdictStatus(row.verdict)}</div>
    <p class="vm-reason">${esc(row.reason)}</p>
    ${row.competitors?.length ? `<p class="vm-reason">Same category as ${row.competitors.map((c) => esc(c.client)).join(", ")} in the same neighborhood.</p>` : ""}
    <div class="vm-scale" aria-hidden="true"><span style="left:${pct(t.borderline)}">Board call ${n(t.borderline)}</span><span style="left:${pct(t.differentiate)}">Distinct angle ${n(t.differentiate)}</span></div>
    <ul class="vm-bars">${cl.map((c, i) => `<li><span>${esc(c.client)}</span>
      <span class="vm-track" role="img" aria-label="conflict ${n(c.conflict)}"><span class="vm-fill${i === 0 ? " top" : ""}" style="width:${pct(c.conflict)}"></span><span class="vm-tick" style="left:${pct(t.borderline)}"></span><span class="vm-tick" style="left:${pct(t.differentiate)}"></span></span>
      <span class="vm-val">${n(c.conflict)}</span></li>`).join("") || `<li class="muted">No audience paths to any signed client.</li>`}</ul>`;
}

$("#ch-screening").addEventListener("click", (e) => {
  const b = e.target.closest("[data-lead]");
  if (!b) return;
  state.netLead = b.dataset.lead;
  document.querySelectorAll("#ch-screening [data-lead]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.lead === state.netLead));
  });
  document.querySelectorAll("#screening-table tbody tr").forEach((tr) => {
    const on = tr.querySelector("[data-lead]")?.dataset.lead === state.netLead;
    tr.classList.toggle("sel", on);
  });
  renderNet();
});

$("#territory-all").addEventListener("click", () => {
  state.territoryAll = !state.territoryAll;
  if (state.analysis) renderTerritory(state.analysis, state.overview);
});

// 3. double take: each blocked draft as a small graph, then the risk arithmetic
function renderDoubleTake(analysis) {
  const t = analysis.thresholds || {};
  const groups = {};
  analysis.double_take.forEach((f) => (groups[f.draft] ||= { ...f, flags: [] }).flags.push(f));
  const list = Object.values(groups);
  $("#cleared-checks").textContent = `${plural(analysis.cleared_checks, "check", "checks")} cleared and ${plural(list.length, "draft was", "drafts were")} blocked in this run.`;
  $("#double-take-table").innerHTML = list.map((g) => {
    const techs = [...new Set(g.flags.flatMap((f) => f.shared || []))];
      return `<article class="dt-card" data-draft="${esc(g.draft)}">
      <div class="dt-graph">
        <svg class="dt-svg" aria-hidden="true"></svg>
        <div class="dt-col"><div class="dt-node draft"><span class="k">Blocked draft</span><b>${bizName(bizByName(g.client), { link: false })}</b><span class="hook">“${esc(g.draft_hook || g.draft)}”</span></div></div>
        <div class="dt-col dt-techs">${techs.map((x) => `<span class="dt-tech" data-tech="${esc(x)}">${techChip(x)}</span>`).join("")}</div>
        <div class="dt-col">${g.flags.map((f) => `<div class="dt-node other" data-shared="${esc((f.shared || []).join("|"))}"><span class="k">Looks like</span><b>${bizName(bizByName(f.with_business), { link: false })}</b><span class="hook">${plural((f.evidence || []).length, "piece", "pieces")} of its work already use${(f.evidence || []).length === 1 ? "s" : ""} these</span></div>`).join("")}</div>
      </div>
      <ul class="dt-risk">${g.flags.map((f) => `<li>
        <span class="dt-eq">vs ${bizName(bizByName(f.with_business), { link: false })}: similarity ${n(f.similarity)} × audience overlap ${n(f.overlap)} = <b>risk ${n(f.risk)}</b></span>
        <span class="dt-bar" role="img" aria-label="risk ${n(f.risk)} against a threshold of ${n(f.flag_risk ?? t.flag_risk)}"><span class="fill" style="width:${Math.min(100, f.risk * 100)}%"></span><span class="tick" data-l="${n(f.flag_risk ?? t.flag_risk)}" style="left:${(f.flag_risk ?? t.flag_risk) * 100}%"></span></span>
      </li>`).join("")}</ul>
    </article>`;
  }).join("") || `<p class="empty-row">No drafts blocked yet. Run step 3 to send spec posts through Double Take.</p>`;
}

function drawDoubleTake() {
  document.querySelectorAll(".dt-graph").forEach((graph) => {
    const svg = graph.querySelector(".dt-svg");
    if (!svg || getComputedStyle(svg).display === "none") return;
    const draft = graph.querySelector(".dt-node.draft");
    const techs = [...graph.querySelectorAll(".dt-tech")];
    const others = [...graph.querySelectorAll(".dt-node.other")];
    const pairs = techs.map((tch) => [draft, tch]);
    others.forEach((o) => o.dataset.shared.split("|").forEach((name) => {
      const tch = techs.find((x) => x.dataset.tech === name);
      if (tch) pairs.push([tch, o]);
    }));
    connect(graph, svg, pairs, { bend: 0.5 });
  });
}

// 4. territory: who claims which rare technique as a signature
function renderTerritory(analysis, overview) {
  const status = Object.fromEntries((overview?.businesses || []).map((b) => [b.id, b.status]));
  const sigs = analysis.signatures;
  const hotCols = new Set(), hotCells = new Set();
  analysis.double_take.forEach((f) => (f.shared || []).forEach((x) => {
    hotCols.add(x); hotCells.add(`${f.client_id}|${x}`); hotCells.add(`${f.with_business_id}|${x}`);
  }));
  const techs = {};
  sigs.forEach((s) => { const x = (techs[s.technique] ||= { name: s.technique, rarity: s.rarity, by: new Set() }); x.by.add(s.business_id); });
  const cols = Object.values(techs).sort((a, z) => hotCols.has(z.name) - hotCols.has(a.name) || z.by.size - a.by.size || z.rarity - a.rarity);
  const hotCount = cols.filter((c) => hotCols.has(c.name)).length;
  const defaultCount = Math.min(cols.length, Math.max(12, hotCount));
  const visibleCols = state.territoryAll ? cols : cols.slice(0, Math.max(12, hotCount));
  const rows = [...new Map(sigs.map((s) => [s.business_id, s.business])).entries()]
    .sort((a, z) => (status[z[0]] === "signed") - (status[a[0]] === "signed") || a[1].localeCompare(z[1]));
  const share = Object.fromEntries(sigs.map((s) => [`${s.business_id}|${s.technique}`, s.share]));
  const visibleRows = rows.filter(([id]) => visibleCols.some((c) => Number(share[`${id}|${c.name}`]) > 0));
  const label = { signed: "Client", pursued: "Pursued", pitched: "Pitched", lead: "Lead", passed: "Passed" };
  $("#territory-all").setAttribute("aria-pressed", String(!!state.territoryAll));
  $("#territory-all").hidden = cols.length <= defaultCount;
  $("#territory-all").textContent = state.territoryAll ? `Show the top ${defaultCount}` : `Show all ${cols.length} techniques`;
  $("#signatures-table").innerHTML = `<caption class="sr-only">Signature techniques by business</caption>
    <thead><tr><td></td>${visibleCols.map((c) => `<th scope="col" class="col${hotCols.has(c.name) ? " contested" : ""}" title="rarity ${n(c.rarity)}, claimed by ${c.by.size}">${techChip(c.name)}</th>`).join("")}</tr></thead>
    <tbody>${visibleRows.map(([id, name]) => `<tr class="${status[id] === "signed" ? "signed" : ""}"><th scope="row">${esc(name)}<small>${label[status[id]] || ""}</small></th>${visibleCols.map((c) => {
      const v = share[`${id}|${c.name}`];
      const d = v ? Math.round(8 + v * 16) : 0;
      return `<td class="${hotCols.has(c.name) ? "contested" : ""}">${v ? `<button type="button" class="dot-button" data-tech-name="${esc(c.name)}" aria-label="${esc(name)} uses ${esc(c.name)} in ${Math.round(v * 100)}% of its work"><span class="dot${hotCells.has(`${id}|${c.name}`) ? " hot" : ""}" style="width:${d}px;height:${d}px"></span></button><span class="sr-only">${Math.round(v * 100)}%</span>` : ""}</td>`;
    }).join("")}</tr>`).join("") || `<tr><td class="muted" colspan="${visibleCols.length + 1}">No signatures in these techniques.</td></tr>`}</tbody>`;
}

// 5. agents and the named queries they are allowed to call
function renderAccess(analysis) {
  const byQuery = new Map();
  analysis.queries.forEach((q) => {
    let entry = byQuery.get(q.query);
    if (!entry) {
      entry = { ...q, tools: [], cypher: [] };
      byQuery.set(q.query, entry);
    }
    if (!entry.tools.includes(q.tool)) entry.tools.push(q.tool);
    q.cypher.forEach((c) => {
      if (!entry.cypher.some((known) => known.constant === c.constant)) entry.cypher.push(c);
    });
  });
  const qs = [...byQuery.values()];
  const agents = Object.entries(analysis.agents);
  const agentJobs = {
    scout: "Screens new leads against signed clients.",
    researcher: "Finds evidence and proposes measurable goals.",
    producer: "Turns research into spec posts and revisions.",
    standards: "Checks each draft for risky overlap before it can ship.",
    style_director: "Finds open creative territory to guide revisions.",
    strategist: "Shapes measurable campaign goals from the research.",
    account_manager: "Prepares pitches and monthly client work.",
    board: "Board = you. Approves, vetoes, and retires goals.",
    auditor: "Reviews existing posts for strengths and opportunities.",
  };
  const queryNames = {
    Q0: "Signature check", Q1: "Same-area client check", Q2: "Double Take check",
    Q3: "Open territory", Q4: "Post history", Q5: "Stale drafts", P1: "Project techniques",
  };
  const queryDescriptions = {
    P1: "Records the techniques used by each draft.",
    Q0: "Finds the techniques that define each business’s usual style.",
    Q1: "Shows how a new lead’s audience overlaps with signed clients.",
    Q2: "Checks whether a draft shares creative moves with businesses reaching the same audience.",
    Q3: "Finds creative moves not already claimed by businesses reaching the same audience.",
    Q4: "Explains what shaped a draft, including its goal, findings, sources, and decisions.",
    Q5: "Finds drafts that still serve a goal the Board retired.",
  };
  const toolNames = {
    check_draft: "Check and flag a draft (uses Q2)",
  };
  let context = $("#analysis-context");
  if (!context) {
    context = document.createElement("div");
    context.id = "analysis-context";
    $("#analysis-agents").parentElement.before(context);
  }
  context.innerHTML = `<div class="agent-job-list">${agents.map(([agent]) =>
    `<article><div class="agent-job-heading">${agentIcon(agent)}<b>${esc(pretty(agent))}</b></div><p>${esc(agentJobs[agent] || "Handles its assigned work for the studio.")}</p></article>`).join("")}</div>
    <div class="query-glossary"><h3>Query glossary</h3>${qs.map((q) => `<article class="query-glossary-row">
      <div class="query-glossary-name"><span class="qtag">${esc(q.query)}</span><b>${esc(queryNames[q.query] || q.tool)}</b></div>
      <div class="query-glossary-detail"><p>${esc(queryDescriptions[q.query] || queryNames[q.query] || q.tool)}</p>
        <details><summary>Show the query</summary><ul>${q.cypher.map((c) => `<li>${esc(c.constant)}</li>`).join("")}</ul></details>
      </div></article>`).join("")}</div>`;
  $("#analysis-agents").innerHTML = `<caption class="sr-only">Which agent can call which named query</caption>
    <thead><tr><td></td>${qs.map((q) => `<th scope="col"><span class="access-heading"><span>${esc(queryNames[q.query] || q.tool)}</span><small>${esc(q.query)}</small></span></th>`).join("")}<th scope="col">Other tools</th></tr></thead>
    <tbody>${agents.map(([agent, tools]) => {
      const other = tools.filter((tool) => !qs.some((q) => q.tool === tool));
      return `<tr><th scope="row"><span class="agent-name">${agentIcon(agent)}${esc(pretty(agent))}</span></th>${qs.map((q) => `<td>${q.tools.some((tool) => tools.includes(tool)) ? `<span class="yes" title="${esc(pretty(agent))} can call ${esc(queryNames[q.query] || q.tool)}"></span><span class="sr-only">yes</span>` : ""}</td>`).join("")}<td class="other">${other.map((tool) => `<span>${esc(toolNames[tool] || pretty(tool))}</span>`).join("") || `<span class="muted">—</span>`}</td></tr>`;
    }).join("")}</tbody>`;
}

function redrawAnalysis() {
  if (!isAnalysisView() || !state.analysis) return;
  drawArchitecture();
  drawDoubleTake();
}

let aRaf = 0, lastNetW = 0;
window.addEventListener("resize", () => {
  cancelAnimationFrame(aRaf);
  aRaf = requestAnimationFrame(() => {
    if (!isAnalysisView()) return;
    const w = $("#audience-net")?.clientWidth || 0;
    if (Math.abs(w - lastNetW) > 4) { lastNetW = w; renderNet(); }
    redrawAnalysis();
  });
});
if (document.fonts) document.fonts.ready.then(() => requestAnimationFrame(redrawAnalysis));
document.addEventListener("toggle", (e) => { if (e.target.closest?.(".analysis-page")) requestAnimationFrame(redrawAnalysis); }, true);

// chapter nav follows the reader
const chapterLinks = [...document.querySelectorAll("[data-analysis-nav]")];
if ("IntersectionObserver" in window) {
  const seen = new Map();
  const io = new IntersectionObserver((entries) => {
    entries.forEach((en) => seen.set(en.target.id, en.isIntersecting ? en.intersectionRatio : 0));
    const active = [...seen.entries()].sort((a, z) => z[1] - a[1])[0];
    chapterLinks.forEach((a) => a.classList.toggle("active", !!active && active[1] > 0 && a.getAttribute("href") === `#${active[0]}`));
  }, { rootMargin: "-80px 0px -45% 0px", threshold: [0, 0.2, 0.5, 1] });
  document.querySelectorAll(".chapter").forEach((c) => io.observe(c));
}

// ---------------------------------------------------------------- analysis: problem → solution intro, video slot, guided tour

function blockedDrafts(analysis) {
  const groups = {};
  (analysis?.double_take || []).forEach((f) => (groups[f.draft] ||= { ...f, flags: [] }).flags.push(f));
  return Object.values(groups)
    .map((g) => ({ ...g, worst: g.flags.reduce((a, f) => (f.risk > a.risk ? f : a)), techs: [...new Set(g.flags.flatMap((f) => f.shared || []))] }))
    .sort((a, z) => z.worst.risk - a.worst.risk);
}
const andList = (xs) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

function renderIntroProof(analysis, overview) {
  const t = analysis.thresholds || {};
  const list = blockedDrafts(analysis);
  const top = list[0];
  if (!top) {
    $("#ps-proof").innerHTML = `<div class="proof-empty">${icon("circle-check")}<span>No blocked drafts in this run yet.</span></div>`;
    $("#ps-proof-more").textContent = "Double Take checks every draft before it can post.";
  } else {
    const lookalikes = [...new Set(top.flags.map((f) => f.with_business).filter(Boolean))];
    const risk = Number(top.worst.risk) || 0;
    const cutoff = Number(top.worst.flag_risk ?? t.flag_risk) || 0;
    const pct = (v) => Math.max(0, Math.min(100, v * 100));
    $("#ps-proof").innerHTML = `
      <div class="vs">
        <div class="vs-side">${bizName(bizByName(top.client), { link: false })}<span>new draft</span></div>
        <span class="vs-eq" aria-hidden="true">≈</span>
        <div class="vs-side"><span class="vs-names">${lookalikes.map((name, i) => `${i ? " and " : ""}${bizName(bizByName(name), { link: false })}`).join("")}</span><span>already ${lookalikes.length === 1 ? "does" : "do"} this</span></div>
      </div>
      <q class="vs-hook">${esc(top.draft_hook || "Draft without a hook")}</q>
      <p class="vs-chips" aria-label="Shared techniques">${top.techs.map((tech) => techChip(tech)).join("")}</p>
      <div class="vs-meter"><b>risk ${n(risk)}</b>
        <span class="vs-track" role="img" aria-label="Risk ${n(risk)}; blocked at ${n(cutoff)}"><span class="vs-fill" style="width:${pct(risk)}%"></span><span class="vs-tick" style="left:${pct(cutoff)}%"></span></span>
        <span>limit ${n(cutoff)}</span></div>`;
    $("#ps-proof-more").innerHTML = `Same rare techniques, same audience, so the Producer had to find new territory. <a href="#ch-double-take">See all ${plural(list.length, "blocked draft", "blocked drafts")} <span aria-hidden="true">→</span></a>`;
  }
  const screening = analysis.screening || [];
  const waiting = overview ? needsEntries(overview).length : 0;
  $("#ps-stats").innerHTML = [
    ["", screening.length, `${screening.length === 1 ? "lead" : "leads"} screened against current clients`],
    ["red", list.length, `lookalike ${list.length === 1 ? "draft" : "drafts"} blocked before posting`],
    ["", analysis.cleared_checks ?? 0, "Double Take checks cleared"],
    ["", waiting, `${waiting === 1 ? "decision" : "decisions"} waiting for you in the Studio`],
  ].map(([cls, v, label]) => `<li class="stat ${cls}"><b>${esc(v)}</b><span>${esc(label)}</span></li>`).join("");
  const conflicts = screening.flatMap((row) => (row.clients || []).map((client) => Number(client.conflict) || 0));
  const maxConflict = Math.max(...conflicts, 0);
  $("#screen-ramp-max").textContent = n(maxConflict);
  document.querySelectorAll(".screen-tick[data-tick]").forEach((tick) => {
    const value = Number(t[tick.dataset.tick]) || 0;
    tick.style.left = `${maxConflict ? Math.min(100, value / maxConflict * 100) : 0}%`;
  });
  document.querySelectorAll("[data-t]").forEach((el) => {
    const v = t[el.dataset.t];
    if (typeof v === "number") el.textContent = n(v);
  });
}

// Each chapter leads with what this run found; the static heading stays as the fallback.
function renderFindings(analysis) {
  const rows = (analysis.screening || []).map((r) => ({ r, top: [...(r.clients || [])].sort((x, z) => z.conflict - x.conflict)[0] }))
    .filter((x) => x.top).sort((x, z) => z.top.conflict - x.top.conflict);
  if (rows[0]) $("#screening-heading").innerHTML = `<em>${esc(rows[0].r.name)}</em> competes with ${esc(rows[0].top.client)} for the same people`;
  const list = blockedDrafts(analysis);
  $("#double-take-heading").innerHTML = list.length
    ? `<em>${plural(list.length, "draft was", "drafts were")}</em> blocked before reaching the same people`
    : "No draft needed blocking in this run";
  const techs = new Set(list.flatMap((d) => d.techs));
  if (techs.size) $("#signatures-heading").innerHTML = `<em>${plural(techs.size, "rare technique", "rare techniques")}</em> behind the blocks were already in use on the same audience`;
}

function renderVideo(u) {
  const fig = $("#a-video");
  if (!u) { fig.hidden = true; return; }
  if (fig.dataset.src === u) return;
  fig.dataset.src = u;
  let html = `<p><a href="${esc(u)}" target="_blank" rel="noopener">Watch the video walkthrough <span aria-hidden="true">↗</span></a></p>`;
  try {
    const url = new URL(u);
    const host = url.hostname.replace(/^(www\.|m\.)/, "");
    let id = "";
    if (host === "youtu.be") id = url.pathname.slice(1);
    else if (host.endsWith("youtube.com")) id = url.searchParams.get("v") || (url.pathname.match(/^\/(?:embed|shorts|live)\/([\w-]+)/) || [])[1] || "";
    if (/^[\w-]{6,}$/.test(id)) {
      html = `<iframe src="https://www.youtube-nocookie.com/embed/${esc(id)}?rel=0" title="Video walkthrough of Red String" allow="encrypted-media; picture-in-picture; fullscreen" allowfullscreen loading="lazy"></iframe>`;
    } else if (/\.(mp4|webm)$/i.test(url.pathname)) {
      html = `<video controls preload="metadata" src="${esc(u)}"></video>`;
    }
  } catch { /* not a URL: keep the plain link */ }
  $("#a-video-frame").innerHTML = html;
  fig.hidden = false;
}

const TOUR = [
  {
    target: "#ps-grid",
    title: "Start with the problem",
    body: () => "An agency that serves many local businesses can end up giving two clients lookalike videos aimed at the same parents. Red String catches that before it happens. These three panels are the short version: the problem, a real block from this run, and where you come in. The rest of the tour shows how.",
  },
  {
    target: "#graph-cards",
    title: "Every client gets a private graph",
    body: () => "Each business's posts, drafts and goals live in its own graph, on the left and right. Only each draft's list of techniques, its fingerprint, is copied to the shared agency graph in the middle, where the cross-client checks run.",
  },
  {
    target: "#ch-screening .net-panel",
    title: "Step 1: a lead arrives and Scout screens it",
    body: (a) => {
      const t = a.thresholds || {};
      const rows = (a.screening || []).map((r) => ({ r, top: [...(r.clients || [])].sort((x, z) => z.conflict - x.conflict)[0] }))
        .filter((x) => x.top).sort((x, z) => z.top.conflict - x.top.conflict);
      const ex = rows[0];
      return `Each button is a new lead, scored against each client the agency already has. Higher numbers mean they compete for the same people.${ex ? ` ${ex.r.name} scores ${n(ex.top.conflict)} against ${ex.top.client}, past the ${n(t.differentiate)} cutoff, so it can only be pitched with a distinct angle.` : ""}`;
    },
  },
  {
    target: "#ch-screening .net-panel",
    title: "Why the lead got that score",
    body: () => "The map shows the paths behind the score: the lead's audiences, the audiences they overlap, and the clients on the other side. Thicker red lines carry more weight. The bars underneath compare each client with the two cutoffs. Pick a lead to redraw it.",
  },
  {
    target: () => {
      const top = blockedDrafts(state.analysis)[0];
      return (top && document.querySelector(`.dt-card[data-draft="${CSS.escape(top.draft)}"]`)) || $("#double-take-table");
    },
    title: "Step 2: Double Take blocks a lookalike draft",
    body: (a) => {
      const top = blockedDrafts(a)[0];
      if (!top) return "Before any draft ships, Standards compares its rare techniques with every business that reaches the same people. No drafts have been blocked in this run yet.";
      return `The Producer wrote “${top.draft_hook || "a draft"}” for ${top.client}. Standards found it shares ${andList(top.techs)} with ${andList(top.flags.map((f) => f.with_business))}, which ${top.flags.length === 1 ? "reaches" : "reach"} the same people. Similarity × audience overlap = risk ${n(top.worst.risk)}, over the ${n(a.thresholds?.flag_risk)} cutoff, so it went back for a new idea before anyone saw it. Overlap is 1.00 only when two businesses reach exactly the same people.`;
    },
  },
  {
    target: () => $("#signatures-table")?.closest(".table-scroll"),
    title: "Who is known for which move",
    body: () => "This is the map Standards checks against. Each dot is a rare technique a business uses often enough to be known for it. The red columns are the moves behind this run's blocked drafts.",
  },
  {
    target: () => $("#analysis-agents")?.closest(".table-scroll"),
    title: "Agents only get their slice",
    body: () => "Agents never write their own database queries. Each one can call only the named queries its job needs, shown as red dots, and every write records who made it and why. That record is what the raw data at the bottom shows.",
  },
  {
    target: "#sidebar-view-toggle",
    title: "Where you come in",
    body: () => "Agents handle the routine work on their own. Anything that matters, like board calls, pitches, signing and posts, stops in the Studio's Needs you list until a person decides. The Studio is what the agency sees day to day.",
    finish: "Open the Studio",
  },
];

const tour = { i: -1, el: null };
const tourTarget = (step) => (typeof step.target === "function" ? step.target() : $(step.target));

function showTourStep(i) {
  tour.el?.classList.remove("tour-focus");
  tour.i = i;
  const step = TOUR[i];
  const el = tourTarget(step);
  tour.el = el;
  $("#tour-count").textContent = `Step ${i + 1} of ${TOUR.length}`;
  $("#tour-title").textContent = step.title;
  $("#tour-body").textContent = step.body(state.analysis || {});
  $("#tour-back").disabled = i === 0;
  $("#tour-next").innerHTML = step.finish ? `${esc(step.finish)} <span aria-hidden="true">→</span>` : `Next <span aria-hidden="true">→</span>`;
  $("#tour").hidden = false;
  if (el) {
    el.classList.add("tour-focus");
    const top = i === TOUR.length - 1 ? 0 : el.getBoundingClientRect().top + window.scrollY - 20;
    window.scrollTo({ top: Math.max(0, top), behavior: reduceMotion.matches ? "auto" : "smooth" });
  }
  $("#tour-title").focus({ preventScroll: true });
}

function endTour() {
  if (tour.i < 0) return;
  tour.el?.classList.remove("tour-focus");
  tour.i = -1;
  tour.el = null;
  $("#tour").hidden = true;
}

$("#tour-start").addEventListener("click", () => showTourStep(0));
$("#tour-back").addEventListener("click", () => { if (tour.i > 0) showTourStep(tour.i - 1); });
$("#tour-next").addEventListener("click", async () => {
  if (TOUR[tour.i]?.finish) {
    endTour();
    history.pushState({}, "", "/");
    await viewChanged();
    return;
  }
  showTourStep(tour.i + 1);
});
$("#tour-close").addEventListener("click", () => { endTour(); $("#tour-start").focus(); });
document.addEventListener("keydown", (e) => {
  if (tour.i < 0 || e.target.closest?.("input, textarea, select")) return;
  if (e.key === "Escape") { endTour(); $("#tour-start").focus(); }
  else if (e.key === "ArrowRight" && !TOUR[tour.i].finish) showTourStep(tour.i + 1);
  else if (e.key === "ArrowLeft" && tour.i > 0) showTourStep(tour.i - 1);
});

$("#steps").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-step]");
  if (!b) return;
  document.querySelectorAll("#steps button").forEach((x) => (x.disabled = true));
  b.setAttribute("aria-busy", "true");
  $("#log").insertAdjacentHTML("beforeend", `<span class="ln cmd">${esc(`> ${b.dataset.step}…`)}</span>`);
  $("#log").scrollTop = 1e6;
  let busy = false;
  try { await api(`/api/step/${b.dataset.step}`, { method: "POST" }); }
  catch (err) {
    if (err.status === 409 && err.message === "agents are busy") busy = true;
    else alert(err.message);
  }
  await refresh();
  if (busy) $("#step-latest").textContent = "Agents are working…";
});

// ---------------------------------------------------------------- the dossier (business detail, docked)

$("#board").addEventListener("click", (e) => {
  if (e.target.closest("[data-more-stage]")) { state.showAllScreened = true; renderBoard(state.overview); drawString(false); return; }
  const b = e.target.closest("[data-biz]");
  if (b) select(b.dataset.biz);
});

$("#pipeline-register").addEventListener("click", (e) => {
  const row = e.target.closest(".register-row[data-biz]");
  if (row) select(row.dataset.biz);
});
$("#pipeline-stage-bar").addEventListener("click", (e) => {
  const button = e.target.closest("[data-pipeline-stage]");
  if (!button) return;
  state.pipelineStage = state.pipelineStage === button.dataset.pipelineStage ? "" : button.dataset.pipelineStage;
  renderPipelineRegister(state.overview);
});
$("#pipeline-show-all").addEventListener("click", () => {
  state.pipelineStage = "";
  renderPipelineRegister(state.overview);
});
$("#dt-pairs").addEventListener("click", (e) => {
  const button = e.target.closest("[data-dt-draft]");
  if (button) selectDoubleTakePair(button.dataset.dtSlug, button.dataset.dtDraft);
});
$("#dt-history").addEventListener("click", (e) => {
  const button = e.target.closest("[data-dt-draft]");
  if (button) selectDoubleTakePair(button.dataset.dtSlug, button.dataset.dtDraft);
});
$("#dt-version-toggle").addEventListener("click", (e) => {
  const button = e.target.closest("[data-dt-version]");
  if (!button || !state.doubleTake.detail) return;
  state.doubleTake.version = Number(button.dataset.dtVersion);
  state.doubleTake.node = { type: "business", id: "business-0" };
  renderDoubleTakeGraph();
});
function inspectDoubleTakeNode(button) {
  if (!button) return;
  const index = Number(button.dataset.dtNodeIndex);
  state.doubleTake.node = state.doubleTake.nodes?.[index];
  $("#dt-graph-box").querySelectorAll(".dt-node").forEach((node) => node.setAttribute("aria-pressed", String(Number(node.dataset.dtNodeIndex) === index)));
  renderDoubleTakeInspector();
}
$("#dt-graph-box").addEventListener("click", (e) => {
  inspectDoubleTakeNode(e.target.closest("[data-dt-node-index]"));
});
$("#dt-graph-box").addEventListener("mouseover", (e) => {
  const button = e.target.closest("[data-dt-node-index]");
  if (button && !button.contains(e.relatedTarget)) inspectDoubleTakeNode(button);
});
$("#dt-graph-box").addEventListener("focusin", (e) => inspectDoubleTakeNode(e.target.closest("[data-dt-node-index]")));
window.addEventListener("resize", () => requestAnimationFrame(drawDoubleTakeEdges));

const pulseTimers = new WeakMap();
function pulseTarget(target) {
  clearTimeout(pulseTimers.get(target));
  target.classList.remove("click-pulse");
  void target.offsetWidth;
  target.classList.add("click-pulse");
  pulseTimers.set(target, setTimeout(() => {
    target.classList.remove("click-pulse");
    pulseTimers.delete(target);
  }, 1200));
}

function revealStage(name) {
  if (document.body.dataset.tab !== "pipeline") history.pushState({}, "", "/#pipeline");
  syncStudioTab();
  state.pipelineStage = String(name).toLowerCase();
  renderPipelineRegister(state.overview);
  requestAnimationFrame(() => {
    const stage = [...$("#pipeline-stage-bar").querySelectorAll(".pipeline-stage")].find((item) => item.dataset.pipelineStage === state.pipelineStage);
    if (!stage) return;
    stage.scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth", block: "start" });
    pulseTarget(stage);
  });
}

async function openBusinessPage(slug, section = "overview") {
  state.selected = slug;
  history.pushState({}, "", `/#business/${encodeURIComponent(slug)}/${encodeURIComponent(section)}`);
  syncStudioTab();
  await openBusiness(slug, { quiet: true });
  scrollBusinessSection(section);
}

function scrollBusinessSection(section = "overview") {
  requestAnimationFrame(() => {
    const target = document.getElementById(`business-section-${section}`) || $("#business-page");
    target?.scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth", block: "start" });
  });
}

async function select(slug) {
  const changed = slug !== state.selected;
  state.selected = slug;
  $("#follow").hidden = true;
  document.querySelectorAll("#board [data-biz]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.biz === slug)));
  await openBusiness(slug, { animate: changed });
}

async function openBusiness(slug, { quiet = false, animate = false } = {}) {
  const panel = $("#drawer");
  const page = $("#business-page");
  const fullPage = studioTabFromHash() === "business";
  if (panel.dataset.slug !== slug) state.dossierTab = "overview";
  let d;
  try { d = await api(`/api/business/${slug}`); }
  catch (err) {
    if (quiet) { state.selected = null; emptyDossier(); return; }
    throw err;
  }
  const b = d.business;
  const ro = state.overview?.readonly;
  const hood = hoodOf(b);
  let h = fullPage
    ? `<header class="business-page-header"><a class="back-link" href="/#pipeline">← Pipeline</a><div class="business-head-row"><div>
        <div class="business-name-row">${avatar(b, "lg")}<h1>${esc(b.name)}</h1></div>
        <p class="business-meta-line"><span>${esc(b.category)}</span>${hood ? ` · <span>${esc(hood)}</span>` : ""} · <span class="business-status ${statusKind(b.status)}"><i aria-hidden="true"></i>${esc(b.status)}</span>${b.voice ? ` · <span>Voice: ${esc(b.voice)}</span>` : ""}</p>
      </div>${b.status === "lead" && d.screening?.verdict === "borderline" && !ro ? `<div class="business-primary-actions"><button type="button" class="btn primary" data-lead-decision="pursue" data-slug="${esc(slug)}">Pursue lead</button><button type="button" class="btn" data-lead-decision="pass" data-slug="${esc(slug)}">Pass</button></div>` : ""}</div></header>`
    : `<div class="dossier-meta"><span class="dossier-cat">${categoryIcon(b.category)}${esc(b.category)}${hood ? ` · ${esc(hood)}` : ""}</span>
      <a class="text-button" href="/#business/${encodeURIComponent(slug)}/overview">Open full page</a><button type="button" class="btn small dossier-close" data-dossier-close>Close</button></div>
    <div class="dossier-title"><h2 class="name" id="dossier-h" tabindex="-1">${bizName(b, { link: false })}</h2></div>
    <div class="status-row">${verdictStatus(b.status)}${b.voice ? `<span class="muted">Voice: ${esc(b.voice)}</span>` : ""}</div>`;

  let overview = "";
  let goalsMarkup = "";
  let pitchMarkup = "";
  let screening = `<p class="muted">Scout has not screened this business yet.</p>`;
  if (b.status === "lead" && d.screening?.verdict === "borderline") {
    overview += ro
      ? `<section class="decide waiting" aria-label="Waiting on the board">
          <p class="decide-kicker">Waiting on the board</p>
          <p class="decide-what">You decide whether to pursue ${esc(b.name)}.</p></section>`
      : `<section class="decide" aria-labelledby="lead-decide-q">
          <p class="decide-kicker">Needs your decision</p>
          <p class="decide-q" id="lead-decide-q">Pursue ${esc(b.name)}?</p>
          <p class="decide-what">Pursue and Scout opens a private graph for this business so research can start. Pass and it leaves the pipeline for 90 days. Your note is kept with the decision.</p>
          <label class="decide-note"><span>Note for the agents (optional)</span><textarea id="lead-decision-note" rows="2" maxlength="500"></textarea></label>
          <div class="decide-actions">
            <button type="button" class="btn primary big" data-lead-decision="pursue" data-slug="${esc(slug)}">Pursue lead</button>
            <button type="button" class="btn big" data-lead-decision="pass" data-slug="${esc(slug)}">Pass</button>
          </div></section>`;
  }
  if (d.screening && d.screening.verdict) {
    const s = d.screening;
    const screeningPathLabel = (path) => String(path || "").split(/\s*,\s*|\s*->\s*|\s*→ overlaps with\s*/).filter(Boolean).join(" → overlaps with ");
    screening = `<div class="thread"><div class="knot"><div class="who">${who(s.by || "Scout")} ${verdictStatus(s.verdict)}</div><p>${esc(displayStudioCopy(s.reason))}</p></div>
      ${(s.paths || []).map((c) => {
        const ps = [...(c.paths || [])].sort((a, z) => z.conflict - a.conflict);
        const pill = (p) => `<li>${esc(screeningPathLabel(p.via))} <span class="metric">· ${n(p.conflict)}</span></li>`;
        return `<div class="knot minor"><div class="who">${avatar(bizByName(c.client), "xs")}${esc(c.client)} <span class="metric">· conflict ${n(c.conflict)}</span>${c.same_category ? " · same category" : ""}</div>
          ${ps.length ? `<p class="muted">via ${ps.slice(0, 2).map((p) => esc(screeningPathLabel(p.via))).join(", ")}</p><p class="muted mono metric">Path contributions: ${ps.slice(0, 2).map((p) => `${esc(screeningPathLabel(p.via))} ${n(p.conflict, 3)}`).join(" · ")}</p>` : ""}
          ${ps.length > 2 ? `<details class="metric"><summary>All ${ps.length} audience paths</summary><ul class="paths">${ps.map(pill).join("")}</ul></details>` : ""}</div>`;
      }).join("")}</div>`;
    screening += `<p class="analysis-bridge-row"><a class="analysis-bridge" href="/analysis?lead=${encodeURIComponent(slug)}#ch-screening" data-analysis-link>How was this decided?</a></p>`;
  }

  if (d.has_graph && d.flags && d.flags.length) {
    const drafts = Object.fromEntries((d.drafts || []).map((x) => [x.id, x]));
    const byDraft = {};
    d.flags.forEach((f) => {
      if (drafts[f.draft]?.status === "flagged") (byDraft[f.draft] ||= []).push(f);
    });
    const ids = Object.keys(byDraft);
    if (ids.length) {
      overview += `<h3>Double Take <span class="muted">${ids.length} ${ids.length === 1 ? "draft" : "drafts"} blocked</span></h3><div class="thread">${ids.map((id) => {
        const dr = drafts[id];
        return `<div class="knot hit"><div class="who">Blocked <span class="metric">v${esc(dr.version)} </span>draft</div><div class="body">
          <p><button type="button" class="row-btn" data-draft="${esc(id)}" data-slug="${esc(slug)}"><b>“${esc(dr.hook)}”</b></button></p>
          ${byDraft[id].map((f) => `<p>Too close to <b>${esc(f.with_business)}</b>: shares ${(f.shared || []).map(esc).join(", ")}.</p>
          <p class="muted mono metric">similarity ${n(f.similarity)} × audience overlap ${n(f.overlap)} = risk ${n(f.risk)}</p>`).join("")}
          <p class="analysis-bridge-row"><a class="analysis-bridge" href="/analysis?draft=${encodeURIComponent(id)}#ch-double-take" data-analysis-link>How was this decided?</a></p></div></div>`;
      }).join("")}</div>`;
    }
  }

  let draftsTab = "";
  let research = `<h3>Who it targets</h3><ul class="targets">${d.audiences.map((a) =>
    `<li><span>${esc(a.audience)}</span><span class="bar" aria-hidden="true"><span style="width:${Math.round(Math.min(1, a.weight || 0) * 100)}%"></span></span><span class="num metric">${n(a.weight, 1)}</span></li>`).join("") || "<li class='muted'>No audiences.</li>"}</ul>
    <h3>Signature moves <span class="muted">rare elsewhere, common in its work</span></h3>${d.signatures.length ? `<ul class="sig-list">${d.signatures.map((s) => `<li>${esc(s.technique)}<span class="metric"> ${Math.round(s.share * 100)}%</span></li>`).join("")}</ul>` : "<p class='muted'>None yet.</p>"}`;
  if (d.has_graph) {
    if (d.stale.length) overview += `<div class="warnbox"><b><span class="metric">${d.stale.length} </span>stale drafts</b> serve a retired goal: ${d.stale.map((s) => esc(s.hook)).join("; ")}</div>`;
    const goalStatus = {
      active: { label: "Active", explanation: "Currently guiding the work." },
      hypothesized: { label: "Hypothesized", explanation: "Proposed, not yet approved." },
      retired: { label: "Retired", explanation: "No longer guiding new work." },
    };
    goalsMarkup = `<ul class="list">${d.goals.map((g) => {
      const currentStatus = goalStatus[g.status] || { label: String(g.status || "Unknown"), explanation: "Goal status recorded." };
      return `<li class="business-goal"><div class="goal-line"><b>${esc(g.text)}</b></div>
      <p class="goal-status-line">${status(g.status, currentStatus.label)}<span class="goal-status-explanation">${esc(currentStatus.explanation)}</span></p>
      <div class="goal-meta">Measure: ${esc(g.metric || "not set")} · Target: ${esc(g.target || "not set")} · Due ${esc(goalDueLabel(g.due))}</div>
      <p class="goal-meta">${g.created_by ? `Set by ${esc(g.created_by)}` : "Creator not recorded"}${g.created_at ? ` · <time datetime="${esc(g.created_at)}" title="${esc(fullDateTime(g.created_at))}">${esc(runDayLabel(g.created_day))}</time>` : ""}</p>
      <div class="goal-support"><b>Findings behind it</b>${(g.findings || []).map((finding) => `<p>${esc(finding.text)}${finding.source_url ? ` · ${link(finding.source_url, `Read ${finding.kind || "finding"} source`)}` : ""}</p>`).join("") || "<p class='muted'>No linked findings.</p>"}</div>
      <div class="goal-support"><b>Drafts serving it</b>${(g.drafts || []).map((draft) => `<p><button type="button" class="row-btn" data-draft="${esc(draft.id)}" data-slug="${esc(slug)}">${esc(draft.hook)}</button></p>`).join("") || "<p class='muted'>No serving drafts.</p>"}</div>
      ${g.status === "active" && !ro ? `<div class="btn-row"><button type="button" class="btn small" data-retire="${esc(g.id)}" data-slug="${esc(slug)}">Retire goal</button></div>` : ""}</li>`;
    }).join("") || "<li class='muted'>None yet.</li>"}</ul>`;
    pitchMarkup = `<ul class="list">${d.pitches.map((p) =>
      `<li><button type="button" class="row-btn" data-pitch="${esc(p.id)}" data-slug="${esc(slug)}">${chip(p.status)} <b>${esc(p.angle)}</b></button></li>`).join("") || "<li class='muted'>No pitch yet.</li>"}</ul>`;
    draftsTab += `<ul class="list">${d.drafts.map((x) =>
      `<li><button type="button" class="row-btn" data-draft="${esc(x.id)}" data-slug="${esc(slug)}">${chip(x.status)}${chip("plain", x.kind)} <b><span class="metric">v${esc(x.version)} · </span>${esc(x.hook)}</b></button></li>`).join("") || "<li class='muted'>None yet.</li>"}</ul>`;
    if (d.taste_profile && d.taste_profile.id) draftsTab += `<h3>Taste profile <span class="muted metric">v${esc(d.taste_profile.version)}</span></h3><p>${esc(d.taste_profile.summary)}</p>
      <p class="muted" style="margin-top:6px">Prefers: ${d.taste_profile.prefers.map((p) => esc(p.name)).join(", ")}${d.taste_profile.avoids.length ? `<br>Avoids: ${d.taste_profile.avoids.map((p) => esc(p.name)).join(", ")}` : ""}</p>`;
    const findingGroups = new Map();
    (d.findings || []).forEach((finding) => {
      if (!findingGroups.has(finding.kind)) findingGroups.set(finding.kind, []);
      findingGroups.get(finding.kind).push(finding);
    });
    const findingGroupNames = { audience: "Audience", competitor: "Competitors", channel: "Channels", audit: "Post audit" };
    const findingMarkup = [...findingGroups].map(([kind, findings]) => `<section class="finding-group">
      <h4>${esc(findingGroupNames[kind] || kind)}</h4><ul class="finding-rows">${findings.map((finding) => {
        let source = "Source";
        try { source = `Source: ${new URL(finding.source_url).hostname.replace(/^www\\./i, "")}`; } catch { source = "Source" }
        const confidence = finding.confidence == null ? "" : `Confidence ${esc(finding.confidence)}`;
        const sourceCopy = finding.kind === "audit" ? "From Auditor's post audit" : "From Researcher's research";
        return `<li class="finding-row"><p class="finding-claim">${esc(finding.text)}</p><div class="finding-meta">
          ${finding.source_url ? link(finding.source_url, source) : `<span class="muted">${sourceCopy}</span>`}
          ${confidence ? `<span class="finding-confidence">${confidence}</span>` : ""}</div></li>`;
      }).join("")}</ul></section>`).join("") || `<p class="muted">No findings yet.</p>`;
    research += `<h3>Findings</h3>${findingMarkup}`;
    research += `<h3>Past posts</h3><ul class="list">${d.posts.map((p) => `<li>${esc(p.hook)} <span class="muted metric">${(p.views ?? 0).toLocaleString()} views · ${(p.saves ?? 0).toLocaleString()} saves</span></li>`).join("") || "<li class='muted'>Not loaded.</li>"}</ul>`;
  } else {
    overview += `<div class="warnbox"><b>No private graph yet.</b> Scout creates one when it pursues this lead.</div>`;
  }

  const tabs = [
    { id: "overview", label: "Overview", content: overview },
    { id: "screening", label: "Screening", content: screening },
  ];
  if (d.has_graph) tabs.push({ id: "goals", label: "Goals", content: goalsMarkup });
  if (d.has_graph) tabs.push({ id: "drafts", label: "Drafts", content: draftsTab });
  tabs.push({ id: "research", label: "Research", content: research });
  if (d.has_graph && d.pitches?.length) tabs.push({ id: "pitch", label: "Pitch", content: pitchMarkup });
  if (d.has_graph && d.decisions && d.decisions.length) {
    tabs.push({
      id: "activity",
      label: "Activity",
      content: `<h3>Latest decisions <span class="muted analysis-only">client:${esc(slug)}</span></h3><div class="thread">${d.decisions.slice(0, 10).map((x) =>
        `<div class="knot minor"><div class="who">${who(x.by)}</div><p><b>${esc(displayStudioCopy(x.text))}</b></p>${x.rationale ? `<p class="muted">${esc(displayStudioCopy(x.rationale))}</p>` : ""}</div>`).join("")}</div>`,
    });
  }
  if (!tabs.some((tab) => tab.id === state.dossierTab)) state.dossierTab = "overview";
  tabs[0].content = tabs[0].content.replace('class="thread"', 'class="thread lead"');
  if (fullPage) {
    const sectionNav = `<nav class="business-section-nav" aria-label="Business sections">${tabs.map((tab) =>
      `<a href="#business-section-${esc(tab.id)}" data-business-nav="${esc(tab.id)}">${esc(tab.label)}</a>`).join("")}</nav>`;
    page.innerHTML = `<div class="business-page-shell">${h}${sectionNav}${tabs.map((tab) =>
      `<section class="business-section" id="business-section-${esc(tab.id)}"><h2>${esc(tab.label)}</h2>${tab.content}</section>`
    ).join("")}</div>`;
    page.querySelectorAll("[data-business-nav]").forEach((item) => item.addEventListener("click", (event) => {
      event.preventDefault();
      document.getElementById(`business-section-${item.dataset.businessNav}`)?.scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth", block: "start" });
    }));
    if ("IntersectionObserver" in window) {
      const observer = new IntersectionObserver((entries) => entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        page.querySelectorAll("[data-business-nav]").forEach((item) => {
          if (item.dataset.businessNav === entry.target.id.replace("business-section-", "")) item.setAttribute("aria-current", "location");
          else item.removeAttribute("aria-current");
        });
      }), { rootMargin: "-20% 0px -65% 0px" });
      page.querySelectorAll(".business-section").forEach((section) => observer.observe(section));
    }
    page.hidden = false;
    $("#drawer-body").innerHTML = "";
    closeOverlay();
  } else {
    page.hidden = true;
    h += `<div class="dossier-tabs" role="tablist" aria-label="${esc(b.name)} dossier">`;
    h += tabs.map((tab) => {
      const selected = tab.id === state.dossierTab;
      const tabId = `dossier-${slug}-${tab.id}-tab`;
      const panelId = `dossier-${slug}-${tab.id}-panel`;
      return `<button type="button" role="tab" id="${esc(tabId)}" aria-controls="${esc(panelId)}" aria-selected="${selected}" tabindex="${selected ? "0" : "-1"}" data-dossier-tab="${esc(tab.id)}">${esc(tab.label)}</button>`;
    }).join("");
    h += `</div>`;
    h += tabs.map((tab) => {
      const selected = tab.id === state.dossierTab;
      const tabId = `dossier-${slug}-${tab.id}-tab`;
      const panelId = `dossier-${slug}-${tab.id}-panel`;
      return `<section class="dossier-panel" role="tabpanel" id="${esc(panelId)}" aria-labelledby="${esc(tabId)}" tabindex="0"${selected ? "" : " hidden"}>${tab.content}</section>`;
    }).join("");

    const keepScroll = !animate && panel.dataset.slug === slug ? panel.scrollTop : 0;
    $("#drawer-body").innerHTML = h;
    panel.dataset.slug = slug;
    panel.scrollTop = keepScroll;
  }
  if (!quiet) $("#sr-status").textContent = `Showing ${b.name}`;
  if (!fullPage && !isSplit() && !quiet) openOverlay();
  drawString(animate);
}

function activateDossierTab(id, focus = false) {
  const tabs = [...$("#drawer-body").querySelectorAll('[role="tab"]')];
  const selected = tabs.find((tab) => tab.dataset.dossierTab === id);
  if (!selected) return;
  state.dossierTab = id;
  tabs.forEach((tab) => {
    const active = tab === selected;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    document.getElementById(tab.getAttribute("aria-controls")).hidden = !active;
  });
  if (focus) selected.focus();
  drawString(false);
}

$("#drawer-body").addEventListener("click", (e) => {
  const tab = e.target.closest('[role="tab"][data-dossier-tab]');
  if (tab) activateDossierTab(tab.dataset.dossierTab);
});
$("#drawer-body").addEventListener("keydown", (e) => {
  const current = e.target.closest('[role="tab"][data-dossier-tab]');
  if (!current) return;
  const tabs = [...$("#drawer-body").querySelectorAll('[role="tab"]')];
  let index = tabs.indexOf(current);
  if (e.key === "ArrowRight") index = (index + 1) % tabs.length;
  else if (e.key === "ArrowLeft") index = (index - 1 + tabs.length) % tabs.length;
  else if (e.key === "Home") index = 0;
  else if (e.key === "End") index = tabs.length - 1;
  else return;
  e.preventDefault();
  activateDossierTab(tabs[index].dataset.dossierTab, true);
});

function emptyDossier() {
  state.dossierTab = "overview";
  delete $("#drawer").dataset.slug;
  $("#drawer-body").innerHTML = `<div class="dossier-empty"><h2 class="placard" id="dossier-h">Pick a business</h2>
    <p class="muted">Each card opens its dossier: Scout's screening, Double Take's flags, goals, pitches, drafts, and every source behind them.</p></div>`;
  drawString(false);
}

// Below 1100px the dossier slides over the page.
let returnFocus = null;
function openOverlay() {
  const panel = $("#drawer");
  if (!panel.classList.contains("open")) returnFocus = document.activeElement;
  panel.classList.add("open");
  $("#scrim").hidden = false;
  ($("#dossier-h") || panel).focus();
}
function closeOverlay() {
  $("#drawer").classList.remove("open");
  $("#scrim").hidden = true;
  if (returnFocus && document.contains(returnFocus)) returnFocus.focus();
}
$("#scrim").addEventListener("click", closeOverlay);
$("#drawer").addEventListener("keydown", (e) => { if (e.key === "Escape") closeOverlay(); });

// ---------------------------------------------------------------- the red string: selected card to its thread

function drawString(animate) {
  const path = $("#string-path");
  const card = state.selected && document.querySelector(`#board [data-biz="${CSS.escape(state.selected)}"]`);
  const panel = $("#drawer");
  if (!isSplit() || !card || panel.dataset.slug !== state.selected) { path.setAttribute("d", ""); return; }
  const desk = $("#desk").getBoundingClientRect();
  const c = card.getBoundingClientRect();
  if (c.bottom < 0 || c.top > window.innerHeight) { path.setAttribute("d", ""); return; }
  const p = panel.getBoundingClientRect();
  const lead = panel.querySelector(".thread.lead");
  const tabs = panel.querySelector(".dossier-tabs");
  const head = panel.querySelector("#dossier-h");
  const anchor = state.dossierTab !== "overview" ? tabs : lead || tabs;
  let ty = anchor === lead ? anchor.getBoundingClientRect().top + 12.5
    : anchor ? anchor.getBoundingClientRect().top + anchor.offsetHeight / 2
      : head ? head.getBoundingClientRect().top + head.offsetHeight / 2 : p.top + 40;
  ty = Math.min(Math.max(ty, p.top + 18), p.bottom - 18);
  const x1 = c.right - desk.left - 15, y1 = c.top + c.height / 2 - desk.top;
  const x2 = p.left - desk.left + 1, y2 = ty - desk.top;
  // Leave the card sideways, turn in the gutter between board and dossier, tie in at the first knot.
  const gx = Math.max(x1 + 24, x2 - 14);
  const f = (v) => v.toFixed(1);
  path.setAttribute("d", `M${f(x1)} ${f(y1)} L${f(Math.max(x1, gx - 46))} ${f(y1)} C${f(gx + 6)} ${f(y1)} ${f(gx - 6)} ${f(y2)} ${f(x2)} ${f(y2)}`);
  if (animate && !reduceMotion.matches) {
    const len = path.getTotalLength();
    state.animating = true;
    path.style.transition = "none";
    path.style.strokeDasharray = `${len}`;
    path.style.strokeDashoffset = `${len}`;
    path.getBoundingClientRect();
    path.style.transition = "stroke-dashoffset 700ms cubic-bezier(.3,.7,.2,1)";
    path.style.strokeDashoffset = "0";
  } else if (!state.animating) {
    path.style.strokeDasharray = "";
    path.style.strokeDashoffset = "";
  }
}
$("#string-path").addEventListener("transitionend", (e) => {
  state.animating = false;
  e.target.style.transition = "";
  e.target.style.strokeDasharray = "";
  e.target.style.strokeDashoffset = "";
});

let raf = 0;
const redraw = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => drawString(false)); };
window.addEventListener("resize", redraw);
window.addEventListener("scroll", redraw, { passive: true });
$("#drawer").addEventListener("scroll", redraw, { passive: true });
$("#board").addEventListener("toggle", redraw, true);
$("#drawer").addEventListener("toggle", redraw, true);
if (document.fonts) document.fonts.ready.then(redraw);

// ---------------------------------------------------------------- shared actions

document.addEventListener("click", async (e) => {
  const cl = e.target.closest("[data-close]");
  if (cl) { cl.closest("dialog").close(); return; }
  if (e.target.closest("[data-dossier-close]")) { closeOverlay(); return; }
  const leadDecision = e.target.closest("[data-lead-decision]");
  if (leadDecision) {
    const verdict = leadDecision.dataset.leadDecision;
    if (verdict === "pass" && !confirm("Pass this lead? It leaves the pipeline for 90 days.")) return;
    const section = leadDecision.closest(".decide, .focus-item");
    const buttons = [...section.querySelectorAll("button")];
    const note = section.querySelector("#lead-decision-note")?.value.trim() || "";
    buttons.forEach((button) => { button.disabled = true; });
    try {
      await api(`/api/lead/${leadDecision.dataset.slug}/decide`, {
        method: "POST",
        body: JSON.stringify({ verdict, note }),
      });
      await refresh();
    } catch (err) {
      buttons.forEach((button) => { button.disabled = false; });
      alert(err.message);
    }
    return;
  }
  const lane = e.target.closest("[data-reveal-lane]");
  if (lane) { revealStage(lane.dataset.revealLane); return; }
  const dr = e.target.closest("[data-draft][data-slug]");
  if (dr) openRoute(dr.dataset.slug, dr.dataset.draft);
  const pi = e.target.closest("[data-pitch]");
  if (pi) openPitch(pi.dataset.slug, pi.dataset.pitch);
  const rg = e.target.closest("[data-retire]");
  if (rg && confirm("Retire this goal? Drafts serving it become stale.")) {
    await api(`/api/retire/${rg.dataset.slug}/${rg.dataset.retire}`, { method: "POST" });
    await openBusiness(rg.dataset.slug); refresh();
  }
  const bd = e.target.closest("[data-board]");
  if (bd) {
    const veto = bd.dataset.board === "veto";
    if (veto && !confirm(`Veto this ${BOARD_COPY[bd.dataset.label].noun}?`)) return;
    const note = $("#board-note")?.value.trim() || (veto ? "Vetoed by the board." : "Approved by the board.");
    bd.closest(".decide")?.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    await api(`/api/board/${bd.dataset.slug}/${bd.dataset.label}/${bd.dataset.id}`, { method: "POST", body: JSON.stringify({ verdict: bd.dataset.board, note }) });
    bd.dataset.label === "Pitch" ? openPitch(bd.dataset.slug, bd.dataset.id) : openRoute(bd.dataset.slug, bd.dataset.id);
    refresh();
  }
});

document.addEventListener("click", async (e) => {
  const pick = e.target.closest("[data-pick]");
  if (!pick || isAnalysisView()) return;
  const slug = pick.dataset.pick;
  if (document.body.dataset.tab === "pipeline") {
    if (pick.closest("#board, #pipeline-register")) return;
    e.preventDefault();
    await select(slug);
    return;
  }
  e.preventDefault();
  const section = pick.dataset.businessSection || (pick.closest(".focus-row") ? "screening" : "overview");
  await openBusinessPage(slug, section);
});

// ---------------------------------------------------------------- route cards (threads) and pitch cards

function knots(decisions) {
  return decisions.map((x) => `<div class="knot"><div class="who">${who(x.by)}</div><p><b>${esc(displayStudioCopy(x.decision))}</b></p>${x.rationale ? `<p class="muted">${esc(displayStudioCopy(x.rationale))}</p>` : ""}</div>`).join("");
}

function sheetTop(kicker) {
  return `<div class="sheet-top"><p class="sheet-kicker">${kicker}</p><button type="button" class="btn small" data-close>Close</button></div>`;
}

const BOARD_COPY = {
  Pitch: {
    noun: "pitch",
    what: "Approve and Account Manager marks this pitch ready to send. Veto sends it back to draft. Your note becomes a rule the agents follow.",
  },
  Draft: {
    noun: "post",
    what: "This post cleared Double Take. Approve and it is ready to post for the client. Veto blocks it, and your note becomes a rule the agents follow.",
  },
};

function decisionBar(label, id, slug, c) {
  const last = c.decisions.filter((x) => /^Board (approve|veto)/.test(x.decision || ""))
    .sort((a, b) => String(b.at).localeCompare(String(a.at)))[0];
  const vetoed = last && /veto/.test(last.decision);
  const pending = label === "Pitch" ? c.status === "draft" && !vetoed : c.status === "queued";
  const { noun } = BOARD_COPY[label];
  const business = state.overview?.businesses.find((b) => b.id === slug);
  const what = label === "Draft" && business?.status !== "signed"
    ? "This spec post cleared Double Take. Approve and Account Manager can show it in the pitch. Veto blocks it, and your note becomes a rule the agents follow."
    : BOARD_COPY[label].what;
  if (!pending) {
    if (!last) return "";
    return `<section class="decide done${vetoed ? " vetoed" : ""}" aria-label="Board decision">
      <p class="decide-kicker">${vetoed ? "Vetoed" : "Approved"} by ${esc(last.by || "the board")}</p>
      ${last.rationale ? `<p class="decide-what">${esc(last.rationale)}</p>` : ""}</section>`;
  }
  if (state.overview?.readonly) {
    return `<section class="decide waiting" aria-label="Waiting on the board">
      <p class="decide-kicker">Waiting on the board</p>
      <p class="decide-what">Nothing goes out until the studio's board approves this ${noun}.</p></section>`;
  }
  const data = `data-label="${label}" data-id="${esc(id)}" data-slug="${esc(slug)}"`;
  return `<section class="decide" aria-labelledby="decide-q">
    <p class="decide-kicker">Needs your decision</p>
    <p class="decide-q" id="decide-q">Approve this ${noun}?</p>
    <p class="decide-what">${what}</p>
    <label class="decide-note"><span>Note for the agents (optional)</span><textarea id="board-note" rows="2" maxlength="500"></textarea></label>
    <div class="decide-actions">
      <button type="button" class="btn primary big" data-board="approve" ${data}>Approve ${noun}</button>
      <button type="button" class="btn veto" data-board="veto" ${data}>Veto</button>
    </div></section>`;
}

function showSheet(h, title) {
  $("#card-body").innerHTML = `<div class="sheet">${h}</div>`;
  $("#card").setAttribute("aria-label", title);
  $("#goal-card").hidden = true;
  $("#tech-card-sheet").hidden = true;
  if (!$("#card").open) $("#card").showModal();
}

async function showGoalPopover(button) {
  activeGoalTrigger = button;
  const card = $("#goal-card");
  const slug = button.dataset.slug;
  const goalId = button.dataset.goalId;
  const goal = await api(`/api/goal/${encodeURIComponent(slug)}/${encodeURIComponent(goalId)}`);
  if (activeGoalTrigger !== button) return;
  const statusCopy = {
    active: "Active · tracked as a current client goal.",
    hypothesized: "Hypothesized · an evidence-based guess, not yet confirmed with the business.",
    retired: "Retired · no longer guides current work.",
  };
  card.innerHTML = `<div class="popover-head"><b>Goal</b><button type="button" class="popover-close" aria-label="Close goal details">×</button></div>
    <p class="goal-popover-text">${esc(goal.text)}</p><p class="goal-popover-status">${esc(statusCopy[goal.status] || goal.status)}</p>
    <p class="goal-popover-meta">${goal.created_by ? `Set by ${esc(goal.created_by)}` : "Who set this goal was not recorded."}${goal.created_at ? ` · <time datetime="${esc(goal.created_at)}" title="${esc(fullDateTime(goal.created_at))}">${esc(runDayLabel(goal.created_day))}</time>` : ""}</p>
    <h4>Findings behind it</h4><ul>${(goal.findings || []).map((finding) => `<li>${esc(finding.text)}${finding.source_url ? ` ${link(finding.source_url, `${finding.kind || "Finding"} source`)}` : ""}</li>`).join("") || "<li>No linked findings.</li>"}</ul>
    <h4>Drafts serving it</h4><ul>${(goal.drafts || []).map((draft) => `<li><button type="button" class="goal-draft-link" data-goal-draft="${esc(draft.id)}" data-slug="${esc(slug)}">${esc(draft.hook)}</button></li>`).join("") || "<li>No drafts serve this goal yet.</li>"}</ul>`;
  card.hidden = false;
  const rect = button.getBoundingClientRect();
  card.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - card.offsetWidth - 8))}px`;
  card.style.top = `${Math.max(8, Math.min(rect.bottom, window.innerHeight - card.offsetHeight - 8))}px`;
}

let goalHideTimer = 0;
let activeGoalTrigger = null;
let pinnedGoalTrigger = null;
function hideGoalPopover() {
  clearTimeout(goalHideTimer);
  $("#goal-card").hidden = true;
  activeGoalTrigger = null;
  pinnedGoalTrigger = null;
}
document.addEventListener("mouseover", (e) => {
  const button = e.target.closest("[data-goal-id]");
  if (button && !button.contains(e.relatedTarget) && window.matchMedia("(hover: hover)").matches) {
    clearTimeout(goalHideTimer);
    $("#goal-card").dataset.goalId = button.dataset.goalId;
    showGoalPopover(button);
  }
  if (e.target.closest("#goal-card")) clearTimeout(goalHideTimer);
});
document.addEventListener("mouseout", (e) => {
  if (pinnedGoalTrigger) return;
  const trigger = e.target.closest("[data-goal-id]");
  if (trigger && !trigger.contains(e.relatedTarget) && !e.relatedTarget?.closest("#goal-card") && !e.relatedTarget?.closest("[data-goal-id]")) {
    goalHideTimer = window.setTimeout(hideGoalPopover, 250);
  }
  if (e.target.closest("#goal-card") && !e.relatedTarget?.closest("#goal-card") && !e.relatedTarget?.closest("[data-goal-id]")) {
    goalHideTimer = window.setTimeout(hideGoalPopover, 250);
  }
});
document.addEventListener("focusin", (e) => {
  const button = e.target.closest("[data-goal-id]");
  if (button) {
    clearTimeout(goalHideTimer);
    $("#goal-card").dataset.goalId = button.dataset.goalId;
    showGoalPopover(button);
  }
  if (e.target.closest("#goal-card")) clearTimeout(goalHideTimer);
});
document.addEventListener("focusout", (e) => {
  if (!pinnedGoalTrigger && (e.target.closest("[data-goal-id], #goal-card"))
    && !e.relatedTarget?.closest("#goal-card") && !e.relatedTarget?.closest("[data-goal-id]")) {
    goalHideTimer = window.setTimeout(hideGoalPopover, 250);
  }
});
document.addEventListener("click", async (e) => {
  const close = e.target.closest(".popover-close");
  if (close) {
    if (close.closest("#biz-card")) hideBizCard();
    else if (close.closest("#tech-card, #tech-card-sheet")) hideTechCard();
    else hideGoalPopover();
    return;
  }
  const goalButton = e.target.closest("[data-goal-id]");
  if (goalButton) {
    e.preventDefault();
    if (pinnedGoalTrigger === goalButton) {
      hideGoalPopover();
    } else {
      pinnedGoalTrigger = goalButton;
      clearTimeout(goalHideTimer);
      $("#goal-card").dataset.goalId = goalButton.dataset.goalId;
      await showGoalPopover(goalButton);
    }
    return;
  }
  const draftButton = e.target.closest("[data-goal-draft]");
  if (draftButton) {
    hideGoalPopover();
    await openRoute(draftButton.dataset.slug, draftButton.dataset.goalDraft);
    return;
  }
  if (!e.target.closest("#goal-card")) hideGoalPopover();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideGoalPopover(); });

async function openRoute(slug, id) {
  const c = await api(`/api/route/${slug}/${id}`);
  let h = sheetTop(`<span class="studio-only">Thread</span><span class="analysis-only">Thread · client:${esc(slug)} · ${esc(id)}</span>`) +
    `<h2>${esc(c.draft)}</h2><p class="serves">${chip(c.status)} ${c.goal ? `serves ${chip(c.goal_status)} <button type="button" class="goal-link" data-goal-id="${esc(c.goal_id)}" data-slug="${esc(slug)}">${esc(c.goal)}</button>` : ""}</p>` + decisionBar("Draft", id, slug, c);
  const kinds = c.technique_kinds || {};
  const me = state.overview?.businesses.find((b) => b.id === slug);
  if (c.status === "flagged" && c.flags.length) h += c.flags.map((f) => `<div class="flagbox"><b>Double Take blocked this draft.</b> It resembles ${esc(f.with_business)}'s work too closely.
    <div class="dt-compare">
      <div class="dt-side">${avatar(me)}<span><b>This draft</b><small>${esc(me?.name || "")}</small></span></div>
      <div class="dt-shared"><span class="dt-string" aria-hidden="true"></span><span class="dt-label">Shares</span>${f.shared.map((t) => techChip(t, kinds)).join("")}</div>
      <div class="dt-side">${avatar(bizByName(f.with_business))}<span><b>${esc(f.with_business)}</b><small>already uses these</small></span></div>
    </div>
    <div class="mono metric" style="margin-top:4px;font-size:.8125rem">similarity ${n(f.similarity)} × audience overlap ${n(f.overlap)} = risk ${n(f.risk)}</div>
    <div class="muted metric" style="margin-top:4px;font-size:.8125rem">Evidence: ${f.evidence.map((e) => `${esc(e.fingerprint)} (${esc(e.kind)}, ${esc(e.hits)} shared)`).join(", ")}</div></div>`).join("");
  else if (c.status !== "flagged" && c.status !== "vetoed") h += `<div class="okbox"><b>Cleared Double Take.</b></div>`;
  if (c.previous.length) h += `<div class="warnbox"><b>Revision</b> of ${c.previous.map((p) => `<span class="metric">v${esc(p.version)} </span>“${esc(p.hook)}”`).join(", ")}${c.flags_on_previous.length ? `, which was blocked for resembling ${c.flags_on_previous.map((f) => esc(f.with)).join(", ")} (${c.flags_on_previous.map((f) => f.shared.map(esc).join(", ")).join("; ")})` : ""}.</div>`;
  if (c.spec) {
    const lines = c.spec.split("\n").filter(Boolean);
    const isShot = (l) => /^\d+ · /.test(l);
    const notes = lines.filter((l) => !isShot(l)).flatMap((l) => l.startsWith("Color:") ? l.split(" · Audio: ").map((x, i) => (i ? `Audio: ${x}` : x)) : [l]);
    h += `<h3>Shot list</h3><ol class="shots">${lines.filter(isShot).map((l) => {
      const [, time, rest] = l.match(/^\d+ · ([^·]+) · (.*)$/) || [null, "", l];
      const m = rest.match(/^(.*?)\s*\[([^\]]+)\]$/);
      return `<li><span class="shot-time">${esc(time.trim())}</span><span>${esc(m ? m[1] : rest)}${m ? ` ${techChip(m[2], kinds)}` : ""}</span></li>`;
    }).join("")}</ol><dl class="shot-notes">${notes.map((l) => {
      const i = l.indexOf(":");
      const v = l.slice(i + 1).trim().replace(/\s*\[[^\]]+\]/g, "");
      const tags = [...l.matchAll(/\[([^\]]+)\]/g)].map((t) => techChip(t[1], kinds)).join(" ");
      return `<div><dt>${esc(l.slice(0, i))}</dt><dd>${esc(v)}${tags ? ` ${tags}` : ""}</dd></div>`;
    }).join("")}</dl>`;
  }
  h += `<h3>Decisions</h3><div class="thread">${knots(c.decisions)}</div>`;
  const sourceKind = { TasteProfile: "Taste profile", Finding: "Research finding", Reference: "Reference video", CollisionFlag: "Double Take flag", Audit: "Audit", Post: "Post" };
  h += `<h3>Sources</h3><ul class="source-rows">${c.sources.filter((s) => s.kind !== "Reference").map((s) => {
    const text = s.text || s.summary || s.hook || s.with_business || "Source detail";
    const url = s.source_url || s.url;
    const kind = sourceKind[s.kind] || String(s.kind || "Source").replace(/([a-z])([A-Z])/g, "$1 $2");
    const linkText = s.kind === "Finding" ? "Read the research source" : s.kind === "Reference" ? "Watch the reference video" : `Open ${kind.toLowerCase()}`;
    return `<li class="source-row"><span class="source-kind">${esc(kind)}</span><span>${esc(text)}</span>${url ? link(url, linkText) : ""}</li>`;
  }).join("") || "<li class='muted'>None.</li>"}</ul>`;
  h += `<h3>Techniques</h3><ul class="tech-list">${c.techniques.map((t) => `<li>${techChip(t, kinds)}</li>`).join("")}</ul>`;
  h += `<h3>References <span class="muted">videos the Producer drew on</span></h3>${c.references.length
    ? `<ul class="refs">${c.references.map(refCard).join("")}</ul>`
    : "<p class='muted'>No close reference in the library.</p>"}`;
  showSheet(h, `Thread for ${c.draft}`);
}

async function openPitch(slug, id) {
  const c = await api(`/api/pitch/${slug}/${id}`);
  const [business, assets] = await Promise.all([
    Promise.resolve(bizById(slug)),
    Promise.all((c.spec_posts || []).map(async (post) => ({ post, detail: await api(`/api/route/${slug}/${post.id}`) }))),
  ]);
  const claimRows = (c.claims || []).map((finding) => {
    let source = "source";
    try { source = new URL(finding.source_url).hostname.replace(/^www\./i, ""); } catch {}
    return `<li>${esc(finding.text)}${finding.source_url ? ` <span class="email-source">${link(finding.source_url, `Source: ${source}`)}</span>` : ""}</li>`;
  }).join("");
  const assetCards = assets.map(({ post, detail }) => {
    const lines = String(detail.spec || "").split(/\r?\n/).filter(Boolean);
    const format = lines.find((line) => /^Format:/i.test(line))?.replace(/^Format:\s*/i, "")
      || (detail.format === "reel" ? "Vertical short-form video (reel)" : detail.format || "Short-form video");
    const shots = lines.filter((line) => /^\d+ · /.test(line)).map((line) => line.replace(/^\d+ · [^·]+ · /, ""));
    const references = (detail.references || []).map((reference) => link(reference.url, `@${String(reference.creator || "").replace(/^@/, "")} · ${reference.category || "Reference"}`)).join("");
    return `<article class="pitch-asset"><p class="asset-kicker">Spec post</p><h4>${esc(post.hook)}</h4><p><b>Format</b> · ${esc(format)}</p><h5>Shot list</h5><ol>${shots.map((shot) => `<li>${esc(shot)}</li>`).join("")}</ol>${references ? `<div class="asset-references"><b>References</b>${references}</div>` : ""}</article>`;
  }).join("");
  const countWords = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"];
  const countText = countWords[assets.length] || String(assets.length);
  const subjectCount = ({ one: "One", two: "Two", three: "Three", four: "Four", five: "Five" })[countText] || countText;
  const postLabel = `${countText} spec ${assets.length === 1 ? "post" : "posts"}`;
  const businessName = business?.name || slug;
  const emailStatus = c.status === "approved"
    ? "Approved · ready to send"
    : c.status === "vetoed" ? "Vetoed · won't be sent" : "Draft · not sent until you approve";
  const emailStatusClass = c.status === "approved" ? "approved" : c.status === "vetoed" ? "vetoed" : "pending";
  const h = sheetTop(`<span class="studio-only pitch-kicker">Pitch</span><span class="analysis-only">Pitch · client:${esc(slug)} · ${esc(id)}</span>`) +
    `<h2>${esc(c.angle)}</h2><p class="serves">${chip(c.status)} argues for ${chip(c.goal_status)} <button type="button" class="goal-link" data-goal-id="${esc(c.goal_id)}" data-slug="${esc(slug)}">${esc(c.goal)}</button></p>${decisionBar("Pitch", id, slug, c)}
    <section class="pitch-email"><p class="email-status ${emailStatusClass}">${emailStatus}</p><dl><div><dt>To</dt><dd>${esc(businessName)}</dd></div><div><dt>Subject</dt><dd>${esc(`${subjectCount} spec ${assets.length === 1 ? "post" : "posts"} for ${businessName}`)}</dd></div></dl>
      <p>Hi ${esc(businessName)},</p>
      <p>We put together ${esc(postLabel)} for ${esc(businessName)}, aimed at a goal we think fits you: <b>${esc(c.goal)}</b>.</p>
      <p>Here are the findings that informed the ideas:</p><ul>${claimRows || "<li>No sourced findings are attached to this pitch.</li>"}</ul>
      <p>Attached are these spec posts:</p><ul>${assets.map(({ post }) => `<li>${esc(post.hook)}</li>`).join("") || "<li>No spec posts attached.</li>"}</ul>
      <p>Best,<br>Corkboard Studio</p></section>
    <h3>Attached spec posts</h3><div class="pitch-assets">${assetCards || `<p class="muted">No spec posts attached.</p>`}</div>
    <h3>Decisions</h3><div class="thread">${knots(c.decisions)}</div>`;
  showSheet(h, `Pitch for ${slug}`);
}

// ---------------------------------------------------------------- try it

$("#lead-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  clearTimeout(leadPreviewTimer);
  await runLeadPreview(true);
});

$("#draft-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const ids = [...document.querySelectorAll("#tech-pick input:checked")].map((x) => x.value);
  if (!ids.length) {
    $("#draft-mobile-warning").textContent = "Pick at least one technique.";
    $("#draft-mobile-warning").hidden = false;
    return;
  }
  $("#draft-mobile-warning").hidden = true;
  const btn = e.target.querySelector("button[type=submit]");
  if (btn) btn.disabled = true;
  try {
    const r = await api("/api/try/draft", { method: "POST", body: JSON.stringify({ client: $("#draft-client").value, technique_ids: ids }) });
    const results = [...(r.results || [])].sort((a, b) => (b.risk || 0) - (a.risk || 0));
    const closest = results[0];
    const shared = (closest?.shared_rare || []).map((item) => {
      const id = typeof item === "string" ? item : item.id;
      const name = typeof item === "string" ? item : item.name;
      const technique = state.techniques.find((candidate) => candidate.id === id || candidate.name === name || candidate.name === id);
      return { id: id || technique?.id, name: name || technique?.name || id };
    }).filter((item) => item.name);
    const sharedSet = new Set(shared.flatMap((item) => [item.id, item.name]));
    const selected = ids.map((id) => state.techniques.find((technique) => technique.id === id)).filter(Boolean);
    const verdictLabel = r.flagged ? "Would be blocked" : "Would clear";
    const ownMoves = selected.map((technique) => `<li class="${sharedSet.has(technique.name) || sharedSet.has(technique.id) ? "shared" : ""}">${esc(technique.name)}</li>`).join("");
    const commonMoves = shared.map((item) => `<li class="shared">${esc(item.name)}</li>`).join("");
    const riskSummary = typeof closest?.risk === "number"
      ? `risk ${n(closest.risk)}, blocked at ${n(r.threshold)}`
      : `Blocked at ${n(r.threshold)} risk`;
    $("#draft-result").innerHTML = `<div class="post-result-box"><div class="post-compare">
        <section class="post-side"><p class="label">Your draft</p><h3>${esc($("#draft-client").selectedOptions[0]?.textContent || "")}</h3><ul class="post-moves">${ownMoves || `<li class="muted">No moves selected.</li>`}</ul></section>
        <section class="post-side closest-side"><p class="label">Closest match</p><h3>${esc(closest?.business || "No close match returned")}</h3>
          <ul class="post-moves">${commonMoves || `<li class="muted">No shared moves returned.</li>`}</ul>
          ${closest ? `<p class="muted">The endpoint does not return the full closest-match move list; only the shared moves above are shown.</p>` : ""}
        </section>
      </div><div class="post-verdict"><span class="status s-${statusKind(r.flagged ? "blocked" : "cleared")}" aria-hidden="true"><i></i></span><b>${esc(verdictLabel)} · ${esc(riskSummary)}</b></div></div>`;
    if (window.matchMedia("(max-width: 760px)").matches) {
      state.mobileTryStep = 2;
      updateTryMobileFlow();
    }
  } catch (err) {
    $("#draft-result").innerHTML = `<div class="flagbox">${esc(err.message)}</div>`;
    if (window.matchMedia("(max-width: 760px)").matches) {
      state.mobileTryStep = 2;
      updateTryMobileFlow();
    }
  }
  finally {
    if (btn) btn.disabled = false;
    $("#draft-result").scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth", block: "nearest" });
  }
});

let draftPreviewTimer = 0;
function scheduleDraftPreview() {
  clearTimeout(draftPreviewTimer);
  draftPreviewTimer = window.setTimeout(() => {
    const ids = [...document.querySelectorAll("#tech-pick input:checked")];
    if (ids.length) $("#draft-form").requestSubmit();
    else $("#draft-result").innerHTML = "";
  }, 250);
}

async function loadTechniques() {
  const ts = await api("/api/techniques");
  state.techniques = ts;
  const rare = state.overview?.thresholds?.rare;
  const by = {};
  ts.forEach((t) => (by[t.style] ||= []).push(t));
  $("#tech-pick").innerHTML = `<p class="rare-note"><span aria-hidden="true">●</span> Rare technique: few businesses use it.</p>${Object.entries(by).map(([s, list]) => `<h3>${esc(s)}</h3>${list.map((t) =>
    `<label><input type="checkbox" value="${esc(t.id)}"><span class="${typeof rare === "number" && t.rarity >= rare ? "rare" : ""}">${esc(t.name)}${typeof rare === "number" && t.rarity >= rare ? '<span class="sr-only">, rare</span>' : ""}</span></label>`).join("")}`).join("")}`;
}

async function loadDraftPresets() {
  const root = $("#draft-presets");
  if (!root) return;
  try {
    const analysis = await api("/api/analysis");
    const top = (analysis.double_take || []).slice().sort((a, b) => (b.risk || 0) - (a.risk || 0))[0];
    const signed = state.overview?.clients?.[0];
    if (!top || !signed) return;
    const detail = await api(`/api/doubletake/${encodeURIComponent(top.client_id)}/${encodeURIComponent(top.draft)}`);
    const flag = detail.flags.find((item) => item.business?.id === top.with_business || item.business?.name === top.with_business)
      || detail.flags.slice().sort((a, b) => (b.risk || 0) - (a.risk || 0))[0];
    const idsFrom = (items) => (items || []).map((item) => typeof item === "string" ? item : item.id).filter(Boolean);
    const presets = [
      { title: "Reuse a neighbor's signature", note: "Try the blocked draft's shared moves.", client: detail.business.id, techniques: idsFrom(flag?.shared) },
      { title: "The rewrite that cleared", note: "Try the revised draft's moves.", client: detail.business.id, techniques: idsFrom(detail.revision?.techniques) },
      { title: "Only common moves", note: "Try the three least rare moves for a signed client.", client: signed.id, techniques: state.techniques.slice().sort((a, b) => (a.rarity || 0) - (b.rarity || 0)).slice(0, 3).map((item) => item.id) },
    ];
    root.innerHTML = presets.map((preset, index) => `<button type="button" class="draft-preset" data-draft-preset="${index}"><b>${esc(preset.title)}</b><small>${esc(preset.note)}</small></button>`).join("");
    root.addEventListener("click", (event) => {
      const button = event.target.closest("[data-draft-preset]");
      if (!button) return;
      const preset = presets[Number(button.dataset.draftPreset)];
      $("#draft-client").value = preset.client;
      document.querySelectorAll("#tech-pick input").forEach((input) => { input.checked = preset.techniques.includes(input.value); });
      if (!preset.techniques.length) return;
      $("#draft-form").requestSubmit();
    });
  } catch (error) {
    console.error("Could not load live post-check presets", error);
  }
}

function setTryTab(tab) {
  state.tryTab = tab;
  state.mobileTryStep = 0;
  document.querySelectorAll("[data-try-tab]").forEach((button) => {
    const selected = button.dataset.tryTab === tab;
    button.setAttribute("aria-selected", String(selected));
  });
  document.querySelectorAll("[data-try-tool]").forEach((tool) => { tool.hidden = tool.dataset.tryTool !== tab; });
  updateTryMobileFlow();
}

function updateTryMobileFlow() {
  const workbench = $("#try-workbench");
  if (!workbench) return;
  const isLead = state.tryTab === "lead";
  const steps = isLead ? 3 : 2;
  const checkStep = isLead ? 2 : 1;
  const resultStep = checkStep + 1;
  workbench.dataset.activeTool = state.tryTab;
  workbench.dataset.mobileStep = String(state.mobileTryStep);
  $("#try-mobile-progress-line").style.width = `${Math.min(1, state.mobileTryStep / steps) * 100}%`;
  $("#try-mobile-next").textContent = state.mobileTryStep >= resultStep
    ? "Edit inputs"
    : state.mobileTryStep >= checkStep ? "See result" : "Next";
}

document.querySelectorAll("[data-try-tab]").forEach((button) => button.addEventListener("click", () => setTryTab(button.dataset.tryTab)));
$("#try-mobile-next").addEventListener("click", () => {
  const isLead = state.tryTab === "lead";
  const checkStep = isLead ? 2 : 1;
  if (state.mobileTryStep > checkStep) {
    state.mobileTryStep = 0;
    updateTryMobileFlow();
    return;
  }
  if (state.mobileTryStep < checkStep) {
    if (isLead && state.mobileTryStep === 1 && state.leadPreset === "own" && !$("#lead-form").reportValidity()) return;
    if (isLead && state.mobileTryStep === 0 && state.leadPreset !== "own") state.mobileTryStep = 2;
    else state.mobileTryStep += 1;
    updateTryMobileFlow();
    return;
  }
  state.mobileTryStep = checkStep + 1;
  updateTryMobileFlow();
});
document.addEventListener("change", (e) => {
  if (e.target.name === "lead-preset") {
    applyLeadPreset(e.target.value);
    return;
  }
  if (e.target.matches("[data-audience]")) {
    $("#lead-mobile-warning").hidden = true;
    const audience = e.target.dataset.audience;
    state.leadTargets[audience] = Number(e.target.value);
    $(`#lead-form [name="aud-${audience}"]`).value = e.target.value;
    scheduleLeadPreview();
    return;
  }
  if (e.target.matches("#tech-pick input")) {
    $("#draft-mobile-warning").hidden = true;
    scheduleDraftPreview();
  }
  if (e.target.matches("#draft-client")) scheduleDraftPreview();
  if (e.target.closest("#lead-form")) scheduleLeadPreview();
});
document.addEventListener("input", (e) => {
  if (e.target.closest("#lead-form") && !e.target.matches("[type=radio]")) scheduleLeadPreview();
});

refresh().then(async () => {
  await loadTechniques();
  await loadDraftPresets();
  updateTryMobileFlow();
  if (isAnalysisView()) await loadAnalysisFromLocation();
});
