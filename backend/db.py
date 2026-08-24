"""
db.py
-----
SQLite persistence for three things:
1. Per-session guest state (GuestState, JSON-serialized)
2. Per-session conversation history (for multi-turn context)
3. Booking holds (used to compute real-time availability)

SQLite is used deliberately (per the assignment's "JSON, SQLite, PostgreSQL,
or any simple storage" allowance) -- sufficient for a single-instance demo,
would be swapped for Postgres in a real multi-instance production deploy.
"""

import sqlite3
import json
import os
from datetime import datetime

from state import GuestState

DB_PATH = os.path.join(os.path.dirname(__file__), "assignment.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            history TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS holds (
            hold_id TEXT PRIMARY KEY,
            session_id TEXT,
            property_id TEXT,
            room_type TEXT,
            check_in TEXT,
            check_out TEXT,
            guest_name TEXT,
            phone_number TEXT,
            num_guests INTEGER,
            add_ons TEXT,
            total_price_inr INTEGER,
            created_at TEXT,
            guest_names TEXT
        )
    """)
    # Migration for databases created before guest_names existed --
    # CREATE TABLE IF NOT EXISTS won't add columns to an already-existing
    # table, so add it explicitly and ignore the error if it's already there.
    try:
        conn.execute("ALTER TABLE holds ADD COLUMN guest_names TEXT")
    except sqlite3.OperationalError:
        pass
    return conn


def load_state(session_id: str) -> GuestState:
    conn = _get_conn()
    row = conn.execute("SELECT state FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    if row:
        return GuestState.from_dict(json.loads(row[0]))
    return GuestState()


def save_state(session_id: str, state: GuestState) -> None:
    conn = _get_conn()
    existing = conn.execute("SELECT history FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    history = existing[0] if existing else "[]"
    conn.execute(
        """INSERT INTO sessions (session_id, state, history) VALUES (?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET state = excluded.state""",
        (session_id, json.dumps(state.to_dict()), history),
    )
    conn.commit()
    conn.close()


def load_history(session_id: str) -> list:
    conn = _get_conn()
    row = conn.execute("SELECT history FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    return json.loads(row[0]) if row else []


def save_history(session_id: str, history: list, max_turns: int = 24) -> None:
    """Keep only the last N messages -- otherwise every turn re-sends the
    ENTIRE conversation to the LLM, which gets progressively slower and
    more expensive as the conversation grows."""
    trimmed = history[-max_turns:]
    conn = _get_conn()
    existing = conn.execute("SELECT state FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    state_json = existing[0] if existing else json.dumps(GuestState().to_dict())
    conn.execute(
        """INSERT INTO sessions (session_id, state, history) VALUES (?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET history = excluded.history""",
        (session_id, state_json, json.dumps(trimmed)),
    )
    conn.commit()
    conn.close()


def count_overlapping_holds(property_id: str, room_type: str, check_in: str, check_out: str) -> int:
    """Counts how many existing holds overlap with the requested date range
    for this room type -- basic interval-overlap check."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT check_in, check_out FROM holds WHERE property_id = ? AND room_type = ?",
        (property_id, room_type),
    ).fetchall()
    conn.close()

    overlap_count = 0
    for existing_in, existing_out in rows:
        if check_in < existing_out and existing_in < check_out:  # standard interval overlap
            overlap_count += 1
    return overlap_count


def create_hold(hold_id, session_id, property_id, room_type, check_in, check_out,
                 guest_name, phone_number, num_guests, add_ons, total_price_inr,
                 guest_names=None) -> None:
    conn = _get_conn()
    conn.execute(
        """INSERT INTO holds (hold_id, session_id, property_id, room_type, check_in, check_out,
           guest_name, phone_number, num_guests, add_ons, total_price_inr, created_at, guest_names)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (hold_id, session_id, property_id, room_type, check_in, check_out, guest_name,
         phone_number, num_guests, json.dumps(add_ons), total_price_inr,
         datetime.now().isoformat(), json.dumps(guest_names or [])),
    )
    conn.commit()
    conn.close()


def get_holds_by_session(session_id: str) -> list:
    """All existing holds for this guest -- used when they reference a
    previous booking ('upgrade my booking', 'change my reservation')."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT hold_id, property_id, room_type, check_in, check_out, guest_name,
           num_guests, add_ons, total_price_inr, created_at, guest_names FROM holds
           WHERE session_id = ? ORDER BY created_at DESC""",
        (session_id,),
    ).fetchall()
    conn.close()
    cols = ["hold_id", "property_id", "room_type", "check_in", "check_out", "guest_name",
            "num_guests", "add_ons", "total_price_inr", "created_at", "guest_names"]
    results = [dict(zip(cols, row)) for row in rows]
    for r in results:
        r["guest_names"] = json.loads(r["guest_names"]) if r["guest_names"] else []
    return results


def get_hold(hold_id: str) -> dict:
    conn = _get_conn()
    row = conn.execute(
        """SELECT hold_id, property_id, room_type, check_in, check_out, guest_name,
           phone_number, num_guests, add_ons, total_price_inr, guest_names FROM holds WHERE hold_id = ?""",
        (hold_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    cols = ["hold_id", "property_id", "room_type", "check_in", "check_out", "guest_name",
            "phone_number", "num_guests", "add_ons", "total_price_inr", "guest_names"]
    result = dict(zip(cols, row))
    result["guest_names"] = json.loads(result["guest_names"]) if result["guest_names"] else []
    return result


def update_hold(hold_id: str, **fields) -> None:
    """Partial update of an existing hold -- used when upgrading/modifying
    a previous booking instead of creating a brand new one."""
    if not fields:
        return
    conn = _get_conn()
    keys = list(fields.keys())
    values = list(fields.values())
    for json_field in ("add_ons", "guest_names"):
        if json_field in fields:
            values[keys.index(json_field)] = json.dumps(values[keys.index(json_field)])
    set_clause = ", ".join(f"{k} = ?" for k in keys)
    conn.execute(f"UPDATE holds SET {set_clause} WHERE hold_id = ?", (*values, hold_id))
    conn.commit()
    conn.close()


def list_all_sessions() -> list:
    """For the admin view: every session that has at least one message,
    with a preview (last message + known destination) so staff can scan
    the list without opening each one."""
    conn = _get_conn()
    rows = conn.execute("SELECT session_id, state, history FROM sessions").fetchall()
    conn.close()

    sessions = []
    for session_id, state_json, history_json in rows:
        state = json.loads(state_json)
        history = json.loads(history_json)
        last_message = ""
        for msg in reversed(history):
            if isinstance(msg.get("content"), str):
                last_message = msg["content"]
                break
        sessions.append({
            "session_id": session_id,
            "destination": state.get("destination"),
            "stage": state.get("stage"),
            "message_count": len(history),
            "last_message": last_message[:80],
        })
    return sessions


def get_full_session(session_id: str) -> dict:
    """For the admin view: full conversation + current state for one session."""
    return {
        "session_id": session_id,
        "state": load_state(session_id).to_dict(),
        "history": load_history(session_id),
    }