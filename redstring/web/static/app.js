const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const VERDICT_LABELS = {
  decline: "Decline: competes nearby",
  pursue: "Pitch",
  pursue_differentiated: "Pitch with a distinct angle",
  borderline: "Board call",
};
const VERDICT_HELP = {
  decline: "Same category as a signed client in the same neighborhood.",
  pursue: "Little audience overlap with signed clients.",
  pursue_differentiated: "Reaches the same people as a client; pitch only with a different creative angle.",
  borderline: "Partial overlap; the board decides.",
};
const chip = (v, label) => {
  if (!(v || label)) return "";
  const verdict = label === undefined && Object.prototype.hasOwnProperty.call(VERDICT_LABELS, v);
  const title = verdict ? ` title="${esc(VERDICT_HELP[v])}"` : "";
  return `<span class="chip ${esc(v || "plain")}"${title}>${esc(label || VERDICT_LABELS[v] || String(v).replace(/_/g, " "))}</span>`;
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
const splitQuery = window.matchMedia("(min-width: 1100px)");
const isSplit = () => splitQuery.matches;
const intro = $("#intro");
const introButton = $("#intro-open");
const introKey = "rs-intro-dismissed";

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "content-type": "application/json" }, ...opts });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

// selected: the business in the dossier. pinned: the viewer picked it (otherwise the dossier follows the action).
let state = { overview: null, techniques: [], selected: null, pinned: false, animating: false, analysis: null, dossierTab: "overview" };

const viewLinks = [...document.querySelectorAll("[data-view-link]")];
const isAnalysisView = () => document.body.dataset.view === "analysis";
function syncViewFromLocation() {
  const view = location.pathname === "/analysis" ? "analysis" : "studio";
  document.body.dataset.view = view;
  viewLinks.forEach((link) => {
    if (link.dataset.viewLink === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  return view;
}

async function viewChanged() {
  const view = syncViewFromLocation();
  if (view === "analysis") {
    closeOverlay();
    if ($("#card").open) $("#card").close();
  }
  if (!state.overview) await refresh();
  if (view === "analysis") await loadAnalysisFromLocation();
  else if (state.selected) await openBusiness(state.selected, { quiet: true });
}

syncViewFromLocation();
viewLinks.forEach((link) => link.addEventListener("click", async (e) => {
  e.preventDefault();
  if (link.getAttribute("aria-current") === "page") return;
  history.pushState({}, "", link.href);
  await viewChanged();
}));
window.addEventListener("popstate", viewChanged);
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

let introSeen = false;
try { introSeen = localStorage.getItem(introKey) === "1"; } catch (_) { /* private mode */ }
setIntroVisible(!introSeen);
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
  await select(hit.business_id);
  dismissIntro();
  $("#dossier-h")?.focus();
});

// Short names for the step knots. The full label from the server stays in the title, aria-label and "Next" line.
const STEP_SHORT = {
  reset: "Seed", screen: "Screen", research: "Research", spec: "Spec + Double Take", pitch: "Pitch",
  approve: "Approve", sign: "Sign", client_month: "Client month", retire_goal: "Retire goal",
};

const STAGES = [
  ["Lead", (b) => b.status === "lead" && !b.verdict, "Every lead has been screened."],
  ["Screened", (b) => b.status === "lead" && b.verdict, "Nothing screened yet. Step 1 runs Scout."],
  ["Pursued", (b) => b.status === "pursued", "No pursuits open."],
  ["Pitched", (b) => b.status === "pitched", "No pitches yet. The board approves every pitch, and nothing is ever sent."],
  ["Signed", (b) => b.status === "signed", "No clients yet."],
];

async function refresh() {
  const o = await api("/api/overview");
  state.overview = o;
  document.body.classList.toggle("readonly", !!o.readonly);
  $("#agency").textContent = o.agency;
  $("#ws-mark").textContent = (o.agency || "").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  const hoods = (o.neighborhoods || []).map((h) => h.name).join(", ");
  $("#ws-meta").textContent = `${o.businesses.length} businesses${hoods ? ` in ${hoods}` : ""}`;
  $("#mode").textContent = `agents: ${o.mode}${o.readonly ? " · read-only" : ""}`;
  $("#meta").textContent = o.graphs.join(" · ");
  // The dossier follows the run (the business in the latest log line) until the viewer picks a card.
  let moved = false;
  if (!state.pinned && isSplit() && !isAnalysisView()) {
    const next = followTarget(o) || state.selected || pickDefault(o.businesses);
    moved = next !== state.selected;
    state.selected = next;
  }
  renderSteps(o);
  renderLog(o.log);
  renderBoard(o);
  renderAttention(o);
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
  if (!$("#aud-sliders .slider")) {
    $("#aud-sliders").insertAdjacentHTML("beforeend", o.audiences.map((a) =>
      `<div class="slider"><label for="aud-${esc(a.id)}">${esc(a.name)}</label><input type="range" min="0" max="1" step="0.1" value="0" id="aud-${esc(a.id)}" name="aud-${esc(a.id)}"><output class="metric" for="aud-${esc(a.id)}">0</output></div>`).join(""));
    $("#aud-sliders").addEventListener("input", (e) => { if (e.target.type === "range") e.target.nextElementSibling.textContent = e.target.value; });
  }
  feed();

  $("#follow").hidden = !state.pinned || !!o.readonly;
  if (state.selected && (isSplit() || $("#drawer").classList.contains("open"))) await openBusiness(state.selected, { quiet: true, animate: moved });
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
    const title = locked ? `Run step ${i - 1} first` : s.label;
    return `<li class="${cls}"><button type="button" data-step="${esc(s.id)}" ${locked ? "disabled" : ""} title="${esc(title)}" aria-label="Step ${i}: ${esc(s.label)} (${said}${locked ? `, run step ${i - 1} first` : ""})"><span class="knot-dot" aria-hidden="true">${i}</span><span class="step-name">${esc(STEP_SHORT[s.id] || s.label)}</span></button></li>`;
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
  const tags = chip(b.verdict);
  return `<button type="button" class="biz" data-biz="${esc(b.id)}" data-status="${esc(b.status)}" aria-pressed="${b.id === state.selected}">
    <span class="biz-name">${esc(b.name)}</span>${meta ? `<span class="biz-meta">${meta}</span>` : ""}
    ${tags ? `<span class="biz-tags">${tags}</span>` : ""}${goal ? `<span class="biz-goal"><b>Goal:</b> ${esc(goal)}</span>` : ""}
    ${b.status === "signed" && client?.won_pitch ? `<span class="biz-goal"><b>Won with spec work</b></span>` : ""}<span class="hole" aria-hidden="true"></span></button>`;
}

const TIE = `<svg viewBox="0 0 44 12" aria-hidden="true"><circle cx="3" cy="6" r="3"/><path d="M3 6 C 15 13, 29 -1, 41 6"/><circle cx="41" cy="6" r="3"/></svg>`;

// Needs you holds decisions only. What Double Take caught is news, so it gets its own column.
function renderAttention(o) {
  const items = o.needs_you || [];
  const byId = Object.fromEntries(o.businesses.map((b) => [b.id, b]));
  const decisions = items.filter((i) => ["borderline", "pitch", "ready"].includes(i.type));
  const unscreened = items.filter((i) => i.type === "unscreened");
  const blocked = items.filter((i) => i.type === "blocked");
  let h = decisions.map((i) => i.type === "pitch"
    ? `<button type="button" class="need-card pitch" data-pitch="${esc(i.pitch_id)}" data-slug="${esc(i.business_id)}"><span class="need-kind">Pitch to approve</span><span class="need-text">${esc(byId[i.business_id]?.name || i.message)}</span><span class="need-cta">Review and decide <span aria-hidden="true">→</span></span></button>`
    : i.type === "ready"
    ? `<button type="button" class="need-card" data-pick="${esc(i.business_ids[0])}"><span class="need-kind">Cleared to pitch</span><span class="need-text">${esc(i.message)}</span></button>`
    : `<button type="button" class="need-card borderline" data-pick="${esc(i.business_id)}"><span class="need-kind">Board call</span><span class="need-text">${esc(i.message)}</span></button>`).join("");
  if (unscreened.length) {
    h += `<button type="button" class="need-card" data-pick="${esc(unscreened[0].business_id)}"><span class="need-kind">Leads to screen</span><span class="need-text">${unscreened.length} new ${unscreened.length === 1 ? "lead is" : "leads are"} waiting for Scout</span></button>`;
  }
  $("#needs-you").innerHTML = h || `<p class="empty-row">Nothing needs a decision right now.</p>`;
  $("#caught").innerHTML = blocked.map((i) => `<button type="button" class="caught-card" data-pick="${esc(i.business_id)}">
      <span class="need-kind">Blocked and revised</span>
      <span class="caught-a">${esc(i.business || byId[i.business_id]?.name)}</span>
      <span class="caught-pair">${TIE}<span>looked like <b>${esc(i.with_business || "")}</b>${i.also_like?.length ? ` and <b>${i.also_like.map(esc).join(", ")}</b>` : ""}</span></span>
      ${i.hook ? `<span class="caught-hook">“${esc(i.hook)}”</span>` : ""}
    </button>`).join("")
    || `<p class="empty-row">Nothing caught yet. Double Take checks every draft from step 3 on.</p>`;
}

function renderBoard(o) {
  $("#board").innerHTML = STAGES.map(([title, test, empty]) => {
    const items = o.businesses.filter(test);
    if (title === "Screened") {
      const order = { pursue: 0, pursue_differentiated: 1, borderline: 2, decline: 3 };
      items.sort((a, z) => (order[a.verdict] ?? 4) - (order[z.verdict] ?? 4) || a.name.localeCompare(z.name));
    }
    const won = (o.clients || []).filter((client) => client.won_pitch).map((client) => client.name);
    const emptyText = title === "Pitched" && won.length
      ? `No open pitches. Won and signed: ${won.join(", ")}.`
      : empty;
    return `<section class="stage" aria-label="${title}, ${items.length}"><h3>${title} <span class="count">${items.length}</span></h3>
      ${items.length ? `<div class="cards">${items.map(bizCard).join("")}</div>` : `<p class="empty-row">${esc(emptyText)}</p>`}</section>`;
  }).join("");
}

async function feed() {
  const ds = await api("/api/decisions");
  $("#feed").innerHTML = ds.map((d) =>
    `<li><div><div class="who">${esc(d.by)}</div><div class="g analysis-only">${esc(d.graph)}</div></div><div><b>${esc(displayStudioCopy(d.text))}</b><div class="muted">${esc(displayStudioCopy(d.rationale))}</div></div></li>`).join("")
    || `<li class="empty">No decisions yet. Run the steps above.</li>`;
}

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

const pretty = (id) => String(id || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
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
      <p class="gname">${esc(b.name || slug)}</p>
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
  const leads = analysis.screening;
  if (!state.netLead || !leads.some((r) => r.id === state.netLead)) {
    state.netLead = [...leads].sort((a, z) => (z.max_conflict || 0) - (a.max_conflict || 0))[0]?.id || null;
  }
  $("#screening-legend").textContent = `Conflict is the sum of path weights to one client. At ${n(t.borderline)} or more it is a board call; at ${n(t.differentiate)} or more Scout only pitches with a distinct angle. Same category in the same neighborhood is an automatic decline.`;
  $("#screening-table").innerHTML = `<caption class="sr-only">Conflict between each lead and each signed client</caption>
    <thead><tr><th scope="col">Lead</th>${clients.map((c) => `<th scope="col">${esc(c.name)}</th>`).join("")}<th scope="col">Verdict</th></tr></thead>
    <tbody>${leads.map((row) => {
      const cells = clients.map((c) => {
        const v = (row.clients || []).find((x) => x.client_id === c.id)?.conflict || 0;
        return `<td><span class="cell b${bin(v)}">${n(v)}</span></td>`;
      }).join("");
      const sel = row.id === state.netLead;
      return `<tr class="${sel ? "sel" : ""}"><th scope="row"><button type="button" class="lead-btn" data-lead="${esc(row.id)}" aria-pressed="${sel}">${esc(row.name)}<small>${esc(row.category)} · ${esc(row.neighborhood)}</small><span class="mobile-verdict">${chip(row.verdict)}</span></button></th>${cells}<td class="v">${chip(row.verdict)}</td></tr>`;
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
      const parts = p.via.split(" -> ").map((x) => audName[x]);
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
  $("#verdict-math").innerHTML = `<div class="vm-head"><b>${esc(row.name)}</b>${chip(row.verdict)}</div>
    <p class="vm-reason">${esc(row.reason)}</p>
    ${row.competitors?.length ? `<p class="vm-reason">Same category as ${row.competitors.map((c) => esc(c.client)).join(", ")} in the same neighborhood.</p>` : ""}
    <div class="vm-scale" aria-hidden="true"><span style="left:${pct(t.borderline)}">Board call ${n(t.borderline)}</span><span style="left:${pct(t.differentiate)}">Distinct angle ${n(t.differentiate)}</span></div>
    <ul class="vm-bars">${cl.map((c, i) => `<li><span>${esc(c.client)}</span>
      <span class="vm-track" role="img" aria-label="conflict ${n(c.conflict)}"><span class="vm-fill${i === 0 ? " top" : ""}" style="width:${pct(c.conflict)}"></span><span class="vm-tick" style="left:${pct(t.borderline)}"></span><span class="vm-tick" style="left:${pct(t.differentiate)}"></span></span>
      <span class="vm-val">${n(c.conflict)}</span></li>`).join("") || `<li class="muted">No audience paths to any signed client.</li>`}</ul>`;
}

$("#screening-table").addEventListener("click", (e) => {
  const b = e.target.closest("[data-lead]");
  if (!b) return;
  state.netLead = b.dataset.lead;
  document.querySelectorAll("#screening-table tbody tr").forEach((tr) => {
    const on = tr.querySelector("[data-lead]")?.dataset.lead === state.netLead;
    tr.classList.toggle("sel", on);
    tr.querySelector("[data-lead]")?.setAttribute("aria-pressed", String(on));
  });
  renderNet();
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
        <div class="dt-col"><div class="dt-node draft"><span class="k">Blocked draft</span><b>${esc(g.client)}</b><span class="hook">“${esc(g.draft_hook || g.draft)}”</span></div></div>
        <div class="dt-col dt-techs">${techs.map((x) => `<span class="dt-tech" data-tech="${esc(x)}">${esc(x)}</span>`).join("")}</div>
        <div class="dt-col">${g.flags.map((f) => `<div class="dt-node other" data-shared="${esc((f.shared || []).join("|"))}"><span class="k">Looks like</span><b>${esc(f.with_business)}</b><span class="hook">${plural((f.evidence || []).length, "piece", "pieces")} of its work already use${(f.evidence || []).length === 1 ? "s" : ""} these</span></div>`).join("")}</div>
      </div>
      <ul class="dt-risk">${g.flags.map((f) => `<li>
        <span class="dt-eq">vs ${esc(f.with_business)}: similarity ${n(f.similarity)} × audience overlap ${n(f.overlap)} = <b>risk ${n(f.risk)}</b></span>
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
  const rows = [...new Map(sigs.map((s) => [s.business_id, s.business])).entries()]
    .sort((a, z) => (status[z[0]] === "signed") - (status[a[0]] === "signed") || a[1].localeCompare(z[1]));
  const share = Object.fromEntries(sigs.map((s) => [`${s.business_id}|${s.technique}`, s.share]));
  const label = { signed: "Client", pursued: "Pursued", pitched: "Pitched", lead: "Lead", passed: "Passed" };
  $("#signatures-table").innerHTML = `<caption class="sr-only">Signature techniques by business</caption>
    <thead><tr><td></td>${cols.map((c) => `<th scope="col" class="col${hotCols.has(c.name) ? " contested" : ""}" title="rarity ${n(c.rarity)}, claimed by ${c.by.size}"><span>${esc(c.name)}</span></th>`).join("")}</tr></thead>
    <tbody>${rows.map(([id, name]) => `<tr class="${status[id] === "signed" ? "signed" : ""}"><th scope="row">${esc(name)}<small>${label[status[id]] || ""}</small></th>${cols.map((c) => {
      const v = share[`${id}|${c.name}`];
      const d = v ? Math.round(8 + v * 16) : 0;
      return `<td class="${hotCols.has(c.name) ? "contested" : ""}">${v ? `<span class="dot${hotCells.has(`${id}|${c.name}`) ? " hot" : ""}" style="width:${d}px;height:${d}px" title="${esc(name)}: ${esc(c.name)} in ${Math.round(v * 100)}% of its work"></span><span class="sr-only">${Math.round(v * 100)}%</span>` : ""}</td>`;
    }).join("")}</tr>`).join("") || `<tr><td class="muted">No signatures yet.</td></tr>`}</tbody>`;
}

// 5. agents and the named queries they are allowed to call
function renderAccess(analysis) {
  const qs = analysis.queries;
  const agents = Object.entries(analysis.agents);
  $("#analysis-agents").innerHTML = `<caption class="sr-only">Which agent can call which named query</caption>
    <thead><tr><td></td>${qs.map((q) => `<th scope="col"><span class="qtag">${esc(q.query)}</span>${esc(q.tool)}</th>`).join("")}<th scope="col">Other tools</th></tr></thead>
    <tbody>${agents.map(([agent, tools]) => {
      const named = qs.filter((q) => tools.includes(q.tool)).length;
      return `<tr><th scope="row">${esc(pretty(agent))}</th>${qs.map((q) => `<td>${tools.includes(q.tool) ? `<span class="yes" title="${esc(pretty(agent))} can call ${esc(q.tool)}"></span><span class="sr-only">yes</span>` : ""}</td>`).join("")}<td class="other">${tools.length - named}</td></tr>`;
    }).join("")}</tbody>`;
  $("#queries").innerHTML = qs.map((q) => `<article class="query-card">
    <h3><span class="qtag">${esc(q.query)}</span>${esc(q.tool)}</h3>
    <p>${esc(q.description.replace(/^[PQ]\d\.\s*/, ""))}</p>
    <p class="muted">Called by ${q.agents.map((a) => esc(pretty(a))).join(", ") || "no agent"}</p>
    ${q.cypher.map((c) => `<details><summary>${esc(c.constant)}</summary><pre>${esc(c.text.trim())}</pre></details>`).join("")}
  </article>`).join("");
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
const chapterLinks = [...document.querySelectorAll(".chapter-nav a")];
if ("IntersectionObserver" in window) {
  const seen = new Map();
  const io = new IntersectionObserver((entries) => {
    entries.forEach((en) => seen.set(en.target.id, en.isIntersecting ? en.intersectionRatio : 0));
    const active = [...seen.entries()].sort((a, z) => z[1] - a[1])[0];
    chapterLinks.forEach((a) => a.classList.toggle("active", !!active && active[1] > 0 && a.getAttribute("href") === `#${active[0]}`));
  }, { rootMargin: "-80px 0px -45% 0px", threshold: [0, 0.2, 0.5, 1] });
  document.querySelectorAll(".chapter").forEach((c) => io.observe(c));
}

$("#steps").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-step]");
  if (!b) return;
  document.querySelectorAll("#steps button").forEach((x) => (x.disabled = true));
  b.setAttribute("aria-busy", "true");
  $("#log").insertAdjacentHTML("beforeend", `<span class="ln cmd">${esc(`> ${b.dataset.step}…`)}</span>`);
  $("#log").scrollTop = 1e6;
  try { await api(`/api/step/${b.dataset.step}`, { method: "POST" }); }
  catch (err) { alert(err.message); }
  await refresh();
});

// ---------------------------------------------------------------- the dossier (business detail, docked)

$("#board").addEventListener("click", (e) => {
  const b = e.target.closest("[data-biz]");
  if (b) select(b.dataset.biz);
});

$("#follow").addEventListener("click", () => { state.pinned = false; refresh(); });

function select(slug) {
  const changed = slug !== state.selected;
  state.selected = slug;
  state.pinned = true;
  $("#follow").hidden = false;
  document.querySelectorAll("#board [data-biz]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.biz === slug)));
  return openBusiness(slug, { animate: changed || !isSplit() });
}

async function openBusiness(slug, { quiet = false, animate = false } = {}) {
  const panel = $("#drawer");
  if (panel.dataset.slug !== slug) state.dossierTab = "overview";
  let d;
  try { d = await api(`/api/business/${slug}`); }
  catch (err) {
    if (quiet) { state.selected = null; state.pinned = false; emptyDossier(); return; }
    throw err;
  }
  const b = d.business;
  const ro = state.overview?.readonly;
  const hood = hoodOf(b);
  let h = `<div class="dossier-meta"><span>${esc(b.category)}${hood ? ` · ${esc(hood)}` : ""}</span>
      <button type="button" class="btn small dossier-close" data-dossier-close>Close</button></div>
    <h2 class="name" id="dossier-h" tabindex="-1">${esc(b.name)}</h2>
    <div class="status-row">${chip(b.status)}${b.voice ? `<span class="muted">Voice: ${esc(b.voice)}</span>` : ""}</div>`;

  let overview = "";
  if (d.screening && d.screening.verdict) {
    const s = d.screening;
    overview += `<h3>Scout's screening</h3><div class="thread"><div class="knot"><div class="who">${esc(s.by || "Scout")} ${chip(s.verdict)}</div><p>${esc(displayStudioCopy(s.reason))}</p></div>
      ${(s.paths || []).map((c) => {
        const ps = [...(c.paths || [])].sort((a, z) => z.conflict - a.conflict);
        const pill = (p) => `<li>${esc(p.via)} <span class="metric">· ${n(p.conflict)}</span></li>`;
        return `<div class="knot minor"><div class="who">${esc(c.client)} <span class="metric">· conflict ${n(c.conflict)}</span>${c.same_category ? " · same category" : ""}</div>
          ${ps.length ? `<p class="muted">via ${ps.slice(0, 2).map((p) => esc(p.via)).join(", ")}</p><p class="muted mono metric">Path contributions: ${ps.slice(0, 2).map((p) => `${esc(p.via)} ${n(p.conflict, 3)}`).join(" · ")}</p>` : ""}
          ${ps.length > 2 ? `<details class="metric"><summary>All ${ps.length} audience paths</summary><ul class="paths">${ps.map(pill).join("")}</ul></details>` : ""}</div>`;
      }).join("")}</div>`;
    overview += `<p class="analysis-bridge-row"><a class="analysis-bridge" href="/analysis?lead=${encodeURIComponent(slug)}#ch-screening" data-analysis-link>How was this decided?</a></p>`;
  }

  if (d.has_graph && d.flags && d.flags.length) {
    const drafts = Object.fromEntries((d.drafts || []).map((x) => [x.id, x]));
    const byDraft = {};
    d.flags.forEach((f) => (byDraft[f.draft] ||= []).push(f));
    const ids = Object.keys(byDraft);
    overview += `<h3>Double Take <span class="muted">${ids.length} ${ids.length === 1 ? "draft" : "drafts"} blocked</span></h3><div class="thread">${ids.map((id) => {
      const dr = drafts[id];
      return `<div class="knot hit"><div class="who">Blocked ${dr ? `<span class="metric">v${esc(dr.version)} </span>draft` : "draft"}</div><div class="body">
        ${dr ? `<p><button type="button" class="row-btn" data-draft="${esc(id)}" data-slug="${esc(slug)}"><b>“${esc(dr.hook)}”</b></button></p>` : ""}
        ${byDraft[id].map((f) => `<p>Too close to <b>${esc(f.with_business)}</b>: shares ${(f.shared || []).map(esc).join(", ")}.</p>
        <p class="muted mono metric">similarity ${n(f.similarity)} × audience overlap ${n(f.overlap)} = risk ${n(f.risk)}</p>`).join("")}
        <p class="analysis-bridge-row"><a class="analysis-bridge" href="/analysis?draft=${encodeURIComponent(id)}#ch-double-take" data-analysis-link>How was this decided?</a></p></div></div>`;
    }).join("")}</div>`;
  }

  let draftsTab = "";
  let research = `<h3>Who it targets</h3><ul class="targets">${d.audiences.map((a) =>
    `<li><span>${esc(a.audience)}</span><span class="bar" aria-hidden="true"><span style="width:${Math.round(Math.min(1, a.weight || 0) * 100)}%"></span></span><span class="num metric">${n(a.weight, 1)}</span></li>`).join("") || "<li class='muted'>No audiences.</li>"}</ul>
    <h3>Signature moves <span class="muted">rare elsewhere, common in its work</span></h3>${d.signatures.length ? `<ul class="sig-list">${d.signatures.map((s) => `<li>${esc(s.technique)}<span class="metric"> ${Math.round(s.share * 100)}%</span></li>`).join("")}</ul>` : "<p class='muted'>None yet.</p>"}`;
  if (d.has_graph) {
    if (d.stale.length) overview += `<div class="warnbox"><b><span class="metric">${d.stale.length} </span>stale drafts</b> serve a retired goal: ${d.stale.map((s) => esc(s.hook)).join("; ")}</div>`;
    overview += `<h3>Goals</h3><ul class="list">${d.goals.map((g) => `<li><div class="goal-line">${chip(g.status)} <b>${esc(g.text)}</b></div>
      <div class="goal-meta metric">${esc(g.metric)} → ${esc(g.target)} by ${esc(g.due)}</div>
      ${g.status === "active" && !ro ? `<div class="btn-row"><button type="button" class="btn small" data-retire="${esc(g.id)}" data-slug="${esc(slug)}">Retire goal</button></div>` : ""}</li>`).join("") || "<li class='muted'>None yet.</li>"}</ul>`;
    if (d.pitches.length) overview += `<h3>Pitches</h3><ul class="list">${d.pitches.map((p) =>
      `<li><button type="button" class="row-btn" data-pitch="${esc(p.id)}" data-slug="${esc(slug)}">${chip(p.status)} <b>${esc(p.angle)}</b></button></li>`).join("")}</ul>`;
    draftsTab += `<h3>Drafts</h3><ul class="list">${d.drafts.map((x) =>
      `<li><button type="button" class="row-btn" data-draft="${esc(x.id)}" data-slug="${esc(slug)}">${chip(x.status)}${chip("plain", x.kind)} <b><span class="metric">v${esc(x.version)} · </span>${esc(x.hook)}</b></button></li>`).join("") || "<li class='muted'>None yet.</li>"}</ul>`;
    if (d.taste_profile && d.taste_profile.id) draftsTab += `<h3>Taste profile <span class="muted metric">v${esc(d.taste_profile.version)}</span></h3><p>${esc(d.taste_profile.summary)}</p>
      <p class="muted" style="margin-top:6px">Prefers: ${d.taste_profile.prefers.map((p) => esc(p.name)).join(", ")}${d.taste_profile.avoids.length ? `<br>Avoids: ${d.taste_profile.avoids.map((p) => esc(p.name)).join(", ")}` : ""}</p>`;
    research += `<h3>Findings <span class="muted">each with its source</span></h3><ul class="list">${d.findings.map((f) => `<li>${chip("plain", f.kind)} ${f.kind === "audit" ? `${esc(f.text)} <span class="muted">From the audit of past posts.</span>` : f.source_url ? link(f.source_url, f.text) : `${esc(f.text)} ${link(f.source_url)}`}</li>`).join("") || "<li class='muted'>None yet.</li>"}</ul>`;
    research += `<h3>Past posts</h3><ul class="list">${d.posts.map((p) => `<li>${esc(p.hook)} <span class="muted metric">${(p.views ?? 0).toLocaleString()} views · ${(p.saves ?? 0).toLocaleString()} saves</span></li>`).join("") || "<li class='muted'>Not loaded.</li>"}</ul>`;
  } else {
    overview += `<div class="warnbox"><b>No private graph yet.</b> Scout creates one when it pursues this lead.</div>`;
  }

  const tabs = [{ id: "overview", label: "Overview", content: overview }];
  if (d.has_graph) tabs.push({ id: "drafts", label: "Drafts", content: draftsTab });
  tabs.push({ id: "research", label: "Research", content: research });
  if (d.has_graph && d.decisions && d.decisions.length) {
    tabs.push({
      id: "activity",
      label: "Activity",
      content: `<h3>Latest decisions <span class="muted analysis-only">client:${esc(slug)}</span></h3><div class="thread">${d.decisions.slice(0, 10).map((x) =>
        `<div class="knot minor"><div class="who">${esc(x.by)}</div><p><b>${esc(displayStudioCopy(x.text))}</b></p>${x.rationale ? `<p class="muted">${esc(displayStudioCopy(x.rationale))}</p>` : ""}</div>`).join("")}</div>`,
    });
  }
  if (!tabs.some((tab) => tab.id === state.dossierTab)) state.dossierTab = "overview";
  tabs[0].content = tabs[0].content.replace('class="thread"', 'class="thread lead"');
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
  if (!quiet) $("#sr-status").textContent = `Showing ${b.name}`;
  if (!isSplit() && !quiet) openOverlay();
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
$("#drawer").addEventListener("keydown", (e) => { if (e.key === "Escape" && !isSplit()) closeOverlay(); });
splitQuery.addEventListener("change", () => {
  if (isSplit()) { $("#drawer").classList.remove("open"); $("#scrim").hidden = true; if (!state.selected) refresh(); }
  drawString(false);
});

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
  const pick = e.target.closest("[data-pick]");
  if (pick) { select(pick.dataset.pick); return; }
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

// ---------------------------------------------------------------- route cards (threads) and pitch cards

function knots(decisions) {
  return decisions.map((x) => `<div class="knot"><div class="who">${esc(x.by)}</div><p><b>${esc(displayStudioCopy(x.decision))}</b></p>${x.rationale ? `<p class="muted">${esc(displayStudioCopy(x.rationale))}</p>` : ""}</div>`).join("");
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
  const { noun, what } = BOARD_COPY[label];
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
  if (!$("#card").open) $("#card").showModal();
}

async function openRoute(slug, id) {
  const c = await api(`/api/route/${slug}/${id}`);
  let h = sheetTop(`<span class="studio-only">Thread</span><span class="analysis-only">Thread · client:${esc(slug)} · ${esc(id)}</span>`) +
    `<h2>${esc(c.draft)}</h2><p class="serves">${chip(c.status)} ${c.goal ? `serves ${chip(c.goal_status)} <b>${esc(c.goal)}</b>` : ""}</p>` + decisionBar("Draft", id, slug, c);
  if (c.flags.length) h += c.flags.map((f) => `<div class="flagbox"><b>Double Take blocked this draft.</b> It resembles ${esc(f.with_business)}: shares ${f.shared.map(esc).join(", ")}.
    <div class="mono metric" style="margin-top:4px;font-size:.8125rem">similarity ${n(f.similarity)} × audience overlap ${n(f.overlap)} = risk ${n(f.risk)}</div>
    <div class="muted metric" style="margin-top:4px;font-size:.8125rem">Evidence: ${f.evidence.map((e) => `${esc(e.fingerprint)} (${esc(e.kind)}, ${esc(e.hits)} shared)`).join(", ")}</div></div>`).join("");
  else if (c.status !== "flagged") h += `<div class="okbox"><b>Cleared Double Take.</b></div>`;
  if (c.previous.length) h += `<div class="warnbox"><b>Revision</b> of ${c.previous.map((p) => `<span class="metric">v${esc(p.version)} </span>“${esc(p.hook)}”`).join(", ")}${c.flags_on_previous.length ? `, which was blocked for resembling ${c.flags_on_previous.map((f) => esc(f.with)).join(", ")} (${c.flags_on_previous.map((f) => f.shared.map(esc).join(", ")).join("; ")})` : ""}.</div>`;
  h += `<h3>Decisions</h3><div class="thread">${knots(c.decisions)}</div>`;
  h += `<h3>Sources</h3><ul class="list">${c.sources.filter((s) => s.kind !== "Reference").map((s) => `<li>${chip("plain", s.kind)} ${s.source_url ? link(s.source_url, s.text) : esc(s.text)}</li>`).join("") || "<li class='muted'>None.</li>"}</ul>`;
  h += `<h3>Techniques</h3><ul class="tech-list">${c.techniques.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>`;
  h += `<h3>References</h3><ul class="list">${c.references.map((r) => {
    const label = r.creator && r.category ? `${r.creator} · ${r.category}` : r.creator || r.category;
    return `<li>${link(r.url, label)}</li>`;
  }).join("") || "<li class='muted'>None.</li>"}</ul>`;
  showSheet(h, `Thread for ${c.draft}`);
}

async function openPitch(slug, id) {
  const c = await api(`/api/pitch/${slug}/${id}`);
  const h = sheetTop(`<span class="studio-only">Pitch</span><span class="analysis-only">Pitch · client:${esc(slug)} · ${esc(id)}</span>`) +
    `<h2>${esc(c.angle)}</h2><p class="serves">${chip(c.status)} argues for ${chip(c.goal_status)} <b>${esc(c.goal)}</b></p>${decisionBar("Pitch", id, slug, c)}
    ${c.goal_status === "hypothesized" ? `<div class="warnbox"><b>The goal is a hypothesis.</b> It is the Researcher's inference, shown to the prospect as one.</div>` : ""}
    <h3>Every claim, with its source</h3><ul class="list">${c.claims.map((f) => `<li>${chip("plain", f.kind)} ${f.kind === "audit" ? `${esc(f.text)} <span class="muted">From our audit of their posts.</span>` : f.source_url ? link(f.source_url, f.text) : `${esc(f.text)} ${link(f.source_url)}`}</li>`).join("")}</ul>
    <h3>Spec posts</h3><ul class="list">${c.spec_posts.map((d) => `<li><button type="button" class="row-btn" data-draft="${esc(d.id)}" data-slug="${esc(slug)}">${chip(d.status)} <b>${esc(d.hook)}</b></button></li>`).join("")}</ul>
    <h3>Decisions</h3><div class="thread">${knots(c.decisions)}</div>`;
  showSheet(h, `Pitch for ${slug}`);
}

// ---------------------------------------------------------------- try it

$("#lead-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const targets = {};
  for (const [k, v] of f.entries()) if (k.startsWith("aud-") && +v > 0) targets[k.slice(4)] = +v;
  const btn = e.target.querySelector("button[type=submit]");
  btn.disabled = true;
  try {
    const r = await api("/api/try/lead", { method: "POST", body: JSON.stringify({ name: f.get("name"), category: f.get("category"), targets, neighborhood: f.get("neighborhood") }) });
    const box = r.verdict === "pursue" ? "okbox" : ["pass", "decline"].includes(r.verdict) ? "declinebox" : "warnbox";
    const savedNote = r.saved === false ? `<p class="muted">Not saved: screening a lead here does not add it to the graph.</p>` : "";
    $("#lead-result").innerHTML = `<div class="${box}">${chip(r.verdict)} ${esc(displayCopy(r.reason))}</div>${savedNote}
      ${r.clients.length ? `<div class="thread">${r.clients.map((c) => {
        const ps = [...c.paths].sort((a, z) => z.conflict - a.conflict);
        return `<div class="knot minor"><div class="who">${esc(c.client)} <span class="metric">· conflict ${n(c.conflict)}</span></div>
          ${ps.length ? `<p class="muted">via ${ps.slice(0, 2).map((p) => esc(p.via)).join(", ")}</p><p class="muted mono metric">Path contributions: ${ps.slice(0, 2).map((p) => `${esc(p.via)} ${n(p.conflict, 3)}`).join(" · ")}</p>` : ""}
          ${ps.length > 2 ? `<details class="metric"><summary>All ${ps.length} audience paths</summary><ul class="paths">${ps.map((p) => `<li>${esc(p.via)} · ${n(p.conflict, 3)}</li>`).join("")}</ul></details>` : ""}</div>`;
      }).join("")}</div>` : ""}
      ${r.lead && r.saved !== false ? `<div class="btn-row"><button type="button" class="btn small" data-pick="${esc(r.lead)}">Open its dossier</button></div>` : ""}`;
    refresh();
  } catch (err) { $("#lead-result").innerHTML = `<div class="flagbox">${esc(err.message)}</div>`; }
  finally { btn.disabled = false; }
});

$("#draft-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const ids = [...document.querySelectorAll("#tech-pick input:checked")].map((x) => x.value);
  if (!ids.length) { $("#draft-result").innerHTML = `<div class="warnbox">Pick at least one technique.</div>`; return; }
  const btn = e.target.querySelector("button[type=submit]");
  btn.disabled = true;
  try {
    const r = await api("/api/try/draft", { method: "POST", body: JSON.stringify({ client: $("#draft-client").value, technique_ids: ids }) });
    $("#draft-result").innerHTML = (r.flagged ? `<div class="flagbox"><b>Would be blocked.</b> Cross-client risk reaches the flag threshold. <span class="metric">Flag threshold ${n(r.threshold)}.</span></div>` : `<div class="okbox"><b>Would clear.</b> <span class="metric">Threshold ${n(r.threshold)}.</span></div>`)
      + `<ul class="list">${r.results.map((x) => `<li>${chip(x.flag ? "flagged" : "cleared", x.flag ? "flag" : "ok")} <b>${esc(x.business)}</b> <span class="muted">(${esc(x.status)})</span>: shares ${x.shared_rare.map(esc).join(", ")}<br><span class="mono metric" style="font-size:.8125rem">similarity ${n(x.similarity)} × overlap ${n(x.overlap)} = <b>${n(x.risk)}</b></span></li>`).join("") || "<li class='muted'>Shares no rare technique with anyone on the same audience.</li>"}</ul>`;
  } catch (err) { $("#draft-result").innerHTML = `<div class="flagbox">${esc(err.message)}</div>`; }
  finally { btn.disabled = false; }
});

async function loadTechniques() {
  const ts = await api("/api/techniques");
  const rare = state.overview?.thresholds.rare ?? 0.6;
  const by = {};
  ts.forEach((t) => (by[t.style] ||= []).push(t));
  $("#tech-pick").innerHTML = Object.entries(by).map(([s, list]) => `<h3>${esc(s)}</h3>${list.map((t) =>
    `<label><input type="checkbox" value="${esc(t.id)}"><span class="${t.rarity >= rare ? "rare" : ""}">${esc(t.name)}</span></label>`).join("")}`).join("");
}

refresh().then(async () => {
  await loadTechniques();
  if (isAnalysisView()) await loadAnalysisFromLocation();
});
