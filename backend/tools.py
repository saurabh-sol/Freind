"""
tools.py
--------
All tools are plain, deterministic Python functions. The LLM decides WHEN
to call them and WITH WHAT arguments, but the actual logic (price math,
availability counting, capacity checks) runs in code -- never guessed by
the model. This directly satisfies the assignment's requirement:
"Pricing calculations should be handled through deterministic application
logic where possible."
 
Each tool returns a plain dict. These dicts are what the agent sees as the
"tool result" and what the UI trace panel displays.
"""
 
import json
import os
import uuid
from datetime import datetime, date
from typing import Optional, List
 
import db
 
with open(os.path.join(os.path.dirname(__file__), "hotel_data.json"), encoding="utf-8") as f:
    HOTEL_DATA = json.load(f)
 
PROPERTIES = {p["property_id"]: p for p in HOTEL_DATA["properties"]}
 
 
def _find_room(property_id: str, room_type: str) -> Optional[dict]:
    prop = PROPERTIES.get(property_id)
    if not prop:
        return None
    for room in prop["rooms"]:
        if room["room_type"].lower() == room_type.lower():
            return room
    return None
 
 
def _nights(check_in: str, check_out: str) -> int:
    d1 = datetime.strptime(check_in, "%Y-%m-%d").date()
    d2 = datetime.strptime(check_out, "%Y-%m-%d").date()
    return max((d2 - d1).days, 0)
 
 
def _is_past_date(d: str) -> bool:
    """Deterministic past-date check -- never trust the model's own date
    arithmetic for this. Returns True if `d` (YYYY-MM-DD) is strictly
    before today's actual server date."""
    try:
        parsed = datetime.strptime(d, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False  # malformed dates are reported elsewhere, not here
    return parsed < date.today()
 
 
def _generate_booking_reference() -> str:
    """Human-friendly booking reference instead of a raw UUID, e.g.
    BK-260824-7F3A (BK + YYMMDD + 4-char random suffix). Kept short enough
    to read aloud/type but still effectively unique for this demo's scale."""
    date_part = datetime.now().strftime("%y%m%d")
    suffix = uuid.uuid4().hex[:4].upper()
    return f"BK-{date_part}-{suffix}"
 
 
# ---------------------------------------------------------------------------
# TOOL 1: update_guest_state
# ---------------------------------------------------------------------------
def update_guest_state(session_id: str, **fields) -> dict:
    """Merges any provided fields into the guest's stored state. This is
    the ONLY way state changes -- makes every update visible in the trace."""
    state = db.load_state(session_id)
    state.merge(fields)
    db.save_state(session_id, state)
    return {"status": "updated", "current_state": state.to_dict()}
 
 
# ---------------------------------------------------------------------------
# TOOL 2: search_properties
# ---------------------------------------------------------------------------
def search_properties(destination: Optional[str] = None,
                       num_guests: Optional[int] = None,
                       budget_per_night_inr: Optional[int] = None,
                       room_preferences: Optional[List[str]] = None) -> dict:
    """Returns properties/rooms matching the guest's stated criteria.
    Matching is deterministic: destination substring match, capacity >=
    guests, price <= budget, preference keywords checked against amenities."""
    room_preferences = room_preferences or []
    matches = []
 
    for prop in HOTEL_DATA["properties"]:
        if destination and destination.lower() not in prop["location"].lower() \
                and destination.lower() not in prop["name"].lower():
            continue
 
        for room in prop["rooms"]:
            if num_guests and room["capacity"] < num_guests:
                continue
            if budget_per_night_inr and room["price_per_night_inr"] > budget_per_night_inr:
                continue
            if room_preferences:
                amenities_lower = [a.lower() for a in room["amenities"]]
                if not all(any(pref.lower() in a for a in amenities_lower) for pref in room_preferences):
                    continue
 
            matches.append({
                "property_id": prop["property_id"],
                "property_name": prop["name"],
                "location": prop["location"],
                "room_type": room["room_type"],
                "capacity": room["capacity"],
                "price_per_night_inr": room["price_per_night_inr"],
                "amenities": room["amenities"],
            })
 
    return {"match_count": len(matches), "matches": matches}
 
 
# ---------------------------------------------------------------------------
# TOOL 3: check_availability
# ---------------------------------------------------------------------------
def check_availability(property_id: str, room_type: str,
                        check_in: str, check_out: str,
                        num_guests: Optional[int] = None) -> dict:
    """Checks real availability against existing holds, AND checks capacity.
    This is where the 'conflicting requirements' and 'no availability' edge
    cases are handled deterministically."""
    room = _find_room(property_id, room_type)
    if not room:
        return {"error": f"No room type '{room_type}' found at property '{property_id}'."}
 
    # Deterministic past-date guard -- do NOT rely on the model to notice a
    # stale/past date on its own. Checked here (not just in create_booking_hold)
    # so both create_booking_hold AND modify_booking_hold get this for free,
    # since both call check_availability before touching a hold.
    if _is_past_date(check_in):
        return {
            "available": False,
            "error": "check_in_date_in_past",
            "reason": f"The check-in date {check_in} has already passed -- today's date is "
                      f"{date.today().isoformat()}. Please ask the guest for a future check-in date.",
        }
 
    if num_guests and num_guests > room["capacity"]:
        # Edge case: conflicting requirements (too many guests for this room)
        alternatives = search_properties(num_guests=num_guests)
        return {
            "available": False,
            "reason": f"This room type has a maximum capacity of {room['capacity']}, "
                      f"but {num_guests} guests were requested.",
            "suggested_alternatives": alternatives["matches"][:3],
        }
 
    nights = _nights(check_in, check_out)
    if nights <= 0:
        return {"error": "check_out date must be after check_in date."}
 
    held_count = db.count_overlapping_holds(property_id, room_type, check_in, check_out)
    rooms_left = room["total_rooms"] - held_count
 
    if rooms_left <= 0:
        # Edge case: no availability -- suggest best alternative deterministically
        prop = PROPERTIES[property_id]
        alternatives = []
        for alt_room in prop["rooms"]:
            if alt_room["room_type"] == room_type:
                continue
            alt_held = db.count_overlapping_holds(property_id, alt_room["room_type"], check_in, check_out)
            if alt_room["total_rooms"] - alt_held > 0:
                alternatives.append({
                    "room_type": alt_room["room_type"],
                    "price_per_night_inr": alt_room["price_per_night_inr"],
                    "capacity": alt_room["capacity"],
                })
        return {
            "available": False,
            "reason": f"{room_type} is fully booked for these dates at {prop['name']}.",
            "suggested_alternatives_same_property": alternatives,
        }
 
    return {
        "available": True,
        "rooms_left": rooms_left,
        "nights": nights,
    }
 
 
# ---------------------------------------------------------------------------
# TOOL 4: get_room_details
# ---------------------------------------------------------------------------
def get_room_details(property_id: str, room_type: str) -> dict:
    """Returns full details for a specific room. If the guest asks about
    an attribute not present in this data (e.g. 'is the pool heated?'),
    the agent must say it doesn't have that information -- it is NOT here."""
    prop = PROPERTIES.get(property_id)
    if not prop:
        return {"error": f"No property '{property_id}' found."}
    room = _find_room(property_id, room_type)
    if not room:
        return {"error": f"No room type '{room_type}' found at '{prop['name']}'."}
 
    return {
        "property_name": prop["name"],
        "location": prop["location"],
        "description": prop["description"],
        "check_in_time": prop["check_in_time"],
        "check_out_time": prop["check_out_time"],
        "room": room,
        "available_add_ons": prop["add_ons"],
    }
 
 
# ---------------------------------------------------------------------------
# TOOL 5: calculate_price
# ---------------------------------------------------------------------------
def calculate_price(property_id: str, room_type: str, check_in: str, check_out: str,
                     add_ons: Optional[List[str]] = None, num_guests: Optional[int] = None) -> dict:
    """100% deterministic arithmetic -- the LLM never computes this itself,
    it only calls this tool and reports the result."""
    room = _find_room(property_id, room_type)
    if not room:
        return {"error": f"No room type '{room_type}' found."}
 
    nights = _nights(check_in, check_out)
    if nights <= 0:
        return {"error": "check_out date must be after check_in date."}
 
    room_total = room["price_per_night_inr"] * nights
 
    add_ons = add_ons or []
    prop = PROPERTIES[property_id]
    add_on_catalog = {a["name"].lower(): a["price_inr"] for a in prop["add_ons"]}
    add_on_total = 0
    add_on_breakdown = []
    for requested in add_ons:
        for name_lower, price in add_on_catalog.items():
            if requested.lower() in name_lower:
                multiplier = num_guests if ("per person" in name_lower and num_guests) else 1
                cost = price * multiplier * (nights if "day" in name_lower else 1)
                add_on_total += cost
                add_on_breakdown.append({"add_on": requested, "cost_inr": cost})
                break
 
    grand_total = room_total + add_on_total
 
    return {
        "nights": nights,
        "price_per_night_inr": room["price_per_night_inr"],
        "room_subtotal_inr": room_total,
        "add_ons_breakdown": add_on_breakdown,
        "add_ons_total_inr": add_on_total,
        "grand_total_inr": grand_total,
    }
 
 
# ---------------------------------------------------------------------------
# TOOL 6: get_policy
# ---------------------------------------------------------------------------
def get_policy(property_id: str, policy_type: Optional[str] = None) -> dict:
    """Returns policy text. If policy_type is unknown/unspecified, returns
    all policies for that property."""
    prop = PROPERTIES.get(property_id)
    if not prop:
        return {"error": f"No property '{property_id}' found."}
 
    if policy_type and policy_type.lower() in prop["policies"]:
        return {policy_type.lower(): prop["policies"][policy_type.lower()]}
    return {"policies": prop["policies"]}
 
 
# ---------------------------------------------------------------------------
# TOOL 7: create_booking_hold
# ---------------------------------------------------------------------------
def create_booking_hold(session_id: str, property_id: str, room_type: str,
                         check_in: str, check_out: str, guest_name: str,
                         num_guests: int, phone_number: Optional[str] = None,
                         add_ons: Optional[List[str]] = None,
                         guest_names: Optional[List[str]] = None) -> dict:
    """Creates a soft hold (not a final confirmed booking -- mirrors the
    human-in-the-loop principle: the AI reserves inventory and notifies
    staff, but a human confirms payment/final booking).
 
    guest_names: full name of EVERY guest staying in this room. Required
    when num_guests > 1 -- enforced deterministically below rather than
    trusting the model to remember to ask, since names are needed for the
    hotel's own ID-proof/check-in records."""
    availability = check_availability(property_id, room_type, check_in, check_out, num_guests)
    if not availability.get("available"):
        return {"error": "Cannot create hold -- room is not available.", "details": availability}
 
    guest_names = guest_names or []
    if num_guests and num_guests > 1:
        if len(guest_names) != num_guests:
            return {
                "error": "guest_names_incomplete",
                "reason": f"This room is for {num_guests} guests, but {len(guest_names)} name(s) "
                          f"were provided. Ask the guest for the full name of every person staying "
                          f"in this room, then call create_booking_hold again with all {num_guests} names.",
                "expected_count": num_guests,
                "received_count": len(guest_names),
            }
    elif not guest_names:
        # Single-guest room: the primary guest_name doubles as the guest list.
        guest_names = [guest_name]
 
    booking_reference = _generate_booking_reference()
    pricing = calculate_price(property_id, room_type, check_in, check_out, add_ons, num_guests)
 
    db.create_hold(
        hold_id=booking_reference, session_id=session_id, property_id=property_id,
        room_type=room_type, check_in=check_in, check_out=check_out,
        guest_name=guest_name, phone_number=phone_number, num_guests=num_guests,
        add_ons=add_ons or [], total_price_inr=pricing.get("grand_total_inr"),
        guest_names=guest_names,
    )
 
    state = db.load_state(session_id)
    state.merge({"stage": "hold_created", "selected_property_id": property_id, "selected_room_type": room_type})
    db.save_state(session_id, state)
 
    prop = PROPERTIES[property_id]
    return {
        "booking_reference": booking_reference,
        "status": "hold_created",
        "total_price_inr": pricing.get("grand_total_inr"),
        "hotel_contact": prop.get("contact", {}),
        "guest_names": guest_names,
        "note": "This is a temporary hold, not a final confirmed booking. Our team will reach out to confirm payment.",
    }
 
 
# ---------------------------------------------------------------------------
# TOOL 8: get_guest_bookings
# ---------------------------------------------------------------------------
def get_guest_bookings(session_id: str) -> dict:
    """Returns this guest's existing booking holds, if any. Call this
    whenever the guest references a previous booking (e.g. 'upgrade my
    booking', 'I booked earlier', 'change my reservation') BEFORE creating
    a new booking -- so the agent can ask whether to modify the existing
    one instead of accidentally creating a duplicate."""
    holds = db.get_holds_by_session(session_id)
    for h in holds:
        h["property_name"] = PROPERTIES.get(h["property_id"], {}).get("name", h["property_id"])
        h["booking_reference"] = h.pop("hold_id")
    return {"existing_bookings": holds, "count": len(holds)}
 
 
# ---------------------------------------------------------------------------
# TOOL 9: modify_booking_hold
# ---------------------------------------------------------------------------
def modify_booking_hold(session_id: str, booking_reference: str,
                         room_type: Optional[str] = None,
                         check_in: Optional[str] = None,
                         check_out: Optional[str] = None,
                         num_guests: Optional[int] = None,
                         add_ons: Optional[List[str]] = None,
                         guest_names: Optional[List[str]] = None) -> dict:
    """Updates an EXISTING hold (e.g. guest wants to upgrade from 4 to 8
    guests) instead of creating a duplicate new booking. Only call this
    after the guest has explicitly confirmed they want to modify their
    existing booking (use get_guest_bookings first, then ask them)."""
    existing = db.get_hold(booking_reference)
    if not existing:
        return {"error": f"No existing booking found with booking reference '{booking_reference}'."}
 
    new_room_type = room_type or existing["room_type"]
    new_check_in = check_in or existing["check_in"]
    new_check_out = check_out or existing["check_out"]
    new_guests = num_guests or existing["num_guests"]
 
    availability = check_availability(existing["property_id"], new_room_type,
                                       new_check_in, new_check_out, new_guests)
    if not availability.get("available"):
        return {"error": "Cannot upgrade -- new requirements are not available.", "details": availability}
 
    # Same deterministic guest-names guard as create_booking_hold: if the guest
    # count is changing (or growing past 1), every name must be accounted for.
    new_guest_names = guest_names if guest_names is not None else existing.get("guest_names") or []
    if new_guests and new_guests > 1:
        if len(new_guest_names) != new_guests:
            return {
                "error": "guest_names_incomplete",
                "reason": f"This room is now for {new_guests} guests, but {len(new_guest_names)} "
                          f"name(s) are on file. Ask the guest for the full name of every person "
                          f"staying in this room, then call modify_booking_hold again with all "
                          f"{new_guests} names.",
                "expected_count": new_guests,
                "received_count": len(new_guest_names),
            }
    elif not new_guest_names:
        new_guest_names = [existing["guest_name"]]
 
    pricing = calculate_price(existing["property_id"], new_room_type, new_check_in,
                               new_check_out, add_ons, new_guests)
 
    db.update_hold(booking_reference, room_type=new_room_type, check_in=new_check_in,
                    check_out=new_check_out, num_guests=new_guests,
                    total_price_inr=pricing.get("grand_total_inr"),
                    guest_names=new_guest_names)
 
    prop = PROPERTIES[existing["property_id"]]
    return {
        "booking_reference": booking_reference,
        "status": "hold_updated",
        "previous": {"room_type": existing["room_type"], "num_guests": existing["num_guests"],
                     "total_price_inr": existing["total_price_inr"]},
        "updated": {"room_type": new_room_type, "num_guests": new_guests,
                    "total_price_inr": pricing.get("grand_total_inr"), "guest_names": new_guest_names},
        "hotel_contact": prop.get("contact", {}),
        "note": "Booking updated. Our team will confirm the new details and any price difference.",
    }