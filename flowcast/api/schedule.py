"""Turns a production plan written in ordinary words into a fan schedule for the day.

A language model reads the plan and says, for each period, which items are running or
present. Flowcast then finds the lowest safe fan setting for each of those room states
and adds up the energy against running at today's setting all day.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from ..sim.spec import CaseSpec, Machine
from . import llm
from .explain import item_name
from .metrics import Assumptions, fan_power_kw

SYSTEM = """You turn a cleanroom's production plan for one day into a list of periods.
You are given the machines and the people in the room, each with a number, and the plan as the engineer wrote it.
Reply with one JSON object and nothing else, in this form:
{"periods": [{"start": "HH:MM", "end": "HH:MM", "label": "a few words", "machines_running": [numbers], "people_present": [numbers]}]}
Rules:
- "machines_running" holds only numbers from the machines list; "people_present" only numbers from the people list.
- Think about each separately. A machine can run with nobody in the room, and a person can be in with every machine off.
- An operator, technician, cleaner or crew member is a person. "Everyone" means every person; "all machines" means every machine.
- "The first machine" is the lowest-numbered machine; "one operator" is the lowest-numbered person.
- Periods must not overlap and together must cover the whole day from 00:00 to 24:00, in order. Use 24:00 for the end of the day.
- If the plan does not mention a time, the room is empty and every machine is off then."""

DEFAULT_PLAN = (
    "The room is empty overnight. The first operator arrives at 06:00 and starts the first machine. "
    "From 08:00 to 12:00 everyone is in and every machine runs. Lunch is 12:00 to 13:00: nobody is in the room "
    "but the machines keep running. The afternoon shift, 13:00 to 17:00, is one operator with one machine. "
    "Everything is switched off at 17:00."
)


def _minutes(text: str) -> int:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(text))
    if not match:
        raise ValueError(f"'{text}' is not a time")
    value = int(match.group(1)) * 60 + int(match.group(2))
    if not 0 <= value <= 24 * 60:
        raise ValueError(f"'{text}' is outside the day")
    return value


def parse_periods(reply: str, items: int) -> list[dict]:
    """Read the model's JSON and repair what can safely be repaired; reject the rest."""
    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("the plan could not be read")
    try:
        raw = json.loads(reply[start : end + 1])["periods"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("the plan could not be read") from error
    periods = []
    for entry in raw:
        a, b = _minutes(entry["start"]), _minutes(entry["end"])
        if b <= a:
            continue
        listed = [*entry.get("machines_running", []), *entry.get("people_present", []), *entry.get("on", [])]
        on = sorted({int(n) for n in listed if 1 <= int(n) <= items})
        periods.append({"start": a, "end": b, "label": str(entry.get("label", "")).strip()[:60], "on": on})
    periods.sort(key=lambda p: p["start"])
    filled, clock = [], 0
    for period in periods:
        if period["start"] > clock:  # a gap in the plan: the room is empty
            filled.append({"start": clock, "end": period["start"], "label": "Empty", "on": []})
        period["start"] = max(period["start"], clock)
        if period["end"] > period["start"]:
            filled.append(period)
            clock = period["end"]
    if clock < 24 * 60:
        filled.append({"start": clock, "end": 24 * 60, "label": "Empty", "on": []})
    return filled


def build(spec: CaseSpec, plan: str, rules, lowest_safe: Callable[[CaseSpec], tuple[float | None, int]]) -> dict:
    listing = {
        "machines": [{"number": i + 1, "what": item_name(m)} for i, m in enumerate(spec.machines) if m.kind != "person"],
        "people": [{"number": i + 1} for i, m in enumerate(spec.machines) if m.kind == "person"],
    }

    def readable(reply: dict) -> bool:
        try:
            return bool(parse_periods(reply.get("content") or "", len(spec.machines)))
        except (ValueError, KeyError, TypeError):
            return False

    message, model = llm.chat(
        [{"role": "system", "content": SYSTEM},
         {"role": "user", "content": f"Items in the room:\n{json.dumps(listing)}\n\nThe plan:\n{plan}"}],
        max_tokens=900, temperature=0.0, usable=readable,
    )
    periods = parse_periods(message.get("content") or "", len(spec.machines))

    people = {i + 1 for i, m in enumerate(spec.machines) if m.kind == "person"}
    settings: dict[tuple[int, ...], dict] = {}
    tested = 0
    for period in periods:
        key = tuple(period["on"])
        if key not in settings:
            machines = tuple(
                Machine(x=m.x, y=m.y, sx=m.sx, sy=m.sy, sz=m.sz, on=(i + 1) in key, emission=m.emission, kind=m.kind)
                for i, m in enumerate(spec.machines)
            )
            a = rules.assumptions(machines)
            best, count = lowest_safe(CaseSpec(machines=machines, ach=spec.ach, room=spec.room))
            tested += count
            ach = best if best is not None else spec.room.ach_range[1]
            settings[key] = {"ach": ach, "feasible": best is not None, "limit": a.particle_limit,
                             "state": "in operation" if key else "at rest"}
        period.update(settings[key], staffed=bool(people & set(key)), kind="plan")

    periods = _add_transitions(periods, rules)
    a = rules.assumptions(spec.machines)
    for period in periods:
        period["power_kw"] = fan_power_kw(period["ach"], a)
    hours = lambda p: (p["end"] - p["start"]) / 60
    used = sum(p["power_kw"] * hours(p) for p in periods)
    today = a.full_fan_power_kw * 24
    clock = lambda minutes: f"{minutes // 60:02d}:{minutes % 60:02d}"
    return {
        "periods": [{**p, "start": clock(p["start"]), "end": clock(p["end"]), "hours": hours(p)} for p in periods],
        "kwh_per_day": used,
        "kwh_per_day_today": today,
        "saving_percent": 100 * (1 - used / today),
        "saving_per_year": (today - used) * 365 * a.electricity_price,
        "room_states": len(settings),
        "settings_tested": tested,
        "today_ach": a.full_ach,
        "standard": rules.describe(spec.machines),
        "model": model,
        "hosted_on": llm.HOSTED_ON,
    }


def _add_transitions(periods: list[dict], rules) -> list[dict]:
    """Bring the fans up before staff arrive, and hold them up while the room cleans up after work.

    Before a staffed period the fans go to that period's setting early, by the lead time.
    When work stops, the regulation expects the room to return to its at-rest limit within a
    clean-up period, so the working setting is held for that long before the fans drop.
    """
    out: list[dict] = []
    for i, period in enumerate(periods):
        period = dict(period)
        previous = periods[i - 1] if i else None
        following = periods[i + 1] if i + 1 < len(periods) else None
        start, end = period["start"], period["end"]
        if previous and previous["on"] and not period["on"] and previous["ach"] > period["ach"]:
            hold = min(rules.cleanup_minutes, end - start)
            if hold > 0:
                out.append({**period, "end": start + hold, "ach": previous["ach"], "label": "Clean-up after work",
                            "kind": "clean-up", "feasible": True})
                start += hold
        lead = 0
        if following and following.get("staffed") and not period.get("staffed") and following["ach"] > period["ach"]:
            lead = min(rules.lead_minutes, end - start)
        if end - lead > start:
            out.append({**period, "start": start, "end": end - lead})
        if lead > 0:
            out.append({**period, "start": end - lead, "end": end, "ach": following["ach"], "label": "Fans up before staff arrive",
                        "kind": "lead", "feasible": True})
    return out
