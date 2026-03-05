/**
 * System Monitor Dashboard
 *
 * Configuration: set SERVER_URL to your deployed server, or leave as empty
 * string to use the same origin (i.e., when the dashboard is served by FastAPI).
 */

const SERVER_URL = "";          // e.g. "https://your-server.onrender.com"
const REFRESH_MS  = 60_000;     // 60 seconds
const API_BASE    = SERVER_URL ? SERVER_URL.replace(/\/$/, "") : "";

let currentMachine = null;
let refreshTimer   = null;

// ── Helpers ───────────────────────────────────────────────────────────────────

function api(path) {
  return fetch(`${API_BASE}${path}`).then(r => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  });
}

function fmtBytes(bytes) {
  if (bytes == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = bytes;
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
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds/60)}m ago`;
  return `${Math.floor(seconds/3600)}h ago`;
}

function colourPct(pct) {
  if (pct >= 90) return "text-red";
  if (pct >= 75) return "text-yellow";
  return "text-green";
}

function fillBar(barId, pct) {
  const el = document.getElementById(barId);
  if (!el) return;
  el.style.width = `${Math.min(pct, 100)}%`;
  el.className = "progress-fill";
  if (pct >= 90) el.classList.add("crit");
  else if (pct >= 75) el.classList.add("warn");
}

function setClass(id, cls) {
  const el = document.getElementById(id);
  if (el) el.className = cls;
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function setHTML(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function show(...ids) { ids.forEach(id => document.getElementById(id)?.classList.remove("hidden")); }
function hide(...ids) { ids.forEach(id => document.getElementById(id)?.classList.add("hidden")); }

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
    tab.innerHTML = `<span class="dot ${dotCls}"></span>${icon} ${m.name}`;
    tab.title = m.online
      ? `Last seen: ${fmtAgo(m.last_seen_ago)}`
      : `Offline — last seen ${fmtAgo(m.last_seen_ago)}`;
    tab.addEventListener("click", () => selectMachine(m.name));
    tabBar.appendChild(tab);
  });

  // Auto-select first machine if none selected
  if (!currentMachine && machines.length) {
    selectMachine(machines[0].name);
  }
}

function selectMachine(name) {
  currentMachine = name;
  // Highlight active tab
  document.querySelectorAll(".tab").forEach(t => {
    t.classList.toggle("active", t.textContent.trim().endsWith(name) || t.textContent.includes(name));
  });
  loadMachineData(name);
}

// ── Main data loader ──────────────────────────────────────────────────────────

async function loadMachineData(machine) {
  try {
    const snap = await api(`/api/machines/${encodeURIComponent(machine)}/latest`);
    renderSnapshot(snap);
    hide("no-data");
    show("overview", "detail-section");
  } catch (err) {
    if (err.message.includes("404")) {
      hide("overview", "detail-section");
      show("no-data");
    } else {
      console.error("Failed to load machine data:", err);
    }
  }

  // Load alerts for this machine
  try {
    const alerts = await api(`/api/alerts?machine=${encodeURIComponent(machine)}&limit=20&unacked_only=true`);
    renderAlerts(alerts);
  } catch (_) {}
}

// ── Render ────────────────────────────────────────────────────────────────────

function renderSnapshot(snap) {
  const sys = snap.system || {};
  const sec = snap.security || {};
  const now = Date.now() / 1000;
  const age = now - snap.timestamp;

  setText("last-refresh", `Updated ${fmtAgo(Math.round(age))}`);

  // --- Status card ---
  const online = snap.online;
  setText("val-status", online ? "Online" : "Offline");
  setClass("val-status", online ? "card-value text-green" : "card-value text-red");
  setText("val-uptime", `Uptime: ${fmtUptime(sys.uptime_seconds)}`);

  // --- CPU card ---
  const cpu = sys.cpu || {};
  const cpuPct = cpu.percent ?? 0;
  setText("val-cpu", `${cpuPct.toFixed(1)}%`);
  setClass("val-cpu", `card-value ${colourPct(cpuPct)}`);
  fillBar("bar-cpu", cpuPct);
  setText("val-cpu-sub", `${cpu.count_logical ?? "?"} cores${cpu.frequency_mhz ? " · " + (cpu.frequency_mhz/1000).toFixed(2) + " GHz" : ""}`);

  // --- Memory card ---
  const mem = sys.memory || {};
  const memPct = mem.percent ?? 0;
  setText("val-mem", `${memPct.toFixed(1)}%`);
  setClass("val-mem", `card-value ${colourPct(memPct)}`);
  fillBar("bar-mem", memPct);
  setText("val-mem-sub", `${mem.used_gb ?? "?"} / ${mem.total_gb ?? "?"} GB`);

  // --- Disk card (primary = first disk) ---
  const disks = sys.disks || [];
  const primaryDisk = disks[0] || {};
  const diskPct = primaryDisk.percent ?? 0;
  setText("val-disk", `${diskPct.toFixed(1)}%`);
  setClass("val-disk", `card-value ${colourPct(diskPct)}`);
  fillBar("bar-disk", diskPct);
  setText("val-disk-sub", `${primaryDisk.used_gb ?? "?"} / ${primaryDisk.total_gb ?? "?"} GB`);

  // --- Network card ---
  const net = sys.network || {};
  setText("val-net-sent", `↑ ${fmtBytes(net.bytes_sent)} sent`);
  setText("val-net-recv", `↓ ${fmtBytes(net.bytes_recv)} received`);

  // --- Security summary card ---
  const ports    = sec.ports || {};
  const flagged  = (ports.flagged || []).length;
  const susProcs = (sec.suspicious_processes || []).length;
  const logins   = (sec.failed_logins || {}).count_24h ?? 0;
  const updates  = (sec.package_updates || {}).count ?? 0;

  let secStatus = "All Clear";
  let secClass  = "card-value text-green";
  if (flagged || susProcs) { secStatus = "Threats Detected"; secClass = "card-value text-red"; }
  else if (logins >= 10)   { secStatus = "Brute Force Risk"; secClass = "card-value text-yellow"; }
  else if (updates >= 10)  { secStatus = "Updates Needed";   secClass = "card-value text-yellow"; }

  setText("val-security", secStatus);
  setClass("val-security", secClass);
  setText("val-security-sub",
    `${flagged} flagged port(s) · ${susProcs} suspicious proc(s) · ${logins} failed login(s)`);

  // ── Detail panels ──────────────────────────────────────────────────────────

  // Disk list
  setHTML("disk-list", disks.length
    ? `<table class="data-table">
        <thead><tr><th>Mount</th><th>Used</th><th>Total</th><th>%</th></tr></thead>
        <tbody>${disks.map(d => `
          <tr>
            <td title="${d.device}">${d.mountpoint}</td>
            <td>${d.used_gb} GB</td>
            <td>${d.total_gb} GB</td>
            <td class="${colourPct(d.percent)}">${d.percent}%</td>
          </tr>`).join("")}
        </tbody>
       </table>`
    : '<p class="empty">No disk data</p>');

  // Open ports
  const listening = ports.listening || [];
  const flaggedPorts = new Set((ports.flagged || []).map(f => f.port));
  setHTML("port-list", listening.length
    ? `<table class="data-table">
        <thead><tr><th>Port</th><th>Process</th><th>PID</th><th></th></tr></thead>
        <tbody>${listening.slice(0, 30).map(p => `
          <tr>
            <td>${p.port}</td>
            <td title="${p.address}">${p.process}</td>
            <td>${p.pid ?? "—"}</td>
            <td>${flaggedPorts.has(p.port) ? '<span class="tag-flag">FLAGGED</span>' : '<span class="tag-ok">ok</span>'}</td>
          </tr>`).join("")}
        </tbody>
       </table>${listening.length > 30 ? `<p class="empty">…and ${listening.length - 30} more</p>` : ""}`
    : '<p class="empty">No listening ports found</p>');

  // Failed logins
  const fl = sec.failed_logins || {};
  const loginEvents = fl.recent || [];
  setHTML("login-list",
    `<p class="card-sub" style="margin-bottom:10px">${fl.count_24h ?? 0} failed attempts in last 24 hours</p>` +
    (loginEvents.length
      ? `<table class="data-table">
          <thead><tr><th>Time</th><th>Source IP</th></tr></thead>
          <tbody>${loginEvents.slice(0, 10).map(e => `
            <tr>
              <td>${e.time || "—"}</td>
              <td>${e.source_ip || "unknown"}</td>
            </tr>`).join("")}
          </tbody>
         </table>`
      : '<p class="empty">No recent failed login attempts</p>'));

  // Package updates
  const pkg = sec.package_updates || {};
  const pkgUpdates = pkg.available_updates || [];
  setHTML("update-list",
    `<p class="card-sub" style="margin-bottom:10px">${pkg.count ?? 0} packages can be updated</p>` +
    (pkgUpdates.length
      ? `<table class="data-table">
          <thead><tr><th>Package</th><th>Type</th></tr></thead>
          <tbody>${pkgUpdates.slice(0, 15).map(u => `
            <tr><td>${u.name}</td><td class="text-muted">${u.type}</td></tr>`).join("")}
          </tbody>
         </table>${pkgUpdates.length > 15 ? `<p class="empty">…and ${pkgUpdates.length - 15} more</p>` : ""}`
      : '<p class="empty">All packages up to date</p>'));

  // Suspicious processes
  const sprocs = sec.suspicious_processes || [];
  setHTML("proc-list", sprocs.length
    ? `<table class="data-table">
        <thead><tr><th>Name</th><th>PID</th><th>User</th></tr></thead>
        <tbody>${sprocs.map(p => `
          <tr>
            <td class="text-red">${p.name}</td>
            <td>${p.pid}</td>
            <td>${p.username || "—"}</td>
          </tr>`).join("")}
        </tbody>
       </table>`
    : '<p class="empty">No suspicious processes detected</p>');

  // Network interfaces
  const ifaces = net.interfaces || {};
  const ifaceRows = Object.entries(ifaces);
  setHTML("iface-list", ifaceRows.length
    ? `<table class="data-table">
        <thead><tr><th>Interface</th><th>Address</th></tr></thead>
        <tbody>${ifaceRows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}
        </tbody>
       </table>`
    : '<p class="empty">No interface data</p>');
}

function renderAlerts(alerts) {
  const section = document.getElementById("alert-section");
  if (!alerts.length) {
    section.classList.add("hidden");
    return;
  }
  section.classList.remove("hidden");
  section.innerHTML = alerts.map(a => `
    <div class="alert-item ${a.severity}" id="alert-${a.id}">
      <span>
        <strong>${a.severity.toUpperCase()}</strong> [${a.category}]
        &mdash; ${escHtml(a.message)}
        <span class="text-muted" style="margin-left:8px;font-size:11px">${fmtAgo(Math.round(Date.now()/1000 - a.timestamp))}</span>
      </span>
      <button class="alert-ack" onclick="ackAlert(${a.id})">Dismiss</button>
    </div>`).join("");
}

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// ── Alert acknowledgment ──────────────────────────────────────────────────────

async function ackAlert(id) {
  // Read API key from localStorage (set once via browser console or settings page)
  const key = localStorage.getItem("monitor_api_key") || "";
  try {
    await fetch(`${API_BASE}/api/alerts/${id}/acknowledge`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${key}` },
    });
    document.getElementById(`alert-${id}`)?.remove();
  } catch (err) {
    alert("Could not dismiss alert. Make sure your API key is saved.\n\nRun in browser console:\n  localStorage.setItem('monitor_api_key', 'your-key-here')");
  }
}

// ── Server status ─────────────────────────────────────────────────────────────

async function checkServerStatus() {
  const badge = document.getElementById("server-status");
  try {
    const status = await api("/api/status");
    badge.className = "badge badge-ok";
    badge.textContent = `Server OK · ${status.machines_online}/${status.machine_count} online`;
  } catch {
    badge.className = "badge badge-crit";
    badge.textContent = "Server Unreachable";
  }
}

// ── Init & refresh loop ───────────────────────────────────────────────────────

async function refresh() {
  await Promise.allSettled([checkServerStatus(), loadMachines()]);
  if (currentMachine) await loadMachineData(currentMachine);
}

async function init() {
  await refresh();
  refreshTimer = setInterval(refresh, REFRESH_MS);
}

init();
