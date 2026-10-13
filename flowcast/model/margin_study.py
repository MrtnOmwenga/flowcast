"""How large must the safety margin be? Compare the model's lowest safe fan setting with the true one.

For each held-out layout the true lowest fan setting that keeps the room within its limit is
found by bisection with real simulations. The model's recommendation at each candidate margin
is then counted as confirmed if it is at least that high.

    python -m flowcast.model.margin_study --data data/cases-v3 --models data/models --count 100
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from ..api.metrics import Assumptions, fan_power_kw, summarise
from ..sim.runner import run_case
from ..sim.spec import CaseSpec
from .dataset import load_cases
from .predict import Ensemble

MARGINS = (0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate the safety margin against real simulations.")
    parser.add_argument("--data", type=Path, default=Path("data/cases-v3"))
    parser.add_argument("--models", type=Path, default=Path("data/models"))
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--out", type=Path, default=Path("data/margin-study"))
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    a = Assumptions()
    ensemble = Ensemble(args.models)
    layouts = [c["spec"] for c in load_cases(args.data, "test") if any(m.on for m in c["spec"].machines)][: args.count]
    room = layouts[0].room
    settings = [float(v) for v in np.linspace(*room.ach_range, 137)]

    def worst_simulated(index: int, setting: int) -> float:
        spec = CaseSpec(machines=layouts[index].machines, ach=settings[setting], room=room)
        folder = args.out / f"layout{index:03d}-setting{setting:03d}"
        try:  # reuse a finished simulation, so an interrupted study can be resumed
            data = np.load(folder / "result.npz")
            data["particles"]
        except (OSError, ValueError, KeyError, EOFError):
            data = np.load(run_case(spec, folder))
        return summarise(spec, data["fluid"], data["particles"], data["age"], a)["worst_level"]

    def true_lowest(index: int) -> int | None:
        """Index of the lowest setting whose simulated worst point is within the limit."""
        if worst_simulated(index, len(settings) - 1) > a.particle_limit:
            return None
        low, high = 0, len(settings) - 1
        while low < high:
            middle = (low + high) // 2
            if worst_simulated(index, middle) <= a.particle_limit:
                high = middle
            else:
                low = middle + 1
        return high

    with ThreadPoolExecutor(args.workers) as pool:
        truths = list(pool.map(true_lowest, range(len(layouts))))

    rows = []
    for index, (layout, truth) in enumerate(zip(layouts, truths)):
        specs = [CaseSpec(machines=layout.machines, ach=s, room=room) for s in settings]
        predicted = np.array([
            summarise(s, p.fluid, p.particles, p.age, a)["worst_level"]
            for s, p in zip(specs, ensemble.predict_many(specs))
        ])
        row = {"layout": index, "true": truth}
        for margin in MARGINS:
            passing = np.flatnonzero(predicted <= a.particle_limit * (1 - margin))
            row[f"model_{margin}"] = int(passing[0]) if len(passing) else None
        rows.append(row)

    report = {"layouts": len(rows), "margins": {}}
    usable = [r for r in rows if r["true"] is not None]
    print(f"{len(rows)} layouts; {len(rows) - len(usable)} cannot be made safe at any setting")
    print(f"{'margin':>7s} {'confirmed safe':>15s} {'no recommendation':>18s} {'extra fan power':>16s}")
    for margin in MARGINS:
        recommended = [(r["true"], r[f"model_{margin}"]) for r in usable if r[f"model_{margin}"] is not None]
        confirmed = np.mean([model >= true for true, model in recommended]) if recommended else float("nan")
        extra = np.median([fan_power_kw(settings[model], a) / fan_power_kw(settings[true], a) - 1 for true, model in recommended])
        none = 1 - len(recommended) / max(len(usable), 1)
        report["margins"][str(margin)] = {"confirmed": float(confirmed), "no_recommendation": float(none), "extra_power": float(extra)}
        print(f"{margin * 100:6.0f}% {confirmed * 100:14.0f}% {none * 100:17.0f}% {extra * 100:+15.0f}%")
    report["rows"] = rows
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
