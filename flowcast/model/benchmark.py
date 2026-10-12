"""Time the ensemble on whatever hardware it is running on.

    python -m flowcast.model.benchmark --models data/models
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from ..sim.rooms import DEFAULT_ROOM, ROOMS
from ..sim.sampling import sample_specs
from ..sim.spec import CaseSpec
from .predict import Ensemble


def timed(fn, repeats: int) -> float:
    fn()  # the first call includes one-off set-up
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    started = time.perf_counter()
    for _ in range(repeats):
        fn()
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    return (time.perf_counter() - started) / repeats


def main() -> None:
    parser = argparse.ArgumentParser(description="Time predictions and the fan-setting sweep.")
    parser.add_argument("--models", type=Path, default=Path("data/models"))
    parser.add_argument("--room", choices=tuple(ROOMS), default=DEFAULT_ROOM)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    ensemble = Ensemble(args.models)
    room = ROOMS[args.room]
    spec = next(s for s in sample_specs(200, 7, room=room) if len(s.machines) == 3)
    sweep = [CaseSpec(machines=spec.machines, ach=float(a), room=room) for a in np.linspace(*room.ach_range, 137)]
    layouts = [s for s in sample_specs(4000, 11, room=room) if s.machines][:1000]

    report = {
        "hardware": ensemble.hardware,
        "members": ensemble.members,
        "one_prediction_seconds": timed(lambda: ensemble.predict(spec), 10),
        "sweep_137_settings_seconds": timed(lambda: ensemble.predict_many(sweep), 2),
        "thousand_layouts_seconds": timed(lambda: [ensemble.predict_many(layouts[i : i + 100]) for i in range(0, 1000, 100)], 1),
    }
    print(f"{report['members']} models on {report['hardware']}")
    print(f"one room:                 {report['one_prediction_seconds'] * 1000:8.0f} ms")
    print(f"137 fan settings at once: {report['sweep_137_settings_seconds']:8.2f} s")
    print(f"1,000 different layouts:  {report['thousand_layouts_seconds']:8.2f} s")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
