"""Measure the ensemble against simulations it never saw.

    python -m flowcast.model.evaluate --data data/cases --models data/models --out docs/accuracy.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from ..api.metrics import Assumptions, protected_zone, summarise
from .dataset import load_cases
from .predict import Ensemble


def relative_error(predicted: np.ndarray, actual: np.ndarray, mask: np.ndarray) -> float:
    """Size of the error over the masked cells, as a fraction of the size of the true field."""
    return float(np.linalg.norm((predicted - actual)[..., mask]) / max(np.linalg.norm(actual[..., mask]), 1e-12))


def evaluate(data: Path, models: Path, split: str = "test") -> dict:
    ensemble = Ensemble(models)
    cases = load_cases(data, split)
    assumptions = Assumptions()
    rows = []
    seconds = []
    for case in cases:
        spec = case["spec"]
        started = time.perf_counter()
        prediction = ensemble.predict(spec)
        seconds.append(time.perf_counter() - started)
        fluid = case["fluid"]
        row = {
            "case": case["name"],
            "machines": len(spec.machines),
            "ach": spec.ach,
            "velocity_error": relative_error(prediction.velocity, case["velocity"], fluid),
            "age_error": relative_error(prediction.age, case["age"], fluid),
        }
        if spec.machines:
            zone = protected_zone(spec, fluid, assumptions)
            predicted = summarise(spec, fluid, prediction.particles, prediction.age, assumptions)
            actual = summarise(spec, fluid, case["particles"], case["age"], assumptions)
            level_p = prediction.particles.sum(axis=0)
            level_a = case["particles"].sum(axis=0)
            row.update(
                particle_error=relative_error(level_p, level_a, zone),
                worst_point_error=abs(predicted["worst_level"] - actual["worst_level"]) / actual["worst_level"],
                mean_level_error=abs(predicted["mean_level"] - actual["mean_level"]) / actual["mean_level"],
                same_verdict=predicted["within_limit"] == actual["within_limit"],
                spread=float(prediction.spread[zone].mean()),
            )
        rows.append(row)

    def stats(key: str) -> dict:
        values = np.array([r[key] for r in rows if key in r], dtype=float)
        return {"median": float(np.median(values)), "p90": float(np.percentile(values, 90)), "mean": float(values.mean())}

    return {
        "split": split,
        "rooms": len(rows),
        "members": ensemble.members,
        "device": str(ensemble.device),
        "seconds_per_prediction": float(np.median(seconds)),
        "velocity_error": stats("velocity_error"),
        "age_error": stats("age_error"),
        "particle_error": stats("particle_error"),
        "worst_point_error": stats("worst_point_error"),
        "mean_level_error": stats("mean_level_error"),
        "same_verdict_fraction": float(np.mean([r["same_verdict"] for r in rows if "same_verdict" in r])),
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the ensemble on held-out rooms.")
    parser.add_argument("--data", type=Path, default=Path("data/cases"))
    parser.add_argument("--models", type=Path, default=Path("data/models"))
    parser.add_argument("--split", default="test")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    report = evaluate(args.data, args.models, args.split)
    print(f"{report['rooms']} {args.split} rooms, {report['members']} models on {report['device']}, "
          f"{report['seconds_per_prediction'] * 1000:.0f} ms a prediction")
    for key in ("velocity_error", "age_error", "particle_error", "worst_point_error", "mean_level_error"):
        s = report[key]
        print(f"{key:20s} median {s['median'] * 100:5.1f}%   90th percentile {s['p90'] * 100:5.1f}%")
    print(f"same verdict on the particle limit as the simulation: {report['same_verdict_fraction'] * 100:.0f}% of rooms")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
