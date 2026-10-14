"""Check the simulation set-up against a published room experiment.

    python -m flowcast.sim.annex20 --out data/annex20 --cells 0.2 0.048 0.024

The experiment is the two-dimensional test case of IEA Annex 20 (Nielsen, 1990): a room 9 m
long and 3 m high, with air blown in through a slot 0.168 m high under the ceiling at 0.455 m/s
and leaving through a 0.48 m slot at the floor of the far wall. Air velocity was measured by
laser-Doppler anemometry along two vertical and two horizontal lines. The same solver,
turbulence model, schemes and boundary conditions that produce Flowcast's training data are
run on this room, and the velocity along those four lines is compared with the measurements.

The room is simulated as a thin slab with symmetry planes for side walls, which is what
"two-dimensional" means here. The measurements are in docs/validation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .runner import run_case
from .spec import CaseSpec, Room

MEASUREMENTS = Path(__file__).resolve().parents[2] / "docs" / "validation" / "annex20-measurements.json"
SLAB_CELLS = 4  # cells across the slab; the flow does not vary across it
LINES = ("x=H", "x=2H", "y=h/2", "y=H-h/2")


def spec_for(cell: float, conditions: dict, steps: int) -> CaseSpec:
    """The benchmark room on a grid of `cell` metres.

    Openings must fall on cell faces. Grids of 0.024 m and 0.012 m reproduce both slots
    exactly; coarser grids round them to the nearest whole cell and keep the airflow the same.
    """
    H, L, h, t, u0 = (conditions[k] for k in ("H", "L", "h", "t", "u0"))
    snap = lambda v: max(1, round(v / cell)) * cell
    inlet, outlet = snap(h), snap(t)
    width = SLAB_CELLS * cell
    k = 1.5 * (conditions["inlet_turbulence_intensity"] * u0) ** 2
    room = Room(
        size=(L, width, H), cell=cell,
        inlets=(("x0", 0.0, round(H - inlet, 6), width, inlet),),
        outlets=(("x1", 0.0, 0.0, width, outlet),),
        symmetry_walls=("y0", "y1"),
        inlet_turbulence=(k, k**1.5 / (h / 10)),
        nu=conditions["nu"],
        ach_range=(1.0, 100.0),
    )
    # The measured airflow per metre of width is u0 * h, whatever the slot is rounded to
    ach = 3600 * u0 * h / (L * H)
    return CaseSpec(room=room, ach=ach, steps=steps, average_last=steps // 4)


def profiles(data, spec: CaseSpec, conditions: dict, measured: dict) -> dict[str, np.ndarray]:
    """Simulated u / u0 at the positions where it was measured."""
    H, h, u0 = conditions["H"], conditions["h"], conditions["u0"]
    cell = spec.room.cell
    nx, ny, nz = spec.room.shape
    u = data["velocity"][0][:, ny // 2, :] / u0  # along the room, on the middle plane
    xs = (np.arange(nx) + 0.5) * cell
    zs = (np.arange(nz) + 0.5) * cell

    def at(x: np.ndarray, z: np.ndarray) -> np.ndarray:
        """Linear interpolation between cell centres, holding the end values to the walls."""
        along = np.stack([np.interp(x, xs, u[:, k]) for k in range(nz)], axis=-1)
        return np.array([np.interp(zi, zs, row) for zi, row in zip(np.broadcast_to(z, x.shape), along)])

    out = {}
    for name in LINES:
        position = np.array([row[0] for row in measured[name]])
        if name.startswith("x="):
            x = np.full_like(position, H if name == "x=H" else 2 * H)
            out[name] = at(x, H * (1 - position))  # measured down from the ceiling
        else:
            z = H - h / 2 if name == "y=h/2" else h / 2
            out[name] = at(position * H, np.full_like(position, z))
    return out


def compare(simulated: dict[str, np.ndarray], measured: dict) -> dict:
    rows = {}
    differences = []
    for name in LINES:
        mean = np.array([row[1] for row in measured[name]])
        difference = simulated[name] - mean
        differences.append(difference)
        rows[name] = {"mean_absolute_difference": float(np.abs(difference).mean()),
                      "largest_difference": float(np.abs(difference).max())}
    everything = np.concatenate(differences)
    rows["all"] = {"mean_absolute_difference": float(np.abs(everything).mean()),
                   "root_mean_square_difference": float(np.sqrt((everything**2).mean()))}
    return rows


def figure(results: dict[str, dict], measured: dict, path: Path) -> None:
    """Four small charts, one per measured line: points are measurements, lines are simulations."""
    colours = ["#b9c2cf", "#f0a35e", "#2fbf5b", "#1f7ae0", "#0b3d91", "#6b21a8"]
    width, height, pad = 300, 220, 44
    titles = {"x=H": "Vertical line one room-height from the inlet", "x=2H": "Vertical line two room-heights from the inlet",
              "y=h/2": "Along the ceiling, through the middle of the jet", "y=H-h/2": "Along the floor"}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {2 * width} {2 * height + 44}" font-family="sans-serif" font-size="10">',
             '<rect width="100%" height="100%" fill="white"/>']
    for index, name in enumerate(LINES):
        ox, oy = (index % 2) * width, (index // 2) * height
        position = np.array([row[0] for row in measured[name]])
        mean = np.array([row[1] for row in measured[name]])
        lo, hi = -0.45, 1.15
        sx = lambda p: ox + pad + (p - position.min()) / (position.max() - position.min()) * (width - pad - 12)
        sy = lambda v: oy + 24 + (hi - v) / (hi - lo) * (height - 24 - 30)
        parts.append(f'<text x="{ox + pad}" y="{oy + 14}" font-weight="bold">{titles[name]}</text>')
        parts.append(f'<line x1="{ox + pad}" x2="{ox + width - 12}" y1="{sy(0)}" y2="{sy(0)}" stroke="#8793a5" stroke-width="0.6"/>')
        for tick in (-0.4, 0, 0.4, 0.8):
            parts.append(f'<text x="{ox + pad - 5}" y="{sy(tick) + 3}" text-anchor="end" fill="#5f6b7d">{tick:g}</text>')
        label = "distance below the ceiling / room height" if name.startswith("x=") else "distance from the inlet wall / room height"
        parts.append(f'<text x="{ox + (width + pad) / 2}" y="{oy + height - 6}" text-anchor="middle" fill="#5f6b7d">{label}</text>')
        for colour, (grid, result) in zip(colours[: len(results)], results.items()):
            points = " ".join(f"{sx(p):.1f},{sy(v):.1f}" for p, v in zip(position, result["profiles"][name]))
            parts.append(f'<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="1.6"/>')
        for p, v in zip(position, mean):
            parts.append(f'<circle cx="{sx(p):.1f}" cy="{sy(v):.1f}" r="2.4" fill="#d92d20"/>')
    legend = [("#d92d20", "measured")] + [(c, f"simulated, {g} m cells") for c, g in zip(colours[: len(results)], results)]
    for index, (colour, text) in enumerate(legend):
        x, y = pad + (index % 3) * 180, 2 * height + 12 + (index // 3) * 16
        parts.append(f'<rect x="{x}" y="{y}" width="14" height="4" fill="{colour}"/><text x="{x + 18}" y="{y + 6}">{text}</text>')
    parts.append(f'<text x="8" y="{height}" transform="rotate(-90 8 {height})" text-anchor="middle" fill="#5f6b7d">air velocity / inlet velocity</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts))


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare the simulation set-up with the IEA Annex 20 measurements.")
    parser.add_argument("--out", type=Path, default=Path("data/annex20"))
    parser.add_argument("--cells", type=float, nargs="+", default=[0.2, 0.048, 0.024])
    parser.add_argument("--steps", type=int, default=8000)
    parser.add_argument("--report", type=Path, default=Path("docs/validation/annex20.json"))
    args = parser.parse_args()

    published = json.loads(MEASUREMENTS.read_text())
    conditions, measured = published["conditions"], published["lines"]
    results = {}
    for cell in args.cells:
        spec = spec_for(cell, conditions, args.steps)
        folder = args.out / f"cell-{cell:g}"
        try:  # reuse a finished run
            data = np.load(folder / "result.npz")
            data["velocity"]
        except (OSError, ValueError, KeyError, EOFError):
            data = np.load(run_case(spec, folder))
        simulated = profiles(data, spec, conditions, measured)
        inlet, outlet = spec.room.inlets[0][4], spec.room.outlets[0][4]
        results[f"{cell:g}"] = {
            "cells": int(np.prod(spec.room.shape)), "inlet_height": inlet, "outlet_height": outlet,
            "exact_geometry": bool(abs(inlet - conditions["h"]) < 1e-9 and abs(outlet - conditions["t"]) < 1e-9),
            "runtime_seconds": float(data["runtime"]),
            "residuals": {k: float(v) for k, v in data["residuals"]},
            "difference": compare(simulated, measured),
            "profiles": {name: [round(float(v), 4) for v in values] for name, values in simulated.items()},
        }
        d = results[f"{cell:g}"]["difference"]
        print(f"{cell:g} m cells ({results[f'{cell:g}']['cells']:,} cells, {float(data['runtime']):.0f} s): mean difference "
              f"{d['all']['mean_absolute_difference']:.3f} of the inlet velocity; "
              + ", ".join(f"{name} {d[name]['mean_absolute_difference']:.3f}" for name in LINES), flush=True)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"source": published["source"], "conditions": conditions, "grids": results}, indent=1))
    figure(results, measured, args.report.with_suffix(".svg"))
    print(f"wrote {args.report} and {args.report.with_suffix('.svg')}")


if __name__ == "__main__":
    main()
