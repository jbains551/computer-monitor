"""SQLite database setup and helper functions."""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).parent / "data" / "monitor.db"))


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                machine     TEXT NOT NULL,
                machine_type TEXT NOT NULL DEFAULT 'unknown',
                timestamp   REAL NOT NULL,
                system_json TEXT NOT NULL,
                security_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_machine
                ON snapshots(machine, timestamp DESC);

            CREATE TABLE IF NOT EXISTS alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                machine     TEXT NOT NULL,
                severity    TEXT NOT NULL,
                category    TEXT NOT NULL,
                message     TEXT NOT NULL,
                timestamp   REAL NOT NULL,
                acknowledged INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_alerts_machine
                ON alerts(machine, timestamp DESC);

            CREATE TABLE IF NOT EXISTS machines (
                name        TEXT PRIMARY KEY,
                machine_type TEXT NOT NULL DEFAULT 'unknown',
                last_seen   REAL NOT NULL,
                first_seen  REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS commands (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                machine     TEXT NOT NULL,
                command     TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                output      TEXT,
                created_at  REAL NOT NULL,
                started_at  REAL,
                completed_at REAL
            );

            CREATE INDEX IF NOT EXISTS idx_commands_machine
                ON commands(machine, status, created_at DESC);
        """)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def save_snapshot(machine: str, machine_type: str, timestamp: float,
                  system_data: dict, security_data: dict):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO snapshots (machine, machine_type, timestamp, system_json, security_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (machine, machine_type, timestamp,
             json.dumps(system_data), json.dumps(security_data)),
        )
        conn.execute(
            "INSERT INTO machines (name, machine_type, last_seen, first_seen) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET last_seen=excluded.last_seen, machine_type=excluded.machine_type",
            (machine, machine_type, timestamp, timestamp),
        )


def get_latest_snapshot(machine: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM snapshots WHERE machine=? ORDER BY timestamp DESC LIMIT 1",
            (machine,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "machine": row["machine"],
        "machine_type": row["machine_type"],
        "timestamp": row["timestamp"],
        "system": json.loads(row["system_json"]),
        "security": json.loads(row["security_json"]),
    }


def get_history(machine: str, hours: int = 24, limit: int = 100) -> list:
    cutoff = time.time() - hours * 3600
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, machine, machine_type, timestamp, system_json, security_json "
            "FROM snapshots WHERE machine=? AND timestamp>=? "
            "ORDER BY timestamp DESC LIMIT ?",
            (machine, cutoff, limit),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "machine": r["machine"],
            "timestamp": r["timestamp"],
            "system": json.loads(r["system_json"]),
            "security": json.loads(r["security_json"]),
        }
        for r in rows
    ]


def list_machines() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name, machine_type, last_seen, first_seen FROM machines ORDER BY name"
        ).fetchall()
    return [dict(r) for r in rows]


def alert_exists(machine: str, category: str, message: str) -> bool:
    """Return True if an identical alert already exists (acknowledged or not)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM alerts WHERE machine=? AND category=? AND message=? LIMIT 1",
            (machine, category, message),
        ).fetchone()
    return row is not None


def save_alert(machine: str, severity: str, category: str, message: str):
    if alert_exists(machine, category, message):
        return
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alerts (machine, severity, category, message, timestamp) VALUES (?,?,?,?,?)",
            (machine, severity, category, message, time.time()),
        )


def get_alerts(machine: str | None = None, limit: int = 50, unacked_only: bool = False) -> list:
    clauses = []
    params = []
    if machine:
        clauses.append("machine=?")
        params.append(machine)
    if unacked_only:
        clauses.append("acknowledged=0")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM alerts {where} ORDER BY timestamp DESC LIMIT ?", params
        ).fetchall()
    return [dict(r) for r in rows]


def acknowledge_alert(alert_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE alerts SET acknowledged=1 WHERE id=?", (alert_id,))


def queue_command(machine: str, command: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO commands (machine, command, status, created_at) VALUES (?,?,?,?)",
            (machine, command, "pending", time.time()),
        )
        return cur.lastrowid


def get_pending_commands(machine: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, command FROM commands WHERE machine=? AND status='pending' ORDER BY created_at ASC",
            (machine,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_command(command_id: int, status: str, output: str | None = None):
    now = time.time()
    if status == "running":
        with get_conn() as conn:
            conn.execute(
                "UPDATE commands SET status=?, started_at=? WHERE id=?",
                (status, now, command_id),
            )
    else:
        with get_conn() as conn:
            conn.execute(
                "UPDATE commands SET status=?, output=?, completed_at=? WHERE id=?",
                (status, output, now, command_id),
            )


def get_commands(machine: str, limit: int = 20) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM commands WHERE machine=? ORDER BY created_at DESC LIMIT ?",
            (machine, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def purge_old_snapshots(days: int = 30):
    cutoff = time.time() - days * 86400
    with get_conn() as conn:
        conn.execute("DELETE FROM snapshots WHERE timestamp<?", (cutoff,))
