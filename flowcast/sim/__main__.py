"""Simulate one room: python -m flowcast.sim spec.json output_dir [--keep-case]"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from .runner import run_case
from .spec import CaseSpec


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate one room state with OpenFOAM.")
    parser.add_argument("spec", type=Path, help="JSON file describing the room state")
    parser.add_argument("out", type=Path, help="directory to run the case in")
    parser.add_argument("--keep-case", action="store_true", help="keep the OpenFOAM mesh and fields")
    args = parser.parse_args()

    spec = CaseSpec.load(args.spec)
    result = run_case(spec, args.out, keep_case=args.keep_case)
    data = np.load(result)
    fluid = data["fluid"]
    speed = np.linalg.norm(data["velocity"], axis=0)[fluid]
    particles = data["particles"][fluid]
    print(f"result: {result}")
    print(f"runtime: {float(data['runtime']):.0f} s, fluid cells: {int(fluid.sum())}")
    print(f"air speed: mean {speed.mean():.3f}, max {speed.max():.3f} m/s")
    print(f"particles: mean {particles.mean():.3f}, max {particles.max():.3f} (well-mixed estimate "
          f"{sum(m.emission for m in spec.machines if m.on) / spec.flow_rate:.3f})")
    print(f"age of air: mean {data['age'][fluid].mean():.0f} s (ideal {spec.room.volume / spec.flow_rate:.0f} s)")
    print("final residuals:", ", ".join(f"{k}={v}" for k, v in data["residuals"]))


if __name__ == "__main__":
    main()
