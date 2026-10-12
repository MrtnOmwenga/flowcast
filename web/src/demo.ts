import { api, type Verification } from "./api";
import { Fields } from "./field";
import { RoomScene, overlaps, type SliceMode } from "./scene";
import { startTutorial } from "./tutorial";
import type { Machine, Payload, RoomState } from "./types";

const CATALOGUE: Record<string, [number, number, number]> = {
  Workbench: [1.6, 0.8, 1.0],
  Cabinet: [0.8, 0.6, 1.8],
  "Filling machine": [1.2, 1.0, 1.4],
  "Small unit": [0.6, 0.6, 1.0],
  Isolator: [2.0, 0.8, 1.6],
  "Shelving rack": [1.2, 0.4, 2.0],
  Cart: [0.8, 0.6, 0.8],
};
const PERSON: [number, number, number] = [0.4, 0.4, 1.8];
// The limits the served models were trained within. Models trained with people allow more.
const LIMITS = { basic: { items: 3, kinds: ["Workbench", "Cabinet", "Filling machine", "Small unit", "Isolator"] } };
const ACH_MIN = 6;
const ACH_MAX = 40;
const TOUR_SEEN = "flowcast-tour-seen";

let view: HTMLElement;
let panel: HTMLElement;
let scene: RoomScene | null = null;

let state: RoomState = { machines: [], ach: 20 };
let fields: Fields | null = null;
let payload: Payload | null = null;
let online = false;
let sliceMode: SliceMode = "particles";
let sliceHeight = 1.1;
let busy = "";
let note = "";
let verification: Verification | null = null;
let people = false; // whether the served models were trained on rooms with people

// Only one prediction request runs at a time; a newer state replaces any that is waiting.
let inFlight = false;
let queued = false;

export function mount(root: HTMLElement): void {
  if (scene) return;
  root.innerHTML = `<div id="view"></div><aside id="panel"></aside>`;
  view = root.querySelector<HTMLElement>("#view")!;
  panel = root.querySelector<HTMLElement>("#panel")!;
  scene = new RoomScene(view);
  scene.onMove = (machines, finished) => {
    state = { ...state, machines };
    if (finished) render();
    verification = null;
    void refresh();
  };
  void start();
}

export function setActive(active: boolean): void {
  scene?.setActive(active);
}

async function refresh(): Promise<void> {
  if (!online) return;
  if (inFlight) {
    queued = true;
    return;
  }
  inFlight = true;
  try {
    const requested = JSON.stringify(state);
    const result = await api.predict(state);
    if (!sameLayout(result.machines, state.machines)) queued = true;
    apply(result, requested === JSON.stringify(state));
  } catch (error) {
    note = `The service did not answer: ${(error as Error).message}`;
    render();
  } finally {
    inFlight = false;
    if (queued) {
      queued = false;
      void refresh();
    }
  }
}

function sameLayout(a: Machine[], b: Machine[]): boolean {
  return a.length === b.length && a.every((m, i) => m.x === b[i].x && m.y === b[i].y && m.sx === b[i].sx && m.sy === b[i].sy);
}

function apply(result: Payload, current: boolean): void {
  payload = result;
  fields = new Fields(result);
  fields.combine(state.machines);
  scene!.setFields(fields);
  if (current) scene!.setMarker(fields.worst(state.machines).position);
  render();
}

function changed(layoutChanged: boolean): void {
  verification = null;
  note = "";
  if (!layoutChanged && fields) {
    // Switching a machine on or off needs no new prediction: its field is already loaded.
    fields.combine(state.machines);
    scene!.updateSlice();
    scene!.setMarker(fields.worst(state.machines).position);
    render();
    return;
  }
  render();
  void refresh();
}

function maxItems(): number {
  return people ? 5 : LIMITS.basic.items;
}

function choices(): string[] {
  return people ? [...Object.keys(CATALOGUE), "Person"] : LIMITS.basic.kinds;
}

function rotate(index: number): void {
  const m = state.machines[index];
  if (!fields || m.sx === m.sy) return;
  const turned = { ...m, sx: m.sy, sy: m.sx };
  const [lx, ly] = fields.size;
  turned.x = round(Math.min(turned.x, lx - turned.sx));
  turned.y = round(Math.min(turned.y, ly - turned.sy));
  if (state.machines.some((other, i) => i !== index && overlaps(turned, other))) {
    note = "There is no room to turn it here. Move it clear of the other items first.";
    render();
    return;
  }
  state = { ...state, machines: state.machines.map((k, i) => (i === index ? turned : k)) };
  scene!.setMachines(state.machines);
  changed(true);
}

function addMachine(kind: string): void {
  if (state.machines.length >= maxItems() || !fields) return;
  const person = kind === "Person";
  const [sx, sy, sz] = person ? PERSON : CATALOGUE[kind];
  const [lx, ly] = fields.size;
  for (let x = 0; x <= lx - sx + 1e-6; x += 0.2) {
    for (let y = 0; y <= ly - sy + 1e-6; y += 0.2) {
      const machine: Machine = { x: round(x), y: round(y), sx, sy, sz, on: true, emission: 1, kind: person ? "person" : "machine" };
      if (!state.machines.some((other) => overlaps(machine, other))) {
        state = { ...state, machines: [...state.machines, machine] };
        scene!.setMachines(state.machines);
        changed(true);
        return;
      }
    }
  }
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}

function number(value: number, digits = 0): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function render(): void {
  if (!fields || !payload) {
    panel.innerHTML = `<h1>Cleanroom demo</h1><p class="muted">Loading the room…</p>`;
    return;
  }
  const scroll = panel.scrollTop;
  const a = payload.assumptions;
  const power = a.full_fan_power_kw * (state.ach / a.full_ach) ** 3;
  const saving = a.full_fan_power_kw - power;
  const worst = fields.worst(state.machines);
  const ratio = worst.level / a.particle_limit;
  // Within the safety margin either side of the limit, the model's error could change the answer.
  const verdict = ratio <= 1 - a.safety_margin ? "ok" : ratio <= 1 + a.safety_margin ? "close" : "bad";
  const bar = Math.min(100, ((Math.log10(Math.max(ratio, 0.01)) + 2) / 2.5) * 100);
  const stale = !sameLayout(payload.machines, state.machines);
  const confidence = payload.metrics.confidence;

  panel.innerHTML = `
    <div class="title">
      <h1>Cleanroom demo</h1>
      <button class="ghost" id="tour">How to use this</button>
    </div>
    <p class="muted">A 6 by 4 metre cleanroom. Move the equipment, switch machines on and off, change the fan setting, and see what the air does.</p>
    ${online ? "" : `<p class="warn">Showing one stored simulation. The prediction service is not connected.</p>`}
    ${note ? `<p class="warn">${note}</p>` : ""}

    <section data-tour="fan">
      <label>Fan setting <b>${number(state.ach, 1)}</b> air changes an hour</label>
      <input id="ach" type="range" min="${ACH_MIN}" max="${ACH_MAX}" step="0.5" value="${state.ach}" />
      <div class="row"><button id="optimise" ${online && !busy ? "" : "disabled"}>Find the lowest safe setting</button></div>
    </section>

    <section class="readouts" data-tour="readouts">
      <div class="status ${verdict}">${verdict === "ok" ? "Within the particle limit" : verdict === "close" ? "Too close to the limit to call: verify" : "Over the particle limit"}${stale ? " (updating…)" : ""}</div>
      <div class="meter"><div class="fill ${verdict}" style="width:${bar}%"></div><div class="tick"></div></div>
      <dl>
        <dt>Worst point in the occupied zone</dt><dd>${number(worst.level)} <small>/ m³ (limit ${number(a.particle_limit)})</small></dd>
        <dt>Fan power</dt><dd>${number(power, 2)} kW <small>of ${number(a.full_fan_power_kw, 1)} kW at full speed</small></dd>
        <dt>Saving</dt><dd>${number((saving / a.full_fan_power_kw) * 100)}% <small>${number(saving * a.hours_per_year)} kWh, $${number(saving * a.hours_per_year * a.electricity_price)} a year</small></dd>
        <dt>Stagnant air</dt><dd>${number(payload.metrics.stagnant_fraction * 100, 1)}% <small>of the room</small></dd>
        ${confidence === undefined ? "" : `<dt>Model confidence</dt><dd class="${confidence < 0.6 ? "amber" : ""}">${confidence < 0.6 ? "Low: verify before relying on it" : "Good"}</dd>`}
      </dl>
      <p class="muted small">The red marker is the worst point: the place for a particle counter.</p>
      <p class="compute">${payload.source !== "model" || !payload.compute ? "OpenFOAM simulation" : `${payload.compute.models} models on ${payload.compute.hardware} · ${number(payload.compute.seconds * 1000)} ms`}</p>
    </section>

    <section data-tour="equipment">
      <h2>Equipment</h2>
      ${state.machines.map((m, i) => `
        <div class="machine">
          <label><input type="checkbox" data-toggle="${i}" ${m.on ? "checked" : ""}/> ${nameOf(m)} <small>${m.kind === "person" ? (m.on ? "present" : "away") : m.on ? "running" : "off"}</small></label>
          <span>${m.sx === m.sy ? "" : `<button class="link" data-rotate="${i}">turn</button> `}<button class="link" data-remove="${i}">remove</button></span>
        </div>`).join("") || `<p class="muted small">The room is empty.</p>`}
      ${state.machines.length < maxItems() ? `<select id="add"><option value="">Add ${people ? "equipment or a person" : "equipment"}…</option>${choices().map((k) => `<option>${k}</option>`).join("")}</select>` : `<p class="muted small">The model was trained on rooms with up to ${maxItems()} items.</p>`}
    </section>

    <section data-tour="view">
      <h2>View</h2>
      <div class="row">
        ${(["particles", "age", "off"] as SliceMode[]).map((m) => `<button class="chip ${sliceMode === m ? "active" : ""}" data-slice="${m}">${m === "particles" ? "Particle level" : m === "age" ? "Stagnant air" : "No slice"}</button>`).join("")}
      </div>
      <label>Slice height <b>${number(sliceHeight, 1)}</b> m</label>
      <input id="height" type="range" min="0.1" max="${fields.size[2] - 0.1}" step="0.2" value="${sliceHeight}" />
    </section>

    <section data-tour="verify">
      <h2>Check against a real simulation</h2>
      <div class="row"><button id="verify" ${online && !busy ? "" : "disabled"}>Verify by simulation</button></div>
      ${busy ? `<p class="muted small">${busy}</p>` : ""}
      ${verificationHtml()}
    </section>

    <section>
      <h2>Assumptions</h2>
      <p class="muted small">A running machine releases ${number(a.machine_emission)} particles a second${people ? ` and a person ${number(a.person_emission)}` : ""}. The limit is ISO class 7 (${number(a.particle_limit)} per m³), applied up to ${number(a.occupied_height, 1)} m. Fan power follows the cube of airflow from ${number(a.full_fan_power_kw, 1)} kW at ${number(a.full_ach)} air changes an hour. Electricity at $${number(a.electricity_price, 2)} per kWh.</p>
    </section>
  `;
  panel.scrollTop = scroll;
  bind();
}

function verificationHtml(): string {
  const v = verification;
  if (!v) return "";
  if (v.status === "failed") return `<p class="warn">The simulation failed.</p>`;
  if (v.status !== "done" || !v.predicted || !v.simulated) return `<p class="muted small">Simulation ${v.status}…</p>`;
  const gap = ((v.predicted.worst_level - v.simulated.worst_level) / v.simulated.worst_level) * 100;
  return `<div class="status ${v.agrees ? "ok" : "bad"}">${v.agrees ? "Confirmed by simulation" : "The simulation disagrees: do not rely on this prediction"}</div>
    <dl>
      <dt>Worst point, predicted</dt><dd>${number(v.predicted.worst_level)}</dd>
      <dt>Worst point, simulated</dt><dd>${number(v.simulated.worst_level)} <small>(${gap >= 0 ? "+" : ""}${number(gap)}%)</small></dd>
      <dt>Simulation time</dt><dd>${number(v.seconds ?? 0)} s</dd>
    </dl>`;
}

function nameOf(m: Machine): string {
  if (m.kind === "person") return "Person";
  for (const [name, [sx, sy, sz]] of Object.entries(CATALOGUE)) {
    if (sz === m.sz && ((sx === m.sx && sy === m.sy) || (sx === m.sy && sy === m.sx))) return name;
  }
  return "Machine";
}

function bind(): void {
  const ach = panel.querySelector<HTMLInputElement>("#ach")!;
  ach.addEventListener("input", () => {
    state = { ...state, ach: Number(ach.value) };
    // Update the label in place so the slider keeps the pointer while it is dragged.
    ach.previousElementSibling!.querySelector("b")!.textContent = number(state.ach, 1);
    verification = null;
    void refresh();
  });
  ach.addEventListener("change", () => render());
  panel.querySelectorAll<HTMLInputElement>("[data-toggle]").forEach((box) =>
    box.addEventListener("change", () => {
      const i = Number(box.dataset.toggle);
      state = { ...state, machines: state.machines.map((m, k) => (k === i ? { ...m, on: box.checked } : m)) };
      scene!.setMachines(state.machines);
      changed(false);
    }),
  );
  panel.querySelectorAll<HTMLButtonElement>("[data-rotate]").forEach((button) =>
    button.addEventListener("click", () => rotate(Number(button.dataset.rotate))),
  );
  panel.querySelectorAll<HTMLButtonElement>("[data-remove]").forEach((button) =>
    button.addEventListener("click", () => {
      const i = Number(button.dataset.remove);
      state = { ...state, machines: state.machines.filter((_, k) => k !== i) };
      scene!.setMachines(state.machines);
      changed(true);
    }),
  );
  panel.querySelector<HTMLSelectElement>("#add")?.addEventListener("change", (e) => {
    const kind = (e.target as HTMLSelectElement).value;
    if (kind) addMachine(kind);
  });
  panel.querySelectorAll<HTMLButtonElement>("[data-slice]").forEach((button) =>
    button.addEventListener("click", () => {
      sliceMode = button.dataset.slice as SliceMode;
      scene!.setSlice(sliceMode, sliceHeight);
      render();
    }),
  );
  const height = panel.querySelector<HTMLInputElement>("#height")!;
  height.addEventListener("input", () => {
    sliceHeight = Number(height.value);
    height.previousElementSibling!.querySelector("b")!.textContent = number(sliceHeight, 1);
    scene!.setSlice(sliceMode, sliceHeight);
  });
  panel.querySelector<HTMLButtonElement>("#optimise")?.addEventListener("click", () => void optimise());
  panel.querySelector<HTMLButtonElement>("#verify")?.addEventListener("click", () => void verify());
  panel.querySelector<HTMLButtonElement>("#tour")?.addEventListener("click", () => startTutorial(view, panel));
}

async function optimise(): Promise<void> {
  busy = "Searching the fan settings…";
  render();
  try {
    const best = await api.lowestSafe(state);
    busy = "";
    note = best.feasible
      ? `Lowest safe setting: ${number(best.ach, 1)} air changes an hour. ${number(best.tested)} settings tested in ${number(best.seconds, 2)} s on ${best.hardware}.`
      : `No setting up to ${ACH_MAX} air changes an hour keeps this layout within the limit.`;
    state = { ...state, ach: best.ach };
    render();
    void refresh();
  } catch (error) {
    busy = "";
    note = `The search failed: ${(error as Error).message}`;
    render();
  }
}

async function verify(): Promise<void> {
  busy = "Running a real OpenFOAM simulation of this room…";
  render();
  try {
    verification = await api.verify(state);
    while (verification.status === "queued" || verification.status === "running") {
      render();
      await new Promise((resolve) => setTimeout(resolve, 1500));
      verification = await api.verification(verification.id);
    }
  } catch (error) {
    note = `The check failed: ${(error as Error).message}`;
  }
  busy = "";
  render();
}

async function start(): Promise<void> {
  render();
  const sample = await api.sample();
  state = { machines: sample.machines, ach: sample.metrics.ach };
  scene!.setRoom(sample.grid.size, sample.room);
  scene!.setMachines(state.machines);
  scene!.setSlice(sliceMode, sliceHeight);
  apply(sample, true);
  try {
    people = (await api.health()).people === true;
    apply(await api.predict(state), true);
    online = true;
  } catch {
    online = false;
  }
  render();
  if (!localStorage.getItem(TOUR_SEEN)) {
    localStorage.setItem(TOUR_SEEN, "1");
    startTutorial(view, panel);
  }
}
