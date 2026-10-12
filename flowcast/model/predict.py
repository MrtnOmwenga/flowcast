"""Loads the trained ensemble and predicts the fields of a room."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from ..sim.spec import CaseSpec
from . import features
from .network import RoomNet


@dataclass
class Prediction:
    fluid: np.ndarray  # (nx, ny, nz) bool
    velocity: np.ndarray  # (3, nx, ny, nz) m/s
    particles: np.ndarray  # (machines, nx, ny, nz) per unit release rate
    age: np.ndarray  # (nx, ny, nz) seconds
    spread: np.ndarray  # (nx, ny, nz) disagreement between ensemble members, in log particle level


class Ensemble:
    def __init__(self, root: Path, device: str | None = None):
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.models = []
        for path in sorted(Path(root).glob("*/model.pt")):
            checkpoint = torch.load(path, map_location=self.device, weights_only=True)
            model = RoomNet(width=checkpoint["width"]).to(self.device).eval()
            model.load_state_dict(checkpoint["model"])
            self.models.append(model)
        if not self.models:
            raise FileNotFoundError(f"no trained models found under {root}")

    @torch.no_grad()
    def raw(self, specs: list[CaseSpec]) -> list[np.ndarray]:
        """Network output for each room: (members, machines or 1, channels, nx, ny, nz)."""
        batches = []
        counts = []
        for spec in specs:
            machines = list(range(len(spec.machines))) or [None]
            counts.append(len(machines))
            batches.extend(features.inputs(spec, m) for m in machines)
        x = torch.from_numpy(np.stack(batches)).to(self.device)
        outputs = []
        for model in self.models:
            parts = [model(chunk) for chunk in x.split(256)]
            outputs.append(torch.cat(parts).float().cpu().numpy())
        stacked = np.stack(outputs)  # (members, total samples, channels, ...)
        result = []
        start = 0
        for count in counts:
            result.append(stacked[:, start : start + count])
            start += count
        return result

    def predict_many(self, specs: list[CaseSpec]) -> list[Prediction]:
        return [self._assemble(spec, raw) for spec, raw in zip(specs, self.raw(specs))]

    def predict(self, spec: CaseSpec) -> Prediction:
        return self.predict_many([spec])[0]

    @staticmethod
    def _assemble(spec: CaseSpec, raw: np.ndarray) -> Prediction:
        fluid = features.solid_mask(spec) < 0.5
        mean = raw.mean(axis=0)  # average the ensemble members
        # Airflow and air age do not depend on which machine's particles are asked for
        flow = features.decode(spec, mean.mean(axis=0))
        if spec.machines:
            particles = np.stack([features.decode(spec, sample)["particles"] for sample in mean])
            spread = raw[:, :, 4].std(axis=0).max(axis=0)
        else:
            particles = np.zeros((0, *fluid.shape), dtype=np.float32)
            spread = np.zeros(fluid.shape, dtype=np.float32)
        return Prediction(
            fluid=fluid,
            velocity=(flow["velocity"] * fluid).astype(np.float32),
            particles=(particles * fluid).astype(np.float32),
            age=(np.maximum(flow["age"], 0) * fluid).astype(np.float32),
            spread=(spread * fluid).astype(np.float32),
        )
