"""The Flowcast service: uvicorn flowcast.api.app:app

FLOWCAST_MODELS   directory holding the trained ensemble (default data/models)
FLOWCAST_VERIFY   directory for verification simulations (default data/verify)
"""

from __future__ import annotations

import os
from dataclasses import asdict
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
from . import assistant as assisting
from . import explain as explaining
from . import llm, payload
from . import schedule as scheduling
from .metrics import Assumptions, protected_zone, summarise

MODELS = Path(os.environ.get("FLOWCAST_MODELS", "data/models"))
VERIFY = Path(os.environ.get("FLOWCAST_VERIFY", "data/verify"))
ASSUMPTIONS = Assumptions()
# How far a confirming simulation may differ from the prediction at the worst point
AGREEMENT_TOLERANCE = 0.3
# Confidence falls to 0.6, the point at which the interface says "low", at the ensemble
# disagreement (in log particle level) exceeded by the fifth of held-out rooms where the
# members disagree most. That figure is measured for each set of models and stored beside
# them in meta.json; this is the value used when it is missing.
DEFAULT_LOW_CONFIDENCE_SPREAD = 0.04

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
    threshold = ensemble.meta.get("low_confidence_spread", DEFAULT_LOW_CONFIDENCE_SPREAD)
    return max(0.0, 1.0 - 0.4 * spread / threshold)


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


class PositionRequest(BaseModel):
    state: RoomState
    item: int = Field(ge=1)
    then_fan: bool = True


@app.post("/api/best-position")
def best_position(request: PositionRequest) -> dict:
    """Try one item across the floor, move it to the best place, and optionally re-tune the fan."""
    spec = request.state.spec()
    session = assisting.Session(
        list(spec.machines), spec.ach, spec.room, ensemble, ASSUMPTIONS, lowest_safe,
        max_items=5 if ensemble.meta.get("people") else 3,
    )
    started = time.perf_counter()
    try:
        before = session.result()
        search = session.find_best_position(request.item)
        fan = session.find_lowest_safe_fan() if request.then_fan else None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    final = session.spec()
    return {
        "state": {"machines": [asdict(m) for m in final.machines], "ach": final.ach},
        "item": search["item"],
        "positions_tried": search["positions_tried"],
        "before_percent": before["worst_point_percent_of_limit"],
        "after_percent": search["result"]["worst_point_percent_of_limit"],
        "worst_tried_percent": search["worst_position_tried_percent_of_limit"],
        "fan": fan,
        "seconds": time.perf_counter() - started,
        "hardware": HARDWARE,
    }


class ScheduleRequest(BaseModel):
    state: RoomState
    plan: str = Field(default=scheduling.DEFAULT_PLAN, min_length=10, max_length=3000)


@app.get("/api/schedule/example")
def schedule_example() -> dict:
    return {"plan": scheduling.DEFAULT_PLAN}


@app.post("/api/schedule")
def schedule(request: ScheduleRequest) -> dict:
    """Read a production plan in plain words and return the day's fan schedule and its energy."""
    spec = request.state.spec()
    try:
        return scheduling.build(spec, request.plan, ASSUMPTIONS, lowest_safe)
    except llm.LanguageModelError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=422, detail=f"The plan could not be turned into a schedule: {error}") from error


class Turn(BaseModel):
    role: str
    content: str


class AssistantRequest(BaseModel):
    state: RoomState
    conversation: list[Turn] = Field(min_length=1, max_length=20)


@app.post("/api/assistant")
def assistant(request: AssistantRequest) -> dict:
    """Carry out a typed request: the language model plans, and Flowcast's own tools do the work."""
    spec = request.state.spec()
    session = assisting.Session(
        list(spec.machines), spec.ach, spec.room, ensemble, ASSUMPTIONS, lowest_safe,
        max_items=5 if ensemble.meta.get("people") else 3,
    )
    conversation = [{"role": t.role, "content": t.content} for t in request.conversation if t.role in ("user", "assistant")]
    try:
        outcome = assisting.run(session, conversation)
    except llm.LanguageModelError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    final = session.spec()
    return {
        **outcome,
        "state": {"machines": [asdict(m) for m in final.machines], "ach": final.ach},
        "hosted_on": llm.HOSTED_ON,
    }


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


MAX_CONFIRMATIONS = 5


def _confirm(job_id: str, base: CaseSpec) -> None:
    """The model proposes a fan setting; real simulations check it and step it up until one passes.

    Measured on unseen rooms, about one in five of the model's own recommendations is too
    low, so a recommendation is only called confirmed once a simulation has passed it.
    """
    job = jobs[job_id]
    job["status"] = "running"
    started = time.perf_counter()
    try:
        low, high = base.room.ach_range
        proposed, tested = lowest_safe(base)
        job["predictions"] = tested
        if proposed is None:
            job.update(status="done", confirmed=False, note=f"The model finds no safe setting up to {high:g} air changes an hour.")
            return
        ach = proposed
        for attempt in range(MAX_CONFIRMATIONS):
            spec = CaseSpec(machines=base.machines, ach=ach, room=base.room)
            p = ensemble.predict(spec)
            predicted = summarise(spec, p.fluid, p.particles, p.age, ASSUMPTIONS)
            job["trail"].append({"ach": ach, "predicted_percent": round(100 * predicted["worst_level"] / ASSUMPTIONS.particle_limit),
                                 "simulated_percent": None, "passed": None})
            data = np.load(run_case(spec, VERIFY / f"{job_id}-{attempt}"))
            simulated = summarise(spec, data["fluid"], data["particles"], data["age"], ASSUMPTIONS)
            ratio = simulated["worst_level"] / ASSUMPTIONS.particle_limit
            job["trail"][-1].update(simulated_percent=round(100 * ratio), passed=bool(ratio <= 1))
            if ratio <= 1:
                job.update(
                    status="done", confirmed=True, ach=ach, model_ach=proposed, seconds=time.perf_counter() - started,
                    payload=payload.build(spec, data["fluid"], data["velocity"], data["particles"], data["age"],
                                          ASSUMPTIONS, source="simulation"),
                )
                return
            if ach >= high:
                break
            # The worst point falls roughly in proportion as air is added, so aim just past the limit.
            ach = min(high, max(ach + 0.25, round(ach * ratio * 1.05 * 4) / 4))
        job.update(status="done", confirmed=False, seconds=time.perf_counter() - started,
                   note=f"No setting was confirmed in {len(job['trail'])} simulations.")
    except Exception as error:  # report the failure to the interface instead of losing it
        job.update(status="failed", error=str(error))


@app.post("/api/confirm-fan")
def confirm_fan(state: RoomState) -> dict:
    """Find the lowest safe fan setting with the model, then confirm it with real simulations."""
    spec = state.spec()
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {"id": job_id, "status": "queued", "trail": []}
    simulations.submit(_confirm, job_id, spec)
    return jobs[job_id]


@app.get("/api/verify/{job_id}")
def verification(job_id: str) -> dict:
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="unknown verification")
    return jobs[job_id]
