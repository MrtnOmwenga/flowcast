"""Turns a simulated room into network inputs and targets, and predictions back into physical units.

Two networks share the work. The flow network maps the layout and fan setting to the air
velocity and the age of the air. The particle network then maps one machine's release point,
together with that airflow, to the machine's particle field. Particles are carried by the air,
so giving the second network the airflow leaves it a much easier problem.

Everything is made dimensionless so the networks see numbers near one whatever the fan setting:
velocity is divided by the supply speed, particle level is multiplied by the flow rate (a
perfectly mixed room gives 1), and the age of the air is divided by the room's ideal air change
time.
"""

from __future__ import annotations

import math

import numpy as np

from ..sim.spec import CaseSpec

CHANNELS = {
    "flow": {"inputs": ("solid", "fan", "x", "y", "z"), "targets": ("ux", "uy", "uz", "age")},
    "particles": {
        "inputs": ("solid", "source", "fan", "x", "y", "z", "ux", "uy", "uz"),
        "targets": ("particles",),
    },
}
# Channels whose sign reverses when the room is mirrored along x or along y
MIRRORED = {
    "flow": {"inputs": (("x",), ("y",)), "targets": (("ux",), ("uy",))},
    "particles": {"inputs": (("x", "ux"), ("y", "uy")), "targets": ((), ())},
}


def solid_mask(spec: CaseSpec) -> np.ndarray:
    """1 where a machine occupies the cell."""
    mask = np.zeros(spec.room.shape, dtype=np.float32)
    for machine in spec.machines:
        mask[_cells(spec, machine.box.lo, machine.box.hi)] = 1.0
    return mask


def source_mask(spec: CaseSpec, index: int) -> np.ndarray:
    """1 in the air cells where one item's particles are released."""
    box = spec.machines[index].source_box(spec.room.cell, spec.room.size)
    mask = np.zeros(spec.room.shape, dtype=np.float32)
    mask[_cells(spec, box.lo, box.hi)] = 1.0
    return mask * (1.0 - solid_mask(spec))


def _common(spec: CaseSpec) -> list[np.ndarray]:
    shape = spec.room.shape
    lo, hi = (math.log(v) for v in spec.room.ach_range)
    fan = (math.log(spec.ach) - lo) / (hi - lo) * 2 - 1
    axes = [np.linspace(-1, 1, n, dtype=np.float32) for n in shape]
    return [np.full(shape, fan, dtype=np.float32), *np.meshgrid(*axes, indexing="ij")]


def flow_inputs(spec: CaseSpec) -> np.ndarray:
    return np.stack([solid_mask(spec), *_common(spec)])


def flow_targets(spec: CaseSpec, data) -> np.ndarray:
    age = data["age"] * spec.flow_rate / spec.room.volume
    return np.concatenate([scale_velocity(spec, data["velocity"]), age[None]]).astype(np.float32)


def particle_inputs(spec: CaseSpec, machine: int, scaled_velocity: np.ndarray) -> np.ndarray:
    """`scaled_velocity` is the air velocity divided by the supply speed."""
    return np.concatenate(
        [np.stack([solid_mask(spec), source_mask(spec, machine), *_common(spec)]), scaled_velocity]
    ).astype(np.float32)


def particle_targets(spec: CaseSpec, data, machine: int) -> np.ndarray:
    return encode_particles(data["particles"][machine] * spec.flow_rate)[None].astype(np.float32)


def scale_velocity(spec: CaseSpec, velocity: np.ndarray) -> np.ndarray:
    return (velocity / spec.supply_speed).astype(np.float32)


def encode_particles(level: np.ndarray) -> np.ndarray:
    """Compress the large peak beside a source so the rest of the room still counts."""
    return np.log1p(np.maximum(level, 0.0))


def decode_flow(spec: CaseSpec, prediction: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Flow network output to velocity in m/s and age of air in seconds."""
    return prediction[0:3] * spec.supply_speed, prediction[3] * spec.room.volume / spec.flow_rate


def decode_particles(spec: CaseSpec, prediction: np.ndarray) -> np.ndarray:
    """Particle network output to particle level for a release of one unit per second."""
    return np.expm1(np.maximum(prediction, 0.0)) / spec.flow_rate


def _cells(spec: CaseSpec, lo, hi) -> tuple[slice, slice, slice]:
    cell = spec.room.cell
    return tuple(slice(round(a / cell), round(b / cell)) for a, b in zip(lo, hi))
