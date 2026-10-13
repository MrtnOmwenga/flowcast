"""Description of one room simulation: geometry, equipment and fan setting."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Box:
    """Axis-aligned box in metres: minimum corner and size."""

    x: float
    y: float
    z: float
    sx: float
    sy: float
    sz: float

    @property
    def lo(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    @property
    def hi(self) -> tuple[float, float, float]:
        return (self.x + self.sx, self.y + self.sy, self.z + self.sz)

    def overlaps(self, other: Box) -> bool:
        return all(a_lo < b_hi and b_lo < a_hi for a_lo, a_hi, b_lo, b_hi in zip(self.lo, self.hi, other.lo, other.hi))


KINDS = ("machine", "person", "component")
# Kinds whose release comes off their whole surface, not from above them
ALL_ROUND = ("person", "component")


@dataclass(frozen=True)
class Machine:
    """Something standing on the floor that releases particles: a piece of equipment or a person.

    A machine releases its particles into the air just above it. A person sheds them from
    the whole body, so theirs are released into the air all around them. The simulation
    computes each item's particle field for a unit release rate, whatever `on` and
    `emission` say.
    """

    x: float
    y: float
    sx: float
    sy: float
    sz: float
    on: bool = False
    emission: float = 1.0  # release rate while on, as a multiple of the usual rate for its kind
    kind: str = "machine"  # "machine" or "person"

    @property
    def box(self) -> Box:
        return Box(self.x, self.y, 0.0, self.sx, self.sy, self.sz)

    def source_box(self, cell: float, room_size: tuple[float, float, float]) -> Box:
        """The region its particles are released into, clipped to the room.

        For a person this box contains the body itself; the body is solid, so only the air
        around it receives particles.
        """
        b = self.box
        if self.kind in ALL_ROUND:
            lo = (b.x - cell, b.y - cell, 0.0)
            hi = (b.hi[0] + cell, b.hi[1] + cell, b.hi[2] + cell)
        else:
            lo = (b.x, b.y, b.hi[2])
            hi = (b.hi[0], b.hi[1], b.hi[2] + 2 * cell)
        lo = tuple(max(0.0, v) for v in lo)
        hi = tuple(min(limit, v) for v, limit in zip(hi, room_size))
        return Box(*lo, *(h - l for l, h in zip(lo, hi)))


@dataclass(frozen=True)
class Room:
    """Room size, grid spacing and the fixed supply and extract openings."""

    size: tuple[float, float, float] = (6.0, 4.0, 3.0)
    # 0.2 m cells keep each simulation small enough to settle fully and to run in about a
    # minute. A finer grid resolves the supply jets better but costs far more per room.
    cell: float = 0.2
    # Ceiling supply panels: (x, y, sx, sy)
    supplies: tuple[tuple[float, float, float, float], ...] = (
        (1.0, 0.4, 1.0, 1.0),
        (4.0, 0.4, 1.0, 1.0),
        (1.0, 2.6, 1.0, 1.0),
        (4.0, 2.6, 1.0, 1.0),
    )
    # Low wall extracts on the two end walls (x = 0 and x = size[0]): y range and height
    extract_y: tuple[float, float] = (0.4, 3.6)
    extract_height: float = 0.4
    # Extracts on one end wall only. With extracts on both ends the room is symmetric and the
    # supply jets settle into one of several lopsided patterns; which one depends on tiny
    # changes in layout, so moving a machine 0.2 m could change the whole room's airflow by
    # more than half. A single return wall gives the air one way out and a pattern that
    # shifts smoothly as the layout changes.
    extract_walls: tuple[str, ...] = ("x0",)
    # The range of fan settings, in air changes an hour, this kind of room is run at
    ach_range: tuple[float, float] = (6.0, 40.0)
    # Openings on any wall, for spaces that are not ceiling-supplied rooms. Each is
    # (wall, u, v, su, sv): the wall ("x0", "x1", "y0", "y1", "z0" or "z1") and a rectangle on
    # it in the wall's own two axes, in x, y, z order. When given, they replace the ceiling
    # supplies and wall extracts above.
    inlets: tuple[tuple, ...] = ()
    outlets: tuple[tuple, ...] = ()
    kind: str = "cleanroom"  # which sampler and readouts apply: "cleanroom" or "cabinet"

    @property
    def shape(self) -> tuple[int, int, int]:
        return tuple(round(s / self.cell) for s in self.size)

    @property
    def volume(self) -> float:
        return math.prod(self.size)

    def inlet_openings(self) -> tuple[tuple, ...]:
        if self.inlets:
            return self.inlets
        return tuple(("z1", x, y, sx, sy) for x, y, sx, sy in self.supplies)

    def outlet_openings(self) -> tuple[tuple, ...]:
        if self.outlets:
            return self.outlets
        y0, y1 = self.extract_y
        return tuple((wall, y0, 0.0, y1 - y0, self.extract_height) for wall in self.extract_walls)

    def opening_box(self, opening: tuple, tolerance: float) -> tuple[tuple[float, ...], tuple[float, ...]]:
        """The thin box around an opening, used to pick its faces out of the wall."""
        wall, u, v, su, sv = opening
        axis = "xyz".index(wall[0])
        position = 0.0 if wall[1] == "0" else self.size[axis]
        others = [i for i in range(3) if i != axis]
        lo, hi = [0.0] * 3, [0.0] * 3
        lo[axis], hi[axis] = position - tolerance, position + tolerance
        lo[others[0]], hi[others[0]] = u, u + su
        lo[others[1]], hi[others[1]] = v, v + sv
        return tuple(lo), tuple(hi)

    @property
    def supply_area(self) -> float:
        return sum(su * sv for _, _, _, su, sv in self.inlet_openings())


@dataclass(frozen=True)
class CaseSpec:
    """Everything needed to simulate one room state."""

    machines: tuple[Machine, ...] = ()
    ach: float = 20.0  # air changes per hour delivered by the fans
    room: Room = field(default_factory=Room)
    steps: int = 2000
    convection: str = "linearUpwind"  # scheme for the momentum equation: "linearUpwind" or "upwind"
    average_last: int = 1000

    @property
    def flow_rate(self) -> float:
        """Supply airflow in cubic metres per second."""
        return self.ach * self.room.volume / 3600.0

    @property
    def supply_speed(self) -> float:
        return self.flow_rate / self.room.supply_area

    def validate(self) -> None:
        room = self.room
        cell = room.cell
        openings = (*room.inlet_openings(), *room.outlet_openings())
        for value in (*room.size, *(v for opening in openings for v in opening[1:])):
            _require_on_grid(value, cell)
        boxes = [m.box for m in self.machines]
        for box in boxes:
            for value in (*box.lo, *box.hi):
                _require_on_grid(value, cell)
            if any(lo < 0 for lo in box.lo) or any(hi > s for hi, s in zip(box.hi, room.size)):
                raise ValueError(f"machine outside the room: {box}")
        for machine in self.machines:
            if machine.kind not in KINDS:
                raise ValueError(f"unknown kind of item: {machine.kind}")
            if machine.kind not in ALL_ROUND and machine.box.hi[2] + 2 * cell > room.size[2]:
                raise ValueError(f"item too tall to leave room for its particle source: {machine.box}")
        for i, a in enumerate(boxes):
            for b in boxes[i + 1 :]:
                if a.overlaps(b):
                    raise ValueError(f"machines overlap: {a} and {b}")
        if self.ach <= 0:
            raise ValueError("ach must be positive")
        if not 0 < self.average_last <= self.steps:
            raise ValueError("average_last must be between 1 and steps")

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> CaseSpec:
        room_data = dict(data.get("room", {}))
        if "size" in room_data:
            room_data["size"] = tuple(room_data["size"])
        if "supplies" in room_data:
            room_data["supplies"] = tuple(tuple(s) for s in room_data["supplies"])
        for key in ("extract_y", "extract_walls", "ach_range"):
            if key in room_data:
                room_data[key] = tuple(room_data[key])
        for key in ("inlets", "outlets"):
            if key in room_data:
                room_data[key] = tuple(tuple(o) for o in room_data[key])
        machines = tuple(Machine(**m) for m in data.get("machines", ()))
        rest = {k: v for k, v in data.items() if k not in ("room", "machines")}
        return cls(machines=machines, room=Room(**room_data), **rest)

    @classmethod
    def load(cls, path: Path) -> CaseSpec:
        return cls.from_dict(json.loads(Path(path).read_text()))


def _require_on_grid(value: float, cell: float) -> None:
    if abs(value / cell - round(value / cell)) > 1e-6:
        raise ValueError(f"{value} is not a multiple of the grid spacing {cell}")
