"""Runs an OpenFOAM case, natively if OpenFOAM is installed, otherwise in a container."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from .case import commands, write_case
from .export import export_case
from .spec import CaseSpec

IMAGE = os.environ.get("FLOWCAST_OPENFOAM_IMAGE", "docker.io/opencfd/openfoam-default:2512")


def run_case(spec: CaseSpec, case_dir: Path, keep_case: bool = False) -> Path:
    """Simulate one room state and return the path of the exported grid file."""
    case_dir = Path(case_dir).resolve()
    write_case(spec, case_dir)
    script = " && ".join(commands(spec))
    started = time.monotonic()
    result = _run_openfoam(script, case_dir)
    (case_dir / "log.run").write_text(result.stdout + result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"OpenFOAM failed in {case_dir}; see the log files there")
    out = export_case(case_dir, runtime=time.monotonic() - started)
    if not keep_case:
        _clean(case_dir)
    return out


def _run_openfoam(script: str, case_dir: Path) -> subprocess.CompletedProcess:
    if shutil.which("simpleFoam"):
        return subprocess.run(["bash", "-c", script], cwd=case_dir, capture_output=True, text=True)
    engine = shutil.which("podman") or shutil.which("docker")
    if engine is None:
        raise RuntimeError("OpenFOAM is not installed and neither podman nor docker was found")
    # The image's entrypoint changes to $HOME, so the case is mounted there.
    cmd = [engine, "run", "--rm"]
    if Path(engine).name == "podman":
        cmd += ["--userns=keep-id", "--user", f"{os.getuid()}:{os.getgid()}"]
    cmd += ["--volume", f"{case_dir}:/home/openfoam:z", IMAGE, "-c", f"cd /home/openfoam && {script}"]
    return subprocess.run(cmd, capture_output=True, text=True)


def _clean(case_dir: Path) -> None:
    """Remove the bulky mesh and field directories, keeping the settings, logs and result."""
    for child in case_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
