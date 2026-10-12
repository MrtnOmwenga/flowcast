import { FACTS } from "../facts";

function box(x: number, y: number, w: number, h: number, title: string, lines: string[], tone = "plain"): string {
  const text = lines.map((line, i) => `<text x="${x + w / 2}" y="${y + 46 + i * 17}" class="d-line">${line}</text>`).join("");
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="10" class="d-box ${tone}"/><text x="${x + w / 2}" y="${y + 25}" class="d-title">${title}</text>${text}`;
}

function diagram(): string {
  return `
  <svg class="diagram" viewBox="0 0 1040 520" role="img" aria-label="Architecture diagram: simulations train an ensemble of networks, which a service uses to answer the interface, with a real simulation available as a check.">
    <defs>
      <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" class="d-head"/></marker>
    </defs>
    <text x="20" y="28" class="d-band">Build the model, once per kind of room</text>
    ${box(20, 44, 170, 96, "Layout sampler", ["random machines,", "positions, fan settings"])}
    ${box(230, 44, 190, 96, "OpenFOAM", [`${FACTS.rooms} rooms simulated,`, "about a minute each"], "sim")}
    ${box(460, 44, 170, 96, "Grid dataset", ["velocity, air age,", "per-machine particles"])}
    ${box(670, 44, 170, 96, "Training", ["PyTorch on an", "AMD GPU with ROCm"], "gpu")}
    <path d="M190 92 H228" class="d-arrow"/><path d="M420 92 H458" class="d-arrow"/><path d="M630 92 H668" class="d-arrow"/>

    <text x="20" y="212" class="d-band">The model: an ensemble of chained networks</text>
    ${box(460, 228, 170, 96, "Flow network", ["layout + fan setting", "→ velocity, air age"], "model")}
    ${box(670, 228, 170, 96, "Particle network", ["one machine + airflow", "→ its particle field"], "model")}
    <path d="M630 276 H668" class="d-arrow"/>
    <path d="M755 140 V226" class="d-arrow"/>
    <text x="766" y="188" class="d-note">trained weights</text>
    <text x="880" y="262" class="d-note">several copies:</text>
    <text x="880" y="279" class="d-note">their spread is</text>
    <text x="880" y="296" class="d-note">the confidence</text>

    <text x="20" y="396" class="d-band">Answer questions, live</text>
    ${box(20, 412, 190, 96, "Interface", ["3D room in the browser,", "TypeScript and three.js"])}
    ${box(290, 412, 220, 96, "Service", ["predict · lowest safe setting", "· verify (FastAPI)"])}
    ${box(590, 412, 190, 96, "OpenFOAM check", ["a real simulation of", "the room as set"], "sim")}
    <path d="M210 448 H288" class="d-arrow"/><path d="M288 474 H210" class="d-arrow"/>
    <text x="249" y="440" class="d-note mid">layout</text><text x="249" y="494" class="d-note mid">fields</text>
    <path d="M510 448 H588" class="d-arrow"/><path d="M588 474 H510" class="d-arrow"/>
    <text x="549" y="440" class="d-note mid">verify</text><text x="549" y="494" class="d-note mid">compare</text>
    <path d="M400 412 V300 Q400 276 424 276 H458" class="d-arrow"/>
    <text x="318" y="352" class="d-note">runs the</text><text x="318" y="369" class="d-note">ensemble</text>
    <path d="M840 480 H960 Q984 480 984 456 V116 Q984 92 960 92 H842" class="d-arrow dashed"/>
    <path d="M780 480 H840" class="d-arrow dashed nohead"/>
    <text x="1002" y="286" class="d-note mid" transform="rotate(90 1002 286)">verified rooms become training data (planned)</text>
  </svg>`;
}

export function architecture(): string {
  return `
  <article class="prose wide">
    <p class="eyebrow">Architecture</p>
    <h1>Simulate in bulk, learn the pattern, answer instantly, check against the real thing.</h1>
    ${diagram()}

    <h2>1. Build the model</h2>
    <table>
      <thead><tr><th>Part</th><th>What it does</th><th>Built with</th></tr></thead>
      <tbody>
        <tr><td>Layout sampler</td><td>Draws random room states: up to three machines from five equipment types, placed on a 0.2 m floor grid, with fan settings from 6 to 40 air changes an hour.</td><td>Python</td></tr>
        <tr><td>Case generator</td><td>Turns one room state into an OpenFOAM case. The room is one block of uniform cells and each machine is cut out of it, so every layout shares the same grid.</td><td>Python, OpenFOAM v2512</td></tr>
        <tr><td>Simulation</td><td>Solves the steady airflow, then carries one particle tracer per machine and an "age of air" tracer through it.</td><td>simpleFoam, k-epsilon</td></tr>
        <tr><td>Batch runner</td><td>Runs many rooms side by side, skips finished ones, and logs failures without stopping.</td><td>Python</td></tr>
        <tr><td>Training</td><td>Trains each network several times from different random starts to form the ensemble.</td><td>PyTorch on an AMD GPU with ROCm</td></tr>
      </tbody>
    </table>

    <h2>2. The model</h2>
    <p>Both networks are 3D U-Nets over the room's 30 by 20 by 15 grid.</p>
    <ul>
      <li><b>The flow network</b> takes the solid cells and the fan setting and returns the air velocity and the age of the air.</li>
      <li><b>The particle network</b> takes one machine's release point and that airflow, and returns the particle field for that machine alone.</li>
      <li><b>Everything is dimensionless.</b> Velocity is divided by the supply speed and particle level multiplied by the flow rate, so the networks see similar numbers at every fan setting.</li>
      <li><b>Fields add up.</b> Particles do not affect the airflow, so the level for any set of running machines is the sum of their separate fields. Switching a machine on or off in the interface is an addition in the browser, not a new prediction.</li>
      <li><b>Each ensemble member runs end to end,</b> its own airflow feeding its own particle network. The spread between members is reported as confidence.</li>
    </ul>

    <h2>3. Answering questions</h2>
    <table>
      <thead><tr><th>Request</th><th>What happens</th></tr></thead>
      <tbody>
        <tr><td>Predict</td><td>The service runs the ensemble for the layout and returns the fields, the worst point, the stagnant fraction, fan power and confidence.</td></tr>
        <tr><td>Lowest safe setting</td><td>On a GPU, all 137 fan settings are predicted in one batch and the lowest safe one is returned. On a processor the settings are bisected instead.</td></tr>
        <tr><td>Verify</td><td>A real OpenFOAM simulation of the room is run in the background. The result is compared with the prediction, and a disagreement withdraws the recommendation.</td></tr>
      </tbody>
    </table>

    <h2>Design decisions worth knowing</h2>
    <ul>
      <li><b>A single return wall.</b> With extracts on both end walls the room was symmetric and its supply jets could settle into several lopsided patterns. Moving a machine 0.2 m changed the whole room's airflow by 65%, which no model can learn. One return wall gives the air a single way out and a pattern that shifts smoothly.</li>
      <li><b>A coarse grid.</b> At 0.2 m cells a simulation settles fully in ${FACTS.simulationSeconds}, which is what made ${FACTS.rooms} rooms affordable. The price is less detail in the supply jets.</li>
      <li><b>A safety margin.</b> A setting is recommended only if the predicted worst point is 15% under the limit, about the model's error there. Within 15% either side, the interface says the result is too close to call.</li>
    </ul>

    <p class="cta"><a class="button" href="#/demos/cleanroom">Open the cleanroom demo</a> <a class="button secondary" href="${FACTS.repository}" target="_blank" rel="noopener">Read the code</a></p>
  </article>`;
}
