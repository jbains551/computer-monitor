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

# Well-known port → service description
KNOWN_SERVICES: dict[int, str] = {
    20:    "FTP (data)",
    21:    "FTP (control)",
    22:    "SSH",
    23:    "Telnet",
    25:    "SMTP",
    53:    "DNS",
    67:    "DHCP Server",
    68:    "DHCP Client",
    80:    "HTTP",
    88:    "Kerberos",
    110:   "POP3",
    111:   "RPC",
    123:   "NTP",
    135:   "MS-RPC",
    137:   "NetBIOS Name",
    138:   "NetBIOS Datagram",
    139:   "NetBIOS Session",
    143:   "IMAP",
    161:   "SNMP",
    389:   "LDAP",
    443:   "HTTPS",
    445:   "SMB / Windows File Sharing",
    512:   "rexec",
    513:   "rlogin",
    514:   "rsh / Syslog",
    548:   "AFP (Apple Filing Protocol)",
    587:   "SMTP (Submission)",
    631:   "CUPS / IPP Printing",
    993:   "IMAP over SSL",
    995:   "POP3 over SSL",
    1080:  "SOCKS Proxy",
    1194:  "OpenVPN",
    1433:  "Microsoft SQL Server",
    1521:  "Oracle Database",
    2049:  "NFS",
    2375:  "Docker (unencrypted)",
    2376:  "Docker TLS",
    3000:  "Dev server (common)",
    3283:  "Apple Remote Desktop",
    3306:  "MySQL / MariaDB",
    3389:  "RDP (Remote Desktop)",
    4000:  "Dev server (common)",
    5000:  "Dev server / AirPlay Receiver",
    5037:  "Android Debug Bridge (ADB)",
    5173:  "Vite dev server",
    5432:  "PostgreSQL",
    5900:  "VNC",
    6379:  "Redis",
    6667:  "IRC",
    7000:  "AirPlay / dev server",
    8000:  "HTTP dev server",
    8080:  "HTTP alt / proxy",
    8443:  "HTTPS alt",
    8888:  "Jupyter Notebook",
    9000:  "PHP-FPM / dev server",
    9090:  "Prometheus",
    9200:  "Elasticsearch HTTP",
    9300:  "Elasticsearch cluster",
    11211: "Memcached",
    27017: "MongoDB",
    27018: "MongoDB (shard)",
    27019: "MongoDB (config)",
    31337: "Back Orifice (malware)",
    50070: "Hadoop NameNode",
    58284: "rapportd (Apple continuity)",
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


def _full_process_name(pid: int | None) -> str | None:
    """Get the full executable name for a PID (handles lsof truncation)."""
    if not pid:
        return None
    try:
        return psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    # Fallback: ask ps directly
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=3,
        )
        name = result.stdout.strip()
        return name if name else None
    except Exception:
        return None


def _enrich_port_entry(entry: dict) -> dict:
    """Add service label and resolve full process name."""
    port = entry["port"]
    entry["service"] = KNOWN_SERVICES.get(port, "")
    full = _full_process_name(entry.get("pid"))
    if full:
        entry["process"] = full
    return entry


def _ports_via_lsof() -> list:
    """Parse listening ports from lsof — works on macOS/Linux without root."""
    result = subprocess.run(
        ["lsof", "-iTCP", "-sTCP:LISTEN", "-n", "-P"],
        capture_output=True, text=True, timeout=10,
    )
    seen = set()
    entries = []
    for line in result.stdout.splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) < 9:
            continue
        # NAME column is second-to-last; last is "(LISTEN)"
        name_field = parts[-2] if parts[-1] == "(LISTEN)" else parts[-1]
        if ":" not in name_field:
            continue
        addr, port_str = name_field.rsplit(":", 1)
        port_str = port_str.rstrip("(LISTEN)").strip()
        try:
            port = int(port_str)
        except ValueError:
            continue
        if port in seen:
            continue
        seen.add(port)
        entries.append({
            "port": port,
            "address": addr.strip("[]") or "*",
            "pid": int(parts[1]) if parts[1].isdigit() else None,
            "process": parts[0],
        })
    return entries


def _ports_via_netstat() -> list:
    """Parse listening ports from netstat — fallback for Linux without lsof."""
    result = subprocess.run(
        ["netstat", "-tlnp"],
        capture_output=True, text=True, timeout=10,
    )
    seen = set()
    entries = []
    for line in result.stdout.splitlines():
        if "LISTEN" not in line:
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        addr_port = parts[3]
        if ":" not in addr_port:
            continue
        port_str = addr_port.rsplit(":", 1)[-1]
        try:
            port = int(port_str)
        except ValueError:
            continue
        if port in seen:
            continue
        seen.add(port)
        proc = parts[-1] if "/" in parts[-1] else "unknown"
        pid_str, _, proc_name = proc.partition("/")
        entries.append({
            "port": port,
            "address": addr_port.rsplit(":", 1)[0],
            "pid": int(pid_str) if pid_str.isdigit() else None,
            "process": proc_name or "unknown",
        })
    return entries


def get_open_ports() -> dict:
    listening = []
    flagged = []
    established_count = 0

    # Try psutil first (works on Linux/Windows and macOS with root)
    try:
        conns = psutil.net_connections(kind="inet")
        for conn in conns:
            if conn.status == "LISTEN" and conn.laddr:
                port = conn.laddr.port
                try:
                    proc_name = psutil.Process(conn.pid).name() if conn.pid else "unknown"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    proc_name = "unknown"
                listening.append({
                    "port": port,
                    "address": conn.laddr.ip,
                    "pid": conn.pid,
                    "process": proc_name,
                })
            elif conn.status == "ESTABLISHED" and conn.raddr:
                established_count += 1

    except psutil.AccessDenied:
        # macOS without root — fall back to lsof then netstat
        try:
            listening = _ports_via_lsof()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            try:
                listening = _ports_via_netstat()
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

    # Deduplicate by port number, enrich with service label + full process name
    seen = set()
    unique = []
    for entry in listening:
        if entry["port"] not in seen:
            seen.add(entry["port"])
            unique.append(_enrich_port_entry(entry))
    listening = sorted(unique, key=lambda e: e["port"])

    for entry in listening:
        if entry["port"] in UNUSUAL_PORTS:
            flagged.append({**entry, "reason": f"Unusual listening port {entry['port']}"})

    return {
        "listening": listening,
        "established_count": established_count,
        "established": [],
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
