"""Turns predicted fields into the numbers an engineer acts on."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..model import features
from ..sim.spec import CaseSpec


@dataclass(frozen=True)
class Assumptions:
    """Figures the readouts depend on. They are stated in the interface, not hidden."""

    full_ach: float = 40.0  # the fan setting the room runs at today
    full_fan_power_kw: float = 3.0  # fan power at that setting
    particle_limit: float = 352_000.0  # particles of 0.5 micrometres and larger per cubic metre (ISO class 7)
    machine_emission: float = 60_000.0  # particles per second released by a running machine
    occupied_height: float = 1.8  # the limit applies from the floor up to this height
    stagnant_age_factor: float = 2.0  # air older than this many ideal air changes counts as a dead zone
    electricity_price: float = 0.15  # US dollars per kWh
    hours_per_year: float = 8760.0


def fan_power_kw(ach: float, a: Assumptions) -> float:
    """Fan affinity law: power falls with the cube of airflow."""
    return a.full_fan_power_kw * (ach / a.full_ach) ** 3


def protected_zone(spec: CaseSpec, fluid: np.ndarray, a: Assumptions) -> np.ndarray:
    """Cells where the particle limit applies: air in the occupied height, away from release points.

    The cells where a machine releases its particles, and their immediate neighbours, are
    left out; the level there is set by the machine itself, not by the ventilation.
    """
    zone = fluid.copy()
    zone[:, :, round(a.occupied_height / spec.room.cell) :] = False
    for i in range(len(spec.machines)):
        padded = np.pad(features.source_mask(spec, i) > 0, 1)
        grown = padded.copy()
        for axis in range(3):
            grown |= np.roll(padded, 1, axis) | np.roll(padded, -1, axis)
        # one cell in every direction, diagonals included, to match the interface
        for axis in range(3):
            grown |= np.roll(grown, 1, axis) | np.roll(grown, -1, axis)
        zone &= ~grown[1:-1, 1:-1, 1:-1]
    return zone


def summarise(spec: CaseSpec, fluid: np.ndarray, particles: np.ndarray, age: np.ndarray, a: Assumptions) -> dict:
    """Readouts for one room state. `particles` holds one unit-release field per machine."""
    weights = np.array([a.machine_emission * m.emission if m.on else 0.0 for m in spec.machines], dtype=np.float32)
    level = np.tensordot(weights, particles, axes=1) if len(weights) else np.zeros(fluid.shape, dtype=np.float32)
    zone = protected_zone(spec, fluid, a)
    worst_index = np.unravel_index(np.argmax(np.where(zone, level, -1.0)), level.shape)
    cell = spec.room.cell
    ideal_age = spec.room.volume / spec.flow_rate
    stagnant = fluid & (age > a.stagnant_age_factor * ideal_age)
    power = fan_power_kw(spec.ach, a)
    full = a.full_fan_power_kw
    return {
        "ach": spec.ach,
        "flow_rate": spec.flow_rate,
        "fan_power_kw": power,
        "saving_kw": full - power,
        "saving_percent": 100 * (1 - power / full),
        "saving_per_year": (full - power) * a.hours_per_year * a.electricity_price,
        "worst_level": float(level[worst_index]),
        "worst_position": [(i + 0.5) * cell for i in worst_index],
        "mean_level": float(level[zone].mean()) if zone.any() else 0.0,
        "limit": a.particle_limit,
        "within_limit": bool(level[worst_index] <= a.particle_limit),
        "stagnant_fraction": float(stagnant.sum() / max(fluid.sum(), 1)),
        "ideal_age": ideal_age,
    }
