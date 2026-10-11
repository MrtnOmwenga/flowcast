"""Converts a finished OpenFOAM case into arrays on the room's regular grid."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from .spec import CaseSpec

RESULT_NAME = "result.npz"
_LIST = re.compile(rb"internalField\s+nonuniform\s+List<(\w+)>\s*(\d+)\s*\(", re.S)
_UNIFORM = re.compile(rb"internalField\s+uniform\s+([^;]+);")
_RESIDUAL = re.compile(r"Solving for (\w+), Initial residual = ([\d.eE+-]+)")


def read_field(path: Path, n_cells: int | None = None) -> np.ndarray:
    """Read the cell values of an ASCII OpenFOAM field as (cells,) or (cells, 3)."""
    data = Path(path).read_bytes()
    match = _LIST.search(data)
    if match is None:
        uniform = _UNIFORM.search(data)
        if uniform is None or n_cells is None:
            raise ValueError(f"cannot read field values from {path}")
        value = np.array(uniform.group(1).replace(b"(", b" ").replace(b")", b" ").split(), dtype=np.float64)
        return np.tile(value, (n_cells, 1)).squeeze()
    kind, count = match.group(1), int(match.group(2))
    width = 3 if kind == b"vector" else 1
    body = data[match.end() : data.index(b"\n)\n;", match.end()) + 1]
    values = np.array(body.replace(b"(", b" ").replace(b")", b" ").split(), dtype=np.float64)
    if values.size != count * width:
        raise ValueError(f"{path}: expected {count * width} numbers, found {values.size}")
    return values.reshape(count, width).squeeze()


def export_case(case_dir: Path, runtime: float = float("nan")) -> Path:
    case_dir = Path(case_dir)
    spec = CaseSpec.load(case_dir / "spec.json")
    final = case_dir / str(spec.steps)
    shape = spec.room.shape

    centres = read_field(final / "C")
    index = tuple(np.floor(centres / spec.room.cell).astype(int).T)

    def to_grid(values: np.ndarray) -> np.ndarray:
        grid = np.zeros(shape + values.shape[1:], dtype=np.float32)
        grid[index] = values
        return grid

    n = centres.shape[0]
    fluid = np.zeros(shape, dtype=bool)
    fluid[index] = True
    out = case_dir / RESULT_NAME
    np.savez_compressed(
        out,
        fluid=fluid,
        velocity=np.moveaxis(to_grid(read_field(final / "UMean", n)), -1, 0),
        # One field per machine, each for a release of one unit per second
        particles=np.stack([to_grid(read_field(final / f"s{i}Mean", n)) for i in range(len(spec.machines))])
        if spec.machines
        else np.zeros((0, *shape), dtype=np.float32),
        age=to_grid(read_field(final / "ageMean", n)),
        residuals=np.array(list(final_residuals(case_dir).items()), dtype=str),
        runtime=runtime,
        spec=spec.to_json(),
    )
    return out


def final_residuals(case_dir: Path) -> dict[str, float]:
    """Initial residual of each solved field at the last step."""
    logs = sorted(Path(case_dir).glob("log.*.simpleFoam"))
    if not logs:
        return {}
    tail = logs[-1].read_text(errors="replace")[-20000:]
    return {name: float(value) for name, value in _RESIDUAL.findall(tail)}
