/* Blender AI Extension dashboard — vanilla JS, polling, no dependencies. */
"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  providers: [], modes: [], tools: [],
  activeJob: null, lastSeq: 0, jobTimer: null,
  selectedTool: null, mcpSnippet: "",
};

const EXAMPLES = [
  ["Detailed futuristic robot", "Create a detailed futuristic robot with metal materials.", "SMART"],
  ["Medieval castle", "Create a medieval castle environment with stone walls, towers and torches.", "ENVIRONMENT"],
  ["Metal material", "Give the selected object a realistic brushed metal material.", "MATERIAL"],
  ["Camera sequence", "Create a cinematic 3-camera sequence around the current scene.", "CUTSCENE"],
  ["Procedural forest", "Build a procedural forest using Geometry Nodes with 150 trees.", "PROCEDURAL"],
  ["Sci-fi lab cinematic", "Create a complete sci-fi laboratory with lighting, materials and animated machinery.", "DIRECTOR"],
  ["Inspect & fix", "Inspect the current scene and fix any obvious problems.", "DEBUG"],
  ["Optimize", "Optimize this scene for better performance.", "OPTIMIZATION"],
];

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

async function api(path, opts) {
  const res = await fetch(path, Object.assign(
    {headers: {"Content-Type": "application/json"}}, opts || {}));
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
  return data;
}

/* ---------------- status / connection ---------------- */

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const b = s.bridge || {};
    const dot = $("dot");
    dot.className = "dot " + (b.reachable ? "green" : "red");
    $("bridgeLine").textContent = "Bridge: " + (b.target || "—") +
      (b.reachable ? " · connected" : " · unreachable");
    $("blenderVer").textContent = "Blender: " + (b.blender || "—");
    $("counts").textContent = s.tools + " tools · " + s.modes + " modes";
    $("connMsg").textContent = b.reachable
      ? "Connected to Blender " + (b.blender || "") + "."
      : ("Not connected: " + (b.error || "bridge offline") +
         " — open Blender → AI Agent → Start Server.");
  } catch (e) {
    $("dot").className = "dot red";
    $("connMsg").textContent = "Extension server error: " + e.message;
  }
}

async function applyConnection() {
  $("connMsg").textContent = "Testing…";
  try {
    const r = await api("/api/connection", {method: "POST", body: JSON.stringify({
      host: $("inHost").value, port: $("inPort").value})});
    $("connMsg").textContent = r.bridge.reachable
      ? "Connected to Blender " + (r.bridge.blender || "") + "."
      : "Not connected: " + r.bridge.error;
    refreshStatus();
  } catch (e) {
    $("connMsg").textContent = "Error: " + e.message;
  }
}

/* ---------------- providers / modes ---------------- */

function engine() {
  const el = document.querySelector('input[name="engine"]:checked');
  return el ? el.value : "builtin";
}

function refreshEngine() {
  $("llmFields").classList.toggle("disabled", engine() !== "llm");
}

async function loadProviders() {
  const {providers} = await api("/api/providers");
  state.providers = providers;
  const sel = $("inProvider");
  sel.innerHTML = "";
  providers.forEach((p) => {
    const o = document.createElement("option");
    o.value = p.id; o.textContent = p.label;
    sel.appendChild(o);
  });
  updateProvHelp();
}

function updateProvHelp() {
  const p = state.providers.find((x) => x.id === $("inProvider").value);
  $("provHelp").textContent = p
    ? ("Default model " + (p.model || "—") + " · " + (p.base_url || "endpoint required") +
       " · key env: " + (p.key_env || []).join(" / "))
    : "—";
}

async function loadModes() {
  const {modes} = await api("/api/modes");
  state.modes = modes;
  const sel = $("inMode");
  sel.innerHTML = "";
  modes.forEach((m) => {
    const o = document.createElement("option");
    o.value = m.id; o.textContent = m.label;
    sel.appendChild(o);
  });
  updateModeDesc();
}

function updateModeDesc() {
  const m = state.modes.find((x) => x.id === $("inMode").value);
  $("modeDesc").textContent = m ? (m.description + " · " + (m.tools || []).length + " tools") : "—";
}

/* ---------------- tools browser + quick run ---------------- */

async function loadTools() {
  const {tools} = await api("/api/tools");
  state.tools = tools;
  const cats = ["all"].concat([...new Set(tools.map((t) => t.category))].sort());
  const sel = $("toolCat");
  sel.innerHTML = "";
  cats.forEach((c) => {
    const o = document.createElement("option");
    o.value = c; o.textContent = c === "all" ? "All categories" : c;
    sel.appendChild(o);
  });
  renderTools();
}

function renderTools() {
  const q = ($("toolSearch").value || "").toLowerCase();
  const cat = $("toolCat").value;
  const list = state.tools.filter((t) =>
    (cat === "all" || t.category === cat) &&
    (!q || t.id.toLowerCase().includes(q) || t.label.toLowerCase().includes(q)));
  $("toolCount").textContent = "· " + list.length;
  const ul = $("toolList");
  ul.innerHTML = "";
  list.slice(0, 300).forEach((t) => {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.className = "toolbtn";
    b.innerHTML = "<strong>" + esc(t.label) + "</strong><span>" + esc(t.id) + "</span>";
    b.onclick = () => selectTool(t.id);
    li.appendChild(b);
    ul.appendChild(li);
  });
}

function selectTool(id) {
  const t = state.tools.find((x) => x.id === id);
  if (!t) return;
  state.selectedTool = t;
  $("qrName").textContent = t.id;
  $("qrDesc").textContent = t.description || "";
  const skeleton = {};
  Object.entries(t.params || {}).forEach(([k, r]) => {
    skeleton[k] = ("default" in r) ? r.default : "?";
  });
  $("qrParams").value = JSON.stringify(skeleton, null, 1);
  $("qrResult").hidden = true;
}

async function runQuickTool() {
  if (!state.selectedTool) return;
  let params;
  try {
    params = JSON.parse($("qrParams").value || "{}");
  } catch (e) {
    showQR({ok: false, error: "Invalid JSON params: " + e.message});
    return;
  }
  showQR({pending: true});
  try {
    const r = await api("/api/tool", {method: "POST",
      body: JSON.stringify({tool: state.selectedTool.id, params})});
    showQR(r);
  } catch (e) {
    showQR({ok: false, error: e.message});
  }
}

function showQR(r) {
  const pre = $("qrResult");
  pre.hidden = false;
  pre.textContent = r.pending ? "Running…" : JSON.stringify(r, null, 2).slice(0, 4000);
  pre.className = "snippet " + (r.ok ? "good" : (r.pending ? "" : "bad"));
}

/* ---------------- plan / run ---------------- */

function fillExamples() {
  const sel = $("inExample");
  sel.innerHTML = "";
  EXAMPLES.forEach(([label], i) => {
    const o = document.createElement("option");
    o.value = i; o.textContent = "Example: " + label;
    sel.appendChild(o);
  });
  sel.onchange = () => {
    const [, task, mode] = EXAMPLES[Number(sel.value)];
    $("inTask").value = task;
    $("inMode").value = mode;
    updateModeDesc();
  };
  sel.value = "0";
}

async function previewPlan() {
  const task = $("inTask").value.trim();
  if (!task) return;
  const ol = $("planList");
  ol.hidden = false;
  ol.innerHTML = "<li>Planning…</li>";
  try {
    const {plan, scene_available} = await api("/api/plan", {method: "POST",
      body: JSON.stringify({task, mode: $("inMode").value})});
    ol.innerHTML = "";
    (plan.notes || []).forEach((n) => {
      const li = document.createElement("li");
      li.className = "note";
      li.textContent = "Note: " + n;
      ol.appendChild(li);
    });
    plan.steps.forEach((s) => {
      const li = document.createElement("li");
      li.textContent = s.label + " <" + s.tool + ">";
      ol.appendChild(li);
    });
    const li = document.createElement("li");
    li.className = "note";
    li.textContent = "Domains: " + (plan.detected_domains.join(", ") || "—") +
      (scene_available ? "" : " · (Blender offline — planned without scene context)");
    ol.appendChild(li);
  } catch (e) {
    ol.innerHTML = "<li>Plan failed: " + esc(e.message) + "</li>";
  }
}

function feedLi(kind, t, text) {
  const li = document.createElement("li");
  li.className = "ev-" + kind;
  li.textContent = "[" + t + "] " + text;
  return li;
}

function resetFeed() {
  const f = $("feed");
  f.innerHTML = "";
}

function setBar(done, total) {
  const pct = total > 0 ? Math.round(100 * done / total) : 0;
  $("bar").style.width = Math.min(100, pct) + "%";
}

async function startAgent() {
  const task = $("inTask").value.trim();
  if (!task) {
    $("finalText").textContent = "Type a task first (or pick an example).";
    return;
  }
  $("btnStart").disabled = true;
  $("btnCancel").disabled = false;
  resetFeed();
  $("finalText").textContent = "Starting…";
  try {
    const body = {task, mode: $("inMode").value, engine: engine()};
    if (body.engine === "llm") {
      body.llm = {provider: $("inProvider").value, model: $("inModel").value,
                  api_key: $("inKey").value, base_url: $("inEndpoint").value,
                  max_iters: Number($("inIters").value || 25)};
    }
    const {job_id} = await api("/api/run", {method: "POST",
      body: JSON.stringify(body)});
    state.activeJob = job_id;
    state.lastSeq = 0;
    $("jobId").textContent = "· " + job_id;
    pollJob();
    state.jobTimer = setInterval(pollJob, 800);
  } catch (e) {
    $("finalText").textContent = "Start failed: " + e.message;
    $("btnStart").disabled = false;
    $("btnCancel").disabled = true;
  }
}

async function pollJob() {
  if (!state.activeJob) return;
  try {
    const job = await api("/api/jobs/" + state.activeJob + "?since=" + state.lastSeq);
    (job.events || []).forEach((e) => {
      state.lastSeq = Math.max(state.lastSeq, e.seq);
      $("feed").prepend(feedLi(e.kind, e.t, e.text));
      while ($("feed").children.length > 200)
        $("feed").removeChild($("feed").lastChild);
    });
    if (job.events && job.events.length) {
      const f = $("feed");
      if (f.firstChild && f.firstChild.classList &&
          f.firstChild.classList.contains("muted")) f.innerHTML = "";
    }
    setBar(job.progress.done, job.progress.total);
    $("curStep").textContent = job.current || "";
    if (["done", "error", "cancelled"].includes(job.status)) {
      clearInterval(state.jobTimer);
      state.jobTimer = null;
      state.activeJob = null;
      $("btnStart").disabled = false;
      $("btnCancel").disabled = true;
      $("finalText").textContent = (job.status.toUpperCase() + " · " + (job.final || "")).slice(0, 2000);
      refreshJobs();
    }
  } catch (e) {
    $("curStep").textContent = "Job poll error: " + e.message;
  }
}

async function cancelJob() {
  if (!state.activeJob) return;
  try {
    await api("/api/jobs/" + state.activeJob + "/cancel", {method: "POST"});
    $("curStep").textContent = "Cancelling…";
  } catch (e) {
    $("curStep").textContent = "Cancel failed: " + e.message;
  }
}

/* ---------------- jobs list ---------------- */

async function refreshJobs() {
  try {
    const {jobs} = await api("/api/jobs");
    const ul = $("jobList");
    ul.innerHTML = "";
    if (!jobs.length) {
      ul.innerHTML = "<li class='muted'>No runs yet.</li>";
      return;
    }
    jobs.forEach((j) => {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.className = "jobbtn st-" + j.status;
      b.textContent = j.id + " · " + j.engine + "/" + j.mode + " · " + j.status +
        " · " + j.task.slice(0, 60);
      b.title = j.task;
      b.onclick = () => openJob(j.id);
      li.appendChild(b);
      ul.appendChild(li);
    });
  } catch (e) { /* keep old list on transient errors */ }
}

async function openJob(id) {
  if (state.jobTimer) return; // don't hijack a live run view
  try {
    const job = await api("/api/jobs/" + id + "?since=0");
    resetFeed();
    (job.events || []).slice().reverse().forEach((e) =>
      $("feed").appendChild(feedLi(e.kind, e.t, e.text)));
    setBar(job.progress.done, job.progress.total);
    $("curStep").textContent = job.current || "";
    $("jobId").textContent = "· " + job.id;
    $("finalText").textContent = ((job.status || "").toUpperCase() + " · " + (job.final || "")).slice(0, 2000);
  } catch (e) {
    $("finalText").textContent = "Open job failed: " + e.message;
  }
}

/* ---------------- MCP info ---------------- */

async function loadMcp() {
  try {
    const m = await api("/api/mcp");
    $("mcpStatus").textContent = "mcp package: " + m.mcp_package +
      " · server script: " + (m.server_script === "missing" ? "missing" : "found");
    state.mcpSnippet = m.snippet || "";
    $("mcpSnippet").textContent = state.mcpSnippet;
  } catch (e) {
    $("mcpStatus").textContent = "MCP info error: " + e.message;
  }
}

/* ---------------- boot ---------------- */

document.addEventListener("DOMContentLoaded", async () => {
  fillExamples();
  $("btnTest").onclick = refreshStatus;
  $("btnConn").onclick = applyConnection;
  $("btnStart").onclick = startAgent;
  $("btnCancel").onclick = cancelJob;
  $("btnPlan").onclick = previewPlan;
  $("btnRunTool").onclick = runQuickTool;
  $("toolSearch").oninput = renderTools;
  $("toolCat").onchange = renderTools;
  $("inProvider").onchange = updateProvHelp;
  $("inMode").onchange = updateModeDesc;
  document.querySelectorAll('input[name="engine"]').forEach(
    (r) => (r.onchange = refreshEngine));
  $("btnCopyMcp").onclick = async () => {
    try {
      await navigator.clipboard.writeText(state.mcpSnippet);
      $("btnCopyMcp").textContent = "Copied!";
      setTimeout(() => ($("btnCopyMcp").textContent = "Copy config"), 1500);
    } catch (e) {
      $("btnCopyMcp").textContent = "Copy failed";
    }
  };
  refreshEngine();
  await refreshStatus();
  try {
    const cfg = await api("/api/config");
    if (cfg.blender) {
      $("inHost").value = cfg.blender.host || "127.0.0.1";
      $("inPort").value = cfg.blender.port || 9876;
    }
    await Promise.all([loadProviders(), loadModes(), loadTools(), loadMcp()]);
    if (cfg.defaults) {
      if (cfg.defaults.mode) { $("inMode").value = cfg.defaults.mode; updateModeDesc(); }
      if (cfg.defaults.engine) {
        const r = document.querySelector('input[name="engine"][value="' + cfg.defaults.engine + '"]');
        if (r) r.checked = true;
        refreshEngine();
      }
      if (cfg.defaults.provider) { $("inProvider").value = cfg.defaults.provider; updateProvHelp(); }
      if (cfg.defaults.max_iters) $("inIters").value = cfg.defaults.max_iters;
    }
  } catch (e) {
    $("finalText").textContent = "Init failed: " + e.message;
  }
  refreshJobs();
  setInterval(refreshStatus, 5000);
  setInterval(() => { if (!state.activeJob) refreshJobs(); }, 4000);
});
