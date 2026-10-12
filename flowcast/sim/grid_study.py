"""How much does the coarse simulation grid cost? Simulate the same rooms at two cell sizes and compare.

    python -m flowcast.sim.grid_study --count 16 --out data/grid-study
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

from .rooms import DEFAULT_ROOM, ROOMS
from .runner import run_case
from .sampling import sample_specs


def coarsen(field: np.ndarray, fluid: np.ndarray, factor: int) -> tuple[np.ndarray, np.ndarray]:
    """Average a fine field over blocks of cells, counting only the cells that contain air."""
    lead = field.shape[: field.ndim - 3]
    nx, ny, nz = (s // factor for s in fluid.shape)
    weights = fluid.reshape(nx, factor, ny, factor, nz, factor).astype(np.float64)
    blocks = field.reshape(*lead, nx, factor, ny, factor, nz, factor) * weights
    count = weights.sum(axis=(1, 3, 5))
    return blocks.sum(axis=(-5, -3, -1)) / np.maximum(count, 1), count > 0


def difference(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> float:
    return float(np.linalg.norm((a - b)[..., mask]) / max(np.linalg.norm(b[..., mask]), 1e-12))


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare coarse and fine simulation grids on the same rooms.")
    parser.add_argument("--count", type=int, default=16)
    parser.add_argument("--seed", type=int, default=5)
    parser.add_argument("--fine", type=float, default=0.1)
    parser.add_argument("--out", type=Path, default=Path("data/grid-study"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--room", choices=tuple(ROOMS), default=DEFAULT_ROOM)
    args = parser.parse_args()

    room = ROOMS[args.room]
    factor = round(room.cell / args.fine)
    specs = [s for s in sample_specs(args.count * 3, args.seed, room=room) if s.machines][: args.count]
    jobs = []
    for i, spec in enumerate(specs):
        jobs.append((args.out / f"room{i:02d}-coarse", spec))
        jobs.append((args.out / f"room{i:02d}-fine", replace(spec, room=replace(room, cell=args.fine), steps=3000, average_last=1500)))

    def run(job):
        path, spec = job
        result = path / "result.npz"
        return result if result.exists() else run_case(spec, path)

    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(run, jobs))

    rows = []
    for i, spec in enumerate(specs):
        coarse, fine = np.load(results[2 * i]), np.load(results[2 * i + 1])
        mask = coarse["fluid"]
        velocity, covered = coarsen(fine["velocity"], fine["fluid"], factor)
        particles, _ = coarsen(fine["particles"].sum(axis=0), fine["fluid"], factor)
        age, _ = coarsen(fine["age"], fine["fluid"], factor)
        mask = mask & covered
        occupied = mask.copy()
        occupied[:, :, round(1.8 / room.cell):] = False
        level = coarse["particles"].sum(axis=0)
        rows.append({
            "velocity": difference(coarse["velocity"], velocity, mask),
            "age": difference(coarse["age"], age, mask),
            "particles": difference(level, particles, occupied),
            "mean_level": abs(level[occupied].mean() - particles[occupied].mean()) / particles[occupied].mean(),
            "fine_runtime": float(fine["runtime"]), "coarse_runtime": float(coarse["runtime"]),
        })
    summary = {k: {"median": float(np.median([r[k] for r in rows])), "p90": float(np.percentile([r[k] for r in rows], 90))} for k in rows[0]}
    print(f"{len(rows)} rooms, coarse {room.cell} m against fine {args.fine} m")
    for key in ("velocity", "age", "particles", "mean_level"):
        print(f"{key:12s} median difference {summary[key]['median'] * 100:5.1f}%   90th percentile {summary[key]['p90'] * 100:5.1f}%")
    print(f"simulation time: coarse {summary['coarse_runtime']['median']:.0f} s, fine {summary['fine_runtime']['median']:.0f} s")
    (args.out / "summary.json").write_text(json.dumps({"rooms": rows, "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
