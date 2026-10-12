"""Writes an OpenFOAM case directory for a CaseSpec.

The room is one block of uniform cells. Machines are cut out of the mesh, so every
layout shares the same grid and a layout is fully described by which cells are solid.
Each machine gets its own particle tracer, released at a fixed rate from the cells just
above it, and a further scalar tracks the age of the air to show where it stagnates.
"""

from __future__ import annotations

from pathlib import Path

from .spec import CaseSpec

NU_AIR = 1.5e-5
EPS = 1e-3  # tolerance used to select faces lying on a wall plane

# Commands that build the mesh, in the order they must run. The starting fields are
# copied in afterwards because the mesh tools rewrite field files and drop new patches.
MESH_COMMANDS = (
    "blockMesh",
    "topoSet -dict system/topoSetDict.cells",
    "subsetMesh fluid -patch equipment -overwrite",
    "topoSet -dict system/topoSetDict.faces",
    "createPatch -overwrite",
    # createPatch discards existing sets, so the particle source cells are selected last
    "topoSet -dict system/topoSetDict.sources",
)
SOLVE_COMMANDS = (
    "rm -rf 0 && cp -r 0.orig 0",
    "simpleFoam",
    "postProcess -func writeCellCentres -latestTime",
)


def write_case(spec: CaseSpec, case_dir: Path) -> None:
    spec.validate()
    case_dir = Path(case_dir)
    for sub in ("0.orig", "constant", "system"):
        (case_dir / sub).mkdir(parents=True, exist_ok=True)
    (case_dir / "spec.json").write_text(spec.to_json())

    files = {
        "system/blockMeshDict": _block_mesh(spec),
        "system/topoSetDict.cells": _topo_cells(spec),
        "system/topoSetDict.faces": _topo_faces(spec),
        "system/topoSetDict.sources": _topo_sources(spec),
        "system/createPatchDict": _create_patch(),
        "system/controlDict": _control(spec),
        "system/fvSchemes": _FV_SCHEMES.replace("@CONVECTION@", _CONVECTION[spec.convection]),
        "system/fvSolution": _FV_SOLUTION,
        "constant/transportProperties": f"transportModel Newtonian;\nnu {NU_AIR};\n",
        "constant/turbulenceProperties": "simulationType RAS;\nRAS { RASModel kEpsilon; turbulence on; printCoeffs off; }\n",
    }
    files.update({f"0.orig/{name}": text for name, text in _fields(spec).items()})
    for rel, body in files.items():
        cls = _FIELD_CLASS.get(rel.split("/")[-1], "dictionary") if rel.startswith("0.orig") else "dictionary"
        (case_dir / rel).write_text(_header(cls, rel.split("/")[-1].split(".")[0]) + body)


def commands(spec: CaseSpec) -> list[str]:
    """Shell commands that mesh and solve the case, each logging to log.<tool>."""
    mesh = list(MESH_COMMANDS)
    if not spec.machines:
        mesh = [c for c in mesh if not c.startswith("subsetMesh")]
    out = []
    for i, cmd in enumerate([*mesh, *SOLVE_COMMANDS]):
        tool = cmd.split()[0]
        out.append(cmd if tool == "rm" else f"{cmd} > log.{i:02d}.{tool} 2>&1")
    return out


def _header(cls: str, obj: str) -> str:
    return f"FoamFile\n{{\n    version 2.0;\n    format ascii;\n    class {cls};\n    object {obj};\n}}\n\n"


def _vec(v) -> str:
    return "(" + " ".join(f"{x:g}" for x in v) + ")"


def _block_mesh(spec: CaseSpec) -> str:
    lx, ly, lz = spec.room.size
    nx, ny, nz = spec.room.shape
    return f"""scale 1;
vertices ((0 0 0)({lx} 0 0)({lx} {ly} 0)(0 {ly} 0)(0 0 {lz})({lx} 0 {lz})({lx} {ly} {lz})(0 {ly} {lz}));
blocks (hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1));
boundary
(
    walls {{ type wall; faces ((0 3 2 1)(4 5 6 7)(0 1 5 4)(3 7 6 2)(0 4 7 3)(1 2 6 5)); }}
    equipment {{ type wall; faces (); }}
);
"""


def _topo_cells(spec: CaseSpec) -> str:
    lx, ly, lz = spec.room.size
    actions = [
        f"    {{ name fluid; type cellSet; action new; source boxToCell; box (-1 -1 -1)({lx + 1} {ly + 1} {lz + 1}); }}"
    ]
    for m in spec.machines:
        b = m.box
        actions.append(
            f"    {{ name fluid; type cellSet; action subtract; source boxToCell; box {_vec(b.lo)}{_vec(b.hi)}; }}"
        )
    return "actions\n(\n" + "\n".join(actions) + "\n);\n"


def _source_box(spec: CaseSpec, index: int) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Two layers of cells directly above a machine, where its particles are released."""
    b = spec.machines[index].box
    top = b.hi[2]
    return (b.x, b.y, top), (b.hi[0], b.hi[1], top + 2 * spec.room.cell)


def _topo_faces(spec: CaseSpec) -> str:
    room = spec.room
    lx, _, lz = room.size
    actions = []
    for i, (x, y, sx, sy) in enumerate(room.supplies):
        action = "new" if i == 0 else "add"
        actions.append(
            f"    {{ name inletFaces; type faceSet; action {action}; source boxToFace; "
            f"box ({x} {y} {lz - EPS})({x + sx} {y + sy} {lz + EPS}); }}"
        )
    y0, y1 = room.extract_y
    walls = [x for name, x in (("x0", 0.0), ("x1", lx)) if name in room.extract_walls]
    for i, x in enumerate(walls):
        action = "new" if i == 0 else "add"
        actions.append(
            f"    {{ name outletFaces; type faceSet; action {action}; source boxToFace; "
            f"box ({x - EPS} {y0} 0)({x + EPS} {y1} {room.extract_height}); }}"
        )
    return "actions\n(\n" + "\n".join(actions) + "\n);\n"


def _topo_sources(spec: CaseSpec) -> str:
    actions = []
    for i in range(len(spec.machines)):
        lo, hi = _source_box(spec, i)
        actions.append(f"    {{ name source{i}; type cellSet; action new; source boxToCell; box {_vec(lo)}{_vec(hi)}; }}")
    return "actions\n(\n" + "\n".join(actions) + "\n);\n"


def _create_patch() -> str:
    return """pointSync false;
patches
(
    { name inlet; patchInfo { type patch; } constructFrom set; set inletFaces; }
    { name outlet; patchInfo { type patch; } constructFrom set; set outletFaces; }
);
"""


def _tracer(name: str, source: str) -> str:
    return f"""    {name}
    {{
        type scalarTransport;
        libs (solverFunctionObjects);
        field {name};
        writeControl writeTime;
        alphaD 1;
        alphaDt 1.43;
        nCorr 0;
        schemesField s;
        fvOptions
        {{
            source
            {{
                type scalarSemiImplicitSource;
                {source}
                sources {{ {name} {{ explicit 1; implicit 0; }} }}
            }}
        }}
    }}
"""


def _control(spec: CaseSpec) -> str:
    # One tracer per machine, each released at one unit per second. The flow does not
    # depend on the particles, so the field for any combination of running machines is
    # the weighted sum of these, and one simulation covers every on/off state.
    tracers = "".join(
        _tracer(f"s{i}", f"selectionMode cellSet; cellSet source{i}; volumeMode absolute;")
        for i in range(len(spec.machines))
    )
    tracers += _tracer("age", "selectionMode all; volumeMode specific;")
    averaged = "\n".join(
        f"            {name} {{ mean on; prime2Mean off; base time; }}"
        for name in ("U", "age", *(f"s{i}" for i in range(len(spec.machines))))
    )
    start = spec.steps - spec.average_last
    return f"""application simpleFoam;
startFrom startTime;
startTime 0;
stopAt endTime;
endTime {spec.steps};
deltaT 1;
writeControl timeStep;
writeInterval {spec.steps};
purgeWrite 1;
writeFormat ascii;
writePrecision 7;
timeFormat general;
timePrecision 6;
runTimeModifiable false;

functions
{{
{tracers}    average
    {{
        type fieldAverage;
        libs (fieldFunctionObjects);
        timeStart {start};
        writeControl writeTime;
        fields
        (
{averaged}
        );
    }}
}}
"""


_FV_SCHEMES = """ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; }
divSchemes
{
    default none;
    div(phi,U) @CONVECTION@;
    div(phi,k) bounded Gauss upwind;
    div(phi,epsilon) bounded Gauss upwind;
    div(phi,s) bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
"""

_CONVECTION = {
    "linearUpwind": "bounded Gauss linearUpwind grad(U)",
    "upwind": "bounded Gauss upwind",
}

_FV_SOLUTION = """solvers
{
    p { solver GAMG; smoother GaussSeidel; tolerance 1e-7; relTol 0.05; }
    "(U|k|epsilon|age|s.*)" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0.1; }
}
SIMPLE
{
    nNonOrthogonalCorrectors 0;
    consistent yes;
}
relaxationFactors
{
    equations { U 0.9; ".*" 0.8; }
    fields { p 0.5; }
}
"""

_FIELD_CLASS = {"U": "volVectorField"}


def _fields(spec: CaseSpec) -> dict[str, str]:
    speed = spec.supply_speed
    k = 1.5 * (0.05 * speed) ** 2
    eps = 0.09**0.75 * k**1.5 / 0.07  # mixing length of 7% of a one-metre supply panel
    wall = "type zeroGradient;"

    def fld(dims: str, internal: str, inlet: str, outlet: str, walls: str) -> str:
        return f"""dimensions {dims};
internalField {internal};
boundaryField
{{
    inlet {{ {inlet} }}
    outlet {{ {outlet} }}
    walls {{ {walls} }}
    equipment {{ {walls} }}
}}
"""

    def scalar(dims: str, value: float, wall_bc: str) -> str:
        return fld(
            dims,
            f"uniform {value:g}",
            f"type fixedValue; value uniform {value:g};",
            f"type inletOutlet; inletValue uniform {value:g}; value uniform {value:g};",
            wall_bc,
        )

    fields = {
        "U": fld(
            "[0 1 -1 0 0 0 0]",
            "uniform (0 0 0)",
            f"type fixedValue; value uniform (0 0 {-speed:g});",
            "type inletOutlet; inletValue uniform (0 0 0); value uniform (0 0 0);",
            "type noSlip;",
        ),
        "p": fld("[0 2 -2 0 0 0 0]", "uniform 0", wall, "type fixedValue; value uniform 0;", wall),
        "k": scalar("[0 2 -2 0 0 0 0]", k, f"type kqRWallFunction; value uniform {k:g};"),
        "epsilon": scalar("[0 2 -3 0 0 0 0]", eps, f"type epsilonWallFunction; value uniform {eps:g};"),
        "nut": fld(
            "[0 2 -1 0 0 0 0]",
            "uniform 0",
            "type calculated; value uniform 0;",
            "type calculated; value uniform 0;",
            "type nutkWallFunction; value uniform 0;",
        ),
        "age": scalar("[0 0 1 0 0 0 0]", 0.0, wall),
    }
    for i in range(len(spec.machines)):
        fields[f"s{i}"] = scalar("[0 0 0 0 0 0 0]", 0.0, wall)
    for name in fields:
        _FIELD_CLASS.setdefault(name, "volScalarField")
    return fields
