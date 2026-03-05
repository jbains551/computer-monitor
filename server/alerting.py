"""Auto-alert generation from incoming snapshots."""

import time
from database import save_alert

# Thresholds (customize as desired)
CPU_WARN = 85.0
CPU_CRIT = 95.0
MEM_WARN = 85.0
MEM_CRIT = 95.0
DISK_WARN = 85.0
DISK_CRIT = 95.0
OFFLINE_SECONDS = 300   # 5 minutes without a heartbeat


def evaluate_snapshot(machine: str, system: dict, security: dict):
    """Generate alerts based on metrics in a snapshot.

    Messages are kept stable (no fluctuating numbers) so the dedup check in
    save_alert() correctly suppresses re-creation after a dismiss.
    """
    cpu = (system.get("cpu") or {}).get("percent", 0)
    if cpu >= CPU_CRIT:
        save_alert(machine, "critical", "health", f"CPU usage exceeds {CPU_CRIT}% threshold")
    elif cpu >= CPU_WARN:
        save_alert(machine, "warning", "health", f"CPU usage exceeds {CPU_WARN}% threshold")

    mem = (system.get("memory") or {}).get("percent", 0)
    if mem >= MEM_CRIT:
        save_alert(machine, "critical", "health", f"Memory usage exceeds {MEM_CRIT}% threshold")
    elif mem >= MEM_WARN:
        save_alert(machine, "warning", "health", f"Memory usage exceeds {MEM_WARN}% threshold")

    for disk in system.get("disks") or []:
        pct = disk.get("percent", 0)
        mp = disk.get("mountpoint", "?")
        if pct >= DISK_CRIT:
            save_alert(machine, "critical", "health", f"Disk {mp} exceeds {DISK_CRIT}% usage")
        elif pct >= DISK_WARN:
            save_alert(machine, "warning", "health", f"Disk {mp} exceeds {DISK_WARN}% usage")

    # Security alerts — these are naturally stable (same port/process = same message)
    flagged_ports = (security.get("ports") or {}).get("flagged") or []
    for fp in flagged_ports:
        save_alert(machine, "critical", "security",
                   f"Unusual port open: {fp.get('port')} ({fp.get('process')}) — {fp.get('reason')}")

    suspicious = security.get("suspicious_processes") or []
    for sp in suspicious:
        save_alert(machine, "critical", "security",
                   f"Suspicious process detected: {sp.get('name')} — {sp.get('reason')}")

    failed = security.get("failed_logins") or {}
    count = failed.get("count_24h", 0)
    if count >= 50:
        save_alert(machine, "critical", "security", "High volume of failed login attempts (50+) in last 24h")
    elif count >= 10:
        save_alert(machine, "warning", "security", "Elevated failed login attempts (10+) in last 24h")

    pkg = security.get("package_updates") or {}
    update_count = pkg.get("count", 0)
    if update_count >= 20:
        save_alert(machine, "warning", "security",
                   "20+ packages have updates available — may include security patches")
