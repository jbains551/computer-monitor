"""System metrics collector — CPU, RAM, disk, network, uptime."""

import platform
import time
import psutil


def collect() -> dict:
    cpu_times = psutil.cpu_times_percent(interval=1)
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()

    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total_gb": round(usage.total / 1e9, 2),
                "used_gb": round(usage.used / 1e9, 2),
                "free_gb": round(usage.free / 1e9, 2),
                "percent": usage.percent,
            })
        except PermissionError:
            continue

    net_io = psutil.net_io_counters()
    net_interfaces = {}
    for iface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family.name in ("AF_INET", "AF_INET6"):
                net_interfaces[iface] = addr.address
                break

    boot_time = psutil.boot_time()
    uptime_seconds = int(time.time() - boot_time)

    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "hostname": platform.node(),
        "architecture": platform.machine(),
        "uptime_seconds": uptime_seconds,
        "cpu": {
            "count_physical": psutil.cpu_count(logical=False),
            "count_logical": psutil.cpu_count(logical=True),
            "percent": psutil.cpu_percent(interval=None),
            "frequency_mhz": psutil.cpu_freq().current if psutil.cpu_freq() else None,
            "user": cpu_times.user,
            "system": cpu_times.system,
            "idle": cpu_times.idle,
        },
        "memory": {
            "total_gb": round(vm.total / 1e9, 2),
            "available_gb": round(vm.available / 1e9, 2),
            "used_gb": round(vm.used / 1e9, 2),
            "percent": vm.percent,
            "swap_total_gb": round(swap.total / 1e9, 2),
            "swap_used_gb": round(swap.used / 1e9, 2),
            "swap_percent": swap.percent,
        },
        "disks": disks,
        "network": {
            "bytes_sent": net_io.bytes_sent,
            "bytes_recv": net_io.bytes_recv,
            "packets_sent": net_io.packets_sent,
            "packets_recv": net_io.packets_recv,
            "errin": net_io.errin,
            "errout": net_io.errout,
            "dropin": net_io.dropin,
            "dropout": net_io.dropout,
            "interfaces": net_interfaces,
        },
        "load_avg": list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else None,
    }
