const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const chip = (v, label) => (v || label) ? `<span class="chip ${esc(v)}">${esc(label || String(v).replace(/_/g, " "))}</span>` : "";
const n = (x, d = 2) => (typeof x === "number" ? x.toFixed(d) : "");
const link = (u) => u ? `<a class="src" href="${esc(u)}" target="_blank" rel="noopener">${esc(u)}</a>` : `<span class="muted">no source URL</span>`;

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "content-type": "application/json" }, ...opts });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

let state = { overview: null, techniques: [] };

const COLUMNS = [
  ["Lead", (b) => b.status === "lead" && !b.verdict],
  ["Screened", (b) => b.status === "lead" && b.verdict],
  ["Pursued", (b) => b.status === "pursued"],
  ["Pitched", (b) => b.status === "pitched"],
  ["Signed", (b) => b.status === "signed"],
];

async function refresh() {
  const o = await api("/api/overview");
  state.overview = o;
  $("#agency").textContent = o.agency;
  $("#mode").textContent = `agents: ${o.mode}${o.readonly ? " · read-only link" : ""}`;
  if (o.readonly) $("#steps").hidden = true;
  $("#meta").innerHTML = o.graphs.map((g) => `<span class="pill">${esc(g)}</span>`).join("");
  $("#steps").innerHTML = o.steps.map((s, i) =>
    `<li class="${s.done ? "done" : ""}"><button data-step="${esc(s.id)}" title="${esc(s.label)}">${i}. ${esc(s.label)}</button></li>`).join("");
  $("#log").textContent = o.log.join("\n");
  $("#log").scrollTop = 1e6;
  $("#board").innerHTML = COLUMNS.map(([title, test]) => {
    const items = o.businesses.filter(test);
    return `<div class="col"><h4>${title} · ${items.length}</h4>${items.map((b) =>
      `<button class="biz" data-biz="${esc(b.id)}"><b>${esc(b.name)}</b><small>${esc(b.category)}</small><br>${chip(b.verdict)}${b.owner ? chip("", "owner: " + b.owner) : ""}</button>`).join("")}</div>`;
  }).join("");
  const sel = $("#draft-client");
  const keep = sel.value;
  sel.innerHTML = o.businesses.filter((b) => ["signed", "pursued", "pitched"].includes(b.status))
    .map((b) => `<option value="${esc(b.id)}">${esc(b.name)}</option>`).join("");
  if (keep) sel.value = keep;
  if (!$("#aud-sliders .slider")) {
    $("#aud-sliders").insertAdjacentHTML("beforeend", o.audiences.map((a) =>
      `<div class="slider"><span>${esc(a.name)}</span><input type="range" min="0" max="1" step="0.1" value="0" name="aud-${esc(a.id)}" aria-label="${esc(a.name)}"><output>0</output></div>`).join(""));
    $("#aud-sliders").addEventListener("input", (e) => { if (e.target.type === "range") e.target.nextElementSibling.textContent = e.target.value; });
  }
  feed();
}

async function feed() {
  const ds = await api("/api/decisions");
  $("#feed").innerHTML = ds.map((d) =>
    `<li><div><div class="who">${esc(d.by)}</div><div class="g">${esc(d.graph)}</div></div><div><b>${esc(d.text)}</b><div class="muted">${esc(d.rationale)}</div></div></li>`).join("")
    || `<li class="muted">No decisions yet. Run the demo steps above.</li>`;
}

$("#steps").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-step]");
  if (!b) return;
  document.querySelectorAll("#steps button").forEach((x) => (x.disabled = true));
  $("#log").textContent += `\n> ${b.dataset.step}…`;
  try { await api(`/api/step/${b.dataset.step}`, { method: "POST" }); }
  catch (err) { alert(err.message); }
  await refresh();
});

// ---------------------------------------------------------------- business drawer

$("#board").addEventListener("click", (e) => {
  const b = e.target.closest("[data-biz]");
  if (b) openBusiness(b.dataset.biz);
});

async function openBusiness(slug) {
  const d = await api(`/api/business/${slug}`);
  const b = d.business;
  let h = `<button class="close" data-close>Close</button><h2>${esc(b.name)}</h2>
    <p class="muted">${esc(b.category)} · ${esc(b.voice || "")} · synthetic</p>
    <dl class="kv"><dt>Status</dt><dd>${chip(b.status)}</dd>
    <dt>Targets</dt><dd>${d.audiences.map((a) => `${esc(a.audience)} <span class="muted">${n(a.weight, 1)}</span>`).join("<br>")}</dd>
    <dt>Signatures</dt><dd>${d.signatures.map((s) => `${esc(s.technique)} <span class="muted">${Math.round(s.share * 100)}%</span>`).join(", ") || "<span class='muted'>none</span>"}</dd></dl>`;
  if (d.screening && d.screening.verdict) {
    const s = d.screening;
    h += `<h3>Scout's thread</h3><div class="thread"><div class="knot"><div class="who">${esc(s.by)} · ${chip(s.verdict)}</div><p>${esc(s.reason)}</p></div>
      ${s.paths.map((c) => `<div class="knot"><div class="who">${esc(c.client)} · conflict ${n(c.conflict)}${c.same_category ? " · same category" : ""}</div>
        <p class="muted">${c.paths.map((p) => `${esc(p.via)} (${n(p.conflict, 3)})`).join(" · ")}</p></div>`).join("")}</div>`;
  }
  if (d.has_graph) {
    if (d.stale.length) h += `<div class="warnbox"><b>${d.stale.length} stale drafts</b> serve a retired goal: ${d.stale.map((s) => esc(s.hook)).join("; ")}</div>`;
    h += `<h3>Goals</h3><ul class="list">${d.goals.map((g) => `<li>${chip(g.status)} ${esc(g.text)} <span class="muted">${esc(g.metric)} → ${esc(g.target)} by ${esc(g.due)}</span>
      ${g.status === "active" ? `<button data-retire="${esc(g.id)}" data-slug="${esc(slug)}">Retire goal</button>` : ""}</li>`).join("") || "<li class='muted'>none yet</li>"}</ul>`;
    if (d.pitches.length) h += `<h3>Pitches</h3><ul class="list">${d.pitches.map((p) =>
      `<li><button class="row-btn" data-pitch="${esc(p.id)}" data-slug="${esc(slug)}">${chip(p.status)} <b>${esc(p.angle)}</b></button></li>`).join("")}</ul>`;
    h += `<h3>Drafts</h3><ul class="list">${d.drafts.map((x) =>
      `<li><button class="row-btn" data-draft="${esc(x.id)}" data-slug="${esc(slug)}">${chip(x.status)}${chip("", x.kind)} <b>v${esc(x.version)} · ${esc(x.hook)}</b></button></li>`).join("") || "<li class='muted'>none yet</li>"}</ul>`;
    if (d.taste_profile && d.taste_profile.id) h += `<h3>Taste profile v${esc(d.taste_profile.version)}</h3><p>${esc(d.taste_profile.summary)}</p>
      <p class="muted">Prefers: ${d.taste_profile.prefers.map((p) => esc(p.name)).join(", ")}${d.taste_profile.avoids.length ? `<br>Avoids: ${d.taste_profile.avoids.map((p) => esc(p.name)).join(", ")}` : ""}</p>`;
    h += `<h3>Findings</h3><ul class="list">${d.findings.map((f) => `<li>${chip("", f.kind)} ${esc(f.text)}<br>${f.kind === "audit" ? "<span class='muted'>from the audit of past posts</span>" : link(f.source_url)}</li>`).join("") || "<li class='muted'>none yet</li>"}</ul>`;
    h += `<h3>Past posts</h3><ul class="list">${d.posts.map((p) => `<li>${esc(p.hook)} <span class="muted">${p.views.toLocaleString()} views · ${p.saves.toLocaleString()} saves</span></li>`).join("") || "<li class='muted'>not loaded</li>"}</ul>`;
  } else {
    h += `<p class="muted">No private graph yet. It is created when Scout pursues this lead.</p>`;
  }
  $("#drawer-body").innerHTML = h;
  if (!$("#drawer").open) $("#drawer").showModal();
}

document.addEventListener("click", async (e) => {
  if (e.target.matches("[data-close]")) e.target.closest("dialog").close();
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

// ---------------------------------------------------------------- route cards

function knots(decisions) {
  return decisions.map((x) => `<div class="knot"><div class="who">${esc(x.by)}</div><p><b>${esc(x.decision)}</b></p>${x.rationale ? `<p class="muted">${esc(x.rationale)}</p>` : ""}</div>`).join("");
}

async function openRoute(slug, id) {
  const c = await api(`/api/route/${slug}/${id}`);
  let h = `<button class="close" data-close>Close</button><p class="muted">Thread · client:${esc(slug)} · ${esc(id)}</p>
    <h2>${esc(c.draft)}</h2><p>${chip(c.status)} ${c.goal ? `serves ${chip(c.goal_status)} <b>${esc(c.goal)}</b>` : ""}</p>`;
  if (c.flags.length) h += c.flags.map((f) => `<div class="flagbox"><b>Double Take blocked this draft:</b> resembles ${esc(f.with_business)}.
    Shares ${f.shared.map(esc).join(", ")}. Similarity ${n(f.similarity)} × audience overlap ${n(f.overlap)} = risk ${n(f.risk)}.
    <div class="muted">Evidence: ${f.evidence.map((e) => `${esc(e.fingerprint)} (${esc(e.kind)}, ${esc(e.hits)} shared)`).join(", ")}</div></div>`).join("");
  else if (c.status !== "flagged") h += `<div class="okbox">Cleared Double Take.</div>`;
  if (c.previous.length) h += `<div class="warnbox">Revision of ${c.previous.map((p) => `v${esc(p.version)} “${esc(p.hook)}”`).join(", ")}${c.flags_on_previous.length ? `, which was blocked for resembling ${c.flags_on_previous.map((f) => esc(f.with)).join(", ")} (${c.flags_on_previous.map((f) => f.shared.map(esc).join(", ")).join("; ")})` : ""}.</div>`;
  h += `<h3>Decisions</h3><div class="thread">${knots(c.decisions)}</div>`;
  h += `<h3>Sources</h3><ul class="list">${c.sources.map((s) => `<li>${chip("", s.kind)} ${esc(s.text)} ${s.source_url ? "<br>" + link(s.source_url) : ""}</li>`).join("") || "<li class='muted'>none</li>"}</ul>`;
  h += `<h3>Techniques</h3><p>${c.techniques.map(esc).join(", ")}</p>`;
  h += `<h3>References</h3><ul class="list">${c.references.map((r) => `<li>${link(r)}</li>`).join("") || "<li class='muted'>none</li>"}</ul>`;
  h += `<p><button data-board="approve" data-label="Draft" data-id="${esc(id)}" data-slug="${esc(slug)}">Board: approve</button>
        <button data-board="veto" data-label="Draft" data-id="${esc(id)}" data-slug="${esc(slug)}">Board: veto</button></p>`;
  $("#card-body").innerHTML = h;
  if (!$("#card").open) $("#card").showModal();
}

async function openPitch(slug, id) {
  const c = await api(`/api/pitch/${slug}/${id}`);
  let h = `<button class="close" data-close>Close</button><p class="muted">Pitch · client:${esc(slug)} · ${esc(id)}</p>
    <h2>${esc(c.angle)}</h2><p>${chip(c.status)} argues for ${chip(c.goal_status)} <b>${esc(c.goal)}</b></p>
    ${c.goal_status === "hypothesized" ? `<div class="warnbox">The goal is the Researcher's inference, shown to the prospect as such.</div>` : ""}
    <h3>Every claim, with its source</h3><ul class="list">${c.claims.map((f) => `<li>${chip("", f.kind)} ${esc(f.text)}<br>${f.kind === "audit" ? "<span class='muted'>from our audit of their posts</span>" : link(f.source_url)}</li>`).join("")}</ul>
    <h3>Spec posts</h3><ul class="list">${c.spec_posts.map((d) => `<li><button class="row-btn" data-draft="${esc(d.id)}" data-slug="${esc(slug)}">${chip(d.status)} <b>${esc(d.hook)}</b></button></li>`).join("")}</ul>
    <h3>Decisions</h3><div class="thread">${knots(c.decisions)}</div>
    <p><button class="primary" data-board="approve" data-label="Pitch" data-id="${esc(id)}" data-slug="${esc(slug)}">Board: approve</button>
       <button data-board="veto" data-label="Pitch" data-id="${esc(id)}" data-slug="${esc(slug)}">Board: veto</button>
       <span class="muted">Approval never sends anything in this build.</span></p>`;
  $("#card-body").innerHTML = h;
  if (!$("#card").open) $("#card").showModal();
}

// ---------------------------------------------------------------- try it

$("#lead-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const targets = {};
  for (const [k, v] of f.entries()) if (k.startsWith("aud-") && +v > 0) targets[k.slice(4)] = +v;
  try {
    const r = await api("/api/try/lead", { method: "POST", body: JSON.stringify({ name: f.get("name"), category: f.get("category"), targets }) });
    $("#lead-result").innerHTML = `<div class="${r.verdict === "pass" ? "flagbox" : r.verdict === "pursue" ? "okbox" : "warnbox"}">${chip(r.verdict)} ${esc(r.reason)}</div>
      <div class="thread">${r.clients.map((c) => `<div class="knot"><div class="who">${esc(c.client)} · ${n(c.conflict)}</div><p class="muted">${c.paths.map((p) => `${esc(p.via)} (${n(p.conflict, 3)})`).join(" · ")}</p></div>`).join("")}</div>`;
    refresh();
  } catch (err) { $("#lead-result").innerHTML = `<div class="flagbox">${esc(err.message)}</div>`; }
});

$("#draft-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const ids = [...document.querySelectorAll("#tech-pick input:checked")].map((x) => x.value);
  if (!ids.length) { $("#draft-result").innerHTML = `<div class="warnbox">Pick at least one technique.</div>`; return; }
  try {
    const r = await api("/api/try/draft", { method: "POST", body: JSON.stringify({ client: $("#draft-client").value, technique_ids: ids }) });
    $("#draft-result").innerHTML = (r.flagged ? `<div class="flagbox"><b>Would be blocked.</b></div>` : `<div class="okbox"><b>Would clear.</b> Threshold ${n(r.threshold)}.</div>`)
      + `<ul class="list">${r.results.map((x) => `<li>${chip(x.flag ? "flagged" : "cleared", x.flag ? "flag" : "ok")} <b>${esc(x.business)}</b> (${esc(x.status)}): shares ${x.shared_rare.map(esc).join(", ")} · similarity ${n(x.similarity)} × overlap ${n(x.overlap)} = <b>${n(x.risk)}</b></li>`).join("") || "<li class='muted'>Shares no rare technique with anyone on the same audience.</li>"}</ul>`;
  } catch (err) { $("#draft-result").innerHTML = `<div class="flagbox">${esc(err.message)}</div>`; }
});

async function loadTechniques() {
  const ts = await api("/api/techniques");
  const rare = state.overview?.thresholds.rare ?? 0.6;
  const by = {};
  ts.forEach((t) => (by[t.style] ||= []).push(t));
  $("#tech-pick").innerHTML = Object.entries(by).map(([s, list]) => `<h5>${esc(s)}</h5>${list.map((t) =>
    `<label title="rarity ${n(t.rarity)} · ${t.ref_count} refs"><input type="checkbox" value="${esc(t.id)}"><span class="${t.rarity >= rare ? "rare" : ""}">${esc(t.name)}</span></label>`).join("")}`).join("")
    + `<p class="muted">Red = rare (rarity ≥ ${rare}). Only rare techniques count toward similarity.</p>`;
}

refresh().then(loadTechniques);
