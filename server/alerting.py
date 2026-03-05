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
    """Generate alerts based on metrics in a snapshot."""
    cpu = (system.get("cpu") or {}).get("percent", 0)
    if cpu >= CPU_CRIT:
        save_alert(machine, "critical", "health", f"CPU at {cpu:.1f}% (threshold: {CPU_CRIT}%)")
    elif cpu >= CPU_WARN:
        save_alert(machine, "warning", "health", f"CPU at {cpu:.1f}% (threshold: {CPU_WARN}%)")

    mem = (system.get("memory") or {}).get("percent", 0)
    if mem >= MEM_CRIT:
        save_alert(machine, "critical", "health", f"Memory at {mem:.1f}% (threshold: {MEM_CRIT}%)")
    elif mem >= MEM_WARN:
        save_alert(machine, "warning", "health", f"Memory at {mem:.1f}% (threshold: {MEM_WARN}%)")

    for disk in system.get("disks") or []:
        pct = disk.get("percent", 0)
        mp = disk.get("mountpoint", "?")
        if pct >= DISK_CRIT:
            save_alert(machine, "critical", "health", f"Disk {mp} at {pct:.1f}%")
        elif pct >= DISK_WARN:
            save_alert(machine, "warning", "health", f"Disk {mp} at {pct:.1f}%")

    # Security alerts
    flagged_ports = (security.get("ports") or {}).get("flagged") or []
    for fp in flagged_ports:
        save_alert(machine, "critical", "security",
                   f"Unusual port open: {fp.get('port')} ({fp.get('process')}) — {fp.get('reason')}")

    suspicious = security.get("suspicious_processes") or []
    for sp in suspicious:
        save_alert(machine, "critical", "security",
                   f"Suspicious process: {sp.get('name')} (PID {sp.get('pid')}) — {sp.get('reason')}")

    failed = security.get("failed_logins") or {}
    count = failed.get("count_24h", 0)
    if count >= 50:
        save_alert(machine, "critical", "security", f"{count} failed login attempts in last 24h")
    elif count >= 10:
        save_alert(machine, "warning", "security", f"{count} failed login attempts in last 24h")

    pkg = security.get("package_updates") or {}
    update_count = pkg.get("count", 0)
    if update_count >= 20:
        save_alert(machine, "warning", "security",
                   f"{update_count} packages have updates available — may include security patches")
