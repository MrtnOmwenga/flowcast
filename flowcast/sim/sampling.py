"""Draws random room states to simulate: which machines, where, and how much air."""

from __future__ import annotations

import math
import random

from .spec import CaseSpec, Machine, Room

# Footprint and height in metres of the equipment types a room can contain.
CATALOGUE = {
    "workbench": (1.6, 0.8, 0.9),
    "cabinet": (0.8, 0.6, 1.8),
    "filling machine": (1.2, 1.0, 1.4),
    "small unit": (0.6, 0.6, 1.0),
    "isolator": (2.0, 0.8, 1.6),
}
MACHINE_COUNTS = (0, 1, 2, 3)
MACHINE_COUNT_WEIGHTS = (0.04, 0.2, 0.4, 0.36)
ACH_RANGE = (6.0, 40.0)
SNAP = 0.2  # machines sit on a floor grid of this spacing, as in the interface


def sample_spec(rng: random.Random, room: Room | None = None, **overrides) -> CaseSpec:
    room = room or Room()
    count = rng.choices(MACHINE_COUNTS, MACHINE_COUNT_WEIGHTS)[0]
    machines: list[Machine] = []
    attempts = 0
    while len(machines) < count and attempts < 200:
        attempts += 1
        sx, sy, sz = rng.choice(list(CATALOGUE.values()))
        if rng.random() < 0.5:
            sx, sy = sy, sx
        x = _snap(rng.uniform(0, room.size[0] - sx))
        y = _snap(rng.uniform(0, room.size[1] - sy))
        candidate = Machine(x=x, y=y, sx=sx, sy=sy, sz=sz, on=True)
        if not any(candidate.box.overlaps(m.box) for m in machines):
            machines.append(candidate)
    ach = math.exp(rng.uniform(math.log(ACH_RANGE[0]), math.log(ACH_RANGE[1])))
    return CaseSpec(machines=tuple(machines), ach=round(ach, 2), room=room, **overrides)


def sample_specs(count: int, seed: int, **overrides) -> list[CaseSpec]:
    """A reproducible list of room states; the same seed always gives the same list."""
    rng = random.Random(seed)
    return [sample_spec(rng, **overrides) for _ in range(count)]


def _snap(value: float) -> float:
    return round(round(value / SNAP) * SNAP, 6)
