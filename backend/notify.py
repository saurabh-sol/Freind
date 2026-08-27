"""
notify.py
---------
Sends an email to hotel staff whenever the agent successfully creates or
updates a booking hold. Handles two things the earlier version got wrong:
 
1. If a guest's party needs multiple rooms and the agent calls
   create_booking_hold several times in ONE turn, we combine all of them
   into a SINGLE email (not one email per room).
2. modify_booking_hold (upgrading an existing booking) sends a distinctly
   worded "Booking Updated" email showing before/after, instead of being
   treated as a brand new booking.
"""
 
import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
 
 
def _send_email(subject: str, body: str) -> bool:
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASSWORD")
    staff_email = os.environ.get("HOTEL_STAFF_EMAIL")
 
    if not all([smtp_user, smtp_pass, staff_email]):
        print("[notify.py] SMTP not configured -- skipping email, check .env")
        return False
 
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = staff_email
 
    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [staff_email], msg.as_string())
        return True
    except Exception as e:
        print(f"[notify.py] Failed to send email: {e}")
        return False
 
 
def _format_new_bookings_email(session_id: str, bookings: list) -> tuple:
    """One or more rooms booked together -> ONE combined email."""
    now = datetime.now().strftime('%d %b %Y, %I:%M %p')
    guest_name = bookings[0].get("guest_name", "Guest")
    room_count_label = f"{len(bookings)} room(s)" if len(bookings) > 1 else "1 room"
 
    lines = [f"New booking HOLD request via AI agent ({now})",
             f"Channel/session: {session_id}",
             f"Guest: {guest_name}",
             f"Rooms requested: {room_count_label}",
             ""]
    for i, b in enumerate(bookings, 1):
        lines.append(f"--- Room {i} ---")
        lines.append(f"Property:     {b.get('property_id', 'N/A')}")
        lines.append(f"Room Type:    {b.get('room_type', 'N/A')}")
        lines.append(f"Check-in:     {b.get('check_in', 'N/A')}")
        lines.append(f"Check-out:    {b.get('check_out', 'N/A')}")
        lines.append(f"Guests:       {b.get('num_guests', 'N/A')}")
        lines.append(f"Phone:        {b.get('phone_number', 'N/A')}")
        lines.append(f"Add-ons:      {b.get('add_ons', 'None')}")
        lines.append(f"Price:        INR {b.get('total_price_inr', 'N/A')}")
        lines.append(f"Hold ID:      {b.get('hold_id', 'N/A')}")
        lines.append("")
 
    lines.append("ACTION NEEDED: These are HOLDS, not confirmed bookings. Please "
                  "contact the guest to confirm availability and collect payment.")
 
    subject = f"New Booking Hold - {guest_name} ({room_count_label})"
    return subject, "\n".join(lines)
 
 
def _format_update_email(session_id: str, update: dict) -> tuple:
    """Guest upgraded/modified an EXISTING booking -- distinct from a new booking."""
    now = datetime.now().strftime('%d %b %Y, %I:%M %p')
    prev = update.get("previous", {})
    upd = update.get("updated", {})
 
    body = f"""Booking UPDATED via AI agent ({now})
Channel/session: {session_id}
Hold ID: {update.get('hold_id', 'N/A')}
 
BEFORE:
  Room:    {prev.get('room_type', 'N/A')}
  Guests:  {prev.get('num_guests', 'N/A')}
  Price:   INR {prev.get('total_price_inr', 'N/A')}
 
AFTER:
  Room:    {upd.get('room_type', 'N/A')}
  Guests:  {upd.get('num_guests', 'N/A')}
  Price:   INR {upd.get('total_price_inr', 'N/A')}
 
ACTION NEEDED: Please confirm the updated details and any price difference with the guest.
"""
    subject = f"Booking Updated - Hold {update.get('hold_id', 'N/A')}"
    return subject, body
 
 
def check_and_notify(session_id: str, trace: list) -> None:
    """Scans an agent turn's trace and sends exactly ONE email per logical
    action: one combined email for all new-booking holds created in this
    turn, and a separate email for each booking update. Call this after
    every run_agent_turn(), from any channel (web, WhatsApp, Telegram).
 
    NOTE: this previously checked for a "booking_reference" key that
    create_booking_hold/modify_booking_hold never actually returned (they
    return "hold_id") -- so this condition was always False and no email
    was EVER sent, silently. Fixed to match the real key."""
    new_bookings = []
    updates = []
 
    for entry in trace:
        result = entry.get("result", {}) or {}
        if entry.get("tool") == "create_booking_hold" and "hold_id" in result and "error" not in result:
            new_bookings.append({**entry["input"], **result})
        elif entry.get("tool") == "modify_booking_hold" and result.get("status") == "hold_updated":
            updates.append(result)
 
    if new_bookings:
        subject, body = _format_new_bookings_email(session_id, new_bookings)
        sent = _send_email(subject, body)
        print(f"[notify.py] New booking email {'sent' if sent else 'FAILED'} for session {session_id}")
 
    for update in updates:
        subject, body = _format_update_email(session_id, update)
        sent = _send_email(subject, body)
        print(f"[notify.py] Update email {'sent' if sent else 'FAILED'} for session {session_id}")
 
 
def send_booking_email(booking: dict) -> bool:
    """Kept for backward compatibility (e.g. direct single-booking calls)."""
    subject, body = _format_new_bookings_email(booking.get("session_id", "unknown"), [booking])
    return _send_email(subject, body)