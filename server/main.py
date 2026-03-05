"""
System Monitor — Central Server
FastAPI application that receives metrics from agents, stores them in SQLite,
and serves the dashboard + REST API.

Start:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

import os
import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import alerting
import database
from models import MetricSnapshot

API_KEY = os.environ.get("API_KEY", "change-me")
DASHBOARD_DIR = Path(__file__).parent.parent / "dashboard"

app = FastAPI(title="System Monitor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    database.init_db()
    # Purge snapshots older than 30 days on startup
    database.purge_old_snapshots(days=30)


# ── Auth ──────────────────────────────────────────────────────────────────────

def verify_api_key(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if token != API_KEY:
        raise HTTPException(403, "Invalid API key")


# ── Ingest ────────────────────────────────────────────────────────────────────

@app.post("/api/metrics", dependencies=[Depends(verify_api_key)])
def ingest_metrics(snapshot: MetricSnapshot):
    database.save_snapshot(
        machine=snapshot.machine_name,
        machine_type=snapshot.machine_type,
        timestamp=snapshot.timestamp,
        system_data=snapshot.system,
        security_data=snapshot.security,
    )
    alerting.evaluate_snapshot(snapshot.machine_name, snapshot.system, snapshot.security)
    return {"status": "ok", "machine": snapshot.machine_name}


# ── Query ─────────────────────────────────────────────────────────────────────

@app.get("/api/machines")
def list_machines():
    machines = database.list_machines()
    now = time.time()
    for m in machines:
        m["online"] = (now - m["last_seen"]) < alerting.OFFLINE_SECONDS
        m["last_seen_ago"] = int(now - m["last_seen"])
    return machines


@app.get("/api/machines/{machine}/latest")
def latest_snapshot(machine: str):
    snap = database.get_latest_snapshot(machine)
    if not snap:
        raise HTTPException(404, f"No data found for machine '{machine}'")
    snap["online"] = (time.time() - snap["timestamp"]) < alerting.OFFLINE_SECONDS
    return snap


@app.get("/api/machines/{machine}/history")
def snapshot_history(
    machine: str,
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(100, ge=1, le=500),
):
    return database.get_history(machine, hours=hours, limit=limit)


@app.get("/api/alerts")
def list_alerts(
    machine: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    unacked_only: bool = False,
):
    return database.get_alerts(machine=machine, limit=limit, unacked_only=unacked_only)


@app.post("/api/alerts/{alert_id}/acknowledge", dependencies=[Depends(verify_api_key)])
def acknowledge_alert(alert_id: int):
    database.acknowledge_alert(alert_id)
    return {"status": "ok"}


@app.get("/api/status")
def server_status():
    machines = database.list_machines()
    now = time.time()
    return {
        "status": "running",
        "machine_count": len(machines),
        "machines_online": sum(1 for m in machines if (now - m["last_seen"]) < alerting.OFFLINE_SECONDS),
        "server_time": now,
    }


# ── Dashboard static files ────────────────────────────────────────────────────

if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")

    @app.get("/")
    def serve_dashboard():
        return FileResponse(str(DASHBOARD_DIR / "index.html"))
