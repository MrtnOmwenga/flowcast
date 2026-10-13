"""Turns predicted fields into the numbers an engineer acts on."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..model import features
from ..sim.spec import CaseSpec


@dataclass(frozen=True)
class Assumptions:
    """Figures the readouts depend on. They are stated in the interface, not hidden."""

    full_ach: float = 30.0  # the fan setting the room runs at today
    full_fan_power_kw: float = 1.5  # fan power at that setting
    # Share of that power that does not fall as the fans slow: drive and motor losses. With
    # it, turning the air down by half saves about four fifths of the power, not seven eighths.
    fan_fixed_loss: float = 0.08
    particle_limit: float = 352_000.0  # particles of 0.5 micrometres and larger per cubic metre (ISO class 7)
    machine_emission: float = 6_000.0  # particles per second released by a running machine
    person_emission: float = 5_000.0  # particles per second shed by a person at work in the room
    occupied_height: float = 1.8  # the limit applies from the floor up to this height
    stagnant_age_factor: float = 1.5  # air older than this many ideal air changes counts as stagnant
    electricity_price: float = 0.15  # US dollars per kWh
    hours_per_year: float = 8760.0
    # A setting is recommended only if the predicted worst point is this far under the limit,
    # which is roughly the model's error at the worst point.
    safety_margin: float = 0.15


def release_rate(machine, a: Assumptions) -> float:
    """Particles per second an item releases in its current state."""
    if not machine.on:
        return 0.0
    if machine.kind == "component":  # heat: machine_emission is per watt
        from .heat import component_power

        return a.machine_emission * component_power(machine) * machine.emission
    usual = a.person_emission if machine.kind == "person" else a.machine_emission
    return usual * machine.emission


def fan_power_kw(ach: float, a: Assumptions) -> float:
    """Fan affinity law (power falls with the cube of airflow) plus a fixed share for drive losses."""
    ratio = ach / a.full_ach
    return a.full_fan_power_kw * (a.fan_fixed_loss + (1 - a.fan_fixed_loss) * ratio**3)


def protected_zone(spec: CaseSpec, fluid: np.ndarray, a: Assumptions) -> np.ndarray:
    """Cells where the particle limit applies: air in the occupied height, away from release points.

    The cells where a machine releases its particles, and their immediate neighbours, are
    left out; the level there is set by the machine itself, not by the ventilation.
    """
    zone = fluid.copy()
    zone[:, :, round(a.occupied_height / spec.room.cell) :] = False
    for i in range(len(spec.machines)):
        # grow the release cells by one cell in every direction, diagonals included
        grown = np.pad(features.source_mask(spec, i) > 0, 1)
        for axis in range(3):
            grown = grown | np.roll(grown, 1, axis) | np.roll(grown, -1, axis)
        zone &= ~grown[1:-1, 1:-1, 1:-1]
    return zone


def summarise(spec: CaseSpec, fluid: np.ndarray, particles: np.ndarray, age: np.ndarray, a: Assumptions) -> dict:
    """Readouts for one room state. `particles` holds one unit-release field per machine."""
    weights = np.array([release_rate(m, a) for m in spec.machines], dtype=np.float32)
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
        "safe": bool(level[worst_index] <= a.particle_limit * (1 - a.safety_margin)),
        "stagnant_fraction": float(stagnant.sum() / max(fluid.sum(), 1)),
        "ideal_age": ideal_age,
    }
