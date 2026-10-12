"""The Flowcast service: uvicorn flowcast.api.app:app

FLOWCAST_MODELS   directory holding the trained ensemble (default data/models)
FLOWCAST_VERIFY   directory for verification simulations (default data/verify)
"""

from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..model.predict import Ensemble, Prediction
from ..sim.runner import run_case
from ..sim.sampling import ACH_RANGE
from ..sim.spec import CaseSpec, Machine
from . import payload
from .metrics import Assumptions, protected_zone, summarise

MODELS = Path(os.environ.get("FLOWCAST_MODELS", "data/models"))
VERIFY = Path(os.environ.get("FLOWCAST_VERIFY", "data/verify"))
ASSUMPTIONS = Assumptions()
# How far a confirming simulation may differ from the prediction at the worst point
AGREEMENT_TOLERANCE = 0.3
# Ensemble disagreement, in log particle level, at which confidence reaches zero. Calibrated
# on held-out rooms: confidence below 0.6 marks the fifth of rooms where the members disagree
# most, and those rooms carry about twice the error of the rest.
SPREAD_AT_ZERO_CONFIDENCE = 0.1

app = FastAPI(title="Flowcast")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
ensemble = Ensemble(MODELS)
simulations = ThreadPoolExecutor(max_workers=int(os.environ.get("FLOWCAST_SIMULATIONS", "3")))
jobs: dict[str, dict] = {}


class MachineIn(BaseModel):
    x: float
    y: float
    sx: float
    sy: float
    sz: float
    on: bool = True
    emission: float = Field(default=1.0, ge=0)
    kind: str = "machine"


class RoomState(BaseModel):
    machines: list[MachineIn] = Field(default_factory=list, max_length=5)
    ach: float = Field(ge=ACH_RANGE[0], le=ACH_RANGE[1])

    def spec(self) -> CaseSpec:
        spec = CaseSpec(machines=tuple(Machine(**m.model_dump()) for m in self.machines), ach=self.ach)
        try:
            spec.validate()
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return spec


def confidence(spec: CaseSpec, prediction: Prediction) -> float:
    zone = protected_zone(spec, prediction.fluid, ASSUMPTIONS)
    spread = float(prediction.spread[zone].mean()) if zone.any() else 0.0
    return max(0.0, 1.0 - spread / SPREAD_AT_ZERO_CONFIDENCE)


def respond(spec: CaseSpec, prediction: Prediction) -> dict:
    body = payload.build(
        spec, prediction.fluid, prediction.velocity, prediction.particles, prediction.age,
        ASSUMPTIONS, uncertainty=prediction.spread, source="model",
    )
    body["metrics"]["confidence"] = confidence(spec, prediction)
    return body


@app.get("/api/health")
def health() -> dict:
    return {"models": ensemble.members, "device": str(ensemble.device)}


@app.post("/api/predict")
def predict(state: RoomState) -> dict:
    spec = state.spec()
    return respond(spec, ensemble.predict(spec))


def _within_limit(spec: CaseSpec, prediction: Prediction) -> bool:
    """Whether the worst point is under the limit with the safety margin to spare."""
    return summarise(spec, prediction.fluid, prediction.particles, prediction.age, ASSUMPTIONS)["safe"]


@app.post("/api/optimise")
def optimise(state: RoomState) -> dict:
    """The lowest fan setting that keeps the worst point under the limit by the safety margin.

    On a GPU every setting is predicted in one batch. On a processor that takes too long
    for an interactive page, so the settings are bisected instead, which assumes that more
    air never makes the worst point worse.
    """
    base = state.spec()
    started = time.perf_counter()
    settings = [float(ach) for ach in np.arange(ACH_RANGE[0], ACH_RANGE[1] + 1e-9, 0.25)]
    specs = [CaseSpec(machines=base.machines, ach=ach) for ach in settings]
    if ensemble.device.type == "cuda":
        passing = [_within_limit(s, p) for s, p in zip(specs, ensemble.predict_many(specs))]
        best = next((i for i, ok in enumerate(passing) if ok), None)
        tested = len(specs)
    else:
        tested = 1
        if not _within_limit(specs[-1], ensemble.predict(specs[-1])):
            best = None
        else:
            low, high = 0, len(specs) - 1  # the answer lies in [low, high]; high passes
            while low < high:
                middle = (low + high) // 2
                tested += 1
                if _within_limit(specs[middle], ensemble.predict(specs[middle])):
                    high = middle
                else:
                    low = middle + 1
            best = high
    return {
        "ach": settings[best] if best is not None else settings[-1],
        "feasible": best is not None,
        "tested": tested,
        "seconds": time.perf_counter() - started,
        "device": ensemble.device.type,
    }


def _simulate(job_id: str, spec: CaseSpec, predicted: dict, prediction: Prediction) -> None:
    job = jobs[job_id]
    job["status"] = "running"
    started = time.perf_counter()
    try:
        data = np.load(run_case(spec, VERIFY / job_id))
        simulated = summarise(spec, data["fluid"], data["particles"], data["age"], ASSUMPTIONS)
        gap = abs(predicted["worst_level"] - simulated["worst_level"]) / max(simulated["worst_level"], 1e-9)
        same_side = predicted["within_limit"] == simulated["within_limit"]
        speed = np.linalg.norm(data["velocity"], axis=0)
        error = np.linalg.norm(prediction.velocity - data["velocity"], axis=0)
        job.update(
            status="done",
            predicted={k: predicted[k] for k in ("worst_level", "mean_level", "within_limit")},
            simulated={k: simulated[k] for k in ("worst_level", "mean_level", "within_limit")},
            field_error=float(error[data["fluid"]].mean() / max(speed[data["fluid"]].mean(), 1e-9)),
            agrees=bool(gap <= AGREEMENT_TOLERANCE and (same_side or not spec.machines)),
            seconds=time.perf_counter() - started,
            payload=payload.build(
                spec, data["fluid"], data["velocity"], data["particles"], data["age"], ASSUMPTIONS, source="simulation"
            ),
        )
    except Exception as error:  # report the failure to the interface instead of losing it
        job.update(status="failed", error=str(error))


@app.post("/api/verify")
def verify(state: RoomState) -> dict:
    """Run a real OpenFOAM simulation of this room and compare it with the prediction."""
    spec = state.spec()
    prediction = ensemble.predict(spec)
    predicted = summarise(spec, prediction.fluid, prediction.particles, prediction.age, ASSUMPTIONS)
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {"id": job_id, "status": "queued"}
    simulations.submit(_simulate, job_id, spec, predicted, prediction)
    return jobs[job_id]


@app.get("/api/verify/{job_id}")
def verification(job_id: str) -> dict:
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="unknown verification")
    return jobs[job_id]
