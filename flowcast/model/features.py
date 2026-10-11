"""Turns a simulated room into network inputs and targets, and predictions back into physical units.

Everything is made dimensionless so the network sees numbers near one whatever the fan setting:
velocity is divided by the supply speed, particle level is multiplied by the flow rate (a
perfectly mixed room gives 1), and the age of the air is divided by the room's ideal air change
time.
"""

from __future__ import annotations

import math

import numpy as np

from ..sim.sampling import ACH_RANGE
from ..sim.spec import CaseSpec

INPUT_CHANNELS = ("solid", "source", "fan", "x", "y", "z")
TARGET_CHANNELS = ("ux", "uy", "uz", "age", "particles")


def solid_mask(spec: CaseSpec) -> np.ndarray:
    """1 where a machine occupies the cell."""
    mask = np.zeros(spec.room.shape, dtype=np.float32)
    for machine in spec.machines:
        mask[_cells(spec, machine.box.lo, machine.box.hi)] = 1.0
    return mask


def source_mask(spec: CaseSpec, index: int) -> np.ndarray:
    """1 in the cells just above one machine, where its particles are released."""
    box = spec.machines[index].box
    top = box.hi[2]
    mask = np.zeros(spec.room.shape, dtype=np.float32)
    mask[_cells(spec, (box.x, box.y, top), (box.hi[0], box.hi[1], top + 2 * spec.room.cell))] = 1.0
    return mask


def inputs(spec: CaseSpec, machine: int | None) -> np.ndarray:
    """Network input for one machine's particle field (or none, for an empty source)."""
    shape = spec.room.shape
    lo, hi = (math.log(v) for v in ACH_RANGE)
    fan = (math.log(spec.ach) - lo) / (hi - lo) * 2 - 1
    axes = [np.linspace(-1, 1, n, dtype=np.float32) for n in shape]
    x, y, z = np.meshgrid(*axes, indexing="ij")
    source = source_mask(spec, machine) if machine is not None else np.zeros(shape, dtype=np.float32)
    return np.stack([solid_mask(spec), source, np.full(shape, fan, dtype=np.float32), x, y, z])


def targets(spec: CaseSpec, data, machine: int | None) -> np.ndarray:
    velocity = data["velocity"] / spec.supply_speed
    age = data["age"] * spec.flow_rate / spec.room.volume
    if machine is None:
        particles = np.zeros(spec.room.shape, dtype=np.float32)
    else:
        particles = encode_particles(data["particles"][machine] * spec.flow_rate)
    return np.concatenate([velocity, age[None], particles[None]]).astype(np.float32)


def encode_particles(level: np.ndarray) -> np.ndarray:
    """Compress the large peak beside a source so the rest of the room still counts."""
    return np.log1p(np.maximum(level, 0.0))


def decode(spec: CaseSpec, prediction: np.ndarray) -> dict[str, np.ndarray]:
    """Network output for one machine back to physical units (unit release rate)."""
    return {
        "velocity": prediction[0:3] * spec.supply_speed,
        "age": prediction[3] * spec.room.volume / spec.flow_rate,
        "particles": np.expm1(np.maximum(prediction[4], 0.0)) / spec.flow_rate,
    }


def _cells(spec: CaseSpec, lo, hi) -> tuple[slice, slice, slice]:
    cell = spec.room.cell
    return tuple(slice(round(a / cell), round(b / cell)) for a, b in zip(lo, hi))
