"""The response the interface receives for one room state."""

from __future__ import annotations

import base64
from dataclasses import asdict

import numpy as np

from ..sim.rooms import ROOMS
from ..sim.spec import CaseSpec
from .metrics import Assumptions, summarise


def _encode(array: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(array, dtype="<f4").tobytes()).decode()


def build(
    spec: CaseSpec,
    fluid: np.ndarray,
    velocity: np.ndarray,
    particles: np.ndarray,
    age: np.ndarray,
    assumptions: Assumptions,
    uncertainty: np.ndarray | None = None,
    source: str = "model",
) -> dict:
    """Fields are little-endian float32, flattened with x slowest and z fastest.

    `particles` has one field per machine for a release of one particle per second; the
    interface scales and adds them, so switching a machine on or off needs no new request.
    """
    room = spec.room
    return {
        "source": source,
        "grid": {"shape": list(room.shape), "cell": room.cell, "size": list(room.size)},
        "room": {
            "supplies": [list(s) for s in room.supplies],
            "extract_y": list(room.extract_y),
            "extract_height": room.extract_height,
            "extract_walls": list(room.extract_walls),
            "ach_range": list(room.ach_range),
            "inlets": [list(o) for o in room.inlet_openings()],
            "outlets": [list(o) for o in room.outlet_openings()],
            "kind": room.kind,
            "design": next((name for name, r in ROOMS.items() if r == room), None),
        },
        "machines": [asdict(m) for m in spec.machines],
        "assumptions": asdict(assumptions),
        "metrics": summarise(spec, fluid, particles, age, assumptions),
        "fields": {
            "fluid": _encode(fluid.astype(np.float32)),
            "velocity": _encode(velocity),
            "particles": _encode(particles),
            "age": _encode(age),
            "uncertainty": _encode(uncertainty) if uncertainty is not None else None,
        },
    }
