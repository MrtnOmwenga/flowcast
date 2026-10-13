"""The cleanliness standards a room can be held to, and the site's own rules on top.

Limits are the maximum number of particles of 0.5 micrometres and larger per cubic metre.
EU GMP Annex 1 (2022), Table 1, gives each grade two limits: "at rest" (equipment installed
but not operating and nobody in the room) and "in operation" (equipment running with staff
at work). ISO 14644-1 gives each class one limit, for whichever state the room is classified in.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..sim.spec import Machine
from .metrics import Assumptions


@dataclass(frozen=True)
class Standard:
    name: str
    in_operation: float
    at_rest: float
    source: str


STANDARDS: dict[str, Standard] = {
    "gmp-c": Standard("EU GMP grade C", 3_520_000, 352_000, "EU GMP Annex 1 (2022), Table 1"),
    "gmp-b": Standard("EU GMP grade B", 352_000, 3_520, "EU GMP Annex 1 (2022), Table 1"),
    "iso-8": Standard("ISO class 8", 3_520_000, 3_520_000, "ISO 14644-1"),
    "iso-7": Standard("ISO class 7", 352_000, 352_000, "ISO 14644-1"),
    "iso-6": Standard("ISO class 6", 35_200, 35_200, "ISO 14644-1"),
}
DEFAULT_STANDARD = "gmp-c"
# Annex 1 gives "less than 20 minutes" as the guidance value for the clean-up period.
CLEAN_UP_GUIDANCE_MINUTES = 20
# The release rates in Assumptions are for the work and garments usual in a room held to
# 352,000 particles per cubic metre. A cleaner class implies better garments and cleaner
# processes, a looser one the reverse, so releases are scaled with the in-operation limit.
REFERENCE_LIMIT = 352_000


@dataclass(frozen=True)
class Rules:
    """What a room must meet: the standard, and the site's minimum fan setting."""

    standard: str = DEFAULT_STANDARD
    minimum_ach: float = 10.0
    lead_minutes: int = 20
    cleanup_minutes: int = CLEAN_UP_GUIDANCE_MINUTES

    @property
    def chosen(self) -> Standard:
        return STANDARDS[self.standard]

    def in_operation(self, machines) -> bool:
        """A room is in operation while anything is running or anyone is in it."""
        return any(m.on for m in machines)

    def assumptions(self, machines: tuple[Machine, ...] | list[Machine], base: Assumptions = Assumptions()) -> Assumptions:
        standard = self.chosen
        scale = standard.in_operation / REFERENCE_LIMIT
        return replace(
            base,
            particle_limit=standard.in_operation if self.in_operation(machines) else standard.at_rest,
            machine_emission=base.machine_emission * scale,
            person_emission=base.person_emission * scale,
        )

    def describe(self, machines) -> dict:
        standard = self.chosen
        return {
            "id": self.standard, "name": standard.name, "source": standard.source,
            "in_operation": standard.in_operation, "at_rest": standard.at_rest,
            "state": "in operation" if self.in_operation(machines) else "at rest",
            "minimum_ach": self.minimum_ach, "lead_minutes": self.lead_minutes, "cleanup_minutes": self.cleanup_minutes,
            "choices": [{"id": key, "name": s.name, "in_operation": s.in_operation, "at_rest": s.at_rest} for key, s in STANDARDS.items()],
        }
