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
  .replace(/similarity [\d.]+\s*[×x]\s*(?:audience )?overlap [\d.]+\s*=\s*risk [\d.]+(?:,?\s*(?:over|under) [\d.]+)?/gi, "similarity check")
  .replace(/The hackathon build sends nothing\./gi, "Nothing is sent from this workspace.");
const n = (x, d = 2) => (typeof x === "number" ? x.toFixed(d) : "");
const link = (u) => u ? `<a class="src" href="${esc(u)}" target="_blank" rel="noopener">${esc(u)}</a>` : `<span class="muted">no source URL</span>`;
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
let state = { overview: null, techniques: [], selected: null, pinned: false, animating: false, analysis: null };

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
  if (view === "analysis") await loadAnalysis();
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

function setIntroVisible(visible) {
  intro.hidden = !visible;
  introButton.setAttribute("aria-expanded", String(visible));
}

function dismissIntro() {
  setIntroVisible(false);
  localStorage.setItem(introKey, "1");
}

setIntroVisible(localStorage.getItem(introKey) !== "1");
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
  await select("tumble-town");
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
  $("#mode").textContent = `agents: ${o.mode}${o.readonly ? " · read-only" : ""}`;
  $("#meta").textContent = o.graphs.join(" · ");
  $("#biz-count").textContent = `${o.businesses.length} businesses in the pipeline`;
  const thresholds = o.thresholds || {};
  $("#thresholds").innerHTML = [
    ["Rare technique", thresholds.rare],
    ["Flag risk", thresholds.flag_risk],
    ["Differentiate", thresholds.differentiate],
    ["Borderline", thresholds.borderline],
  ].map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${n(value)}</dd></div>`).join("");
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
  renderNeedsYou(o);
  renderClients(o);
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
  const meta = [b.category, hoodOf(b)].filter(Boolean).map(esc).join(" · ");
  const tags = chip(b.verdict) + (b.owner ? chip("owner", "owner: " + b.owner) : "");
  return `<button type="button" class="biz" data-biz="${esc(b.id)}" data-status="${esc(b.status)}" aria-pressed="${b.id === state.selected}">
    <span class="biz-name">${esc(b.name)}</span>${meta ? `<span class="biz-meta">${meta}</span>` : ""}
    ${tags ? `<span class="biz-tags">${tags}</span>` : ""}<span class="hole" aria-hidden="true"></span></button>`;
}

function renderNeedsYou(o) {
  const items = o.needs_you || [];
  $("#needs-you").innerHTML = items.length
    ? items.map((item) => `<button type="button" class="need-card ${esc(item.type)}" data-pick="${esc(item.business_id)}">
        <span class="need-kind">${esc(item.type === "blocked" ? "Caught before it shipped" : item.type === "borderline" ? "Board call" : item.type === "pitch" ? "Pitch" : "Lead")}</span>
        <span>${esc(item.message)}</span>
      </button>`).join("")
    : `<p class="empty-row">Nothing needs you right now.</p>`;
}

function renderClients(o) {
  const clients = o.clients || [];
  $("#clients").innerHTML = clients.length
    ? clients.map((client) => `<button type="button" class="client-card" data-pick="${esc(client.id)}">
        <span class="client-card-name">${esc(client.name)}</span>
        <span class="client-card-meta">${esc(client.category)}${client.neighborhood ? ` · ${esc(client.neighborhood)}` : ""}</span>
        <span class="client-card-goals">${client.goals.length
          ? client.goals.map((goal) => esc(goal.text)).join(" · ")
          : "No active goals."}</span>
      </button>`).join("")
    : `<p class="empty-row">No clients yet.</p>`;
}

function renderBoard(o) {
  $("#board").innerHTML = STAGES.map(([title, test, empty]) => {
    const items = o.businesses.filter(test);
    return `<section class="stage" aria-label="${title}, ${items.length}"><h3>${title} <span class="count">${items.length}</span></h3>
      ${items.length ? `<div class="cards">${items.map(bizCard).join("")}</div>` : `<p class="empty-row">${esc(empty)}</p>`}</section>`;
  }).join("");
}

async function feed() {
  const ds = await api("/api/decisions");
  $("#feed").innerHTML = ds.map((d) =>
    `<li><div><div class="who">${esc(d.by)}</div><div class="g analysis-only">${esc(d.graph)}</div></div><div><b>${esc(displayCopy(d.text))}</b><div class="muted">${esc(displayCopy(d.rationale))}</div></div></li>`).join("")
    || `<li class="empty">No decisions yet. Run the steps above.</li>`;
}

async function loadAnalysis() {
  const [analysis, decisions] = await Promise.all([api("/api/analysis"), api("/api/decisions")]);
  state.analysis = analysis;
  renderAnalysis(analysis, state.overview, decisions);
}

function renderAnalysis(analysis, overview, decisions) {
  const threshold = analysis.thresholds || {};
  $("#graph-cards").innerHTML = analysis.graphs.map((graph) => {
    const nodes = Object.entries(graph.nodes || {});
    const edges = Object.entries(graph.edges || {});
    const countList = (items) => items.length
      ? items.map(([label, count]) => `<li><span>${esc(label)}</span><span class="mono">${esc(count)}</span></li>`).join("")
      : `<li class="muted">None</li>`;
    return `<article class="graph-card">
      <h3><code>${esc(graph.name)}</code></h3>
      <div class="graph-counts"><div><h4>Nodes</h4><ul>${countList(nodes)}</ul></div><div><h4>Edges</h4><ul>${countList(edges)}</ul></div></div>
    </article>`;
  }).join("") || `<p class="empty-row">No graphs.</p>`;

  const signedClients = overview?.clients || [];
  const leads = analysis.screening.filter((row) => row.status === "lead");
  const clientHeaders = signedClients.map((client) => `<th scope="col">${esc(client.name)}</th>`).join("");
  $("#screening-legend").textContent = `Differentiate at ≥ ${n(threshold.differentiate)}; borderline at ≥ ${n(threshold.borderline)}.`;
  $("#screening-table").innerHTML = `<thead><tr><th scope="col">Lead</th><th scope="col">Category</th><th scope="col">Neighborhood</th>${clientHeaders}<th scope="col">Verdict</th><th scope="col">Same-area rule</th></tr></thead>
    <tbody>${leads.map((row) => {
      const perClient = row.clients || [];
      const clientCells = signedClients.map((client) => {
        const conflict = perClient.find((item) => item.client_id === client.id);
        return `<td class="mono">${n(conflict?.conflict ?? 0, 3)}</td>`;
      }).join("");
      const sameArea = row.competitors?.length
        ? `<span class="chip decline">Decline · ${esc(row.competitors.map((x) => x.client).join(", "))}</span>`
        : `<span class="muted">No same-area decline</span>`;
      const paths = perClient.flatMap((client) => (client.paths || []).map((path) =>
        `<li><b>${esc(client.client)}</b> · ${esc(path.via)} <span class="mono">contribution ${n(path.conflict, 3)}</span></li>`));
      return `<tr>
        <th scope="row">${esc(row.name)}</th><td>${esc(row.category)}</td><td>${esc(row.neighborhood)}</td>${clientCells}
        <td>${chip(row.verdict)} <small class="mono">${esc(row.verdict)} · max ${n(row.max_conflict, 3)}</small></td><td>${sameArea}</td>
      </tr>
      <tr class="detail-row"><td colspan="${5 + signedClients.length}"><details><summary>Audience paths</summary>
        <ul class="paths">${paths.join("") || "<li class='muted'>No audience paths.</li>"}</ul></details></td></tr>`;
    }).join("") || `<tr><td colspan="${5 + signedClients.length}" class="muted">No leads to screen.</td></tr>`}</tbody>`;

  $("#cleared-checks").textContent = `${analysis.cleared_checks} Double Take checks cleared.`;
  $("#double-take-table").innerHTML = `<thead><tr><th scope="col">Client and draft</th><th scope="col">Resembles</th><th scope="col">Shared rare techniques</th><th scope="col">Similarity</th><th scope="col">Overlap</th><th scope="col">Risk</th><th scope="col">Threshold</th><th scope="col">Outcome</th></tr></thead>
    <tbody>${analysis.double_take.map((flag) => `<tr>
      <th scope="row">${esc(flag.client)}<span class="table-sub">${esc(flag.draft_hook || flag.draft)}</span></th>
      <td>${esc(flag.with_business)}</td><td>${(flag.shared || []).map(esc).join(", ") || "—"}</td>
      <td class="mono">${n(flag.similarity, 3)}</td><td class="mono">${n(flag.overlap, 3)}</td>
      <td class="mono">${n(flag.risk, 3)}</td><td class="mono">${n(flag.flag_risk, 3)}</td><td>${chip("flagged", "Blocked")}</td>
    </tr>`).join("") || `<tr><td colspan="8" class="muted">No blocked drafts.</td></tr>`}</tbody>`;

  $("#signatures-table").innerHTML = `<thead><tr><th scope="col">Client</th><th scope="col">Signature</th><th scope="col">Rarity</th><th scope="col">Share</th></tr></thead>
    <tbody>${analysis.signatures.map((signature) => `<tr>
      <th scope="row">${esc(signature.business)}</th><td>${esc(signature.technique)}</td>
      <td class="mono">${n(signature.rarity, 3)}</td><td class="mono">${n(signature.share * 100, 1)}%</td>
    </tr>`).join("") || `<tr><td colspan="4" class="muted">No signatures yet.</td></tr>`}</tbody>`;

  $("#queries").innerHTML = analysis.queries.map((query) => `<article class="query-card">
    <h3><span class="query-label">${esc(query.query)}</span> · ${esc(query.tool)}</h3>
    <p class="muted">Agents: ${query.agents.map(esc).join(", ") || "—"}</p>
    <p>${esc(query.description)}</p>
    ${query.cypher.map((cypher) => `<details><summary>${esc(cypher.constant)}</summary><pre>${esc(cypher.text)}</pre></details>`).join("")}
  </article>`).join("");

  $("#analysis-agents").innerHTML = Object.entries(analysis.agents).map(([agent, tools]) =>
    `<article class="agent-card"><h3>${esc(agent)}</h3><ul>${tools.map((tool) => `<li>${esc(tool)}</li>`).join("")}</ul></article>`).join("");

  $("#raw-decisions").innerHTML = `<thead><tr><th scope="col">Agent</th><th scope="col">Graph</th><th scope="col">Text</th><th scope="col">Rationale</th></tr></thead>
    <tbody>${decisions.map((decision) => `<tr><th scope="row">${esc(decision.by)}</th><td class="mono">${esc(decision.graph)}</td>
      <td>${esc(decision.text)}</td><td>${esc(decision.rationale)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">No decisions yet.</td></tr>`}</tbody>`;

  const log = overview?.log || [];
  renderLog(log);
  $("#run-log-note").hidden = log.length > 0 || !overview?.readonly;
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

  if (d.screening && d.screening.verdict) {
    const s = d.screening;
    h += `<h3>Scout's screening</h3><div class="thread"><div class="knot"><div class="who">${esc(s.by || "Scout")} ${chip(s.verdict)}</div><p>${esc(displayCopy(s.reason))}</p></div>
      ${(s.paths || []).map((c) => {
        const ps = [...(c.paths || [])].sort((a, z) => z.conflict - a.conflict);
        const pill = (p) => `<li>${esc(p.via)} <span class="metric">· ${n(p.conflict)}</span></li>`;
        return `<div class="knot minor"><div class="who">${esc(c.client)} <span class="metric">· conflict ${n(c.conflict)}</span>${c.same_category ? " · same category" : ""}</div>
          ${ps.length ? `<p class="muted">via ${ps.slice(0, 2).map((p) => esc(p.via)).join(", ")}</p><p class="muted mono metric">Path contributions: ${ps.slice(0, 2).map((p) => `${esc(p.via)} ${n(p.conflict, 3)}`).join(" · ")}</p>` : ""}
          ${ps.length > 2 ? `<details class="metric"><summary>All ${ps.length} audience paths</summary><ul class="paths">${ps.map(pill).join("")}</ul></details>` : ""}</div>`;
      }).join("")}</div>`;
  }

  if (d.has_graph && d.flags && d.flags.length) {
    const drafts = Object.fromEntries((d.drafts || []).map((x) => [x.id, x]));
    const byDraft = {};
    d.flags.forEach((f) => (byDraft[f.draft] ||= []).push(f));
    const ids = Object.keys(byDraft);
    h += `<h3>Double Take <span class="muted"><span class="metric">${ids.length} </span>${ids.length === 1 ? "draft" : "drafts"} blocked</span></h3><div class="thread">${ids.map((id) => {
      const dr = drafts[id];
      return `<div class="knot hit"><div class="who">Blocked ${dr ? `<span class="metric">v${esc(dr.version)} </span>draft` : "draft"}</div><div class="body">
        ${dr ? `<p><button type="button" class="row-btn" data-draft="${esc(id)}" data-slug="${esc(slug)}"><b>“${esc(dr.hook)}”</b></button></p>` : ""}
        ${byDraft[id].map((f) => `<p>Too close to <b>${esc(f.with_business)}</b>: shares ${(f.shared || []).map(esc).join(", ")}.</p>
        <p class="muted mono metric">similarity ${n(f.similarity)} × audience overlap ${n(f.overlap)} = risk ${n(f.risk)}</p>`).join("")}</div></div>`;
    }).join("")}</div>`;
  }

  if (d.has_graph && d.decisions && d.decisions.length) {
    h += `<h3>Latest decisions <span class="muted analysis-only">client:${esc(slug)}</span></h3><div class="thread">${d.decisions.slice(0, 4).map((x) =>
      `<div class="knot minor"><div class="who">${esc(x.by)}</div><p><b>${esc(displayCopy(x.text))}</b></p>${x.rationale ? `<p class="muted">${esc(displayCopy(x.rationale))}</p>` : ""}</div>`).join("")}</div>`;
  }

  h += `<h3>Who it targets</h3><ul class="targets">${d.audiences.map((a) =>
    `<li><span>${esc(a.audience)}</span><span class="bar" aria-hidden="true"><span style="width:${Math.round(Math.min(1, a.weight || 0) * 100)}%"></span></span><span class="num metric">${n(a.weight, 1)}</span></li>`).join("") || "<li class='muted'>No audiences.</li>"}</ul>`;
  h += `<h3>Signatures <span class="muted">rare moves it owns</span></h3><p>${d.signatures.map((s) => `${esc(s.technique)} <span class="muted metric">${Math.round(s.share * 100)}%</span>`).join(", ") || "<span class='muted'>None yet.</span>"}</p>`;

  if (d.has_graph) {
    if (d.stale.length) h += `<div class="warnbox"><b><span class="metric">${d.stale.length} </span>stale drafts</b> serve a retired goal: ${d.stale.map((s) => esc(s.hook)).join("; ")}</div>`;
    h += `<h3>Goals</h3><ul class="list">${d.goals.map((g) => `<li><div class="goal-line">${chip(g.status)} <b>${esc(g.text)}</b></div>
      <div class="goal-meta metric">${esc(g.metric)} → ${esc(g.target)} by ${esc(g.due)}</div>
      ${g.status === "active" && !ro ? `<div class="btn-row"><button type="button" class="btn small" data-retire="${esc(g.id)}" data-slug="${esc(slug)}">Retire goal</button></div>` : ""}</li>`).join("") || "<li class='muted'>None yet.</li>"}</ul>`;
    if (d.pitches.length) h += `<h3>Pitches</h3><ul class="list">${d.pitches.map((p) =>
      `<li><button type="button" class="row-btn" data-pitch="${esc(p.id)}" data-slug="${esc(slug)}">${chip(p.status)} <b>${esc(p.angle)}</b></button></li>`).join("")}</ul>`;
    h += `<h3>Drafts</h3><ul class="list">${d.drafts.map((x) =>
      `<li><button type="button" class="row-btn" data-draft="${esc(x.id)}" data-slug="${esc(slug)}">${chip(x.status)}${chip("plain", x.kind)} <b><span class="metric">v${esc(x.version)} · </span>${esc(x.hook)}</b></button></li>`).join("") || "<li class='muted'>None yet.</li>"}</ul>`;
    if (d.taste_profile && d.taste_profile.id) h += `<h3>Taste profile <span class="muted metric">v${esc(d.taste_profile.version)}</span></h3><p>${esc(d.taste_profile.summary)}</p>
      <p class="muted" style="margin-top:6px">Prefers: ${d.taste_profile.prefers.map((p) => esc(p.name)).join(", ")}${d.taste_profile.avoids.length ? `<br>Avoids: ${d.taste_profile.avoids.map((p) => esc(p.name)).join(", ")}` : ""}</p>`;
    h += `<h3>Findings <span class="muted">each with its source</span></h3><ul class="list">${d.findings.map((f) => `<li>${chip("plain", f.kind)} ${esc(f.text)}<br>${f.kind === "audit" ? "<span class='muted'>From the audit of past posts.</span>" : link(f.source_url)}</li>`).join("") || "<li class='muted'>None yet.</li>"}</ul>`;
    h += `<h3>Past posts</h3><ul class="list">${d.posts.map((p) => `<li>${esc(p.hook)} <span class="muted metric">${(p.views ?? 0).toLocaleString()} views · ${(p.saves ?? 0).toLocaleString()} saves</span></li>`).join("") || "<li class='muted'>Not loaded.</li>"}</ul>`;
  } else {
    h += `<div class="warnbox"><b>No private graph yet.</b> Scout creates one when it pursues this lead.</div>`;
  }

  // The first thread in the dossier is where the string from the board ties in.
  h = h.replace('class="thread"', 'class="thread lead"');

  const panel = $("#drawer");
  const keepScroll = !animate && panel.dataset.slug === slug ? panel.scrollTop : 0;
  $("#drawer-body").innerHTML = h;
  panel.dataset.slug = slug;
  panel.scrollTop = keepScroll;
  if (!quiet) $("#sr-status").textContent = `Showing ${b.name}`;
  if (!isSplit() && !quiet) openOverlay();
  drawString(animate);
}

function emptyDossier() {
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
  const p = panel.getBoundingClientRect();
  const lead = panel.querySelector(".thread.lead");
  const head = panel.querySelector("#dossier-h");
  let ty = lead ? lead.getBoundingClientRect().top + 12.5 : head ? head.getBoundingClientRect().top + head.offsetHeight / 2 : p.top + 40;
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
  const dr = e.target.closest("[data-draft]");
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
    const note = prompt(`Board note (${bd.dataset.board}):`, bd.dataset.board === "approve" ? "Approved. Nothing is sent from this workspace." : "Veto: ") ?? null;
    if (note === null) return;
    await api(`/api/board/${bd.dataset.slug}/${bd.dataset.label}/${bd.dataset.id}`, { method: "POST", body: JSON.stringify({ verdict: bd.dataset.board, note }) });
    bd.dataset.label === "Pitch" ? openPitch(bd.dataset.slug, bd.dataset.id) : openRoute(bd.dataset.slug, bd.dataset.id);
    refresh();
  }
});

// ---------------------------------------------------------------- route cards (threads) and pitch cards

function knots(decisions) {
  return decisions.map((x) => `<div class="knot"><div class="who">${esc(x.by)}</div><p><b>${esc(x.decision)}</b></p>${x.rationale ? `<p class="muted">${esc(x.rationale)}</p>` : ""}</div>`).join("");
}

function sheetTop(kicker) {
  return `<div class="sheet-top"><p class="sheet-kicker">${kicker}</p><button type="button" class="btn small" data-close>Close</button></div>`;
}

function boardButtons(label, id, slug, primary) {
  if (state.overview?.readonly) return "";
  return `<div class="btn-row"><button type="button" class="btn${primary ? " primary" : ""}" data-board="approve" data-label="${label}" data-id="${esc(id)}" data-slug="${esc(slug)}">Board: approve</button>
    <button type="button" class="btn" data-board="veto" data-label="${label}" data-id="${esc(id)}" data-slug="${esc(slug)}">Board: veto</button>
    ${label === "Pitch" ? `<span class="muted">Approval never sends anything in this build.</span>` : ""}</div>`;
}

function showSheet(h, title) {
  $("#card-body").innerHTML = `<div class="sheet">${h}</div>`;
  $("#card").setAttribute("aria-label", title);
  if (!$("#card").open) $("#card").showModal();
}

async function openRoute(slug, id) {
  const c = await api(`/api/route/${slug}/${id}`);
  let h = sheetTop(`<span class="studio-only">Thread</span><span class="analysis-only">Thread · client:${esc(slug)} · ${esc(id)}</span>`) +
    `<h2>${esc(c.draft)}</h2><p class="serves">${chip(c.status)} ${c.goal ? `serves ${chip(c.goal_status)} <b>${esc(c.goal)}</b>` : ""}</p>`;
  if (c.flags.length) h += c.flags.map((f) => `<div class="flagbox"><b>Double Take blocked this draft.</b> It resembles ${esc(f.with_business)}: shares ${f.shared.map(esc).join(", ")}.
    <div class="mono metric" style="margin-top:4px;font-size:.8125rem">similarity ${n(f.similarity)} × audience overlap ${n(f.overlap)} = risk ${n(f.risk)}</div>
    <div class="muted metric" style="margin-top:4px;font-size:.8125rem">Evidence: ${f.evidence.map((e) => `${esc(e.fingerprint)} (${esc(e.kind)}, ${esc(e.hits)} shared)`).join(", ")}</div></div>`).join("");
  else if (c.status !== "flagged") h += `<div class="okbox"><b>Cleared Double Take.</b></div>`;
  if (c.previous.length) h += `<div class="warnbox"><b>Revision</b> of ${c.previous.map((p) => `<span class="metric">v${esc(p.version)} </span>“${esc(p.hook)}”`).join(", ")}${c.flags_on_previous.length ? `, which was blocked for resembling ${c.flags_on_previous.map((f) => esc(f.with)).join(", ")} (${c.flags_on_previous.map((f) => f.shared.map(esc).join(", ")).join("; ")})` : ""}.</div>`;
  h += `<h3>Decisions</h3><div class="thread">${knots(c.decisions)}</div>`;
  h += `<h3>Sources</h3><ul class="list">${c.sources.map((s) => `<li>${chip("plain", s.kind)} ${esc(s.text)} ${s.source_url ? "<br>" + link(s.source_url) : ""}</li>`).join("") || "<li class='muted'>None.</li>"}</ul>`;
  h += `<h3>Techniques</h3><ul class="tech-list">${c.techniques.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>`;
  h += `<h3>References</h3><ul class="list">${c.references.map((r) => `<li>${link(r)}</li>`).join("") || "<li class='muted'>None.</li>"}</ul>`;
  h += boardButtons("Draft", id, slug, false);
  showSheet(h, `Thread for ${c.draft}`);
}

async function openPitch(slug, id) {
  const c = await api(`/api/pitch/${slug}/${id}`);
  const h = sheetTop(`<span class="studio-only">Pitch</span><span class="analysis-only">Pitch · client:${esc(slug)} · ${esc(id)}</span>`) +
    `<h2>${esc(c.angle)}</h2><p class="serves">${chip(c.status)} argues for ${chip(c.goal_status)} <b>${esc(c.goal)}</b></p>
    ${c.goal_status === "hypothesized" ? `<div class="warnbox"><b>The goal is a hypothesis.</b> It is the Researcher's inference, shown to the prospect as one.</div>` : ""}
    <h3>Every claim, with its source</h3><ul class="list">${c.claims.map((f) => `<li>${chip("plain", f.kind)} ${esc(f.text)}<br>${f.kind === "audit" ? "<span class='muted'>From our audit of their posts.</span>" : link(f.source_url)}</li>`).join("")}</ul>
    <h3>Spec posts</h3><ul class="list">${c.spec_posts.map((d) => `<li><button type="button" class="row-btn" data-draft="${esc(d.id)}" data-slug="${esc(slug)}">${chip(d.status)} <b>${esc(d.hook)}</b></button></li>`).join("")}</ul>
    <h3>Decisions</h3><div class="thread">${knots(c.decisions)}</div>` + boardButtons("Pitch", id, slug, true);
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
    const savedNote = r.saved === false ? `<p class="muted">Not saved: the public demo screens leads without adding them to the graph.</p>` : "";
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
  if (isAnalysisView()) await loadAnalysis();
});
