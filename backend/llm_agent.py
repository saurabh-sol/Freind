"""
llm_agent.py
------------
This is the agent's "brain": the system prompt, the tool schemas, and the
AGENT LOOP that lets the model call multiple tools in sequence before
replying (e.g. update_guest_state -> search_properties -> check_availability
-> final natural-language response), which is what the assignment calls
"decide what is known, what is missing, whether to ask a question or use
a tool, and what should happen next."
 
Supports Claude (primary -- best tool-calling reliability) and Groq
(fallback/free option) behind one interface, same pattern as the earlier
WhatsApp project.
"""
 
import os
import json
import time
from datetime import datetime
from typing import List, Dict, Any
from dotenv import load_dotenv
 
load_dotenv()  # safeguard -- ensures MODEL_PROVIDER/API keys are available
                # even if this module gets imported before main.py's own
                # load_dotenv() call (load_dotenv() is safe to call multiple times).
 
import tools
from state import GuestState
 
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "groq")  # groq is default: free, fast, no rate-limit
                                                        # issues like Gemini's free tier had for us
MAX_TOOL_ITERATIONS = 5  # last iteration forces a text-only reply (see run_agent_turn),
                          # so the guest always gets SOME answer instead of a generic
                          # "taking too long" fallback
 
# ---------------------------------------------------------------------------
# Tool schemas -- session_id is deliberately NOT exposed to the model; it's
# injected server-side when we execute the call. This stops the model from
# ever having to "know" or invent a session id.
# ---------------------------------------------------------------------------
TOOL_DEFS = [
    {
        "name": "update_guest_state",
        "description": (
            "Call this FIRST whenever the guest gives new or changed information "
            "(destination, dates, number of guests, budget, room preferences, "
            "amenities wanted, special requirements). Only pass the fields that "
            "are new or have changed -- do not repeat unchanged fields. This is "
            "the ONLY way guest information gets remembered."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "destination": {"type": "string"},
                "check_in": {"type": "string", "description": "YYYY-MM-DD"},
                "check_out": {"type": "string", "description": "YYYY-MM-DD"},
                "num_guests": {"type": "integer"},
                "budget_per_night_inr": {"type": "integer"},
                "room_preferences": {"type": "array", "items": {"type": "string"}},
                "amenities_wanted": {"type": "array", "items": {"type": "string"}},
                "special_requirements": {"type": "string"},
            },
        },
    },
    {
        "name": "search_properties",
        "description": "Search for properties/rooms matching the guest's known criteria. Use after enough state is known (at least destination or guests or budget).",
        "input_schema": {
            "type": "object",
            "properties": {
                "destination": {"type": "string"},
                "num_guests": {"type": "integer"},
                "budget_per_night_inr": {"type": "integer"},
                "room_preferences": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "check_availability",
        "description": "Check if a specific room type at a specific property is available for exact dates. ALWAYS call this before confirming a room is bookable.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_id": {"type": "string"},
                "room_type": {"type": "string"},
                "check_in": {"type": "string", "description": "YYYY-MM-DD"},
                "check_out": {"type": "string", "description": "YYYY-MM-DD"},
                "num_guests": {"type": "integer"},
            },
            "required": ["property_id", "room_type", "check_in", "check_out"],
        },
    },
    {
        "name": "get_room_details",
        "description": "Get full details (amenities, description, add-ons) for a specific room at a property. Use when the guest asks about specifics of a room/property.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_id": {"type": "string"},
                "room_type": {"type": "string"},
            },
            "required": ["property_id", "room_type"],
        },
    },
    {
        "name": "calculate_price",
        "description": "Calculate the exact total price for a stay, including any add-ons. NEVER calculate or estimate price yourself in text -- always call this tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_id": {"type": "string"},
                "room_type": {"type": "string"},
                "check_in": {"type": "string"},
                "check_out": {"type": "string"},
                "add_ons": {"type": "array", "items": {"type": "string"}},
                "num_guests": {"type": "integer"},
            },
            "required": ["property_id", "room_type", "check_in", "check_out"],
        },
    },
    {
        "name": "get_policy",
        "description": "Get cancellation, payment, pet, or ID-proof policy for a property.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_id": {"type": "string"},
                "policy_type": {"type": "string", "description": "e.g. cancellation, payment, pets, id_proof. Omit for all policies."},
            },
            "required": ["property_id"],
        },
    },
    {
        "name": "create_booking_hold",
        "description": "Create a temporary booking hold once the guest has confirmed they want to proceed with a specific room and has given their name and guest count. This does NOT finalize payment -- it reserves inventory and notifies staff. Do NOT use this to modify an existing booking -- use modify_booking_hold instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_id": {"type": "string"},
                "room_type": {"type": "string"},
                "check_in": {"type": "string"},
                "check_out": {"type": "string"},
                "guest_name": {"type": "string"},
                "num_guests": {"type": "integer"},
                "phone_number": {"type": "string"},
                "add_ons": {"type": "array", "items": {"type": "string"}},
                "guest_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Full name of EVERY guest staying in this room. REQUIRED "
                                    "whenever num_guests is more than 1 -- ask the guest for "
                                    "each person's name before calling this tool.",
                },
            },
            "required": ["property_id", "room_type", "check_in", "check_out", "guest_name", "num_guests"],
        },
    },
    {
        "name": "get_guest_bookings",
        "description": "Check whether this guest already has any existing booking holds. ALWAYS call this first when the guest mentions a previous booking, says things like 'upgrade my booking', 'change my reservation', 'I booked earlier', or references something they already booked.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "modify_booking_hold",
        "description": "Update an EXISTING booking hold (e.g. change guest count, room, or dates) instead of creating a duplicate new one. Only call this AFTER the guest has explicitly confirmed they want to modify their existing booking (not create a new one).",
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_reference": {"type": "string"},
                "room_type": {"type": "string"},
                "check_in": {"type": "string"},
                "check_out": {"type": "string"},
                "num_guests": {"type": "integer"},
                "add_ons": {"type": "array", "items": {"type": "string"}},
                "guest_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Full name of EVERY guest staying in this room. REQUIRED "
                                    "if num_guests is being changed to more than 1.",
                },
            },
            "required": ["booking_reference"],
        },
    },
]
 
TOOL_FUNCTIONS = {
    "update_guest_state": tools.update_guest_state,
    "search_properties": tools.search_properties,
    "check_availability": tools.check_availability,
    "get_room_details": tools.get_room_details,
    "calculate_price": tools.calculate_price,
    "get_policy": tools.get_policy,
    "create_booking_hold": tools.create_booking_hold,
    "get_guest_bookings": tools.get_guest_bookings,
    "modify_booking_hold": tools.modify_booking_hold,
}
 
 
def _dispatch_provider_call(history: list, system_prompt: str, allow_tools: bool = True) -> dict:
    if MODEL_PROVIDER == "groq":
        return _call_groq(history, system_prompt, allow_tools)
    elif MODEL_PROVIDER == "gemini":
        return _call_gemini(history, system_prompt, allow_tools)
    elif MODEL_PROVIDER == "openai":
        return _call_openai(history, system_prompt, allow_tools)
    return _call_claude(history, system_prompt, allow_tools)
 
 
def _call_provider_with_retry(history: list, system_prompt: str, max_retries: int = 2, allow_tools: bool = True) -> dict:
    """Free-tier APIs (Gemini, Groq) can hit rate limits (HTTP 429) under
    normal use, especially with our multi-step tool loop firing several
    calls per guest message. Retries with a short backoff before giving
    up, instead of surfacing a transient rate-limit as a hard failure."""
    result = {}
    for attempt in range(max_retries + 1):
        result = _dispatch_provider_call(history, system_prompt, allow_tools)
        error = result.get("error", "")
        is_rate_limit = "429" in error or "rate limit" in error.lower() or "too many requests" in error.lower()
        if is_rate_limit and attempt < max_retries:
            wait_seconds = 3 * (attempt + 1)  # 3s, then 6s
            print(f"[llm_agent.py] Rate limited, retrying in {wait_seconds}s (attempt {attempt + 1}/{max_retries})...")
            time.sleep(wait_seconds)
            continue
        return result
    return result
 
 
def build_system_prompt(state: GuestState) -> str:
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    return f"""You are Mira, a guest-facing hotel booking assistant for a hospitality platform \
covering multiple properties across India.
 
Today's date is: {today}
 
CURRENT KNOWN GUEST STATE (for your reference -- keep this updated via update_guest_state):
{json.dumps(state.to_dict(), indent=2)}
 
YOUR JOB:
- Understand the guest's request from natural language, however they phrase it.
- Whenever the guest gives new or CHANGED information, call update_guest_state FIRST,
  before anything else, with only the fields that are new/changed.
- When the guest uses a relative date ("next weekend", "in 3 days"), convert it to an
  exact YYYY-MM-DD date yourself using today's date above, then pass the exact date to
  update_guest_state and any other tool. Never pass relative date words into a tool.
- PAST DATES: never let a booking go through for a check-in date that has already passed.
  You are told today's exact date above -- use it. If check_availability or
  create_booking_hold comes back with error "check_in_date_in_past", do NOT retry with the
  same date -- tell the guest plainly that date has already passed and ask them for a
  future check-in date instead.
- Decide what is still missing, and either ask ONE clear question, or call the
  appropriate tool if you have enough information.
- EFFICIENCY: if you already know enough to call more than one tool (e.g. you
  just learned new state AND already have enough to search or check
  availability), call them together in the SAME turn rather than spreading
  them across multiple back-and-forth turns -- this keeps replies fast.
- Use search_properties once you know at least the destination or guest count or budget.
- ALWAYS call check_availability before telling the guest a room is available.
- NEVER calculate prices yourself -- always call calculate_price and report its result exactly.
- If a tool result says something is unavailable, or capacity is exceeded, explain this to
  the guest and offer the suggested alternatives from the tool result.
- If the guest asks about an attribute that is not present in a tool's result or the hotel
  data (e.g. "is the pool heated?"), say clearly that you don't have that information --
  NEVER guess or invent an answer. Offer to find out or suggest they ask on-site.
- Keep the conversation natural and conversational -- do not read out raw JSON or make it
  feel like a form. Move the conversation toward a booking, one step at a time.
- Only call create_booking_hold after the guest has clearly confirmed they want to proceed
  with a specific room, and you have their name and guest count.
- Never guarantee a booking is 100% final -- create_booking_hold only creates a hold;
  a human team member follows up to confirm payment.
- CRITICAL: whenever the guest changes any requirement (dates, guests, room, add-ons) AFTER
  you already gave a recommendation or price, you MUST call check_availability and/or
  calculate_price AGAIN with the new details before replying. NEVER reuse an earlier tool
  result or repeat an earlier price/availability answer after something has changed --
  always re-verify against the current state.
- If the guest asks something like "do you remember me?" or references earlier context,
  answer truthfully based on the actual current state shown above -- do not just say "yes"
  without checking it's actually still accurate.
- BOOKING CONTINUITY: if the guest mentions a previous booking in ANY way ("upgrade my
  booking", "change my reservation", "I already booked", "before checkout", etc.), call
  get_guest_bookings FIRST. If they have an existing hold, explicitly ask them to confirm:
  "Would you like to update your existing booking, or make a new separate one?" Only call
  modify_booking_hold (for updating) or create_booking_hold (for a genuinely new, separate
  booking) after they've clearly answered that question. NEVER silently create a new
  booking when they meant to upgrade an existing one, and never silently modify one when
  they wanted a new one.
- GUEST NAMES: whenever a room's num_guests is more than 1, you MUST ask the guest for the
  full name of every person staying in that room (not just the primary booker) BEFORE calling
  create_booking_hold or modify_booking_hold, and pass all of them in guest_names. If you call
  either tool without enough names, it will return error "guest_names_incomplete" instead of
  creating/updating the hold -- when that happens, ask the guest for the missing name(s) and
  call the tool again with the complete list. For a single-guest room this is not needed.
- MULTIPLE ROOMS IN ONE REQUEST: if the guest's party doesn't fit in one room and they agree
  to split into multiple rooms, you may call create_booking_hold multiple times (once per
  room) within the same turn -- the system automatically combines these into a single
  notification to staff, so you don't need to worry about sending duplicate messages.
- AFTER a successful create_booking_hold or modify_booking_hold, always tell the guest in
  your reply that their request has been sent to the hotel team, and include the hotel's
  contact phone number and email from the tool result's "hotel_contact" field, so they have
  a direct contact for reference. Always refer to the tool result's "booking_reference" as
  the "Booking Reference" (or "Reference No.") in your reply -- never call it a "Hold ID".
- MULTI-ROOM GUEST SPLIT: if the guest's party needs more than one room, YOU decide how many
  guests go in each room, and every create_booking_hold call's num_guests must add up EXACTLY
  to the guest's total party size in state -- never less, never more. After each
  create_booking_hold result, check the "_guest_count_check" field it returns:
  "guests_booked_so_far_this_turn" vs "target_total_guests". If "guests_still_unaccounted" is
  greater than 0, you are NOT done -- book another room (or correct the split) before replying.
  Do not tell the guest the booking is complete while guests_still_unaccounted > 0.
- FORMATTING (plain text only -- this is read in WhatsApp/Telegram/a plain chat UI):
  - NEVER use markdown bold or asterisks (no **text**), no markdown tables, no "#" headers.
    Do not wrap names in ** ** for emphasis -- just write the name plainly.
  - When presenting room/property options, put ONE fact per line, blank line between options:
    Goa Palm Villas - Private Pool Villa
    Rs 18,000/night
    Up to 4 guests
    Amenities: private pool, AC, WiFi
 
  - When confirming a booking hold (after create_booking_hold or modify_booking_hold), also
    put each fact on its own line -- do NOT cram Reference No / Total / add-ons onto one line
    with "|" separators. Use this shape, one block per room, blank line between rooms:
    Beachfront Suite #2 (new)
    Reference No: BK-260824-7F3A
    Total: Rs 26,100
    Add-ons: Airport Pickup, Breakfast
    Guests: Rohan Mehta, Priya Mehta
 
  - Keep it scannable -- short lines, no dense paragraphs, no asterisks anywhere.
"""
 
 
def _ensure_booking_confirmation_mentioned(final_text: str, trace: list) -> str:
    """Deterministic safety net. The model is INSTRUCTED to always mention a
    successful hold in its reply, but instructions aren't guarantees -- some
    provider responses come back empty or skip it. Rather than let the guest
    silently not know their booking went through, we check the trace ourselves:
    if a hold was created/updated this turn and its booking_reference isn't already
    present in the model's reply, we append a plain-text confirmation built directly
    from the tool result (same format rules: no markdown, one fact per line)."""
    new_holds = [t for t in trace if t.get("tool") == "create_booking_hold" and "booking_reference" in t.get("result", {})]
    updated_holds = [t for t in trace if t.get("tool") == "modify_booking_hold" and t.get("result", {}).get("status") == "hold_updated"]
 
    if not new_holds and not updated_holds:
        return final_text
 
    def _reference_of(entry):
        r = entry["result"]
        return r.get("booking_reference", "")
 
    all_refs = [_reference_of(h) for h in new_holds] + [_reference_of(h) for h in updated_holds]
    already_mentioned = any(ref and ref in final_text for ref in all_refs)
    if already_mentioned:
        return final_text
 
    lines = [final_text.strip()] if final_text.strip() else []
    if lines:
        lines.append("")
    lines.append("Just confirming -- your request has been sent to our team:")
    lines.append("")
 
    for h in new_holds:
        r = h["result"]
        lines.append(f"Reference No: {r.get('booking_reference', 'N/A')}")
        lines.append(f"Total: Rs {r.get('total_price_inr', 'N/A')}")
        guest_names = r.get("guest_names") or []
        if guest_names:
            lines.append(f"Guests: {', '.join(guest_names)}")
        contact = r.get("hotel_contact", {}) or {}
        if contact:
            lines.append(f"Contact: {contact.get('phone', 'N/A')} | {contact.get('email', 'N/A')}")
        lines.append("")
 
    for h in updated_holds:
        r = h["result"]
        upd = r.get("updated", {})
        lines.append(f"Reference No: {r.get('booking_reference', 'N/A')} (updated)")
        lines.append(f"New total: Rs {upd.get('total_price_inr', 'N/A')}")
        guest_names = upd.get("guest_names") or []
        if guest_names:
            lines.append(f"Guests: {', '.join(guest_names)}")
        contact = r.get("hotel_contact", {}) or {}
        if contact:
            lines.append(f"Contact: {contact.get('phone', 'N/A')} | {contact.get('email', 'N/A')}")
        lines.append("")
 
    lines.append("Our team will reach out shortly to confirm payment and finalize everything.")
    return "\n".join(lines)
 
 
def _execute_tool(session_id: str, name: str, tool_input: dict) -> dict:
    fn = TOOL_FUNCTIONS.get(name)
    if not fn:
        return {"error": f"Unknown tool: {name}"}
    # Inject session_id server-side for the tools that need it
    if name in ("update_guest_state", "create_booking_hold"):
        tool_input = {**tool_input, "session_id": session_id}
    try:
        return fn(**tool_input)
    except Exception as e:
        return {"error": f"Tool execution failed: {e}"}
 
 
def run_agent_turn(session_id: str, user_message: str) -> Dict[str, Any]:
    """Runs one full agent turn: may involve several tool calls before the
    final natural-language reply. Returns the reply plus a full trace of
    every tool call + result, for the UI's debug panel.
 
    Design note: `working` (the live tool-calling back-and-forth) is kept
    SEPARATE from what gets persisted to the database. Only the final
    plain-text exchange (user message + final reply) is saved for future
    turns. This avoids replaying provider-specific tool_use/tool_result
    formatting across turns -- some models (e.g. Groq's gpt-oss via its
    "Harmony" template) get confused re-parsing old tool-call structures
    from a prior turn. Since the guest state is always freshly re-injected
    into the system prompt every turn anyway, old tool-call plumbing isn't
    needed for correctness -- only the human-readable conversation is."""
    import db
    persisted_history = db.load_history(session_id)  # plain text turns only
    working = list(persisted_history)
    working.append({"role": "user", "content": user_message})
 
    trace = []
    final_text = ""
 
    for i in range(MAX_TOOL_ITERATIONS):
        state = db.load_state(session_id)
        system_prompt = build_system_prompt(state)
 
        # On the LAST allowed iteration, force a text-only reply (no tools)
        # so the model can't keep looping on tool calls and leave the guest
        # with nothing -- it must answer conversationally with whatever it
        # already knows.
        is_last_iteration = (i == MAX_TOOL_ITERATIONS - 1)
        result = _call_provider_with_retry(working, system_prompt, allow_tools=not is_last_iteration)
 
        if result.get("error"):
            trace.append({"type": "error", "message": result["error"]})
            final_text = "Sorry, I ran into an issue processing that. Could you try rephrasing?"
            break
 
        working.append({"role": "assistant", "content": result["raw_content"]})
 
        if not result["tool_calls"]:
            final_text = result["text"]
            break
 
        tool_results_for_history = []
        for call in result["tool_calls"]:
            tool_output = _execute_tool(session_id, call["name"], call["input"])
 
            # Deterministic guardrail (fixes the "2 guests -> 8 guests, but rooms
            # only add up to 5" bug): the LLM decides how to split a party across
            # multiple rooms, and that split-arithmetic is exactly the kind of thing
            # a model can get wrong. Rather than trust it silently, we count the
            # running total of guests committed across ALL create_booking_hold calls
            # made so far THIS turn and hand that number back to the model so it can
            # see, in the next iteration, whether the party is fully accounted for.
            if call["name"] == "create_booking_hold" and "booking_reference" in tool_output:
                prior_guests = sum(
                    t["input"].get("num_guests", 0) for t in trace
                    if t.get("tool") == "create_booking_hold" and "booking_reference" in t.get("result", {})
                )
                this_call_guests = call["input"].get("num_guests", 0) or 0
                running_total = prior_guests + this_call_guests
                target = state.num_guests or running_total
                tool_output["_guest_count_check"] = {
                    "guests_booked_so_far_this_turn": running_total,
                    "target_total_guests": target,
                    "guests_still_unaccounted": max(target - running_total, 0),
                }
 
            trace.append({"tool": call["name"], "input": call["input"], "result": tool_output})
            tool_results_for_history.append({
                "tool_use_id": call["id"],
                "name": call["name"],
                "output": tool_output,
            })
 
        working.append({"role": "user", "content": _format_tool_results(tool_results_for_history)})
    else:
        # Loop exhausted MAX_TOOL_ITERATIONS without a final text reply
        # (shouldn't normally happen now that the last iteration forces
        # text-only, but kept as a final safety net).
        if not final_text:
            final_text = "Sorry, that request is taking longer than expected. Could you try rephrasing or simplifying it?"
 
    # Deterministic guarantee (fixes "sometimes doesn't confirm the booking until
    # asked"): don't rely on the model to REMEMBER to mention a successful hold in
    # its final reply. If a booking was created/updated this turn but the reply
    # never actually mentions its booking_reference, append a plain-text confirmation built
    # straight from the tool result -- so the guest is never left without an answer.
    final_text = _ensure_booking_confirmation_mentioned(final_text, trace)
 
    # Persist ONLY the clean text exchange -- not the tool-call mechanics.
    persisted_history.append({"role": "user", "content": user_message})
    persisted_history.append({"role": "assistant", "content": final_text})
    db.save_history(session_id, persisted_history)
 
    final_state = db.load_state(session_id)
    return {"reply": final_text, "trace": trace, "state": final_state.to_dict()}
 
 
def _format_tool_results(tool_results: list):
    """Claude expects tool_result content blocks; we store them in a
    provider-neutral intermediate form and reformat per-provider inside the
    _call_* functions when needed. For simplicity here we standardize on
    Claude's format since Claude is the primary provider."""
    return [
        {"type": "tool_result", "tool_use_id": tr["tool_use_id"], "content": json.dumps(tr["output"])}
        for tr in tool_results
    ]
 
 
def _call_claude(history: list, system_prompt: str, allow_tools: bool = True) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    claude_model = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
 
    try:
        kwargs = dict(
            model=claude_model,
            max_tokens=800,
            temperature=0,
            system=system_prompt,
            messages=history,
        )
        if allow_tools:
            kwargs["tools"] = TOOL_DEFS
        resp = client.messages.create(**kwargs)
    except Exception as e:
        return {"error": str(e)}
 
    text_parts, tool_calls, raw_content = [], [], []
    for block in resp.content:
        if block.type == "text":
            text_parts.append(block.text)
            raw_content.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            tool_calls.append({"id": block.id, "name": block.name, "input": block.input})
            raw_content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
 
    return {"text": " ".join(text_parts).strip(), "tool_calls": tool_calls, "raw_content": raw_content}
 
 
def _call_groq(history: list, system_prompt: str, allow_tools: bool = True) -> dict:
    """Groq/OpenAI-compatible fallback. Note: tool-result formatting differs
    from Claude's, so history format is translated here for this provider."""
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url="https://api.groq.com/openai/v1")
 
    openai_tools = [{"type": "function", "function": {
        "name": t["name"], "description": t["description"], "parameters": t["input_schema"]
    }} for t in TOOL_DEFS]
 
    # Translate our Claude-style history into OpenAI-style messages
    oa_messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if isinstance(msg["content"], str):
            oa_messages.append({"role": msg["role"], "content": msg["content"]})
        elif isinstance(msg["content"], list):
            for block in msg["content"]:
                if block.get("type") == "text":
                    oa_messages.append({"role": msg["role"], "content": block["text"]})
                elif block.get("type") == "tool_result":
                    oa_messages.append({"role": "tool", "tool_call_id": block["tool_use_id"], "content": block["content"]})
                elif block.get("type") == "tool_use":
                    oa_messages.append({"role": "assistant", "content": None, "tool_calls": [{
                        "id": block["id"], "type": "function",
                        "function": {"name": block["name"], "arguments": json.dumps(block["input"])}
                    }]})
 
    try:
        kwargs = dict(model="openai/gpt-oss-20b", max_tokens=800, temperature=0, messages=oa_messages)
        if allow_tools:
            kwargs["tools"] = openai_tools
        resp = client.chat.completions.create(**kwargs)
    except Exception as e:
        return {"error": str(e)}
 
    choice = resp.choices[0].message
    tool_calls, raw_content = [], []
    if choice.tool_calls:
        for tc in choice.tool_calls:
            tool_input = json.loads(tc.function.arguments)
            tool_calls.append({"id": tc.id, "name": tc.function.name, "input": tool_input})
            raw_content.append({"type": "tool_use", "id": tc.id, "name": tc.function.name, "input": tool_input})
    text = choice.content or ""
    if text:
        raw_content.append({"type": "text", "text": text})
 
    return {"text": text.strip(), "tool_calls": tool_calls, "raw_content": raw_content}
 
 
def _call_openai(history: list, system_prompt: str, allow_tools: bool = True) -> dict:
    """Native OpenAI (ChatGPT) provider using the official OpenAI API.
    Uses the same OpenAI-style history translation as _call_groq."""
    from openai import OpenAI
    openai_model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
 
    openai_tools = [{"type": "function", "function": {
        "name": t["name"], "description": t["description"], "parameters": t["input_schema"]
    }} for t in TOOL_DEFS]
 
    # Translate Claude-style history to OpenAI-style messages
    oa_messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if isinstance(msg["content"], str):
            oa_messages.append({"role": msg["role"], "content": msg["content"]})
        elif isinstance(msg["content"], list):
            for block in msg["content"]:
                if block.get("type") == "text":
                    oa_messages.append({"role": msg["role"], "content": block["text"]})
                elif block.get("type") == "tool_result":
                    oa_messages.append({"role": "tool", "tool_call_id": block["tool_use_id"], "content": block["content"]})
                elif block.get("type") == "tool_use":
                    oa_messages.append({"role": "assistant", "content": None, "tool_calls": [{
                        "id": block["id"], "type": "function",
                        "function": {"name": block["name"], "arguments": json.dumps(block["input"])}
                    }]})
 
    try:
        kwargs = dict(model=openai_model, max_tokens=800, temperature=0, messages=oa_messages)
        if allow_tools:
            kwargs["tools"] = openai_tools
        resp = client.chat.completions.create(**kwargs)
    except Exception as e:
        return {"error": str(e)}
 
    choice = resp.choices[0].message
    tool_calls, raw_content = [], []
    if choice.tool_calls:
        for tc in choice.tool_calls:
            tool_input = json.loads(tc.function.arguments)
            tool_calls.append({"id": tc.id, "name": tc.function.name, "input": tool_input})
            raw_content.append({"type": "tool_use", "id": tc.id, "name": tc.function.name, "input": tool_input})
    text = choice.content or ""
    if text:
        raw_content.append({"type": "text", "text": text})
 
    return {"text": text.strip(), "tool_calls": tool_calls, "raw_content": raw_content}
 
 
def _call_gemini(history: list, system_prompt: str, allow_tools: bool = True) -> dict:
    """Gemini via plain REST (no extra SDK dependency needed -- we already
    use `requests` elsewhere in the project). Gemini's function-calling
    format differs from both Claude and OpenAI: tool calls don't carry an
    id, so we generate a synthetic one to keep our generic tool-execution
    loop working, and tool RESULTS need the tool's `name` (not an id), so
    we rebuild a tool_use_id -> name map from history on every call."""
    import requests as req
 
    model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    api_key = os.environ["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
 
    gemini_tools = [{"functionDeclarations": [
        {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}
        for t in TOOL_DEFS
    ]}]
 
    id_to_name = {}
    for msg in history:
        if isinstance(msg["content"], list):
            for block in msg["content"]:
                if block.get("type") == "tool_use":
                    id_to_name[block["id"]] = block["name"]
 
    contents = []
    for msg in history:
        role = "model" if msg["role"] == "assistant" else "user"
        if isinstance(msg["content"], str):
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        elif isinstance(msg["content"], list):
            parts = []
            for block in msg["content"]:
                if block.get("type") == "text":
                    parts.append({"text": block["text"]})
                elif block.get("type") == "tool_use":
                    parts.append({"functionCall": {"name": block["name"], "args": block["input"]}})
                elif block.get("type") == "tool_result":
                    name = id_to_name.get(block["tool_use_id"], "unknown_tool")
                    try:
                        response_obj = json.loads(block["content"])
                    except Exception:
                        response_obj = {"result": block["content"]}
                    parts.append({"functionResponse": {"name": name, "response": response_obj}})
            if parts:
                contents.append({"role": role, "parts": parts})
 
    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"temperature": 0, "maxOutputTokens": 800},
    }
    if allow_tools:
        body["tools"] = gemini_tools
 
    try:
        resp = req.post(url, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"error": str(e)}
 
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError):
        return {"error": f"Unexpected Gemini response: {data}"}
 
    text_parts, tool_calls, raw_content = [], [], []
    for i, part in enumerate(parts):
        if "text" in part:
            text_parts.append(part["text"])
            raw_content.append({"type": "text", "text": part["text"]})
        elif "functionCall" in part:
            fc = part["functionCall"]
            call_id = f"gemini_call_{i}_{fc['name']}"
            args = fc.get("args", {})
            tool_calls.append({"id": call_id, "name": fc["name"], "input": args})
            raw_content.append({"type": "tool_use", "id": call_id, "name": fc["name"], "input": args})
 
    return {"text": " ".join(text_parts).strip(), "tool_calls": tool_calls, "raw_content": raw_content}