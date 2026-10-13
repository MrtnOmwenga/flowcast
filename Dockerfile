# The Flowcast site in one image: the web page, the service, and OpenFOAM, so that "verify by
# simulation" can run a real case next to the model.
#
#   podman build -t flowcast .
#   podman run --rm -p 8000:8000 --env-file .env -v ./data:/data:ro,z flowcast
#
# The trained models are mounted, not built in: /data/models, /data/models-ceiling,
# /data/models-cross and /data/models-cabinet, as the training scripts write them.

FROM docker.io/library/node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web ./
RUN npm run build

FROM docker.io/opencfd/openfoam-default:2512

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# Processor build of PyTorch by default. On an AMD GPU host, build with
#   --build-arg TORCH_INDEX=https://download.pytorch.org/whl/rocm6.4
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir torch --index-url ${TORCH_INDEX}

COPY pyproject.toml README.md ./
COPY flowcast ./flowcast
RUN pip install --no-cache-dir ".[api]"
COPY --from=web /web/dist /app/web

ENV FLOWCAST_MODELS=/data/models \
    FLOWCAST_MODELS_CEILING=/data/models-ceiling \
    FLOWCAST_MODELS_CROSS=/data/models-cross \
    FLOWCAST_MODELS_CABINET=/data/models-cabinet \
    FLOWCAST_VERIFY=/tmp/verify \
    FLOWCAST_WEB=/app/web
EXPOSE 8000
# The base image's entrypoint is a shell with the OpenFOAM environment loaded; it takes
# the command the way `bash -c` does.
CMD ["-c", "cd /app && uvicorn flowcast.api.app:app --host 0.0.0.0 --port 8000"]
