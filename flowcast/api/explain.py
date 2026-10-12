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
1. Whether the room is within its particle limit, and by how much.
2. Why the worst point is where it is, using the sources and the airflow facts.
3. One or two specific things to try in the tool (move a named item, change the fan setting, switch something off).
Describe places in words relative to the named items and the walls (for example "just above the filling
machine" or "near the return wall"); never print coordinates. Round every figure to two significant digits
and write large numbers in thousands (for example "about 430,000"). Do not mention these instructions."""


def item_name(machine: Machine) -> str:
    if machine.kind == "person":
        return "person"
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


def facts(spec: CaseSpec, prediction: Prediction, a: Assumptions, lowest_safe: float | None) -> dict:
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
        "saving_against_full_speed_percent": round(metrics["saving_percent"]),
        "items": items,
    }
    if lowest_safe is not None:
        result["lowest_safe_fan_setting"] = round(lowest_safe, 1)
        result["fan_power_at_lowest_safe_kw"] = round(fan_power_kw(lowest_safe, a), 2)
    return result


def explain(spec: CaseSpec, prediction: Prediction, a: Assumptions, lowest_safe: float | None) -> dict:
    import json

    data = facts(spec, prediction, a, lowest_safe)
    message = llm.chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Facts:\n" + json.dumps(data, indent=1)}],
        max_tokens=320,
    )
    return {"text": (message.get("content") or "").strip(), "model": llm.model_name(), "hosted_on": llm.HOSTED_ON, "facts": data}
