"""
main.py
-------
FastAPI backend for the assignment. Exposes a single /chat endpoint that
runs one full agent turn (see llm_agent.run_agent_turn) and returns the
reply plus a full trace (tool calls + results) and the current state --
exactly what the assignment asks the UI to display.

Run: uvicorn main:app --reload --port 8000
Then open frontend/index.html in a browser (it calls this API directly).
"""

import os
from dotenv import load_dotenv

load_dotenv()  # MUST run before importing llm_agent -- that module reads
                # MODEL_PROVIDER from the environment at import time.

from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

import llm_agent
import db
import notify

app = FastAPI(title="Mehman Assignment - Mira Hotel Booking Agent")

# ---------------------------------------------------------------------------
# CORS – list every origin that is allowed to call this API.
# Add your Vercel deployment URL (or set FRONTEND_URL env var on Render).
# ---------------------------------------------------------------------------
_frontend_url = os.getenv("FRONTEND_URL", "")  # e.g. https://my-app.vercel.app

ALLOWED_ORIGINS = [
    "http://localhost:5173",        # Vite dev server
    "http://localhost:8000",        # backend serving its own HTML in dev
    "https://freind.onrender.com",  # backend itself (same-origin requests)
]

# Accept any *.vercel.app preview URL automatically
import re as _re
_VERCEL_RE = _re.compile(r"https://[a-z0-9\-]+(\.vercel\.app)$", _re.I)

if _frontend_url:
    ALLOWED_ORIGINS.append(_frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://[a-z0-9\-]+(\.vercel\.app)$",
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str
    message: str


@app.post("/chat")
def chat(req: ChatRequest):
    result = llm_agent.run_agent_turn(req.session_id, req.message)
    notify.check_and_notify(req.session_id, result["trace"])
    return result


@app.post("/whatsapp")
async def whatsapp_webhook(From: str = Form(...), Body: str = Form(...)):
    """Twilio webhook -- same agent, same state/db, just a different
    channel. Session ID is prefixed so it's distinguishable in the admin
    dashboard from web-demo or Telegram sessions."""
    session_id = f"whatsapp:{From.replace('whatsapp:', '')}"
    result = llm_agent.run_agent_turn(session_id, Body)
    notify.check_and_notify(session_id, result["trace"])

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Message>{result['reply']}</Message></Response>"""
    return Response(content=twiml, media_type="application/xml")


@app.get("/state/{session_id}")
def get_state(session_id: str):
    state = db.load_state(session_id)
    return state.to_dict()


@app.get("/admin/sessions")
def admin_list_sessions():
    """Lists every guest conversation that has happened -- for staff/admin
    oversight, separate from any single guest's own chat window."""
    return db.list_all_sessions()


@app.get("/admin/sessions/{session_id}")
def admin_get_session(session_id: str):
    """Full transcript + current state for one guest conversation."""
    return db.get_full_session(session_id)


@app.post("/reset/{session_id}")
def reset_session(session_id: str):
    """Clears a session's state and history -- handy for re-running demo
    conversations from a clean slate."""
    conn = db._get_conn()
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
    return {"status": "reset"}


@app.get("/health")
def health():
    return {"status": "ok", "provider": llm_agent.MODEL_PROVIDER}


# Serve the frontend as static files so the whole thing runs from one command
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    def serve_frontend():
        return FileResponse(os.path.join(frontend_dir, "index.html"))

    @app.get("/admin")
    def serve_admin():
        return FileResponse(os.path.join(frontend_dir, "index.html"))
