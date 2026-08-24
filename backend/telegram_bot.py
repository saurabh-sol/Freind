"""
telegram_bot.py
----------------
Telegram channel adapter -- polling mode, no ngrok/public URL needed.
Reuses the exact same llm_agent.run_agent_turn() as the web demo and
WhatsApp webhook, so state/history land in the SAME database and show up
in the SAME /admin dashboard, just with a "telegram:" prefixed session_id.

Run this in its own terminal, alongside `uvicorn main:app`:
    python telegram_bot.py

Setup: message @BotFather on Telegram, /newbot, put the token in .env as
TELEGRAM_BOT_TOKEN=xxxxx
"""

import os
import time
from dotenv import load_dotenv

load_dotenv()

import requests
import llm_agent
import notify

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def send_message(chat_id: str, text: str) -> None:
    requests.post(f"{TELEGRAM_API}/sendMessage", json={"chat_id": chat_id, "text": text})


def run_polling_loop():
    print("Telegram bot running (polling mode, no ngrok needed). Ctrl+C to stop.")
    offset = None

    while True:
        try:
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset

            resp = requests.get(f"{TELEGRAM_API}/getUpdates", params=params, timeout=35)
            updates = resp.json().get("result", [])

            for update in updates:
                offset = update["update_id"] + 1

                message = update.get("message")
                if not message or "text" not in message:
                    continue

                chat_id = str(message["chat"]["id"])
                user_text = message["text"]
                session_id = f"telegram:{chat_id}"

                print(f"[{session_id}] {user_text}")
                result = llm_agent.run_agent_turn(session_id, user_text)

                # Print any errors from the trace so we can actually see
                # what's failing in this terminal, instead of just getting
                # the generic fallback message.
                for entry in result.get("trace", []):
                    if entry.get("type") == "error":
                        print(f"[telegram_bot.py] Agent error: {entry.get('message')}")

                notify.check_and_notify(session_id, result["trace"])
                send_message(chat_id, result["reply"])

        except Exception as e:
            print(f"[telegram_bot.py] Polling error: {e}")
            time.sleep(3)


if __name__ == "__main__":
    run_polling_loop()
