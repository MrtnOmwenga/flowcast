"""Draws random room states to simulate: which equipment and people, where, and how much air."""

from __future__ import annotations

import math
import random

from .spec import CaseSpec, Machine, Room

# Footprint and height in metres of the equipment types a room can contain.
CATALOGUE = {
    "workbench": (1.6, 0.8, 1.0),
    "cabinet": (0.8, 0.6, 1.8),
    "filling machine": (1.2, 1.0, 1.4),
    "small unit": (0.6, 0.6, 1.0),
    "isolator": (2.0, 0.8, 1.6),
    "shelving rack": (1.2, 0.4, 2.0),
    "cart": (0.8, 0.6, 0.8),
}
PERSON = (0.4, 0.4, 1.8)
MACHINE_COUNTS = (0, 1, 2, 3)
MACHINE_COUNT_WEIGHTS = (0.06, 0.26, 0.4, 0.28)
PEOPLE_COUNTS = (0, 1, 2, 3)
PEOPLE_COUNT_WEIGHTS = (0.25, 0.3, 0.25, 0.2)
MAX_ITEMS = 5
SNAP = 0.2  # machines sit on a floor grid of this spacing, as in the interface


# Height up the cabinet, width across it and depth out from the mounting plate, in metres
COMPONENTS = {
    "drive": (0.4, 0.2, 0.25),
    "large drive": (0.6, 0.3, 0.3),
    "controller rack": (0.15, 0.4, 0.15),
    "power supply": (0.2, 0.15, 0.15),
    "transformer": (0.25, 0.25, 0.25),
    "contactor row": (0.1, 0.5, 0.1),
    "braking resistor": (0.3, 0.1, 0.1),
}
COMPONENT_COUNTS = (2, 3, 4, 5, 6)
COMPONENT_SNAP = 0.05
INLET_CLEARANCE = 0.2  # keep the first stretch above the inlet clear, as a cabinet builder would


def sample_spec(rng: random.Random, room: Room | None = None, **overrides) -> CaseSpec:
    room = room or Room()
    if room.kind == "cabinet":
        return _sample_cabinet(rng, room, **overrides)
    machine_count = rng.choices(MACHINE_COUNTS, MACHINE_COUNT_WEIGHTS)[0]
    people_count = min(rng.choices(PEOPLE_COUNTS, PEOPLE_COUNT_WEIGHTS)[0], MAX_ITEMS - machine_count)
    kinds = ["machine"] * machine_count + ["person"] * people_count
    machines: list[Machine] = []
    attempts = 0
    while len(machines) < len(kinds) and attempts < 400:
        attempts += 1
        kind = kinds[len(machines)]
        sx, sy, sz = PERSON if kind == "person" else rng.choice(list(CATALOGUE.values()))
        if rng.random() < 0.5:
            sx, sy = sy, sx
        x = _snap(rng.uniform(0, room.size[0] - sx))
        y = _snap(rng.uniform(0, room.size[1] - sy))
        candidate = Machine(x=x, y=y, sx=sx, sy=sy, sz=sz, on=True, kind=kind)
        if not any(candidate.box.overlaps(m.box) for m in machines):
            machines.append(candidate)
    low, high = room.ach_range
    ach = math.exp(rng.uniform(math.log(low), math.log(high)))
    return CaseSpec(machines=tuple(machines), ach=round(ach, 2), room=room, **overrides)


def _sample_cabinet(rng: random.Random, room: Room, **overrides) -> CaseSpec:
    count = rng.choice(COMPONENT_COUNTS)
    parts: list[Machine] = []
    attempts = 0
    while len(parts) < count and attempts < 600:
        attempts += 1
        sx, sy, sz = rng.choice(list(COMPONENTS.values()))
        x = _snap(rng.uniform(INLET_CLEARANCE, room.size[0] - sx), COMPONENT_SNAP)
        y = _snap(rng.uniform(0, room.size[1] - sy), COMPONENT_SNAP)
        candidate = Machine(x=x, y=y, sx=sx, sy=sy, sz=sz, on=True, kind="component")
        if not any(candidate.box.overlaps(p.box) for p in parts):
            parts.append(candidate)
    low, high = room.ach_range
    ach = math.exp(rng.uniform(math.log(low), math.log(high)))
    return CaseSpec(machines=tuple(parts), ach=round(ach, 2), room=room, **overrides)


def sample_specs(count: int, seed: int, room: Room | None = None, realistic: bool = False, **overrides) -> list[CaseSpec]:
    """A reproducible list of room states; the same seed always gives the same list.

    `realistic` draws layouts the way rooms are actually arranged instead of anywhere at random.
    """
    rng = random.Random(seed)
    draw = sample_realistic if realistic else sample_spec
    return [draw(rng, room, **overrides) for _ in range(count)]


# Realistic layouts. Random placement rarely puts machines against walls or people at the
# machines they work at, which is how real rooms look; on such rooms the model was found to
# be much less sure of itself (14 October). These layouts fill that gap.
AGAINST_WALL = 0.8  # share of machines placed with their long side against a wall
AT_A_MACHINE = 0.8  # share of people standing at a machine's working side


def sample_realistic(rng: random.Random, room: Room | None = None, **overrides) -> CaseSpec:
    room = room or Room()
    if room.kind == "cabinet":
        return _sample_cabinet_rows(rng, room, **overrides)
    lx, ly = room.size[0], room.size[1]
    machine_count = rng.choice((1, 2, 2, 3, 3))
    people_count = min(rng.choice((0, 1, 2, 2, 3)), MAX_ITEMS - machine_count)
    machines: list[Machine] = []
    for _ in range(400):
        if len(machines) == machine_count:
            break
        sx, sy, sz = rng.choice(list(CATALOGUE.values()))
        long_side, short_side = max(sx, sy), min(sx, sy)
        if rng.random() < AGAINST_WALL:
            wall = rng.choice(("y0", "y1", "y0", "y1", "x1", "x0"))  # long walls more often
            if wall in ("y0", "y1"):
                sx, sy = long_side, short_side
                x = _snap(rng.uniform(0, lx - sx))
                y = 0.0 if wall == "y0" else _snap(ly - sy)
            else:
                sx, sy = short_side, long_side
                y = _snap(rng.uniform(0, ly - sy))
                x = 0.0 if wall == "x0" else _snap(lx - sx)
        else:
            if rng.random() < 0.5:
                sx, sy = sy, sx
            x, y = _snap(rng.uniform(0, lx - sx)), _snap(rng.uniform(0, ly - sy))
        candidate = Machine(x=x, y=y, sx=sx, sy=sy, sz=sz, on=True)
        if not any(candidate.box.overlaps(m.box) for m in machines):
            machines.append(candidate)
    people: list[Machine] = []
    px, py, pz = PERSON
    for _ in range(400):
        if len(people) == people_count:
            break
        if machines and rng.random() < AT_A_MACHINE:
            m = rng.choice(machines)
            gap = rng.choice((0.0, 0.0, 0.2))
            side = rng.choice(("x0", "x1", "y0", "y1"))
            if side in ("y0", "y1"):
                x = _snap(rng.uniform(m.x - px / 2, m.x + m.sx - px / 2))
                y = m.y - py - gap if side == "y0" else m.y + m.sy + gap
            else:
                y = _snap(rng.uniform(m.y - py / 2, m.y + m.sy - py / 2))
                x = m.x - px - gap if side == "x0" else m.x + m.sx + gap
            x, y = _snap(x), _snap(y)
        else:
            x, y = _snap(rng.uniform(0, lx - px)), _snap(rng.uniform(0, ly - py))
        if not (0 <= x <= lx - px + 1e-9 and 0 <= y <= ly - py + 1e-9):
            continue
        candidate = Machine(x=x, y=y, sx=px, sy=py, sz=pz, on=True, kind="person")
        if not any(candidate.box.overlaps(o.box) for o in (*machines, *people)):
            people.append(candidate)
    low, high = room.ach_range
    ach = math.exp(rng.uniform(math.log(low), math.log(high)))
    return CaseSpec(machines=(*machines, *people), ach=round(ach, 2), room=room, **overrides)


def _sample_cabinet_rows(rng: random.Random, room: Room, **overrides) -> CaseSpec:
    """Components in tidy rows across the plate, rows stacked up the cabinet, as panels are built."""
    count = rng.choice(COMPONENT_COUNTS)
    width = room.size[1]
    parts: list[Machine] = []
    x = INLET_CLEARANCE + rng.choice((0.0, 0.05, 0.1))
    while len(parts) < count:
        row_height = 0.0
        y = rng.choice((0.0, 0.05))
        placed_in_row = 0
        for _ in range(6):
            if len(parts) == count:
                break
            sx, sy, sz = rng.choice(list(COMPONENTS.values()))
            if y + sy > width + 1e-9 or x + sx > room.size[0] + 1e-9:
                break
            parts.append(Machine(x=_snap(x, COMPONENT_SNAP), y=_snap(y, COMPONENT_SNAP), sx=sx, sy=sy, sz=sz, on=True, kind="component"))
            placed_in_row += 1
            row_height = max(row_height, sx)
            y += sy + rng.choice((0.05, 0.05, 0.1))
        if placed_in_row == 0:
            break
        x += row_height + rng.choice((0.05, 0.1, 0.15))
        if x >= room.size[0] - 0.1:
            break
    low, high = room.ach_range
    ach = math.exp(rng.uniform(math.log(low), math.log(high)))
    return CaseSpec(machines=tuple(parts), ach=round(ach, 2), room=room, **overrides)


def _snap(value: float, step: float = SNAP) -> float:
    return round(round(value / step) * step, 6)
