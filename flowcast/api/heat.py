"""Heat in a fan-cooled control cabinet, handled the way particles are handled in a cleanroom.

The fan drives the air hard enough that heat is carried, not lifted: buoyancy is neglected,
so a component's heat travels as a passive tracer. The simulation already gives each item's
field for a release of one unit per second; releasing P watts into air with a volumetric heat
capacity of about 1,200 joules per cubic metre per kelvin raises the air temperature by
P / 1200 times that field. Every component's share adds up, as the particles do.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..sim.spec import Machine
from .metrics import Assumptions

AIR_HEAT_CAPACITY = 1200.0  # joules per cubic metre per kelvin, air at about 35 degrees

# Heat each component gives off at full load, in watts: typical losses for the size drawn.
# These are assumptions stated on the page; a datasheet would replace them.
COMPONENTS: dict[str, tuple[tuple[float, float, float], float]] = {
    "drive": ((0.4, 0.2, 0.25), 120.0),  # a 4 kW variable-speed drive, about 3% loss
    "large drive": ((0.6, 0.3, 0.3), 400.0),  # a 15 kW drive
    "controller rack": ((0.15, 0.4, 0.15), 40.0),
    "power supply": ((0.2, 0.15, 0.15), 30.0),  # a 24 V supply at about 90% efficiency
    "transformer": ((0.25, 0.25, 0.25), 60.0),  # a 1 kVA control transformer
    "contactor row": ((0.1, 0.5, 0.1), 25.0),
    "braking resistor": ((0.3, 0.1, 0.1), 150.0),  # averaged over a braking cycle
}


def component_name(machine: Machine) -> str | None:
    for name, ((sx, sy, sz), _) in COMPONENTS.items():
        if abs(machine.sz - sz) > 1e-6:
            continue
        if {round(machine.sx, 3), round(machine.sy, 3)} == {round(sx, 3), round(sy, 3)}:
            return name
    return None


def component_power(machine: Machine) -> float:
    """Watts a component gives off at full load; an unknown size counts as a drive."""
    name = component_name(machine)
    return COMPONENTS[name or "drive"][1]


@dataclass(frozen=True)
class CabinetLimit:
    name: str
    max_air: float  # degrees Celsius
    source: str


LIMITS: dict[str, CabinetLimit] = {
    "drives-40": CabinetLimit("Drives rated 40 °C", 40.0, "Usual rating for drives without derating"),
    "drives-50": CabinetLimit("Drives rated 50 °C", 50.0, "Usual rating for drives with derating"),
    "plc-55": CabinetLimit("Controllers rated 55 °C", 55.0, "Usual rating for controllers and power supplies"),
}
DEFAULT_LIMIT = "drives-50"


def cabinet_assumptions(ambient: float, limit: CabinetLimit) -> Assumptions:
    """The cleanroom's readouts reused for heat: 'particle level' becomes temperature rise."""
    return Assumptions(
        full_ach=1562.5,  # the fan's top setting, 1,000 cubic metres an hour
        full_fan_power_kw=0.15,  # a filter fan of that size
        particle_limit=max(limit.max_air - ambient, 0.1),  # allowed rise in kelvin
        machine_emission=1.0 / AIR_HEAT_CAPACITY,  # per watt; scaled by each component's power
        person_emission=0.0,
        occupied_height=10.0,  # the limit applies through the whole cabinet
        safety_margin=0.15,
    )


@dataclass(frozen=True)
class CabinetRules:
    """What a cabinet must meet: the air around components under their rating."""

    limit: str = DEFAULT_LIMIT
    ambient: float = 35.0  # air drawn in, degrees Celsius
    minimum_ach: float = 312.5
    lead_minutes: int = 0
    cleanup_minutes: int = 0

    @property
    def chosen(self) -> CabinetLimit:
        return LIMITS[self.limit]

    @property
    def standard(self) -> str:
        return self.limit

    def in_operation(self, machines) -> bool:
        return any(m.on for m in machines)

    def assumptions(self, machines, base: Assumptions | None = None) -> Assumptions:
        a = cabinet_assumptions(self.ambient, self.chosen)
        return a if base is None else replace(base, **{k: getattr(a, k) for k in ("particle_limit", "machine_emission")})

    def describe(self, machines) -> dict:
        chosen = self.chosen
        return {
            "id": self.limit, "name": chosen.name, "source": chosen.source,
            "kind": "heat", "ambient": self.ambient, "max_air": chosen.max_air,
            "allowed_rise": chosen.max_air - self.ambient,
            "state": "running" if self.in_operation(machines) else "idle",
            "minimum_ach": self.minimum_ach, "lead_minutes": 0, "cleanup_minutes": 0,
            "components": {name: power for name, (_, power) in COMPONENTS.items()},
            "choices": [{"id": key, "name": c.name, "max_air": c.max_air} for key, c in LIMITS.items()],
        }
