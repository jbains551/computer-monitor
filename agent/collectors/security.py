"""Security collector — open ports, failed logins, suspicious processes, package checks."""

import os
import platform
import re
import subprocess
import time
from datetime import datetime, timedelta

import psutil

# Processes commonly associated with malware/RATs (expand as needed)
SUSPICIOUS_PROCESS_NAMES = {
    "nc", "ncat", "netcat", "nmap", "masscan", "msfconsole", "msfvenom",
    "mimikatz", "cobaltstrike", "beacon", "empire", "pupy", "backdoor",
    "cryptominer", "xmrig", "cgminer", "minerd",
}

# Ports that should never be open on a personal machine (customize as needed)
UNUSUAL_PORTS = {
    23,    # Telnet
    135,   # MSRPC
    137,   # NetBIOS
    138,   # NetBIOS
    139,   # NetBIOS
    445,   # SMB
    512,   # rexec
    513,   # rlogin
    514,   # rsh
    1080,  # SOCKS proxy
    3389,  # RDP
    5900,  # VNC
    6667,  # IRC (common C2)
    31337, # Back Orifice
}


def get_open_ports() -> dict:
    listening = []
    established = []
    flagged = []

    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == "LISTEN" and conn.laddr:
                port = conn.laddr.port
                try:
                    proc_name = psutil.Process(conn.pid).name() if conn.pid else "unknown"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    proc_name = "unknown"

                entry = {
                    "port": port,
                    "address": conn.laddr.ip,
                    "pid": conn.pid,
                    "process": proc_name,
                }
                listening.append(entry)
                if port in UNUSUAL_PORTS:
                    flagged.append({**entry, "reason": f"Unusual listening port {port}"})

            elif conn.status == "ESTABLISHED" and conn.raddr:
                try:
                    proc_name = psutil.Process(conn.pid).name() if conn.pid else "unknown"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    proc_name = "unknown"
                established.append({
                    "local": f"{conn.laddr.ip}:{conn.laddr.port}",
                    "remote": f"{conn.raddr.ip}:{conn.raddr.port}",
                    "pid": conn.pid,
                    "process": proc_name,
                })
    except psutil.AccessDenied:
        pass

    return {
        "listening": listening,
        "established_count": len(established),
        "established": established[:50],  # cap to avoid huge payloads
        "flagged": flagged,
    }


def get_suspicious_processes() -> list:
    found = []
    for proc in psutil.process_iter(["pid", "name", "username", "cmdline", "create_time"]):
        try:
            info = proc.info
            name_lower = (info.get("name") or "").lower()
            if name_lower in SUSPICIOUS_PROCESS_NAMES:
                found.append({
                    "pid": info["pid"],
                    "name": info["name"],
                    "username": info.get("username"),
                    "cmdline": " ".join(info.get("cmdline") or [])[:200],
                    "started": datetime.fromtimestamp(info["create_time"]).isoformat(),
                    "reason": "Name matches known suspicious process",
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def get_failed_logins() -> dict:
    system = platform.system()
    events = []
    count = 0

    if system == "Linux":
        log_paths = ["/var/log/auth.log", "/var/log/secure"]
        since = datetime.now() - timedelta(hours=24)
        pattern = re.compile(
            r"(\w+\s+\d+\s+\d+:\d+:\d+).*?(?:Failed password|Invalid user|authentication failure).*?(?:from\s+(\S+))?",
            re.IGNORECASE,
        )
        for path in log_paths:
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", errors="replace") as f:
                    for line in f:
                        m = pattern.search(line)
                        if m:
                            count += 1
                            if len(events) < 20:
                                events.append({
                                    "time": m.group(1),
                                    "source_ip": m.group(2) or "unknown",
                                    "raw": line.strip()[:200],
                                })
            except PermissionError:
                events.append({"error": f"Cannot read {path} — run agent as root for full access"})

    elif system == "Darwin":
        # macOS — use 'last' for failed logins; full auth log needs sudo
        try:
            result = subprocess.run(
                ["log", "show", "--predicate",
                 'process == "sshd" AND eventMessage CONTAINS "Failed"',
                 "--last", "24h", "--style", "syslog"],
                capture_output=True, text=True, timeout=10,
            )
            ip_pattern = re.compile(r"from\s+([\d.a-fA-F:]+)")
            for line in result.stdout.splitlines():
                count += 1
                ip_match = ip_pattern.search(line)
                if len(events) < 20:
                    events.append({
                        "time": line[:20],
                        "source_ip": ip_match.group(1) if ip_match else "unknown",
                        "raw": line.strip()[:200],
                    })
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    elif system == "Windows":
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-EventLog -LogName Security -InstanceId 4625 -Newest 50 | "
                 "Select-Object TimeGenerated,Message | ConvertTo-Json"],
                capture_output=True, text=True, timeout=15,
            )
            import json
            entries = json.loads(result.stdout or "[]")
            if isinstance(entries, dict):
                entries = [entries]
            for e in entries:
                count += 1
                if len(events) < 20:
                    events.append({
                        "time": e.get("TimeGenerated", ""),
                        "source_ip": "see message",
                        "raw": str(e.get("Message", ""))[:200],
                    })
        except Exception:
            pass

    return {"count_24h": count, "recent": events}


def get_package_updates() -> dict:
    system = platform.system()
    updates = []
    error = None

    try:
        if system == "Darwin":
            result = subprocess.run(
                ["brew", "outdated", "--json=v2"],
                capture_output=True, text=True, timeout=30,
            )
            import json
            data = json.loads(result.stdout or "{}")
            formulae = data.get("formulae", [])
            casks = data.get("casks", [])
            for pkg in formulae[:20]:
                updates.append({"name": pkg.get("name"), "type": "formula"})
            for pkg in casks[:20]:
                updates.append({"name": pkg.get("name"), "type": "cask"})

        elif system == "Linux":
            # Try apt first, then dnf/yum
            for cmd in [
                ["apt-get", "--simulate", "upgrade"],
                ["dnf", "check-update", "--quiet"],
            ]:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    lines = [l for l in result.stdout.splitlines() if l and not l.startswith("NOTE")]
                    updates = [{"name": l.split()[0], "type": "package"} for l in lines[:20] if l.split()]
                    break
                except FileNotFoundError:
                    continue

        elif system == "Windows":
            # Check winget
            result = subprocess.run(
                ["winget", "upgrade", "--include-unknown"],
                capture_output=True, text=True, timeout=30,
            )
            for line in result.stdout.splitlines()[3:]:
                parts = line.split()
                if len(parts) >= 2:
                    updates.append({"name": parts[0], "type": "winget"})
                if len(updates) >= 20:
                    break

    except Exception as e:
        error = str(e)

    return {"available_updates": updates, "count": len(updates), "error": error}


def collect() -> dict:
    return {
        "ports": get_open_ports(),
        "suspicious_processes": get_suspicious_processes(),
        "failed_logins": get_failed_logins(),
        "package_updates": get_package_updates(),
    }
