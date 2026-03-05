#!/usr/bin/env python3
"""
System Monitor Agent
Runs on each monitored machine. Collects system health and security metrics,
then posts them to the central server at a configurable interval.

Usage:
    python agent.py --config config.yaml
    python agent.py --config config.yaml --once   # single run, then exit
"""

import argparse
import json
import logging
import platform
import time
from pathlib import Path

import requests
import yaml

from collectors import security, system

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "server_url": "http://localhost:8000",
    "api_key": "change-me",
    "machine_name": platform.node(),
    "machine_type": "unknown",   # mac | pc | raspberry-pi
    "interval_seconds": 60,
    "timeout_seconds": 15,
}


def load_config(path: str) -> dict:
    cfg = DEFAULT_CONFIG.copy()
    p = Path(path)
    if p.exists():
        with open(p) as f:
            overrides = yaml.safe_load(f) or {}
        cfg.update(overrides)
    else:
        log.warning("Config file %s not found — using defaults", path)
    return cfg


def collect_snapshot(cfg: dict) -> dict:
    log.info("Collecting system metrics...")
    sys_data = system.collect()

    log.info("Collecting security data...")
    sec_data = security.collect()

    return {
        "machine_name": cfg["machine_name"],
        "machine_type": cfg["machine_type"],
        "timestamp": time.time(),
        "system": sys_data,
        "security": sec_data,
    }


def send_snapshot(snapshot: dict, cfg: dict) -> bool:
    url = f"{cfg['server_url'].rstrip('/')}/api/metrics"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, json=snapshot, headers=headers, timeout=cfg["timeout_seconds"])
        if resp.status_code == 200:
            log.info("Snapshot sent successfully (HTTP 200)")
            return True
        else:
            log.warning("Server returned %s: %s", resp.status_code, resp.text[:200])
            return False
    except requests.ConnectionError:
        log.error("Cannot reach server at %s — will retry next interval", cfg["server_url"])
        return False
    except requests.Timeout:
        log.error("Request timed out after %ss", cfg["timeout_seconds"])
        return False


def main():
    parser = argparse.ArgumentParser(description="System monitor agent")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print snapshot instead of sending")
    args = parser.parse_args()

    cfg = load_config(args.config)
    log.info("Agent starting — machine: %s (%s), server: %s, interval: %ss",
             cfg["machine_name"], cfg["machine_type"], cfg["server_url"], cfg["interval_seconds"])

    while True:
        try:
            snapshot = collect_snapshot(cfg)
            if args.dry_run:
                print(json.dumps(snapshot, indent=2, default=str))
            else:
                send_snapshot(snapshot, cfg)
        except Exception as e:
            log.exception("Unexpected error during collection: %s", e)

        if args.once:
            break

        log.info("Sleeping %ss until next collection...", cfg["interval_seconds"])
        time.sleep(cfg["interval_seconds"])


if __name__ == "__main__":
    main()
