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
You are given the items in the room, each with a number, and the plan as the engineer wrote it.
Reply with one JSON object and nothing else, in this form:
{"periods": [{"start": "HH:MM", "end": "HH:MM", "label": "a few words", "on": [item numbers]}]}
Rules:
- People are items too. "on" lists every machine that is running AND every person who is in the room in that
  period. Everything else is off or away. An operator, technician, cleaner or crew member is a person item.
- "Everyone" or "all operators" means every person item; "all machines" means every machine item.
- Periods must not overlap and together must cover the whole day from 00:00 to 24:00, in order. Use 24:00 for the end of the day.
- If the plan does not mention a time, the room is empty and every machine is off then.
- If the plan names a kind of item and there are several, use the lowest numbers first.
- Use only item numbers from the list."""

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
        on = sorted({int(n) for n in entry.get("on", []) if 1 <= int(n) <= items})
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


def build(spec: CaseSpec, plan: str, a: Assumptions, lowest_safe: Callable[[CaseSpec], tuple[float | None, int]]) -> dict:
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

    settings: dict[tuple[int, ...], dict] = {}
    tested = 0
    for period in periods:
        key = tuple(period["on"])
        if key not in settings:
            machines = tuple(
                Machine(x=m.x, y=m.y, sx=m.sx, sy=m.sy, sz=m.sz, on=(i + 1) in key, emission=m.emission, kind=m.kind)
                for i, m in enumerate(spec.machines)
            )
            best, count = lowest_safe(CaseSpec(machines=machines, ach=spec.ach, room=spec.room))
            tested += count
            ach = best if best is not None else spec.room.ach_range[1]
            settings[key] = {"ach": ach, "feasible": best is not None, "power_kw": fan_power_kw(ach, a)}
        period.update(settings[key])

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
        "model": model,
        "hosted_on": llm.HOSTED_ON,
    }
