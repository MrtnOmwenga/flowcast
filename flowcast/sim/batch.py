"""Simulate many random room states side by side.

    python -m flowcast.sim.batch --count 500 --seed 1 --out data/cases

Finished cases are skipped, so an interrupted batch can be restarted with the same command.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from .export import RESULT_NAME
from .runner import run_case
from .rooms import DEFAULT_ROOM, ROOMS
from .sampling import sample_specs
from .spec import CaseSpec


def run_batch(specs: list[CaseSpec], out: Path, workers: int, prefix: str = "case") -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    todo = []
    results = []
    for i, spec in enumerate(specs):
        case_dir = out / f"{prefix}_{i:05d}"
        if (case_dir / RESULT_NAME).exists():
            results.append(case_dir / RESULT_NAME)
        else:
            shutil.rmtree(case_dir, ignore_errors=True)  # leftovers from an interrupted run
            todo.append((case_dir, spec))
    print(f"{len(results)} already finished, {len(todo)} to run on {workers} workers", flush=True)

    started = time.monotonic()
    failures = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_case, spec, case_dir): case_dir for case_dir, spec in todo}
        for done, future in enumerate(as_completed(futures), start=1):
            case_dir = futures[future]
            try:
                results.append(future.result())
                status = "ok"
            except Exception as error:  # one failed room must not stop the batch
                failures += 1
                status = f"FAILED: {error}"
                with (out / "failures.log").open("a") as log:
                    log.write(f"{case_dir.name}\t{error}\n")
            elapsed = time.monotonic() - started
            remaining = elapsed / done * (len(todo) - done)
            print(f"[{done}/{len(todo)}] {case_dir.name} {status}  "
                  f"elapsed {elapsed / 60:.0f} min, about {remaining / 60:.0f} min left", flush=True)
    write_manifest(out)
    print(f"finished: {len(results)} results, {failures} failures", flush=True)
    return results


def write_manifest(out: Path) -> Path:
    """One line per finished case: its settings, run time and how well it settled."""
    manifest = out / "manifest.jsonl"
    with manifest.open("w") as handle:
        for result in sorted(out.glob(f"*/{RESULT_NAME}")):
            data = np.load(result)
            handle.write(json.dumps({
                "case": result.parent.name,
                "runtime": float(data["runtime"]),
                "residuals": {k: float(v) for k, v in data["residuals"]},
                "spec": json.loads(str(data["spec"])),
            }) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate many random room states.")
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, default=Path("data/cases"))
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--steps", type=int, default=None)
    parser.add_argument("--average-last", type=int, default=None)
    parser.add_argument("--prefix", default="case", help="case folder prefix; use a new one for each seed")
    parser.add_argument("--room", choices=tuple(ROOMS), default=DEFAULT_ROOM, help="which room design to simulate")
    args = parser.parse_args()

    overrides = {}
    if args.steps is not None:
        overrides["steps"] = args.steps
    if args.average_last is not None:
        overrides["average_last"] = args.average_last
    specs = sample_specs(args.count, args.seed, room=ROOMS[args.room], **overrides)
    run_batch(specs, args.out, args.workers, prefix=args.prefix)


if __name__ == "__main__":
    main()
