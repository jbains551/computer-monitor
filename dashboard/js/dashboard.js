/**
 * System Monitor Dashboard
 *
 * Configuration: set SERVER_URL to your deployed server, or leave as empty
 * string to use the same origin (when the dashboard is served by FastAPI).
 */

const SERVER_URL = "";
const REFRESH_MS  = 60_000;
const API_BASE    = SERVER_URL ? SERVER_URL.replace(/\/$/, "") : "";

let currentMachine = null;
let refreshTimer   = null;
let countdown      = REFRESH_MS / 1000;
const CIRCUMFERENCE = 2 * Math.PI * 15; // r=15

// ── API ───────────────────────────────────────────────────────────────────────

function api(path) {
  return fetch(`${API_BASE}${path}`).then(r => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  });
}

// ── Formatters ────────────────────────────────────────────────────────────────

function fmtBytes(bytes) {
  if (bytes == null) return "—";
  const units = ["B","KB","MB","GB","TB"];
  let i = 0, v = bytes;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(1)} ${units[i]}`;
}

function fmtUptime(seconds) {
  if (seconds == null) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const parts = [];
  if (d) parts.push(`${d}d`);
  if (h) parts.push(`${h}h`);
  parts.push(`${m}m`);
  return parts.join(" ");
}

function fmtAgo(seconds) {
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds/60)}m ago`;
  return `${Math.floor(seconds/3600)}h ago`;
}

function pctClass(pct) {
  if (pct >= 90) return "text-red";
  if (pct >= 75) return "text-yellow";
  return "text-green";
}

function accentClass(pct) {
  if (pct >= 90) return "accent-red";
  if (pct >= 75) return "accent-yellow";
  return "accent-green";
}

function diskFillClass(pct) {
  if (pct >= 90) return "crit";
  if (pct >= 75) return "warn";
  return "ok";
}

// ── DOM helpers ───────────────────────────────────────────────────────────────

function setText(id, text)  { const el = document.getElementById(id); if (el) el.textContent = text; }
function setHTML(id, html)  { const el = document.getElementById(id); if (el) el.innerHTML = html; }
function setClass(id, cls)  { const el = document.getElementById(id); if (el) el.className = cls; }
function show(...ids) { ids.forEach(id => document.getElementById(id)?.classList.remove("hidden")); }
function hide(...ids) { ids.forEach(id => document.getElementById(id)?.classList.add("hidden")); }
function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function fillBar(barId, pct) {
  const el = document.getElementById(barId);
  if (!el) return;
  el.style.width = `${Math.min(pct, 100)}%`;
  el.className = "progress-fill";
  if (pct >= 90) el.classList.add("crit");
  else if (pct >= 75) el.classList.add("warn");
}

function setCardAccent(cardId, pct) {
  const el = document.getElementById(cardId);
  if (!el) return;
  el.classList.remove("accent-green","accent-yellow","accent-red","accent-blue","accent-accent");
  el.classList.add(accentClass(pct));
}

// ── Countdown ring ────────────────────────────────────────────────────────────

function updateRing() {
  const ring = document.getElementById("refresh-ring");
  const label = document.getElementById("refresh-countdown");
  if (!ring || !label) return;
  const offset = CIRCUMFERENCE * (1 - countdown / (REFRESH_MS / 1000));
  ring.style.strokeDashoffset = offset;
  label.textContent = countdown;
}

function tickCountdown() {
  countdown--;
  if (countdown < 0) countdown = REFRESH_MS / 1000;
  updateRing();
}

// ── Machine tabs ──────────────────────────────────────────────────────────────

async function loadMachines() {
  const machines = await api("/api/machines");
  const tabBar = document.getElementById("machine-tabs");
  tabBar.innerHTML = "";

  if (!machines.length) {
    tabBar.innerHTML = '<span class="muted">No machines connected yet.</span>';
    return;
  }

  machines.forEach(m => {
    const tab = document.createElement("button");
    tab.className = "tab" + (m.name === currentMachine ? " active" : "");
    const dotCls = m.online ? "dot-online" : "dot-offline";
    const icon = { mac: "🍎", pc: "🖥️", "raspberry-pi": "🫐" }[m.machine_type] || "💻";
    const ago = fmtAgo(m.last_seen_ago);
    tab.innerHTML = `<span class="dot ${dotCls}"></span>${icon} ${escHtml(m.name)}`;
    tab.title = m.online ? `Online · last seen ${ago}` : `Offline · last seen ${ago}`;
    tab.addEventListener("click", () => selectMachine(m.name));
    tabBar.appendChild(tab);
  });

  if (!currentMachine && machines.length) selectMachine(machines[0].name);
}

function selectMachine(name) {
  currentMachine = name;
  document.querySelectorAll(".tab").forEach(t => {
    t.classList.toggle("active", t.textContent.includes(name));
  });
  loadMachineData(name);
}

// ── Main data loader ──────────────────────────────────────────────────────────

async function loadMachineData(machine) {
  try {
    const snap = await api(`/api/machines/${encodeURIComponent(machine)}/latest`);
    renderSnapshot(snap);
    hide("no-data");
    show("overview", "detail-section", "machine-info-bar");
  } catch (err) {
    if (err.message.includes("404")) {
      hide("overview", "detail-section", "machine-info-bar");
      show("no-data");
    }
  }

  try {
    const alerts = await api(`/api/alerts?machine=${encodeURIComponent(machine)}&limit=20&unacked_only=true`);
    renderAlerts(alerts);
  } catch (_) {}

  await loadCommands(machine);
  reinitIcons();
}

// ── Snapshot renderer ─────────────────────────────────────────────────────────

function renderSnapshot(snap) {
  const sys = snap.system || {};
  const sec = snap.security || {};
  const now = Date.now() / 1000;
  const age = Math.round(now - snap.timestamp);

  setText("last-refresh", `Updated ${fmtAgo(age)}`);

  // Info bar
  const chipText = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.querySelector("span").textContent = text;
  };
  chipText("info-os",       `${sys.os || "?"} ${sys.os_version ? sys.os_version.split(" ")[0] : ""}`.trim());
  chipText("info-hostname",  sys.hostname || "?");
  chipText("info-uptime",   `Up ${fmtUptime(sys.uptime_seconds)}`);
  const load = sys.load_avg;
  chipText("info-load", load ? `Load ${load.map(v => v.toFixed(2)).join(" ")}` : "Load —");

  // ── Status card ────────────────────────────────────────────────
  const online = snap.online;
  const statusCard = document.getElementById("card-status");
  if (statusCard) {
    statusCard.classList.remove("accent-green","accent-red");
    statusCard.classList.add(online ? "accent-green" : "accent-red");
    // Manage pulse ring
    let ring = statusCard.querySelector(".pulse-ring");
    if (!ring) {
      ring = document.createElement("div");
      ring.className = "pulse-ring";
      statusCard.appendChild(ring);
    }
    ring.className = `pulse-ring ${online ? "online" : "offline"}`;
    // Hide the card-icon on status card (replaced by pulse)
    const icon = statusCard.querySelector(".card-icon");
    if (icon) icon.style.display = "none";
  }
  setText("val-status", online ? "Online" : "Offline");
  setClass("val-status", `card-value ${online ? "text-green" : "text-red"}`);
  setText("val-uptime", fmtUptime(sys.uptime_seconds));

  // ── CPU card ───────────────────────────────────────────────────
  const cpu = sys.cpu || {};
  const cpuPct = cpu.percent ?? 0;
  setText("val-cpu", `${cpuPct.toFixed(1)}%`);
  setClass("val-cpu", `card-value ${pctClass(cpuPct)}`);
  fillBar("bar-cpu", cpuPct);
  setText("val-cpu-sub", `${cpu.count_logical ?? "?"} cores${cpu.frequency_mhz ? " · " + (cpu.frequency_mhz/1000).toFixed(2) + " GHz" : ""}`);
  setCardAccent("card-cpu", cpuPct);

  // ── Memory card ────────────────────────────────────────────────
  const mem = sys.memory || {};
  const memPct = mem.percent ?? 0;
  setText("val-mem", `${memPct.toFixed(1)}%`);
  setClass("val-mem", `card-value ${pctClass(memPct)}`);
  fillBar("bar-mem", memPct);
  setText("val-mem-sub", `${mem.used_gb ?? "?"} / ${mem.total_gb ?? "?"} GB`);
  setCardAccent("card-mem", memPct);

  // ── Disk card (primary) ────────────────────────────────────────
  const disks = sys.disks || [];
  const primary = disks[0] || {};
  const diskPct = primary.percent ?? 0;
  setText("val-disk", `${diskPct.toFixed(1)}%`);
  setClass("val-disk", `card-value ${pctClass(diskPct)}`);
  fillBar("bar-disk", diskPct);
  setText("val-disk-sub", `${primary.used_gb ?? "?"} / ${primary.total_gb ?? "?"} GB`);
  setCardAccent("card-disk", diskPct);

  // ── Network card ───────────────────────────────────────────────
  const net = sys.network || {};
  setText("val-net-sent", fmtBytes(net.bytes_sent));
  setText("val-net-recv", fmtBytes(net.bytes_recv));
  const netCard = document.getElementById("card-net");
  if (netCard) { netCard.classList.remove("accent-green","accent-yellow","accent-red"); netCard.classList.add("accent-blue"); }

  // ── Security card ──────────────────────────────────────────────
  const ports    = sec.ports || {};
  const flagged  = (ports.flagged || []).length;
  const susProcs = (sec.suspicious_processes || []).length;
  const logins   = (sec.failed_logins || {}).count_24h ?? 0;
  const updates  = (sec.package_updates || {}).count ?? 0;
  let secStatus = "All Clear", secCls = "card-value text-green", secAccent = "accent-green";
  if (flagged || susProcs) { secStatus = "Threats Found"; secCls = "card-value text-red"; secAccent = "accent-red"; }
  else if (logins >= 10)   { secStatus = "Brute Force";   secCls = "card-value text-yellow"; secAccent = "accent-yellow"; }
  else if (updates >= 10)  { secStatus = "Updates Needed";secCls = "card-value text-yellow"; secAccent = "accent-yellow"; }
  setText("val-security", secStatus);
  setClass("val-security", secCls);
  setText("val-security-sub", `${flagged} flagged · ${susProcs} procs · ${logins} logins`);
  const secCard = document.getElementById("card-security");
  if (secCard) { secCard.classList.remove("accent-green","accent-yellow","accent-red"); secCard.classList.add(secAccent); }

  // ── Detail panels ──────────────────────────────────────────────

  // Disk details — individual bars per partition
  setHTML("disk-list", disks.length
    ? disks.map(d => {
        const fc = diskFillClass(d.percent);
        return `<div class="disk-row">
          <div class="disk-header">
            <span class="disk-mount">${escHtml(d.mountpoint)}</span>
            <span class="disk-stat ${pctClass(d.percent)}">${d.percent}% &middot; ${d.used_gb}/${d.total_gb} GB</span>
          </div>
          <div class="disk-bar"><div class="disk-fill ${fc}" style="width:${Math.min(d.percent,100)}%"></div></div>
        </div>`;
      }).join("")
    : '<p class="empty">No disk data</p>');

  // Listening ports
  const listening = ports.listening || [];
  const flaggedSet = new Set((ports.flagged || []).map(f => f.port));
  setHTML("port-list", listening.length
    ? `<table class="data-table">
        <thead><tr><th>Port</th><th>Process</th><th>PID</th><th>Status</th></tr></thead>
        <tbody>${listening.slice(0,30).map(p => `
          <tr>
            <td>${p.port}</td>
            <td title="${escHtml(String(p.address))}">${escHtml(p.process)}</td>
            <td>${p.pid ?? "—"}</td>
            <td>${flaggedSet.has(p.port) ? '<span class="tag-flag">FLAGGED</span>' : '<span class="tag-ok">OK</span>'}</td>
          </tr>`).join("")}
        </tbody>
       </table>${listening.length > 30 ? `<p class="empty">+${listening.length-30} more</p>` : ""}`
    : '<p class="empty">No listening ports detected</p>');

  // Failed logins
  const fl = sec.failed_logins || {};
  const loginEvents = fl.recent || [];
  const loginCount = fl.count_24h ?? 0;
  const loginColour = loginCount >= 50 ? "text-red" : loginCount >= 10 ? "text-yellow" : "text-green";
  setHTML("login-list",
    `<div class="stat-row"><span class="stat-label">Attempts (24h)</span><span class="stat-val ${loginColour}">${loginCount}</span></div>` +
    (loginEvents.length
      ? `<table class="data-table" style="margin-top:10px">
          <thead><tr><th>Time</th><th>Source IP</th></tr></thead>
          <tbody>${loginEvents.slice(0,10).map(e => `
            <tr><td>${escHtml(e.time||"—")}</td><td>${escHtml(e.source_ip||"unknown")}</td></tr>`).join("")}
          </tbody></table>`
      : `<p class="empty" style="margin-top:10px">No recent failed attempts</p>`));

  // Package updates
  const pkg = sec.package_updates || {};
  const pkgList = pkg.available_updates || [];
  const pkgColour = pkg.count >= 20 ? "text-yellow" : "text-green";
  setHTML("update-list",
    `<div class="stat-row"><span class="stat-label">Packages available</span><span class="stat-val ${pkgColour}">${pkg.count ?? 0}</span></div>` +
    (pkgList.length
      ? `<table class="data-table" style="margin-top:10px">
          <thead><tr><th>Package</th><th>Type</th></tr></thead>
          <tbody>${pkgList.slice(0,15).map(u => `
            <tr><td>${escHtml(u.name)}</td><td class="text-muted">${escHtml(u.type)}</td></tr>`).join("")}
          </tbody></table>${pkgList.length>15?`<p class="empty">+${pkgList.length-15} more</p>`:""}`
      : `<p class="empty" style="margin-top:10px">All packages up to date</p>`));

  // Suspicious processes
  const sprocs = sec.suspicious_processes || [];
  setHTML("proc-list", sprocs.length
    ? `<table class="data-table">
        <thead><tr><th>Name</th><th>PID</th><th>User</th></tr></thead>
        <tbody>${sprocs.map(p => `
          <tr>
            <td class="text-red">${escHtml(p.name)}</td>
            <td>${p.pid}</td>
            <td>${escHtml(p.username||"—")}</td>
          </tr>`).join("")}
        </tbody></table>`
    : '<p class="empty">No suspicious processes found</p>');

  // Network interfaces
  const ifaces = net.interfaces || {};
  const ifaceRows = Object.entries(ifaces);
  setHTML("iface-list", ifaceRows.length
    ? `<table class="data-table">
        <thead><tr><th>Interface</th><th>Address</th></tr></thead>
        <tbody>${ifaceRows.map(([k,v]) => `
          <tr><td>${escHtml(k)}</td><td>${escHtml(v)}</td></tr>`).join("")}
        </tbody></table>`
    : '<p class="empty">No interface data</p>');
}

// ── Alerts ────────────────────────────────────────────────────────────────────

function renderAlerts(alerts) {
  const section = document.getElementById("alert-section");
  if (!alerts.length) { section.classList.add("hidden"); return; }
  section.classList.remove("hidden");
  section.innerHTML = alerts.map(a => {
    const age = fmtAgo(Math.round(Date.now()/1000 - a.timestamp));
    return `<div class="alert-item ${escHtml(a.severity)}" id="alert-${a.id}">
      <span class="alert-text">
        <strong>${escHtml(a.severity.toUpperCase())}</strong>
        <span class="text-muted"> [${escHtml(a.category)}]</span>
        &mdash; ${escHtml(a.message)}
        <span class="alert-meta">${age}</span>
      </span>
      <button class="alert-ack" onclick="ackAlert(${a.id})">Dismiss</button>
    </div>`;
  }).join("");
}

async function ackAlert(id) {
  const key = localStorage.getItem("monitor_api_key") || "";
  try {
    await fetch(`${API_BASE}/api/alerts/${id}/acknowledge`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${key}` },
    });
    document.getElementById(`alert-${id}`)?.remove();
  } catch {
    alert("Set your API key first:\n\nlocalStorage.setItem('monitor_api_key', 'your-key')");
  }
}

// ── Commands ──────────────────────────────────────────────────────────────────

async function runUpdateAll() {
  const key = localStorage.getItem("monitor_api_key") || "";
  if (!key) {
    alert("Set your API key first in the browser console:\n\nlocalStorage.setItem('monitor_api_key', 'your-key')");
    return;
  }
  if (!currentMachine) return;
  const btn = document.getElementById("btn-update-all");
  if (btn) { btn.disabled = true; btn.classList.add("running"); }

  try {
    const resp = await fetch(`${API_BASE}/api/machines/${encodeURIComponent(currentMachine)}/commands`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({ command: "update_packages" }),
    });
    const data = await resp.json();
    if (resp.ok) {
      await loadCommands(currentMachine);
    } else {
      alert(`Failed to queue command: ${data.detail || JSON.stringify(data)}`);
    }
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    if (btn) { btn.disabled = false; btn.classList.remove("running"); reinitIcons(); }
  }
}

async function loadCommands(machine) {
  try {
    const cmds = await api(`/api/machines/${encodeURIComponent(machine)}/commands?limit=10`);
    renderCommands(cmds);
  } catch (_) {}
}

function renderCommands(cmds) {
  const el = document.getElementById("command-list");
  if (!el) return;
  if (!cmds.length) { el.innerHTML = '<p class="empty">No commands run yet</p>'; return; }

  el.innerHTML = cmds.map(c => {
    const name = { update_packages: "Update All Packages" }[c.command] || c.command;
    const age = fmtAgo(Math.round(Date.now()/1000 - c.created_at));
    const hasOutput = c.output && c.output.trim();
    const isActive = c.status === "pending" || c.status === "running";
    return `<div class="cmd-item">
      <div class="cmd-header" onclick="toggleOutput(${c.id})">
        <span class="cmd-name">${escHtml(name)}</span>
        <span class="cmd-time">${age}</span>
        <span class="cmd-status ${c.status}">${isActive ? '<span style="animation:spin 1s linear infinite;display:inline-block">↻</span> ' : ''}${c.status}</span>
      </div>
      ${hasOutput
        ? `<div class="cmd-output" id="cmdout-${c.id}">${escHtml(c.output)}</div>`
        : isActive
          ? `<div class="cmd-output" id="cmdout-${c.id}" style="color:var(--muted)">Waiting for agent to pick up command… (checks every 60s)</div>`
          : ''}
    </div>`;
  }).join("");
}

function toggleOutput(id) {
  const el = document.getElementById(`cmdout-${id}`);
  if (el) el.classList.toggle("open");
}

// ── Server status ─────────────────────────────────────────────────────────────

async function checkServerStatus() {
  const badge = document.getElementById("server-status");
  try {
    const s = await api("/api/status");
    badge.className = "badge badge-ok";
    badge.textContent = `Server OK · ${s.machines_online}/${s.machine_count} online`;
  } catch {
    badge.className = "badge badge-crit";
    badge.textContent = "Server Unreachable";
  }
}

// ── Footer clock ──────────────────────────────────────────────────────────────

function updateFooterTime() {
  const el = document.getElementById("footer-time");
  if (el) el.textContent = new Date().toLocaleTimeString();
}

// ── Feather icons ─────────────────────────────────────────────────────────────

function reinitIcons() {
  if (window.feather) feather.replace({ "stroke-width": 2 });
}

// ── Init & refresh loop ───────────────────────────────────────────────────────

async function refresh() {
  countdown = REFRESH_MS / 1000;
  await Promise.allSettled([checkServerStatus(), loadMachines()]);
  if (currentMachine) await loadMachineData(currentMachine);
  reinitIcons();
}

async function init() {
  reinitIcons();
  updateFooterTime();
  await refresh();

  // Countdown tick every second
  setInterval(() => {
    tickCountdown();
    updateFooterTime();
  }, 1000);

  // Full refresh every 60s
  setInterval(refresh, REFRESH_MS);
}

init();
