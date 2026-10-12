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


def sample_spec(rng: random.Random, room: Room | None = None, **overrides) -> CaseSpec:
    room = room or Room()
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


def sample_specs(count: int, seed: int, room: Room | None = None, **overrides) -> list[CaseSpec]:
    """A reproducible list of room states; the same seed always gives the same list."""
    rng = random.Random(seed)
    return [sample_spec(rng, room, **overrides) for _ in range(count)]


def _snap(value: float) -> float:
    return round(round(value / SNAP) * SNAP, 6)
