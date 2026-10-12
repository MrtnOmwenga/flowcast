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
from ..sim.rooms import DEFAULT_ROOM, ROOMS
from ..sim.spec import CaseSpec, Machine
from . import explain as explaining
from . import llm, payload
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
SWEEP = os.environ.get("FLOWCAST_SWEEP") == "1"
# Shown beside every answer. Set FLOWCAST_HARDWARE to name the exact card.
HARDWARE = os.environ.get("FLOWCAST_HARDWARE", ensemble.hardware)
simulations = ThreadPoolExecutor(max_workers=int(os.environ.get("FLOWCAST_SIMULATIONS", "3")))
jobs: dict[str, dict] = {}


def warm_up() -> None:
    """Run each batch size once so the GPU's first real answer is not slowed by set-up."""
    room = ROOMS[DEFAULT_ROOM]
    box = Machine(x=1.0, y=1.0, sx=0.6, sy=0.6, sz=1.0, on=True)
    ensemble.predict(CaseSpec(room=room))
    ensemble.predict(CaseSpec(machines=(box,), room=room))
    if SWEEP:
        ensemble.predict_many([CaseSpec(machines=(box,), ach=a, room=room) for a in np.linspace(*room.ach_range, 137)])


if ensemble.device.type == "cuda":
    warm_up()


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
    ach: float = Field(gt=0)

    def spec(self) -> CaseSpec:
        room = ROOMS[DEFAULT_ROOM]
        spec = CaseSpec(machines=tuple(Machine(**m.model_dump()) for m in self.machines), ach=self.ach, room=room)
        try:
            if not room.ach_range[0] <= self.ach <= room.ach_range[1]:
                raise ValueError(f"fan setting outside {room.ach_range[0]:g} to {room.ach_range[1]:g} air changes an hour")
            spec.validate()
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return spec


def confidence(spec: CaseSpec, prediction: Prediction) -> float:
    zone = protected_zone(spec, prediction.fluid, ASSUMPTIONS)
    spread = float(prediction.spread[zone].mean()) if zone.any() else 0.0
    return max(0.0, 1.0 - spread / SPREAD_AT_ZERO_CONFIDENCE)


def respond(spec: CaseSpec, prediction: Prediction, seconds: float) -> dict:
    body = payload.build(
        spec, prediction.fluid, prediction.velocity, prediction.particles, prediction.age,
        ASSUMPTIONS, uncertainty=prediction.spread, source="model",
    )
    body["metrics"]["confidence"] = confidence(spec, prediction)
    body["compute"] = {"hardware": HARDWARE, "gpu": ensemble.device.type == "cuda", "seconds": seconds,
                       "models": ensemble.members}
    return body


@app.get("/api/health")
def health() -> dict:
    return {"models": ensemble.members, "device": str(ensemble.device), "hardware": HARDWARE,
            "language_model": llm.model_name() if llm.available() else None, **ensemble.meta}


@app.post("/api/predict")
def predict(state: RoomState) -> dict:
    spec = state.spec()
    started = time.perf_counter()
    prediction = ensemble.predict(spec)
    return respond(spec, prediction, time.perf_counter() - started)


def _within_limit(spec: CaseSpec, prediction: Prediction) -> bool:
    """Whether the worst point is under the limit with the safety margin to spare."""
    return summarise(spec, prediction.fluid, prediction.particles, prediction.age, ASSUMPTIONS)["safe"]


def lowest_safe(base: CaseSpec) -> tuple[float | None, int]:
    """Bisect the fan settings for the lowest that is safe. Returns it and how many were tested."""
    low, high = base.room.ach_range
    settings = [float(ach) for ach in np.linspace(low, high, 137)]
    specs = [CaseSpec(machines=base.machines, ach=ach, room=base.room) for ach in settings]
    tested = 1
    if not _within_limit(specs[-1], ensemble.predict(specs[-1])):
        return None, tested
    lo, hi = 0, len(specs) - 1  # the answer lies in [lo, hi]; hi passes
    while lo < hi:
        middle = (lo + hi) // 2
        tested += 1
        if _within_limit(specs[middle], ensemble.predict(specs[middle])):
            hi = middle
        else:
            lo = middle + 1
    return settings[hi], tested


@app.post("/api/explain")
def explain(state: RoomState) -> dict:
    """A plain-language account of the current room, written by a language model on AMD GPUs."""
    spec = state.spec()
    prediction = ensemble.predict(spec)
    best, _ = lowest_safe(spec)
    try:
        return explaining.explain(spec, prediction, ASSUMPTIONS, best)
    except llm.LanguageModelError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/optimise")
def optimise(state: RoomState) -> dict:
    """The lowest fan setting that keeps the worst point under the limit by the safety margin.

    The settings are bisected, which assumes that more air never makes the worst point
    worse and needs about eight predictions. Set FLOWCAST_SWEEP=1 on a large GPU to predict
    every setting in one batch instead, which makes no such assumption.
    """
    base = state.spec()
    started = time.perf_counter()
    low, high = base.room.ach_range
    settings = [float(ach) for ach in np.linspace(low, high, 137)]
    specs = [CaseSpec(machines=base.machines, ach=ach, room=base.room) for ach in settings]
    if SWEEP:
        passing = [_within_limit(s, p) for s, p in zip(specs, ensemble.predict_many(specs))]
        best = next((i for i, ok in enumerate(passing) if ok), None)
        tested = len(specs)
    else:
        found, tested = lowest_safe(base)
        best = settings.index(found) if found is not None else None
    return {
        "ach": settings[best] if best is not None else settings[-1],
        "feasible": best is not None,
        "tested": tested,
        "seconds": time.perf_counter() - started,
        "device": ensemble.device.type,
        "hardware": HARDWARE,
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
