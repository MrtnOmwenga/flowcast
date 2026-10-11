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


@dataclass(frozen=True)
class Machine:
    """A piece of equipment standing on the floor. It releases particles while it is on.

    The simulation computes each machine's particle field for a unit release rate, whatever
    `on` and `emission` say; combine them with `particle_level` to get a room state.
    """

    x: float
    y: float
    sx: float
    sy: float
    sz: float
    on: bool = False
    emission: float = 1.0  # particle release rate while on, in arbitrary units per second

    @property
    def box(self) -> Box:
        return Box(self.x, self.y, 0.0, self.sx, self.sy, self.sz)


@dataclass(frozen=True)
class Room:
    """Room size, grid spacing and the fixed supply and extract openings."""

    size: tuple[float, float, float] = (6.0, 4.0, 3.0)
    cell: float = 0.1
    # Ceiling supply panels: (x, y, sx, sy)
    supplies: tuple[tuple[float, float, float, float], ...] = (
        (1.0, 0.5, 1.0, 1.0),
        (4.0, 0.5, 1.0, 1.0),
        (1.0, 2.5, 1.0, 1.0),
        (4.0, 2.5, 1.0, 1.0),
    )
    # Low wall extracts on the two end walls (x = 0 and x = size[0]): y range and height
    extract_y: tuple[float, float] = (0.5, 3.5)
    extract_height: float = 0.4

    @property
    def shape(self) -> tuple[int, int, int]:
        return tuple(round(s / self.cell) for s in self.size)

    @property
    def volume(self) -> float:
        return math.prod(self.size)

    @property
    def supply_area(self) -> float:
        return sum(sx * sy for _, _, sx, sy in self.supplies)


@dataclass(frozen=True)
class CaseSpec:
    """Everything needed to simulate one room state."""

    machines: tuple[Machine, ...] = ()
    ach: float = 20.0  # air changes per hour delivered by the fans
    room: Room = field(default_factory=Room)
    steps: int = 2000
    average_last: int = 500

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
        for value in (*room.size, *(v for s in room.supplies for v in s), *room.extract_y, room.extract_height):
            _require_on_grid(value, cell)
        boxes = [m.box for m in self.machines]
        for box in boxes:
            for value in (*box.lo, *box.hi):
                _require_on_grid(value, cell)
            if any(lo < 0 for lo in box.lo) or any(hi > s for hi, s in zip(box.hi, room.size)):
                raise ValueError(f"machine outside the room: {box}")
            if box.hi[2] + 2 * cell > room.size[2]:
                raise ValueError(f"machine too tall to leave room for its particle source: {box}")
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
        if "extract_y" in room_data:
            room_data["extract_y"] = tuple(room_data["extract_y"])
        machines = tuple(Machine(**m) for m in data.get("machines", ()))
        rest = {k: v for k, v in data.items() if k not in ("room", "machines")}
        return cls(machines=machines, room=Room(**room_data), **rest)

    @classmethod
    def load(cls, path: Path) -> CaseSpec:
        return cls.from_dict(json.loads(Path(path).read_text()))


def _require_on_grid(value: float, cell: float) -> None:
    if abs(value / cell - round(value / cell)) > 1e-6:
        raise ValueError(f"{value} is not a multiple of the grid spacing {cell}")
