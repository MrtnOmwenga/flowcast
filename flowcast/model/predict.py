"""Loads the trained networks and predicts the fields of a room.

The models directory holds `flow/<name>/model.pt` and `particles/<name>/model.pt`. Several
of each form an ensemble: their average is the prediction and their disagreement is the
uncertainty.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from ..sim.spec import CaseSpec
from . import features
from .network import RoomNet

BATCH = 256


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
        self.flow = self._load(Path(root) / "flow", "flow")
        self.particles = self._load(Path(root) / "particles", "particles")

    def _load(self, root: Path, task: str) -> list[RoomNet]:
        names = features.CHANNELS[task]
        models = []
        for path in sorted(root.glob("*/model.pt")):
            checkpoint = torch.load(path, map_location=self.device, weights_only=True)
            model = RoomNet(len(names["inputs"]), len(names["targets"]), width=checkpoint["width"])
            model.load_state_dict(checkpoint["model"])
            models.append(model.to(self.device).eval())
        if not models:
            raise FileNotFoundError(f"no trained {task} models found under {root}")
        return models

    @property
    def members(self) -> int:
        return min(len(self.flow), len(self.particles))

    def _run(self, models: list[RoomNet], inputs: np.ndarray) -> np.ndarray:
        """Output of every member: (members, samples, channels, nx, ny, nz)."""
        x = torch.from_numpy(inputs).to(self.device)
        return np.stack([torch.cat([m(chunk) for chunk in x.split(BATCH)]).float().cpu().numpy() for m in models])

    @torch.no_grad()
    def predict_many(self, specs: list[CaseSpec]) -> list[Prediction]:
        """Each member is a flow network chained to a particle network.

        A member's particle network is given that member's own airflow, so the disagreement
        between members reflects uncertainty in the airflow as well as in the particles.
        """
        fluids = [features.solid_mask(spec) < 0.5 for spec in specs]
        members = self.members
        flows = self._run(self.flow[:members], np.stack([features.flow_inputs(spec) for spec in specs]))
        flow = flows.mean(axis=0)

        owners = np.array([i for i, spec in enumerate(specs) for _ in spec.machines], dtype=int)
        if len(owners):
            raw = np.stack([
                self._run([self.particles[k]], np.stack([
                    features.particle_inputs(spec, machine, flows[k, i, 0:3] * fluid)
                    for i, (spec, fluid) in enumerate(zip(specs, fluids))
                    for machine in range(len(spec.machines))
                ]))[0, :, 0]
                for k in range(members)
            ])  # (members, samples, nx, ny, nz)
            mean, spread = raw.mean(axis=0), raw.std(axis=0)

        predictions = []
        for i, (spec, fluid) in enumerate(zip(specs, fluids)):
            velocity, age = features.decode_flow(spec, flow[i])
            mine = np.flatnonzero(owners == i)
            if len(mine):
                particles = np.stack([features.decode_particles(spec, mean[k]) for k in mine])
                disagreement = spread[mine].max(axis=0)
            else:
                particles = np.zeros((0, *fluid.shape), dtype=np.float32)
                disagreement = np.zeros(fluid.shape, dtype=np.float32)
            predictions.append(Prediction(
                fluid=fluid,
                velocity=(velocity * fluid).astype(np.float32),
                particles=(particles * fluid).astype(np.float32),
                age=(np.maximum(age, 0) * fluid).astype(np.float32),
                spread=(disagreement * fluid).astype(np.float32),
            ))
        return predictions

    def predict(self, spec: CaseSpec) -> Prediction:
        return self.predict_many([spec])[0]
