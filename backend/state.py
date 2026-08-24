"""
state.py
--------
Structured "GuestState" -- this is the explicit, inspectable record of what
the agent currently knows about the guest's request. It is updated ONLY via
the `update_guest_state` tool (see tools.py), never guessed or inferred
silently by the LLM in free text. This makes state changes auditable: every
change shows up as a visible tool call in the UI trace, satisfying the
assignment's "maintain context" and "update state, don't restart" requirements.

Design choice: state merges are PARTIAL updates. Calling update_guest_state
with only `num_guests=4` leaves destination/dates/budget untouched. This is
what makes "Actually make that 4 people and stay one more night" work
correctly -- the model only sends the fields that changed.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List


@dataclass
class GuestState:
    destination: Optional[str] = None
    check_in: Optional[str] = None          # ISO format YYYY-MM-DD
    check_out: Optional[str] = None         # ISO format YYYY-MM-DD
    num_guests: Optional[int] = None
    budget_per_night_inr: Optional[int] = None
    room_preferences: List[str] = field(default_factory=list)   # e.g. ["private pool"]
    amenities_wanted: List[str] = field(default_factory=list)   # e.g. ["AC", "WiFi"]
    special_requirements: Optional[str] = None
    selected_property_id: Optional[str] = None
    selected_room_type: Optional[str] = None
    add_ons: List[str] = field(default_factory=list)
    stage: str = "collecting"  # collecting -> recommended -> hold_created

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GuestState":
        if not d:
            return cls()
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def merge(self, updates: dict) -> None:
        """Partial update -- only overwrite fields that were actually provided
        (not None), so previously known info is never silently erased."""
        for key, value in updates.items():
            if key not in self.__dataclass_fields__:
                continue
            if value is None:
                continue
            if key in ("room_preferences", "amenities_wanted", "add_ons"):
                # Lists: merge (union) rather than overwrite, so "also add
                # breakfast" doesn't wipe out an earlier add-on.
                existing = set(getattr(self, key) or [])
                existing.update(value if isinstance(value, list) else [value])
                setattr(self, key, sorted(existing))
            else:
                setattr(self, key, value)

    def missing_fields(self) -> List[str]:
        """Used for quick debugging/logging -- what do we still not know?"""
        required = ["destination", "check_in", "check_out", "num_guests"]
        return [f for f in required if getattr(self, f) is None]
