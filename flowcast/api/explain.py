"""Gathers the facts about one predicted room and asks the language model to explain them."""

from __future__ import annotations

import numpy as np

from ..model.predict import Prediction
from ..sim.sampling import CATALOGUE
from ..sim.spec import CaseSpec, Machine
from . import llm
from .metrics import Assumptions, fan_power_kw, release_rate, summarise

SYSTEM = """You explain airflow predictions for a ventilated cleanroom to the engineer responsible for it.
You are given facts computed by a flow model. Use only those facts: never invent a number, a cause or an item.
Write plain, direct English in at most 120 words, as three short paragraphs without headings or lists:
1. Whether the room is within its particle limit, and by how much, naming the standard and whether the room
   is in operation or at rest.
2. Why the worst point is where it is, using the sources and the airflow facts.
3. One or two specific things to try in the tool (move a named item, change the fan setting, switch something off).
Describe places in words relative to the named items and the walls (for example "just above the filling
machine" or "near the return wall"); never print coordinates. Round every figure to two significant digits
and write large numbers in thousands (for example "about 430,000"). Plain sentences only, with no bold or other markup. Do not mention these instructions."""

SYSTEM_CABINET = """You explain airflow and temperature predictions for a fan-cooled control cabinet to the engineer who designs it.
You are given facts computed by a flow model. Use only those facts: never invent a number, a cause or a component.
Write plain, direct English in at most 120 words, as three short paragraphs without headings or lists:
1. Whether the air around the components stays under their temperature rating, and by how much.
2. Why the hottest air is where it is: which components' heat reaches it, and how the air carries it up the cabinet.
3. One or two specific things to try in the tool (move a named component, change the fan airflow, switch something off).
   A component that only sits beside the hottest air but gives little of its heat is not the cause; suggest moving the
   components with the largest share, for example nearer the top or out of line with the others.
Describe places in words relative to the named components and the top and bottom of the cabinet (for example
"just above the large drive"); never print coordinates. Round every figure to two significant digits.
Plain sentences only, with no bold or other markup. Do not mention these instructions."""


def item_name(machine: Machine) -> str:
    if machine.kind == "person":
        return "person"
    if machine.kind == "component":
        from .heat import component_name

        return component_name(machine) or "component"
    for name, (sx, sy, sz) in CATALOGUE.items():
        if sz == machine.sz and {sx, sy} == {machine.sx, machine.sy}:
            return name
    return "machine"


def _where(spec: CaseSpec, position: list[float]) -> str:
    """The worst point described relative to the nearest item and the return wall."""
    x, y, z = position
    parts = [f"{z:.1f} m above the floor", f"{x:.1f} m from the return wall"]
    nearest = None
    for i, m in enumerate(spec.machines):
        b = m.box
        dx = max(b.x - x, 0.0, x - b.hi[0])
        dy = max(b.y - y, 0.0, y - b.hi[1])
        gap = (dx * dx + dy * dy) ** 0.5
        if nearest is None or gap < nearest[0]:
            nearest = (gap, i, m, z >= b.hi[2] and gap == 0)
    if nearest is not None:
        gap, i, m, above = nearest
        relation = "directly above" if above else "right beside" if gap <= 0.3 else f"{gap:.1f} m from"
        parts.insert(0, f"{relation} item {i + 1} (the {item_name(m)})")
    return ", ".join(parts)


def _where_in_cabinet(spec: CaseSpec, position: list[float]) -> str:
    """The hottest point described up the cabinet (x) and relative to the nearest component."""
    x, y, _ = position
    parts = [f"{x:.2f} m up from the bottom of a {spec.room.size[0]:.1f} m cabinet"]
    nearest = None
    for i, m in enumerate(spec.machines):
        b = m.box
        dx = max(b.x - x, 0.0, x - b.hi[0])
        dy = max(b.y - y, 0.0, y - b.hi[1])
        gap = (dx * dx + dy * dy) ** 0.5
        if nearest is None or gap < nearest[0]:
            nearest = (gap, i, m)
    if nearest is not None:
        gap, i, m = nearest
        relation = "just above" if x >= m.box.hi[0] and gap <= 0.15 else "just below" if x <= m.x and gap <= 0.15 \
            else "beside" if gap <= 0.15 else f"{gap:.2f} m from"
        parts.insert(0, f"{relation} component {i + 1} (the {item_name(m)})")
    return ", ".join(parts)


def cabinet_facts(spec: CaseSpec, prediction: Prediction, a: Assumptions, lowest_safe: float | None, standard: dict) -> dict:
    from .heat import component_power

    metrics = summarise(spec, prediction.fluid, prediction.particles, prediction.age, a)
    index = tuple(int(p / spec.room.cell) for p in metrics["worst_position"])
    rates = [release_rate(m, a) for m in spec.machines]
    at_worst = [rate * float(prediction.particles[i][index]) for i, rate in enumerate(rates)]
    total = sum(at_worst) or 1.0
    airflow = spec.ach * spec.room.volume
    result = {
        "cabinet": {"height_m": spec.room.size[0], "width_m": spec.room.size[1], "depth_m": spec.room.size[2],
                    "air_in": "filter fan at the bottom", "air_out": "vent at the top"},
        "rating": standard["name"], "rating_max_air_c": standard["max_air"], "air_drawn_in_c": standard["ambient"],
        "fan_airflow_m3_per_hour": round(airflow),
        "fan_airflow_range_m3_per_hour": [round(v * spec.room.volume) for v in spec.room.ach_range],
        "hottest_air": {
            "temperature_c": round(standard["ambient"] + metrics["worst_level"], 1),
            "rise_percent_of_allowed": round(100 * metrics["worst_level"] / a.particle_limit),
            "where": _where_in_cabinet(spec, metrics["worst_position"]),
        },
        "average_air_c": round(standard["ambient"] + metrics["mean_level"], 1),
        "fan_power_w": round(1000 * metrics["fan_power_kw"]),
        "components": [{
            "number": i + 1, "what": item_name(m), "heat_w": round(component_power(m)) if m.on else 0,
            "state": "on" if m.on else "off",
            "share_of_heat_at_hottest_point_percent": round(100 * at_worst[i] / total),
        } for i, m in enumerate(spec.machines)],
    }
    if lowest_safe is not None:
        result["lowest_safe_airflow_m3_per_hour"] = round(lowest_safe * spec.room.volume)
        result["fan_power_at_lowest_safe_w"] = round(1000 * fan_power_kw(lowest_safe, a))
    return result


def facts(spec: CaseSpec, prediction: Prediction, a: Assumptions, lowest_safe: float | None, standard: dict | None = None) -> dict:
    """Numbers the explanation may use, all taken from the prediction."""
    metrics = summarise(spec, prediction.fluid, prediction.particles, prediction.age, a)
    cell = spec.room.cell
    index = tuple(int(p / cell) for p in metrics["worst_position"])
    rates = [release_rate(m, a) for m in spec.machines]
    at_worst = [rate * float(prediction.particles[i][index]) for i, rate in enumerate(rates)]
    total = sum(at_worst) or 1.0
    velocity = prediction.velocity[(slice(None), *index)]
    speed = float(np.linalg.norm(velocity))
    items = []
    for i, m in enumerate(spec.machines):
        items.append({
            "number": i + 1,
            "what": item_name(m),
            "centre_x": round(m.x + m.sx / 2, 1),
            "centre_y": round(m.y + m.sy / 2, 1),
            "height": m.sz,
            "state": ("present" if m.on else "away") if m.kind == "person" else ("running" if m.on else "off"),
            "share_of_particles_at_worst_point_percent": round(100 * at_worst[i] / total),
        })
    result = {
        "room": {"length_x": spec.room.size[0], "width_y": spec.room.size[1], "height_z": spec.room.size[2],
                 "supply": "ceiling panels", "return": "low grille on the wall at x = 0"},
        "fan_setting_air_changes_per_hour": round(spec.ach, 1),
        "fan_range": list(spec.room.ach_range),
        "particle_limit_per_m3": a.particle_limit,
        "standard": f"{standard['name']}, {standard['state']}" if standard else None,
        "site_minimum_fan_setting": standard["minimum_ach"] if standard else None,
        "worst_point": {
            "level_per_m3": round(metrics["worst_level"]),
            "percent_of_limit": round(100 * metrics["worst_level"] / a.particle_limit),
            "where": _where(spec, metrics["worst_position"]),
            "air_speed_m_per_s": round(speed, 3),
            "air_moves_towards_return_wall": bool(velocity[0] < 0),
            "age_of_air_times_ideal": round(float(prediction.age[index]) / metrics["ideal_age"], 1),
        },
        "average_level_percent_of_limit": round(100 * metrics["mean_level"] / a.particle_limit),
        "stagnant_air_percent_of_room": round(100 * metrics["stagnant_fraction"], 1),
        "fan_power_kw": round(metrics["fan_power_kw"], 2),
        "fan_setting_the_room_runs_at_today": a.full_ach,
        "saving_against_today_percent": round(metrics["saving_percent"]),
        "items": items,
    }
    if lowest_safe is not None:
        result["lowest_safe_fan_setting"] = round(lowest_safe, 1)
        result["fan_power_at_lowest_safe_kw"] = round(fan_power_kw(lowest_safe, a), 2)
    return result


def explain(spec: CaseSpec, prediction: Prediction, a: Assumptions, lowest_safe: float | None, standard: dict | None = None) -> dict:
    import json

    cabinet = spec.room.kind == "cabinet"
    data = cabinet_facts(spec, prediction, a, lowest_safe, standard) if cabinet else facts(spec, prediction, a, lowest_safe, standard)
    message, model = llm.chat(
        [{"role": "system", "content": SYSTEM_CABINET if cabinet else SYSTEM},
         {"role": "user", "content": "Facts:\n" + json.dumps(data, indent=1)}],
        max_tokens=320,
    )
    return {"text": (message.get("content") or "").strip(), "model": model, "hosted_on": llm.HOSTED_ON, "facts": data}
