"""Store one simulated room as the page's offline sample.

    python -m flowcast.api.sample data/cases-v3/case_00049 web/public/sample.json

The page shows the sample before the service answers, and instead of it when the service is
not reachable.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ..sim.export import RESULT_NAME
from ..sim.spec import CaseSpec
from . import payload
from .heat import CabinetRules
from .standards import Rules


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("case", type=Path, help="a finished case directory")
    parser.add_argument("out", type=Path)
    args = parser.parse_args()

    data = np.load(args.case / RESULT_NAME)
    spec = CaseSpec.from_dict(json.loads(str(data["spec"])))
    rules = CabinetRules() if spec.room.kind == "cabinet" else Rules()
    body = payload.build(spec, data["fluid"], data["velocity"], data["particles"], data["age"],
                         rules.assumptions(spec.machines), source="simulation")
    body["standard"] = rules.describe(spec.machines)
    args.out.write_text(json.dumps(body))
    print(f"{args.out}: {args.out.stat().st_size / 1e6:.1f} MB, {len(spec.machines)} items, {spec.ach:g} air changes an hour")


if __name__ == "__main__":
    main()
