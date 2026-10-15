# Notices

Flowcast's own code is released under the MIT License (see `LICENSE`). It uses the following
work by others.

## Software it imports or bundles

| Component | Licence | Use |
|---|---|---|
| [PyTorch](https://pytorch.org) (ROCm build) | BSD-3-Clause | Training and running the airflow model |
| [NumPy](https://numpy.org) | BSD-3-Clause, with parts under 0BSD, MIT and Zlib | Arrays |
| [FastAPI](https://fastapi.tiangolo.com), [Starlette](https://www.starlette.io) | MIT, BSD-3-Clause | The web service |
| [Uvicorn](https://www.uvicorn.org) | BSD-3-Clause | The web server |
| [Pydantic](https://docs.pydantic.dev) | MIT | Request checking |
| [three.js](https://threejs.org) | MIT | The 3D view in the browser |

## Software it runs as a separate program

| Component | Licence | Use |
|---|---|---|
| [OpenFOAM](https://www.openfoam.com) v2512, from the `opencfd/openfoam-default` container image | GPL-3.0 | Producing the training data and the "verify by simulation" check |
| [Caddy](https://caddyserver.com) | Apache-2.0 | HTTPS in front of the public demo |

Flowcast writes OpenFOAM's input files and reads its output files. It does not modify, link to
or redistribute OpenFOAM's source code. The container image built from the `Dockerfile` starts
from the OpenFOAM image, and anyone distributing that image takes on OpenFOAM's GPL obligations
for the OpenFOAM part.

## Models it calls

The plain-language features call language models served by AMD's Token Factory over its API.
No model weights are included in this repository.

- **Gemma 4** (Google): used under the [Gemma Terms of Use](https://ai.google.dev/gemma/terms).
- **DeepSeek** (DeepSeek AI): the fallback when Gemma is unavailable, used under DeepSeek's licence terms.

## Data

`docs/validation/annex20-measurements.json` holds laser-Doppler measurements from P. V. Nielsen,
*Specification of a Two-Dimensional Test Case*, IEA Annex 20, Aalborg University, 1990
(ISSN 0902-7513 R9040), as published by Aalborg University at
<https://www.en.build.aau.dk/web/cfd-benchmarks/two-dimensional-benchmark-test>. They are used to
check the simulation set-up and are credited wherever they are shown.

All other data in this project (the simulated rooms and the trained models) was produced by
this project.
