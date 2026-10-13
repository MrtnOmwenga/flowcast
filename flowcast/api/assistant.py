"""An agent that carries out a typed request by operating Flowcast.

The language model never does the physics. It decides what to try; every number it reports
comes back from a tool, and every tool is the same code the interface calls.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from ..model.predict import Ensemble
from ..sim.sampling import CATALOGUE, INLET_CLEARANCE, PERSON
from ..sim.spec import CaseSpec, Machine, Room
from . import llm
from .explain import item_name
from .heat import COMPONENTS
from .metrics import Assumptions, fan_power_kw, summarise

MAX_STEPS = 10
MAX_CANDIDATES = 60

SYSTEM = """You operate Flowcast, a tool that predicts airflow and particle levels in a cleanroom, for the engineer
responsible for the room. Carry out the request by calling tools. You cannot see the room except through tools.

Rules:
- The current room is given with the request. Call `look` again only after you have changed something and need the full list.
- A question about what is possible ("what is the lowest...", "can I...") is answered by running the search, not by reasoning.
- Describe places in words relative to the walls and the other items ("near the return wall, beside the
  isolator"); never write coordinates or "x =", "y =" in your answer.
- Every number you state must come from a tool result. Never estimate or invent one.
- The room is {length} m long (x, measured from the return wall), {width} m wide (y) and {height} m high.
  Items stand on the floor; positions are of an item's corner nearest x = 0, y = 0, in steps of 0.2 m.
- The room is held to a cleanliness standard with two limits: a looser one "in operation" (anything running or
  anyone present) and a stricter one "at rest" (everything off and nobody in). `look` says which applies now.
- The particle limit applies at the worst point of the occupied zone. "Safe" means at least {margin}% under it.
- The site has a minimum fan setting; no search goes below it.
- When asked to save energy, the goal is the lowest safe fan setting; use `find_lowest_safe_fan`.
- Two items cannot share floor space, and nothing can be stacked on anything else. If a request is impossible,
  say why and suggest the nearest thing that is possible; do not keep retrying.
- If a tool returns an error, read it and try something else at most twice. Stop when the request is done.
- Your last message is shown to the engineer exactly as written. It must contain only the outcome: no reasoning,
  no checking aloud, no ticks or checklists, no repetition.
- Finish with a short plain answer (at most 90 words): what you did, the result with its figures, and anything
  the engineer should check. Plain sentences only: no headings, lists, bold or other markup. Reply in the
  language the request was written in."""

SYSTEM_CABINET = """You operate Flowcast, a tool that predicts airflow and air temperature in a fan-cooled control cabinet, for
the engineer who designs or maintains it. Carry out the request by calling tools. You cannot see the cabinet except through tools.

Rules:
- The current cabinet is given with the request. Call `look` again only after you have changed something and need the full list.
- A question about what is possible ("what is the lowest...", "can I...") is answered by running the search, not by reasoning.
- Describe places in words relative to the components and the ends of the cabinet ("near the bottom, beside the
  power supply"); never write coordinates or "x =", "y =" in your answer.
- Every number you state must come from a tool result. Never estimate or invent one.
- The cabinet is {length} m tall (x, measured up from the bottom, where a filter fan blows air in), {width} m wide (y)
  and {height} m deep. Components are mounted on the back plate; positions are of a component's lower corner nearest
  x = 0, y = 0, in steps of {step} m. The bottom {clearance} m, just above the fan, is kept clear. Warm air leaves at the top.
- The air around every component must stay under the components' temperature rating. `look` gives the rating, the
  temperature of the air drawn in and the hottest air now. "Safe" means the rise over the air drawn in is at least
  {margin}% under the allowed rise.
- When asked to save energy, reduce noise or reduce dust drawn in, the goal is the lowest safe fan airflow; use `find_lowest_safe_fan`.
- Two components cannot share plate space. If a request is impossible, say why and suggest the nearest thing
  that is possible; do not keep retrying.
- If a tool returns an error, read it and try something else at most twice. Stop when the request is done.
- Your last message is shown to the engineer exactly as written. It must contain only the outcome: no reasoning,
  no checking aloud, no ticks or checklists, no repetition.
- Finish with a short plain answer (at most 90 words): what you did, the result with its figures, and anything
  the engineer should check. Plain sentences only: no headings, lists, bold or other markup. Reply in the
  language the request was written in."""


def _tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
    }}


_ITEM = {"type": "integer", "description": "The item's number, as listed by `look`."}
KINDS = [*CATALOGUE, "person"]
COMPONENT_KINDS = list(COMPONENTS)
TOOLS = [
    _tool("look", "Describe the room: every item with its number, position and state, the fan setting, and the predicted result."),
    _tool("move_item", "Move an item to a new position on the floor.",
          {"item": _ITEM, "x": {"type": "number"}, "y": {"type": "number"}}, ["item", "x", "y"]),
    _tool("turn_item", "Turn an item by 90 degrees where it stands.", {"item": _ITEM}, ["item"]),
    _tool("set_running", "Switch a machine on or off, or mark a person present or away.",
          {"item": _ITEM, "on": {"type": "boolean"}}, ["item", "on"]),
    _tool("add_item", "Add an item to the room at a position.",
          {"what": {"type": "string", "enum": KINDS}, "x": {"type": "number"}, "y": {"type": "number"}}, ["what", "x", "y"]),
    _tool("remove_item", "Remove an item from the room.", {"item": _ITEM}, ["item"]),
    _tool("clear_room", "Remove every item, leaving an empty room to set up from scratch."),
    _tool("set_fan", "Set the fan, in air changes an hour.", {"air_changes_per_hour": {"type": "number"}}, ["air_changes_per_hour"]),
    _tool("find_lowest_safe_fan", "Search the fan settings for the lowest that is safe for the room as it stands, and set it."),
    _tool("find_best_position", "Try an item at many positions across the floor and move it to the one with the lowest "
          "particle level at the worst point. Returns the best three.", {"item": _ITEM}, ["item"]),
]


def tools_for(room: Room) -> list[dict]:
    """The cleanroom's tools, worded for a cabinet when the room is one."""
    if room.kind != "cabinet":
        return TOOLS
    words = {
        "look": _tool("look", "Describe the cabinet: every component with its number, position, heat and state, the fan airflow, and the predicted result."),
        "move_item": _tool("move_item", "Move a component to a new position on the mounting plate.",
                           {"item": _ITEM, "x": {"type": "number"}, "y": {"type": "number"}}, ["item", "x", "y"]),
        "turn_item": _tool("turn_item", "Turn a component by 90 degrees where it is mounted.", {"item": _ITEM}, ["item"]),
        "set_running": _tool("set_running", "Switch a component on or off.", {"item": _ITEM, "on": {"type": "boolean"}}, ["item", "on"]),
        "add_item": _tool("add_item", "Add a component to the mounting plate at a position.",
                          {"what": {"type": "string", "enum": COMPONENT_KINDS}, "x": {"type": "number"}, "y": {"type": "number"}}, ["what", "x", "y"]),
        "remove_item": _tool("remove_item", "Remove a component.", {"item": _ITEM}, ["item"]),
        "clear_room": _tool("clear_room", "Remove every component, leaving an empty plate to lay out from scratch."),
        "set_fan": _tool("set_fan", "Set the fan airflow, in cubic metres an hour.", {"airflow_m3_per_hour": {"type": "number"}}, ["airflow_m3_per_hour"]),
        "find_lowest_safe_fan": _tool("find_lowest_safe_fan", "Search the fan airflows for the lowest that is safe for the cabinet as it stands, and set it."),
        "find_best_position": _tool("find_best_position", "Try a component at many positions across the plate and move it to the one where the "
                                    "hottest air is coolest. Returns the best three.", {"item": _ITEM}, ["item"]),
    }
    return [words.get(t["function"]["name"], t) for t in TOOLS]


class Session:
    """The room as the agent is changing it, with the tools that act on it."""

    def __init__(self, machines: list[Machine], ach: float, room: Room, ensemble: Ensemble,
                 assume: Callable[[list[Machine]], Assumptions], lowest_safe: Callable[[CaseSpec], tuple[float | None, int]],
                 max_items: int, minimum_ach: float = 0.0, standard: str = "", ambient: float | None = None):
        self.machines = list(machines)
        self.ach = ach
        self.room = room
        self.ensemble = ensemble
        self.assume = assume
        self.lowest_safe = lowest_safe
        self.max_items = max_items
        self.minimum_ach = minimum_ach
        self.standard = standard
        self.ambient = ambient
        self.cabinet = room.kind == "cabinet"
        self.steps: list[dict] = []

    @property
    def a(self) -> Assumptions:
        """The limit and release rates that apply to the room as it stands: staffed or empty."""
        return self.assume(self.machines)

    def spec(self, machines: list[Machine] | None = None, ach: float | None = None) -> CaseSpec:
        spec = CaseSpec(machines=tuple(self.machines if machines is None else machines),
                        ach=self.ach if ach is None else ach, room=self.room)
        low, high = max(self.room.ach_range[0], self.minimum_ach), self.room.ach_range[1]
        if not low - 1e-6 <= spec.ach <= high + 1e-6:
            if self.cabinet:
                raise ValueError(f"the fan airflow must be between {self.airflow(low):.0f} and {self.airflow(high):.0f} cubic metres an hour")
            raise ValueError(f"the fan setting must be between {low:g} (the site minimum) and {high:g} air changes an hour")
        spec.validate()
        return spec

    def airflow(self, ach: float) -> float:
        """Cubic metres an hour for a fan setting in air changes an hour."""
        return ach * self.room.volume

    def result(self, spec: CaseSpec | None = None) -> dict:
        spec = spec or self.spec()
        p = self.ensemble.predict(spec)
        m = summarise(spec, p.fluid, p.particles, p.age, self.a)
        if self.cabinet:
            return {
                "hottest_air_c": round((self.ambient or 0) + m["worst_level"], 1),
                "rise_percent_of_allowed": round(100 * m["worst_level"] / self.a.particle_limit),
                "verdict": "safe" if m["safe"] else "within the rating but too close to call" if m["within_limit"] else "over the rating",
                "fan_airflow_m3_per_hour": round(self.airflow(spec.ach)),
                "fan_power_w": round(1000 * m["fan_power_kw"]),
            }
        return {
            "worst_point_percent_of_limit": round(100 * m["worst_level"] / self.a.particle_limit),
            "verdict": "safe" if m["safe"] else "within the limit but too close to call" if m["within_limit"] else "over the limit",
            "fan_setting": round(spec.ach, 1),
            "fan_power_kw": round(m["fan_power_kw"], 2),
            "stagnant_air_percent": round(100 * m["stagnant_fraction"], 1),
        }

    def _item(self, number: int) -> int:
        if not 1 <= number <= len(self.machines):
            raise ValueError(f"there is no item {number}; the room has {len(self.machines)} items")
        return number - 1

    def _check(self, machine: Machine, skip: int | None) -> None:
        """Refuse a placement in words the language model can act on."""
        name = item_name(machine)
        lx, ly = self.room.size[0], self.room.size[1]
        if self.cabinet and machine.x < INLET_CLEARANCE - 1e-9:
            raise ValueError(f"the bottom {INLET_CLEARANCE:g} m above the fan is kept clear; x must be at least {INLET_CLEARANCE:g}")
        if machine.x < 0 or machine.y < 0 or machine.x + machine.sx > lx + 1e-9 or machine.y + machine.sy > ly + 1e-9:
            raise ValueError(f"the {name} would be outside the room; x must be between 0 and {lx - machine.sx:.1f} "
                             f"and y between 0 and {ly - machine.sy:.1f}")
        for k, other in enumerate(self.machines):
            if k != skip and machine.box.overlaps(other.box):
                raise ValueError(f"that overlaps item {k + 1} (the {item_name(other)}), which occupies x {other.x:.1f} to "
                                 f"{other.x + other.sx:.1f} and y {other.y:.1f} to {other.y + other.sy:.1f}")

    def _replace(self, index: int, machine: Machine) -> None:
        self._check(machine, index)
        candidate = [*self.machines]
        candidate[index] = machine
        self.spec(candidate)
        self.machines = candidate

    # Tools. Each returns a small dictionary for the language model to read.

    def look(self) -> dict:
        if self.cabinet:
            from .heat import component_power

            items = [{
                "number": i + 1, "what": item_name(m), "x": m.x, "y": m.y, "length_x": m.sx, "width_y": m.sy,
                "heat_w": round(component_power(m)) if m.on else 0, "state": "on" if m.on else "off",
            } for i, m in enumerate(self.machines)]
            low, high = max(self.room.ach_range[0], self.minimum_ach), self.room.ach_range[1]
            return {"components": items, "result": self.result(), "rating": self.standard,
                    "air_drawn_in_c": self.ambient, "allowed_rise_c": self.a.particle_limit,
                    "fan_airflow_range_m3_per_hour": [round(self.airflow(low)), round(self.airflow(high))]}
        items = [{
            "number": i + 1, "what": item_name(m), "x": m.x, "y": m.y, "length_x": m.sx, "width_y": m.sy, "height": m.sz,
            "state": ("present" if m.on else "away") if m.kind == "person" else ("running" if m.on else "off"),
        } for i, m in enumerate(self.machines)]
        return {"items": items, "result": self.result(),
                "standard": self.standard, "state": "in operation" if any(m.on for m in self.machines) else "at rest",
                "particle_limit_per_m3": self.a.particle_limit,
                "fan_range": [max(self.room.ach_range[0], self.minimum_ach), self.room.ach_range[1]],
                "fan_setting_today": self.a.full_ach, "fan_power_today_kw": self.a.full_fan_power_kw}

    def move_item(self, item: int, x: float, y: float) -> dict:
        i = self._item(item)
        m = self.machines[i]
        self._replace(i, Machine(x=self.snap(x), y=self.snap(y), sx=m.sx, sy=m.sy, sz=m.sz, on=m.on, emission=m.emission, kind=m.kind))
        return {"moved": item_name(m), "to": [self.machines[i].x, self.machines[i].y], "result": self.result()}

    def turn_item(self, item: int) -> dict:
        i = self._item(item)
        m = self.machines[i]
        self._replace(i, Machine(x=m.x, y=m.y, sx=m.sy, sy=m.sx, sz=m.sz, on=m.on, emission=m.emission, kind=m.kind))
        return {"turned": item_name(m), "result": self.result()}

    def set_running(self, item: int, on: bool) -> dict:
        i = self._item(item)
        m = self.machines[i]
        self._replace(i, Machine(x=m.x, y=m.y, sx=m.sx, sy=m.sy, sz=m.sz, on=bool(on), emission=m.emission, kind=m.kind))
        return {"item": item_name(m), "on": bool(on), "result": self.result()}

    def add_item(self, what: str, x: float, y: float) -> dict:
        if len(self.machines) >= self.max_items:
            raise ValueError(f"the model was trained on rooms with at most {self.max_items} items")
        if self.cabinet:
            if what not in COMPONENTS:
                raise ValueError(f"unknown component; choose one of {COMPONENT_KINDS}")
            size, kind = COMPONENTS[what][0], "component"
        elif what == "person":
            if self.max_items <= 3:
                raise ValueError("this model was not trained on rooms with people")
            size, kind = PERSON, "person"
        elif what in CATALOGUE:
            size, kind = CATALOGUE[what], "machine"
        else:
            raise ValueError(f"unknown item; choose one of {KINDS}")
        new = Machine(x=self.snap(x), y=self.snap(y), sx=size[0], sy=size[1], sz=size[2], on=True, kind=kind)
        self._check(new, None)
        candidate = [*self.machines, new]
        self.spec(candidate)
        self.machines = candidate
        return {"added": what, "as_item": len(self.machines), "result": self.result()}

    def remove_item(self, item: int) -> dict:
        i = self._item(item)
        removed = item_name(self.machines.pop(i))
        return {"removed": removed, "note": "the remaining items have been renumbered", "result": self.result()}

    def clear_room(self) -> dict:
        removed = len(self.machines)
        self.machines = []
        return {"removed": removed, "result": self.result()}

    def set_fan(self, air_changes_per_hour: float | None = None, airflow_m3_per_hour: float | None = None) -> dict:
        if airflow_m3_per_hour is not None:
            air_changes_per_hour = float(airflow_m3_per_hour) / self.room.volume
        if air_changes_per_hour is None:
            raise ValueError("give the fan setting")
        self.spec(ach=float(air_changes_per_hour))
        self.ach = float(air_changes_per_hour)
        return {"result": self.result()}

    def find_lowest_safe_fan(self) -> dict:
        before = fan_power_kw(self.ach, self.a)
        best, tested = self.lowest_safe(self.spec())
        if best is None:
            top = f"{self.airflow(self.room.ach_range[1]):.0f} cubic metres an hour" if self.cabinet else f"{self.room.ach_range[1]:g}"
            return {"found": False, "note": f"no setting up to {top} is safe for this layout", "settings_tested": tested}
        self.ach = best
        after = fan_power_kw(best, self.a)
        if self.cabinet:
            return {"found": True, "lowest_safe_airflow_m3_per_hour": round(self.airflow(best)), "settings_tested": tested,
                    "fan_power_w": round(1000 * after), "fan_power_before_w": round(1000 * before),
                    "below_full_speed_power_percent": round(100 * (1 - after / self.a.full_fan_power_kw)),
                    "result": self.result()}
        return {"found": True, "lowest_safe_fan_setting": round(best, 1), "settings_tested": tested,
                "fan_power_kw": round(after, 2), "fan_power_before_kw": round(before, 2),
                "saving_against_today_percent": round(100 * (1 - after / self.a.full_fan_power_kw)),
                "result": self.result()}

    def find_best_position(self, item: int) -> dict:
        i = self._item(item)
        m = self.machines[i]
        step = 0.1 if self.cabinet else 0.4
        candidates = []
        x = INLET_CLEARANCE if self.cabinet else 0.0
        while x <= self.room.size[0] - m.sx + 1e-9:
            y = 0.0
            while y <= self.room.size[1] - m.sy + 1e-9:
                moved = Machine(x=self.snap(x), y=self.snap(y), sx=m.sx, sy=m.sy, sz=m.sz, on=m.on, emission=m.emission, kind=m.kind)
                layout = [*self.machines]
                layout[i] = moved
                try:
                    candidates.append((moved, self.spec(layout)))
                except ValueError:
                    pass
                y += step
            x += step
        if len(candidates) > MAX_CANDIDATES:  # keep an even spread across the floor
            stride = len(candidates) / MAX_CANDIDATES
            candidates = [candidates[int(k * stride)] for k in range(MAX_CANDIDATES)]
        scored = []
        for (moved, spec), p in zip(candidates, self.ensemble.predict_many([spec for _, spec in candidates])):
            worst = summarise(spec, p.fluid, p.particles, p.age, self.a)["worst_level"]
            scored.append((worst, moved))
        scored.sort(key=lambda pair: pair[0])
        self.machines[i] = scored[0][1]
        return {"item": item_name(m), "positions_tried": len(scored), "moved_to": [scored[0][1].x, scored[0][1].y],
                "best_three": [{"x": mm.x, "y": mm.y, "worst_point_percent_of_limit": round(100 * w / self.a.particle_limit)} for w, mm in scored[:3]],
                "worst_position_tried_percent_of_limit": round(100 * scored[-1][0] / self.a.particle_limit),
                "result": self.result()}

    def snap(self, value: float) -> float:
        """Positions move in whole cells, as in the simulations."""
        step = self.room.cell
        return round(round(float(value) / step) * step, 6)


_COORDINATES = re.compile(r"\s*(?:(?:at|to|from)\s+)?\(\s*(?:x\s*=\s*)?-?\d+(?:\.\d+)?\s*(?:m\s*)?,\s*(?:y\s*=\s*)?-?\d+(?:\.\d+)?\s*m?\s*\)")
MAX_REPLY_WORDS = 110


def tidy(reply: str) -> str:
    """Hold the final answer to its rules whichever model wrote it: no coordinates, said once."""
    reply = _COORDINATES.sub("", reply.strip())
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", reply) if p.strip()]
    # Weaker models sometimes give the answer and then give it again; keep the first telling.
    while len(paragraphs) > 1 and sum(len(p.split()) for p in paragraphs) > MAX_REPLY_WORDS:
        paragraphs.pop()
    return "\n\n".join(paragraphs)


def run(session: Session, conversation: list[dict]) -> dict:
    """Let the model work through the request, running each tool it asks for."""
    a = session.a
    size = dict(length=session.room.size[0], width=session.room.size[1], height=session.room.size[2], margin=round(100 * a.safety_margin))
    system = (SYSTEM_CABINET.format(**size, step=session.room.cell, clearance=INLET_CLEARANCE) if session.cabinet
              else SYSTEM.format(**size))
    tools = tools_for(session.room)
    # The agent always starts from the room as it is, so it cannot answer from guesswork.
    first = session.look()
    session.steps.append({"tool": "look", "arguments": {}, "outcome": first})
    messages = [{"role": "system", "content": system}, *conversation[:-1],
                {"role": "user", "content": conversation[-1]["content"] + "\n\nThe room now, from `look`:\n" + json.dumps(first)}]
    model = llm.model_name()
    for _ in range(MAX_STEPS):
        reply, model = llm.chat(messages, tools=tools, max_tokens=700)
        calls = reply.get("tool_calls") or []
        if not calls:
            return {"reply": tidy(reply.get("content") or ""), "steps": session.steps, "model": model}
        messages.append({"role": "assistant", "content": reply.get("content") or "", "tool_calls": calls})
        for call in calls:
            name = call["function"]["name"]
            arguments: dict = {}
            try:
                arguments = json.loads(call["function"].get("arguments") or "{}")
                if name not in {t["function"]["name"] for t in tools}:
                    raise ValueError(f"there is no tool called {name}")
                outcome = getattr(session, name)(**arguments)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                outcome = {"error": str(error)}
            session.steps.append({"tool": name, "arguments": arguments, "outcome": outcome})
            messages.append({"role": "tool", "tool_call_id": call.get("id", name), "content": json.dumps(outcome)})
    return {"reply": "I ran out of steps before finishing. The room shows what I had done so far.", "steps": session.steps,
            "model": model}
