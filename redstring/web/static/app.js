const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const chip = (v, label) => (v || label) ? `<span class="chip ${esc(v || "plain")}">${esc(label || String(v).replace(/_/g, " "))}</span>` : "";
const n = (x, d = 2) => (typeof x === "number" ? x.toFixed(d) : "");
const link = (u) => u ? `<a class="src" href="${esc(u)}" target="_blank" rel="noopener">${esc(u)}</a>` : `<span class="muted">no source URL</span>`;
const hoodOf = (b) => b.neighborhood_name || b.neighborhood || "";
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const splitQuery = window.matchMedia("(min-width: 1100px)");
const isSplit = () => splitQuery.matches;

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "content-type": "application/json" }, ...opts });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

// selected: the business in the dossier. pinned: the viewer picked it (otherwise the dossier follows the action).
let state = { overview: null, techniques: [], selected: null, pinned: false, animating: false };

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
  $("#mode").textContent = `agents: ${o.mode}${o.readonly ? " · read-only link" : ""}`;
  $("#meta").textContent = o.graphs.join(" · ");
  $("#biz-count").textContent = `${o.businesses.length} businesses · all synthetic`;
  // The dossier follows the run (the business in the latest log line) until the viewer picks a card.
  let moved = false;
  if (!state.pinned && isSplit()) {
    const next = followTarget(o) || state.selected || pickDefault(o.businesses);
    moved = next !== state.selected;
    state.selected = next;
  }
  renderSteps(o);
  renderLog(o.log);
  renderBoard(o);

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
      `<div class="slider"><label for="aud-${esc(a.id)}">${esc(a.name)}</label><input type="range" min="0" max="1" step="0.1" value="0" id="aud-${esc(a.id)}" name="aud-${esc(a.id)}"><output for="aud-${esc(a.id)}">0</output></div>`).join(""));
    $("#aud-sliders").addEventListener("input", (e) => { if (e.target.type === "range") e.target.nextElementSibling.textContent = e.target.value; });
  }
  feed();

  $("#follow").hidden = !state.pinned;
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
    : `<b>All ${o.steps.length} steps ran.</b> Step 0 resets the demo.`;
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
    `<li><div><div class="who">${esc(d.by)}</div><div class="g">${esc(d.graph)}</div></div><div><b>${esc(d.text)}</b><div class="muted">${esc(d.rationale)}</div></div></li>`).join("")
    || `<li class="empty">No decisions yet. Run the demo steps above.</li>`;
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
  openBusiness(slug, { animate: changed || !isSplit() });
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
  let h = `<div class="dossier-meta"><span>${esc(b.category)}${hood ? ` · ${esc(hood)}` : ""}</span>${b.synthetic === false ? "" : `<span class="synthetic">synthetic</span>`}
      <button type="button" class="btn small dossier-close" data-dossier-close>Close</button></div>
    <h2 class="name" id="dossier-h" tabindex="-1">${esc(b.name)}</h2>
    <div class="status-row">${chip(b.status)}${b.voice ? `<span class="muted">Voice: ${esc(b.voice)}</span>` : ""}</div>`;

  if (d.screening && d.screening.verdict) {
    const s = d.screening;
    h += `<h3>Scout's screening</h3><div class="thread"><div class="knot"><div class="who">${esc(s.by || "Scout")} ${chip(s.verdict)}</div><p>${esc(s.reason)}</p></div>
      ${(s.paths || []).map((c) => {
        const ps = [...(c.paths || [])].sort((a, z) => z.conflict - a.conflict);
        const pill = (p) => `<li>${esc(p.via)} · ${n(p.conflict)}</li>`;
        return `<div class="knot minor"><div class="who">${esc(c.client)} · conflict ${n(c.conflict)}${c.same_category ? " · same category" : ""}</div>
          ${ps.length ? `<p class="muted">via ${ps.slice(0, 2).map((p) => `${esc(p.via)} (${n(p.conflict)})`).join(", ")}</p>` : ""}
          ${ps.length > 2 ? `<details><summary>All ${ps.length} audience paths</summary><ul class="paths">${ps.map(pill).join("")}</ul></details>` : ""}</div>`;
      }).join("")}</div>`;
  }

  if (d.has_graph && d.flags && d.flags.length) {
    const drafts = Object.fromEntries((d.drafts || []).map((x) => [x.id, x]));
    const byDraft = {};
    d.flags.forEach((f) => (byDraft[f.draft] ||= []).push(f));
    const ids = Object.keys(byDraft);
    h += `<h3>Double Take <span class="muted">${ids.length} ${ids.length === 1 ? "draft" : "drafts"} blocked</span></h3><div class="thread">${ids.map((id) => {
      const dr = drafts[id];
      return `<div class="knot hit"><div class="who">Blocked ${dr ? `v${esc(dr.version)} draft` : "draft"}</div><div class="body">
        ${dr ? `<p><button type="button" class="row-btn" data-draft="${esc(id)}" data-slug="${esc(slug)}"><b>“${esc(dr.hook)}”</b></button></p>` : ""}
        ${byDraft[id].map((f) => `<p>Too close to <b>${esc(f.with_business)}</b>: shares ${(f.shared || []).map(esc).join(", ")}.</p>
        <p class="muted mono">similarity ${n(f.similarity)} × audience overlap ${n(f.overlap)} = risk ${n(f.risk)}</p>`).join("")}</div></div>`;
    }).join("")}</div>`;
  }

  if (d.has_graph && d.decisions && d.decisions.length) {
    h += `<h3>Latest decisions <span class="muted">client:${esc(slug)}</span></h3><div class="thread">${d.decisions.slice(0, 4).map((x) =>
      `<div class="knot minor"><div class="who">${esc(x.by)}</div><p><b>${esc(x.text)}</b></p>${x.rationale ? `<p class="muted">${esc(x.rationale)}</p>` : ""}</div>`).join("")}</div>`;
  }

  h += `<h3>Who it targets</h3><ul class="targets">${d.audiences.map((a) =>
    `<li><span>${esc(a.audience)}</span><span class="bar" aria-hidden="true"><span style="width:${Math.round(Math.min(1, a.weight || 0) * 100)}%"></span></span><span class="num">${n(a.weight, 1)}</span></li>`).join("") || "<li class='muted'>No audiences.</li>"}</ul>`;
  h += `<h3>Signatures <span class="muted">rare moves it owns</span></h3><p>${d.signatures.map((s) => `${esc(s.technique)} <span class="muted">${Math.round(s.share * 100)}%</span>`).join(", ") || "<span class='muted'>None yet.</span>"}</p>`;

  if (d.has_graph) {
    if (d.stale.length) h += `<div class="warnbox"><b>${d.stale.length} stale drafts</b> serve a retired goal: ${d.stale.map((s) => esc(s.hook)).join("; ")}</div>`;
    h += `<h3>Goals</h3><ul class="list">${d.goals.map((g) => `<li><div class="goal-line">${chip(g.status)} <b>${esc(g.text)}</b></div>
      <div class="goal-meta">${esc(g.metric)} → ${esc(g.target)} by ${esc(g.due)}</div>
      ${g.status === "active" && !ro ? `<div class="btn-row"><button type="button" class="btn small" data-retire="${esc(g.id)}" data-slug="${esc(slug)}">Retire goal</button></div>` : ""}</li>`).join("") || "<li class='muted'>None yet.</li>"}</ul>`;
    if (d.pitches.length) h += `<h3>Pitches</h3><ul class="list">${d.pitches.map((p) =>
      `<li><button type="button" class="row-btn" data-pitch="${esc(p.id)}" data-slug="${esc(slug)}">${chip(p.status)} <b>${esc(p.angle)}</b></button></li>`).join("")}</ul>`;
    h += `<h3>Drafts</h3><ul class="list">${d.drafts.map((x) =>
      `<li><button type="button" class="row-btn" data-draft="${esc(x.id)}" data-slug="${esc(slug)}">${chip(x.status)}${chip("plain", x.kind)} <b>v${esc(x.version)} · ${esc(x.hook)}</b></button></li>`).join("") || "<li class='muted'>None yet.</li>"}</ul>`;
    if (d.taste_profile && d.taste_profile.id) h += `<h3>Taste profile <span class="muted">v${esc(d.taste_profile.version)}</span></h3><p>${esc(d.taste_profile.summary)}</p>
      <p class="muted" style="margin-top:6px">Prefers: ${d.taste_profile.prefers.map((p) => esc(p.name)).join(", ")}${d.taste_profile.avoids.length ? `<br>Avoids: ${d.taste_profile.avoids.map((p) => esc(p.name)).join(", ")}` : ""}</p>`;
    h += `<h3>Findings <span class="muted">each with its source</span></h3><ul class="list">${d.findings.map((f) => `<li>${chip("plain", f.kind)} ${esc(f.text)}<br>${f.kind === "audit" ? "<span class='muted'>From the audit of past posts.</span>" : link(f.source_url)}</li>`).join("") || "<li class='muted'>None yet.</li>"}</ul>`;
    h += `<h3>Past posts</h3><ul class="list">${d.posts.map((p) => `<li>${esc(p.hook)} <span class="muted">${(p.views ?? 0).toLocaleString()} views · ${(p.saves ?? 0).toLocaleString()} saves</span></li>`).join("") || "<li class='muted'>Not loaded.</li>"}</ul>`;
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
    const note = prompt(`Board note (${bd.dataset.board}):`, bd.dataset.board === "approve" ? "Approved. Nothing is sent in the hackathon build." : "Veto: ") ?? null;
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
  let h = sheetTop(`Thread · client:${esc(slug)} · ${esc(id)}`) +
    `<h2>${esc(c.draft)}</h2><p class="serves">${chip(c.status)} ${c.goal ? `serves ${chip(c.goal_status)} <b>${esc(c.goal)}</b>` : ""}</p>`;
  if (c.flags.length) h += c.flags.map((f) => `<div class="flagbox"><b>Double Take blocked this draft.</b> It resembles ${esc(f.with_business)}: shares ${f.shared.map(esc).join(", ")}.
    <div class="mono" style="margin-top:4px;font-size:.8125rem">similarity ${n(f.similarity)} × audience overlap ${n(f.overlap)} = risk ${n(f.risk)}</div>
    <div class="muted" style="margin-top:4px;font-size:.8125rem">Evidence: ${f.evidence.map((e) => `${esc(e.fingerprint)} (${esc(e.kind)}, ${esc(e.hits)} shared)`).join(", ")}</div></div>`).join("");
  else if (c.status !== "flagged") h += `<div class="okbox"><b>Cleared Double Take.</b></div>`;
  if (c.previous.length) h += `<div class="warnbox"><b>Revision</b> of ${c.previous.map((p) => `v${esc(p.version)} “${esc(p.hook)}”`).join(", ")}${c.flags_on_previous.length ? `, which was blocked for resembling ${c.flags_on_previous.map((f) => esc(f.with)).join(", ")} (${c.flags_on_previous.map((f) => f.shared.map(esc).join(", ")).join("; ")})` : ""}.</div>`;
  h += `<h3>Decisions</h3><div class="thread">${knots(c.decisions)}</div>`;
  h += `<h3>Sources</h3><ul class="list">${c.sources.map((s) => `<li>${chip("plain", s.kind)} ${esc(s.text)} ${s.source_url ? "<br>" + link(s.source_url) : ""}</li>`).join("") || "<li class='muted'>None.</li>"}</ul>`;
  h += `<h3>Techniques</h3><ul class="tech-list">${c.techniques.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>`;
  h += `<h3>References</h3><ul class="list">${c.references.map((r) => `<li>${link(r)}</li>`).join("") || "<li class='muted'>None.</li>"}</ul>`;
  h += boardButtons("Draft", id, slug, false);
  showSheet(h, `Thread for ${c.draft}`);
}

async function openPitch(slug, id) {
  const c = await api(`/api/pitch/${slug}/${id}`);
  const h = sheetTop(`Pitch · client:${esc(slug)} · ${esc(id)}`) +
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
    $("#lead-result").innerHTML = `<div class="${box}">${chip(r.verdict)} ${esc(r.reason)}</div>${savedNote}
      ${r.clients.length ? `<div class="thread">${r.clients.map((c) => {
        const ps = [...c.paths].sort((a, z) => z.conflict - a.conflict);
        return `<div class="knot minor"><div class="who">${esc(c.client)} · conflict ${n(c.conflict)}</div>
          ${ps.length ? `<p class="muted">via ${ps.slice(0, 2).map((p) => `${esc(p.via)} (${n(p.conflict, 3)})`).join(", ")}</p>` : ""}
          ${ps.length > 2 ? `<details><summary>All ${ps.length} audience paths</summary><ul class="paths">${ps.map((p) => `<li>${esc(p.via)} · ${n(p.conflict, 3)}</li>`).join("")}</ul></details>` : ""}</div>`;
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
    $("#draft-result").innerHTML = (r.flagged ? `<div class="flagbox"><b>Would be blocked.</b> Risk at or above ${n(r.threshold)} with someone on the same audience.</div>` : `<div class="okbox"><b>Would clear.</b> Threshold ${n(r.threshold)}.</div>`)
      + `<ul class="list">${r.results.map((x) => `<li>${chip(x.flag ? "flagged" : "cleared", x.flag ? "flag" : "ok")} <b>${esc(x.business)}</b> <span class="muted">(${esc(x.status)})</span>: shares ${x.shared_rare.map(esc).join(", ")}<br><span class="mono" style="font-size:.8125rem">similarity ${n(x.similarity)} × overlap ${n(x.overlap)} = <b>${n(x.risk)}</b></span></li>`).join("") || "<li class='muted'>Shares no rare technique with anyone on the same audience.</li>"}</ul>`;
  } catch (err) { $("#draft-result").innerHTML = `<div class="flagbox">${esc(err.message)}</div>`; }
  finally { btn.disabled = false; }
});

async function loadTechniques() {
  const ts = await api("/api/techniques");
  const rare = state.overview?.thresholds.rare ?? 0.6;
  const by = {};
  ts.forEach((t) => (by[t.style] ||= []).push(t));
  $("#tech-pick").innerHTML = Object.entries(by).map(([s, list]) => `<h3>${esc(s)}</h3>${list.map((t) =>
    `<label title="rarity ${n(t.rarity)} · ${t.ref_count} refs"><input type="checkbox" value="${esc(t.id)}"><span class="${t.rarity >= rare ? "rare" : ""}">${esc(t.name)}</span></label>`).join("")}`).join("");
  $("#tech-pick").insertAdjacentHTML("afterend", `<p class="legend-note">Rare means rarity ${rare} or higher. Only rare techniques count toward similarity.</p>`);
}

refresh().then(loadTechniques);
