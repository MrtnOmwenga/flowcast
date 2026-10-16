# Flowcast

**Find the lowest safe fan setting for a ventilated room, in seconds, from a model trained on airflow simulations.**

Cleanrooms, control cabinets and many other enclosed spaces run their fans at a fixed, worst-case
setting because nobody can predict what a lower one would do. A flow simulation could answer,
but each run needs a specialist and hours of computing, so it is done once at design time and
never again. Fan power rises with the cube of airflow: 20% less air saves about half the fan's
power. Flowcast puts that answer within reach of the person who runs the room.

Built for the AMD Developer Hackathon (lablab.ai), Intelligent Industry track.

<!-- Live demo: link added at deployment -->

## What it does

- **Predicts the airflow** in a room from its layout and fan setting: air velocity, the age of the air, and each source's particle level (or heat, in the cabinet). One prediction takes about 0.05 to 0.13 s on an AMD Radeon GPU, depending on the design.
- **Finds the lowest safe fan setting** for the room as it stands, against a named standard (EU GMP Annex 1 grades, ISO 14644-1 classes) or a component temperature rating.
- **Confirms by simulation.** The model proposes a setting, a real OpenFOAM simulation checks it, and the fan steps up until a simulation passes.
- **Finds the best place for an item**, by trying it across the floor.
- **Takes requests in plain words.** A language model on AMD's Token Factory (Gemma 4, with DeepSeek as fallback) plans the steps, and Flowcast's own tools do the work. Every number in an answer comes from a tool, not from the language model.
- **Plans a day.** Paste a production plan; it becomes a fan schedule with lead and clean-up periods, and an energy total.

Two demonstrations ship with it: a **small cleanroom** in three ventilation designs (ceiling panels, filter ceiling, cross-flow), and a **fan-cooled control cabinet**, where heat takes the place of particles.

## How accurate it is

Every figure below is measured on rooms the model never saw during training. "Realistic" rooms
are laid out the way real ones are (machines against walls, people at machines, cabinet
components in rows); "random" rooms place items anywhere.

| Design | Test rooms | Worst point, median error | Air velocity, median error | Same within-limit verdict as the simulation |
|---|---|---|---|---|
| Cleanroom, ceiling panels: random | 267 | 8.9% | 13.7% | 92% |
| Cleanroom, ceiling panels: realistic | 105 | 13.1% | 14.8% | 98% |
| Cleanroom, filter ceiling: random | 194 | 4.2% | 3.3% | 98% |
| Cleanroom, cross-flow: random | 226 | 5.8% | 6.3% | 94% |
| Control cabinet: random | 240 | 9.8% | 12.0% | 94% |
| Control cabinet: realistic | 68 | 13.0% | 14.7% | 94% |

The first models were trained on random layouts only and were about twice as wrong at the worst
point on realistic rooms. Realistic layouts were then simulated and added to training, which
closed most of that gap. The filter-ceiling and cross-flow models have not yet been retrained
this way.

**The simulations themselves** were checked against a published experiment: the IEA Annex 20
room (Nielsen, 1990), whose air velocity was measured by laser. On a fine grid our set-up
reproduces it to within 4.3% of the supply velocity; on the 20 cm grid used for the training
data, to within 10%. See `docs/validation/`.

**Safety margin, measured.** On 100 unseen rooms, the model's recommended setting was confirmed
safe by simulation 81% of the time at the 15% margin it uses. That is not enough to rely on
alone, which is why the search confirms its answer with real simulations.

## Where AMD hardware is used

1. **Our airflow model** is trained and served with PyTorch on ROCm on an AMD Radeon RX 6600.
2. **The language features** use models served on AMD Instinct GPUs through AMD's Token Factory.

The page shows which hardware answered each prediction.

## How it works

```
room layout + fan setting
      │
      ▼
flow network (3D U-Net) ──► air velocity, age of air
      │
      ▼
particle network (3D U-Net, once per source) ──► each source's field for a release of 1 per second
      │
      ▼
scale by each source's release, add up ──► level everywhere, worst point, verdict
```

- **Training data:** 7,000+ rooms simulated with OpenFOAM (steady RANS, k-epsilon turbulence model, 20 cm grid), each with one tracer per source and an age-of-air tracer.
- **Two networks:** the flow network predicts the airflow; the particle network predicts one source's field given that airflow. Because tracers do not change the air, fields add up, so switching a source on or off needs no new prediction.
- **Scaled inputs:** velocity is divided by the supply speed and particle level multiplied by the airflow, so one network covers every fan setting.
- **Ensemble:** two to four networks per design, trained from different random starts. Their average is the prediction; their disagreement is the confidence reading on the page.

## Run it

You need Python 3.12, Node 22, and for training a GPU supported by PyTorch (ROCm or CUDA).
Simulations need OpenFOAM v2512 natively, or podman or docker to run the `opencfd/openfoam-default:2512` image.

```bash
# the service (put AMD_TOKEN_FACTORY_KEY in .env for the language features)
pip install torch --index-url https://download.pytorch.org/whl/rocm6.4   # or the CPU/CUDA index
pip install -e ".[api]"
uvicorn flowcast.api.app:app --port 8000

# the page
cd web && npm ci && npm run dev

# simulate a batch of rooms, then train
python -m flowcast.sim.batch --room panels --count 1500 --out data/cases
python -m flowcast.model.train --task flow --data data/cases --out data/models/flow/0
python -m flowcast.model.train --task particles --data data/cases --out data/models/particles/0
python -m flowcast.model.evaluate --data data/cases --models data/models
```

Or the whole site in one container, with the trained models mounted from `./data`:

```bash
podman build -t flowcast .
podman run --rm -p 8000:8000 --env-file .env -v ./data:/data:ro,z flowcast
```

## Repository

| Folder | Contents |
|---|---|
| `flowcast/sim` | Room designs, layout sampling, OpenFOAM case writing, batch runner, the Annex 20 check |
| `flowcast/model` | Feature scaling, the networks, training, the ensemble, evaluation, the margin study |
| `flowcast/api` | The service: predictions, search, verification, standards, heat, the agent, explanations, day planning |
| `web` | The site: TypeScript and three.js |
| `docs/validation` | The Annex 20 measurements, results and chart |
| `deploy/aws` | Scripts to host the demo on one AMD EPYC machine |

## Limits

- It is a screening and planning tool. It does not replace the tests a regulated room must pass.
- Each room design has its own trained models; a new kind of room needs new simulations and training.
- The training grid is coarse (20 cm). It is the largest single source of error, and a finer training set is the next step.
- People are fixed blocks that release particles, heat is left out of the cleanroom, and release rates are assumptions stated on the page.

## Licence

MIT. See `LICENSE`, and `NOTICE.md` for the software, models and data it uses.
