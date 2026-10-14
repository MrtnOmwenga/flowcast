import { api, type AgentAnswer, type AgentStep, type Confirmation, type DaySchedule, type Explanation, type Verification } from "./api";
import { Fields } from "./field";
import { RoomScene, overlaps, type SliceMode } from "./scene";
import { startTutorial } from "./tutorial";
import type { Machine, Payload, RoomState } from "./types";

const CLEANROOM_ITEMS: Record<string, [number, number, number]> = {
  Workbench: [1.6, 0.8, 1.0],
  Cabinet: [0.8, 0.6, 1.8],
  "Filling machine": [1.2, 1.0, 1.4],
  "Small unit": [0.6, 0.6, 1.0],
  Isolator: [2.0, 0.8, 1.6],
  "Shelving rack": [1.2, 0.4, 2.0],
  Cart: [0.8, 0.6, 0.8],
};
// Components on a cabinet's mounting plate: length, width, depth out from the plate
const CABINET_ITEMS: Record<string, [number, number, number]> = {
  Drive: [0.4, 0.2, 0.25],
  "Large drive": [0.6, 0.3, 0.3],
  "Controller rack": [0.15, 0.4, 0.15],
  "Power supply": [0.2, 0.15, 0.15],
  Transformer: [0.25, 0.25, 0.25],
  "Contactor row": [0.1, 0.5, 0.1],
  "Braking resistor": [0.3, 0.1, 0.1],
};
const PERSON: [number, number, number] = [0.4, 0.4, 1.8];
const SOON = `<span class="soon">soon</span>`;

// The limits the served models were trained within. Models trained with people allow more.
const LIMITS = { basic: { items: 3, kinds: ["Workbench", "Cabinet", "Filling machine", "Small unit", "Isolator"] } };

/** A room design: each has its own trained models. `ach` is the setting it opens at. */
interface Design { id: string; name: string; note: string; ready: boolean; ach: number }
interface Profile {
  kind: "cleanroom" | "cabinet";
  title: string;
  designs: Design[];
  catalogue: Record<string, [number, number, number]>;
  sample: string;
  examples: string[];
  tasks: Task[];
  sliceHeight: number;
}

type Task = "explore" | "optimise" | "plan" | "confirm" | "compare";
const PROFILES: Record<string, Profile> = {
  cleanroom: {
    kind: "cleanroom",
    title: "Cleanroom demo",
    designs: [
      { id: "panels", name: "Ceiling panels", note: "Four supply panels, one return wall", ready: true, ach: 20 },
      { id: "ceiling", name: "Filter ceiling", note: "Air moves straight down, out at both ends", ready: true, ach: 60 },
      { id: "cross", name: "Cross-flow", note: "Filter wall to return wall", ready: true, ach: 20 },
    ],
    catalogue: CLEANROOM_ITEMS,
    sample: "/sample.json",
    examples: [
      "Set this up as a small filling suite: an isolator by the far wall, a workbench near the return wall and two operators at the isolator. Then find the lowest safe fan setting and tell me what it saves.",
      "We are adding a second filling machine next month. Put it where it does least harm, then tell me how far the fans can still come down.",
      "The operators have gone home and only the isolator keeps running. What can the fans drop to overnight?",
      "Which item makes the worst point worst? Move it somewhere better and compare the fan setting before and after.",
    ],
    tasks: ["explore", "optimise", "plan", "compare", "confirm"],
    sliceHeight: 1.1,
  },
  cabinet: {
    kind: "cabinet",
    title: "Control cabinet demo",
    designs: [
      { id: "cabinet", name: "Filter fan", note: "In at the bottom, out at the top", ready: true, ach: 625 },
      { id: "roof", name: "Roof fan", note: "Drawn out through the roof", ready: false, ach: 625 },
      { id: "side", name: "Side to side", note: "In one side wall, out the other", ready: false, ach: 625 },
    ],
    catalogue: CABINET_ITEMS,
    sample: "/sample-cabinet.json",
    examples: [
      "Lay out an empty plate with a large drive, a power supply, a controller rack and a contactor row, then find the lowest fan airflow that keeps every component within its rating.",
      "We are adding a second drive. Put it where it does least harm, then tell me how far the fan can come down.",
      "Which component is heating the hottest air? Move it somewhere better and compare the airflow before and after.",
      "The braking resistor only runs during stops. With it switched off, how far can the fan come down?",
    ],
    tasks: ["explore", "optimise", "confirm"],
    sliceHeight: 0.2,
  },
};
let profile = PROFILES.cleanroom;
const TOUR_SEEN = "flowcast-tour-seen";

const TASKS: { id: Task; name: string; about: string; soon?: boolean }[] = [
  { id: "explore", name: "Explore", about: "Change the room by hand and watch the air respond. Each change is predicted by the model in about a tenth of a second." },
  { id: "optimise", name: "Optimise", about: "Let Flowcast search. The model is run many times to find the best fan setting or the best place for an item." },
  { id: "plan", name: "Plan a day", about: "Give Flowcast the day's production plan in your own words. A language model reads it, and the airflow model sets the fans for each part of the day." },
  { id: "compare", name: "Compare and report", soon: true, about: "Pin the room as it is, make a change by hand or by asking, and see before and after side by side. Then take the result away as a written record." },
  { id: "confirm", name: "Confirm", about: "Check the model against a real OpenFOAM simulation of the room exactly as it is set. This takes about a minute." },
];

let view: HTMLElement;
let panel: HTMLElement;
let askBar: HTMLElement;
let task: Task = "explore";
let positionItem = 0;
let positionThenFan = true;
let searchNote = "";
let confirmation: Confirmation | null = null;
let plan = "The room is empty overnight. The first operator arrives at 06:00 and starts the first machine. From 08:00 to 12:00 everyone is in and every machine runs. Lunch is 12:00 to 13:00: nobody is in the room but the machines keep running. The afternoon shift, 13:00 to 17:00, is one operator with one machine. Everything is switched off at 17:00.";
let day: DaySchedule | null = null;
let planning = false;
let scene: RoomScene | null = null;

let state: RoomState = { machines: [], ach: 20, room: "panels", standard: "gmp-c", minimum_ach: 10 };
let drawnDesign = "";
let fields: Fields | null = null;
let payload: Payload | null = null;
let online = false;
let sliceMode: SliceMode = "particles";
let sliceHeight = 1.1;
let busy = "";
let note = "";
let verification: Verification | null = null;
let conversation: { role: string; content: string }[] = [];
let answer: AgentAnswer | null = null;
let asking = false;
let draft = "";
let explanation: Explanation | null = null;
let explaining = false;
let languageModel: string | null = null;
let people = false; // whether the served models were trained on rooms with people
let trained: Record<string, boolean> | null = null; // designs the service has models for

/** A design can be chosen once it is built and the service has models for it. */
function available(d: Design): boolean {
  return d.ready && (trained?.[d.id] ?? d.id === profile.designs[0].id);
}

// Only one prediction request runs at a time; a newer state replaces any that is waiting.
let inFlight = false;
let queued = false;

export function mount(root: HTMLElement, name = "cleanroom"): void {
  if (scene) {
    if (PROFILES[name] !== profile) {
      profile = PROFILES[name];
      reset();
      void start();
    }
    return;
  }
  profile = PROFILES[name];
  root.innerHTML = `<div id="stage"><div id="view"></div><div id="askbar"></div></div><aside id="panel"></aside>`;
  view = root.querySelector<HTMLElement>("#view")!;
  panel = root.querySelector<HTMLElement>("#panel")!;
  askBar = root.querySelector<HTMLElement>("#askbar")!;
  scene = new RoomScene(view);
  scene.onMove = (machines, finished) => {
    state = { ...state, machines };
    explanation = null;
    if (finished) render();
    verification = null;
    void refresh();
  };
  void start();
}

/** Forget everything about the previous room when the demo or design changes. */
function reset(): void {
  task = "explore";
  verification = null;
  confirmation = null;
  explanation = null;
  answer = null;
  conversation = [];
  day = null;
  searchNote = "";
  note = "";
  positionItem = 0;
  sliceHeight = profile.sliceHeight;
}

function setDesign(id: string): void {
  const design = profile.designs.find((d) => d.id === id);
  if (!design || !available(design) || state.room === id) return;
  reset();
  state = { ...state, room: id, ach: design.ach, minimum_ach: profile.kind === "cabinet" ? 0 : 10 };
  render();
  void refresh();
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
  const design = result.room.design ?? "panels";
  if (design !== drawnDesign) {
    drawnDesign = design;
    scene!.setRoom(result.grid.size, result.room, result.grid.cell);
    scene!.setMachines(state.machines); // placed again now the room's size is known
    scene!.setSlice(sliceMode, sliceHeight);
  }
  fields = new Fields(result);
  fields.combine(state.machines);
  scene!.setFields(fields);
  if (current) scene!.setMarker(fields.worst(state.machines).position);
  render();
}

function changed(layoutChanged: boolean): void {
  verification = null;
  confirmation = null;
  explanation = null;
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

function fanRange(): [number, number] {
  const [low, high] = payload?.room.ach_range ?? [6, 40];
  return [Math.max(low, state.minimum_ach ?? low), high];
}

function inOperation(machines: Machine[]): boolean {
  return machines.some((m) => m.on);
}

function maxItems(): number {
  if (profile.kind === "cabinet") return 6;
  return people ? 5 : LIMITS.basic.items;
}

function choices(): string[] {
  if (profile.kind === "cabinet") return Object.keys(CABINET_ITEMS);
  return people ? [...Object.keys(CLEANROOM_ITEMS), "Person"] : LIMITS.basic.kinds;
}

const cabinet = () => profile.kind === "cabinet";

/** Cubic metres of air in the room or cabinet. */
function volume(): number {
  const [lx, ly, lz] = fields?.size ?? [6, 4, 3];
  return lx * ly * lz;
}

/** A fan setting in the unit people use for it: air changes an hour for a room, airflow for a cabinet. */
function fanText(ach: number): string {
  return cabinet() ? `${number(ach * volume())} m³/h` : `${number(ach, 1)} air changes an hour`;
}

function ambient(): number {
  return payload?.standard?.ambient ?? state.ambient ?? 35;
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
  const [sx, sy, sz] = person ? PERSON : profile.catalogue[kind];
  const [lx, ly] = fields.size;
  const step = fields.cell;
  // keep clear of a cabinet's inlet, as the simulated layouts do
  for (let x = cabinet() ? 0.2 : 0; x <= lx - sx + 1e-6; x += step) {
    for (let y = 0; y <= ly - sy + 1e-6; y += step) {
      const machine: Machine = { x: round(x), y: round(y), sx, sy, sz, on: true, emission: 1, kind: person ? "person" : cabinet() ? "component" : "machine" };
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
  renderAsk();
  if (!fields || !payload) {
    panel.innerHTML = `<h1>${profile.title}</h1><p class="muted">Loading…</p>`;
    return;
  }
  const scroll = panel.scrollTop;
  const a = payload.assumptions;
  const [low, high] = fanRange();
  const power = a.full_fan_power_kw * (a.fan_fixed_loss + (1 - a.fan_fixed_loss) * (state.ach / a.full_ach) ** 3);
  const saving = a.full_fan_power_kw - power;
  const worst = fields.worst(state.machines);
  const ratio = worst.level / a.particle_limit;
  // Within the safety margin either side of the limit, the model's error could change the answer.
  const verdict = ratio <= 1 - a.safety_margin ? "ok" : ratio <= 1 + a.safety_margin ? "close" : "bad";
  const bar = Math.min(100, ((Math.log10(Math.max(ratio, 0.01)) + 2) / 2.5) * 100);
  const stale = !sameLayout(payload.machines, state.machines);
  const confidence = payload.metrics.confidence;
  const current = TASKS.find((k) => k.id === task)!;
  const tasks = TASKS.filter((k) => profile.tasks.includes(k.id));
  const std = payload.standard;
  const heatRules = std?.kind === "heat";

  panel.innerHTML = `
    <div class="title">
      <h1>${profile.title}</h1>
      ${cabinet() ? "" : `<button class="ghost" id="tour">How to use this</button>`}
    </div>
    <div class="designs" data-tour="designs">
      ${profile.designs.map((d) => `<button class="design ${d.id === state.room ? "active" : ""}" data-design="${d.id}" ${available(d) ? "" : "disabled"} title="${d.note}">${d.name}${available(d) ? "" : SOON}<small>${d.note}</small></button>`).join("")}
    </div>
    ${std && heatRules ? `
    <section class="rules" data-tour="rules">
      <h2>What the cabinet must meet</h2>
      <div class="rule-row">
        <label for="limit">Components</label>
        <select id="limit">${std.choices.map((c) => `<option value="${c.id}" ${c.id === std.id ? "selected" : ""}>${c.name}</option>`).join("")}</select>
      </div>
      <div class="rule-row">
        <label for="ambient">Air drawn in, °C</label>
        <input id="ambient" type="number" min="15" max="45" step="1" value="${number(ambient())}" />
      </div>
      <p class="muted small">The air around every component must stay under <b>${number(std.max_air ?? 0)} °C</b>: a rise of ${number(std.allowed_rise ?? 0)} °C over the air drawn in. ${std.source}.</p>
    </section>` : ""}
    ${std && !heatRules ? `
    <section class="rules" data-tour="rules">
      <h2>What the room must meet</h2>
      <div class="rule-row">
        <label for="standard">Standard</label>
        <select id="standard">${std!.choices.map((c) => `<option value="${c.id}" ${c.id === std!.id ? "selected" : ""}>${c.name}</option>`).join("")}</select>
      </div>
      <div class="rule-row">
        <label for="minimum">Site minimum fan setting</label>
        <input id="minimum" type="number" min="${payload.room.ach_range?.[0] ?? 6}" max="${payload.room.ach_range?.[1] ?? 40}" step="1" value="${Math.max(state.minimum_ach ?? 10, payload.room.ach_range?.[0] ?? 6)}" />
      </div>
      <p class="muted small">Limit ${std!.state}: <b>${number(a.particle_limit)}</b> per m³. In operation ${number(std!.in_operation)}, at rest ${number(std!.at_rest)} (${std!.source}).</p>
    </section>` : ""}
    ${online ? "" : `<p class="warn">Showing one stored simulation. The prediction service is not connected.</p>`}
    ${note ? `<p class="warn">${escape(note)}</p>` : ""}

    <section class="readouts" data-tour="readouts">
      <h2>${cabinet() ? "The cabinet now" : "The room now"}</h2>
      <div class="status ${verdict}">${verdict === "ok" ? "Within the limit" : verdict === "close" ? "Too close to the limit to call: verify" : "Over the limit"}${std && !heatRules ? `, ${std.state}` : ""}${stale ? " (updating…)" : ""}</div>
      <div class="meter"><div class="fill ${verdict}" style="width:${bar}%"></div><div class="tick"></div></div>
      <dl class="grid">
        ${cabinet()
          ? `<div><dt>Hottest air</dt><dd>${number(ambient() + worst.level, 1)} °C <small>${number(ratio * 100)}% of the allowed rise</small></dd></div>
        <div><dt>Fan airflow</dt><dd>${number(state.ach * volume())} <small>m³/h</small></dd></div>
        <div><dt>Fan power</dt><dd>${number(power * 1000)} W</dd></div>
        <div><dt>${saving >= 0 ? "Below full speed" : "Above full speed"}</dt><dd>${number((Math.abs(saving) / a.full_fan_power_kw) * 100)}% <small>less power, dust and noise</small></dd></div>
        <div><dt>Heat given off</dt><dd>${number(state.machines.filter((m) => m.on).reduce((sum, m) => sum + (fields!.powerOf(m)), 0))} W</dd></div>`
          : `<div><dt>Worst point</dt><dd>${number(ratio * 100)}% <small>of the limit</small></dd></div>
        <div><dt>Fan setting</dt><dd>${number(state.ach, 1)} <small>air changes an hour</small></dd></div>
        <div><dt>Fan power</dt><dd>${number(power, 2)} kW</dd></div>
        <div><dt>${saving >= 0 ? "Saving" : "Extra cost"}</dt><dd>${number((Math.abs(saving) / a.full_fan_power_kw) * 100)}% <small>$${number(Math.abs(saving) * a.hours_per_year * a.electricity_price)} a year</small></dd></div>
        <div><dt>Stagnant air</dt><dd>${number(payload.metrics.stagnant_fraction * 100, 1)}% <small>of the room</small></dd></div>`}
        ${confidence === undefined ? "" : `<div><dt>Model confidence</dt><dd class="${confidence < 0.6 ? "amber" : ""}">${confidence < 0.6 ? "Low" : "Good"}</dd></div>`}
      </dl>
      ${confidence !== undefined && confidence < 0.6 ? `<p class="muted small">The models disagree about this layout. Confirm it by simulation before relying on it.</p>` : ""}
      ${languageModel ? `<div class="row"><button class="ghost" id="explain" ${online && !explaining ? "" : "disabled"}>${explaining ? "Writing…" : "Explain this result"}</button>
</div>` : ""}
      ${explanation ? `<div class="explanation">${explanation.text.split(/\n+/).map((p) => `<p>${escape(p)}</p>`).join("")}<p class="compute">${escape(explanation.model)} on ${escape(explanation.hosted_on)}</p></div>` : ""}
      ${computeBadge()}
    </section>

    <div class="task-picker" data-tour="tasks">
      <label for="task">What do you want to do?</label>
      <select id="task">
        ${tasks.map((k) => `<option value="${k.id}" ${k.id === task ? "selected" : ""}>${k.name}${k.soon ? " (soon)" : ""}</option>`).join("")}
      </select>
    </div>
    <p class="muted small about">${current.soon ? `${SOON} ` : ""}${current.about}</p>

    ${task === "explore" ? `
    <section data-tour="fan">
      <label>Fan setting <b>${fanText(state.ach)}</b></label>
      <input id="ach" type="range" min="${low}" max="${high}" step="${cabinet() ? 12.5 : 0.5}" value="${state.ach}" />
      <p class="muted small">${cabinet()
        ? `The fan's top setting is ${fanText(a.full_ach)}. Less air means less power, less dust drawn through the filter and less noise, but the components run hotter.`
        : `The room runs at ${number(a.full_ach)} today. Less air costs far less to move, but particles build up.`}</p>
    </section>

    <section data-tour="equipment">
      <h2>${cabinet() ? "On the mounting plate" : "What is in the room"}</h2>
      <p class="muted small">${cabinet() ? "The cabinet is drawn lying on its back: air comes in at the bottom (left, blue) and leaves at the top (right, grey). Drag a component to move it." : "Drag an item in the picture to move it."}</p>
      ${state.machines.map((m, i) => `
        <div class="machine">
          <label><input type="checkbox" data-toggle="${i}" ${m.on ? "checked" : ""}/> ${nameOf(m)} <small>${m.kind === "person" ? (m.on ? "present" : "away") : m.kind === "component" ? (m.on ? `${number(fields!.powerOf(m))} W` : "off") : m.on ? "running" : "off"}</small></label>
          <span>${m.sx === m.sy ? "" : `<button class="link" data-rotate="${i}">turn</button> `}<button class="link" data-remove="${i}">remove</button></span>
        </div>`).join("") || `<p class="muted small">The room is empty.</p>`}
      ${state.machines.length < maxItems() ? `<select id="add"><option value="">Add ${cabinet() ? "a component" : people ? "equipment or a person" : "equipment"}…</option>${choices().map((k) => `<option>${k}</option>`).join("")}</select>` : `<p class="muted small">The model was trained on rooms with up to ${maxItems()} items.</p>`}
      <div class="row"><button class="ghost" disabled>Import an item from a datasheet</button>${SOON}</div>
    </section>

    <section data-tour="view">
      <h2>What the picture shows</h2>
      <div class="row">
        ${(["particles", "age", "off"] as SliceMode[]).map((m) => `<button class="chip ${sliceMode === m ? "active" : ""}" data-slice="${m}">${m === "particles" ? (cabinet() ? "Air temperature" : "Particle level") : m === "age" ? "Stagnant air" : "No slice"}</button>`).join("")}
      </div>
      <label>${cabinet() ? "Slice distance from the plate" : "Slice height"} <b>${number(sliceHeight, 2)}</b> m</label>
      <input id="height" type="range" min="${fields.cell / 2}" max="${fields.size[2] - fields.cell / 2}" step="${fields.cell}" value="${sliceHeight}" />
      <p class="muted small">${cabinet() ? "The red marker is the hottest air away from the component surfaces: the place for a temperature sensor." : "The red marker is the worst point: the place for a particle counter."}</p>
    </section>` : ""}

    ${task === "optimise" ? `
    <section data-tour="optimise">
      <h2>The fan setting</h2>
      <p class="muted small">Finds the lowest setting that keeps the worst point ${number(a.safety_margin * 100)}% under the limit, for the room as it stands.</p>
      <div class="row">
        <button id="optimise" ${online && !busy ? "" : "disabled"}>Find the lowest safe setting</button>
        <button class="ghost" id="confirm-fan" ${online && !busy ? "" : "disabled"}>Find it and confirm by simulation</button>
      </div>
      <p class="muted small">The first asks the model only and takes about a second. The second then checks the answer with real simulations, stepping the fan up until one passes: one to three minutes.${cabinet() ? " Tested on 100 unseen cabinets, the model's own answer was confirmed safe 86% of the time." : " Tested on 100 unseen rooms, the model's own answer was confirmed safe 81% of the time."}</p>
      ${confirmationHtml()}
    </section>
    <section>
      <h2>Where an item stands</h2>
      <p class="muted small">Tries one item at positions across the whole ${cabinet() ? "plate" : "floor"} and moves it to where the worst point is lowest.</p>
      ${state.machines.length ? `
      <select id="position-item">${state.machines.map((m, i) => `<option value="${i}" ${i === positionItem ? "selected" : ""}>${i + 1}. ${nameOf(m)}</option>`).join("")}</select>
      <label class="check"><input type="checkbox" id="position-fan" ${positionThenFan ? "checked" : ""}/> then find the lowest safe fan setting</label>
      <div class="row"><button id="position" ${online && !busy ? "" : "disabled"}>Find its best position</button></div>` : `<p class="muted small">Add an item first.</p>`}
    </section>
    ${busy ? `<p class="muted small">${busy}</p>` : ""}
    ${searchNote ? `<div class="explanation"><p>${escape(searchNote)}</p></div>` : ""}` : ""}

    ${task === "plan" ? `
    <section data-tour="plan">
      <h2>Today's production plan</h2>
      <textarea id="plan" rows="7" ${planning ? "disabled" : ""}>${escape(plan)}</textarea>
      <div class="row"><button id="schedule" ${online && languageModel && !planning ? "" : "disabled"}>${planning ? "Reading the plan…" : "Build the fan schedule"}</button></div>
      ${languageModel ? "" : `<p class="warn">Reading a plan needs the language model, which is not connected.</p>`}
      ${dayHtml()}
      <div class="row"><button class="ghost" disabled>Confirm every period by simulation</button>${SOON}</div>
      <div class="row"><button class="ghost" disabled>Send the schedule to the building controls</button>${SOON}</div>
    </section>` : ""}

    ${task === "compare" ? `
    <section class="preview-block">
      <h2>Before and after</h2>
      <div class="row"><button disabled>Pin the room as it is now</button></div>
      <p class="muted small">Then change the room by hand, or ask for the change in words, for example by pasting a change request.</p>
      <table class="schedule"><thead><tr><th></th><th>Before</th><th>After</th></tr></thead><tbody>
        <tr><td>Worst point</td><td>–</td><td>–</td></tr>
        <tr><td>Lowest safe fan setting</td><td>–</td><td>–</td></tr>
        <tr><td>Fan energy a year</td><td>–</td><td>–</td></tr>
        <tr><td>Stagnant air</td><td>–</td><td>–</td></tr>
        <tr><td>Counter position</td><td>–</td><td>–</td></tr>
      </tbody></table>
      <h2>Take it away</h2>
      <div class="row"><button disabled>Download the change report</button></div>
      <p class="muted small">One page for the change record: both layouts, the comparison above, the confirming simulation and the recommended setting, with the wording drafted for you.</p>
      <div class="row"><button disabled>Fan settings for the building controls</button></div>
      <p class="muted small">One setting for each state of the room: empty, staffed, each machine running.</p>
    </section>` : ""}

    ${task === "confirm" ? `
    <section data-tour="verify">
      <h2>A real simulation of this room</h2>
      <p class="muted small">If the simulation and the model differ by more than 30% at the worst point, or fall on different sides of the limit, the page says so.</p>
      <div class="row"><button id="verify" ${online && !busy ? "" : "disabled"}>Verify by simulation</button></div>
      ${busy ? `<p class="muted small">${busy}</p>` : ""}
      ${verificationHtml()}
      <div class="row"><button class="ghost" disabled>Add this room to the training data</button>${SOON}</div>
      <p class="muted small">Every confirmed room can become a training example, so the model improves where it is used.</p>
    </section>` : ""}

    <details>
      <summary>Assumptions</summary>
      ${cabinet() ? `<p class="muted small">Each component gives off its typical loss at full load: ${(std?.components ?? []).map((c) => `${c.name} ${number(c.power)} W`).join(", ")}. The fan moves heat far faster than it rises, so rising warm air is left out, which is fair for a fan-cooled cabinet and not for one cooled by natural draught. The limit applies to the air at least one cell (5 cm) from every component. The fan uses ${number(a.full_fan_power_kw * 1000)} W at ${fanText(a.full_ach)}; power follows the cube of airflow, with ${number(a.fan_fixed_loss * 100)}% that does not fall.</p>` : `<p class="muted small">A running machine releases ${number(a.machine_emission)} particles a second${people ? ` and a person ${number(a.person_emission)}` : ""}. The limit is ISO class 7 (${number(a.particle_limit)} per m³), applied at the worst point up to ${number(a.occupied_height, 1)} m, which is ${number(worst.level)} per m³ now. The room runs at ${number(a.full_ach)} air changes an hour today, using ${number(a.full_fan_power_kw, 1)} kW of fan power. Power follows the cube of airflow, with ${number(a.fan_fixed_loss * 100)}% that does not fall as the fans slow. Electricity at $${number(a.electricity_price, 2)} per kWh.</p>`}
    </details>
  `;
  panel.scrollTop = scroll;
  bind();
}

/** The request box under the picture. Drawn apart from the panel so typing is never interrupted. */
function renderAsk(): void {
  if (!languageModel || profile.examples.length === 0) {
    askBar.innerHTML = "";
    askBar.hidden = true;
    return;
  }
  askBar.hidden = false;
  askBar.innerHTML = `
    ${asking ? `<div class="ask-output"><p class="muted small">Planning, and testing each step with the airflow model…</p></div>` : ""}
    ${answer ? `<div class="ask-output">
        <ol class="steps">${answer.steps.map(stepHtml).join("")}</ol>
        <div class="explanation">${answer.reply.split(/\n+/).map((p) => `<p>${escape(p)}</p>`).join("")}<p class="compute blue">${escape(answer.model)} on ${escape(answer.hosted_on)}</p></div>
      </div>` : ""}
    <div class="ask-box" data-tour="ask">
      <textarea id="question" rows="2" placeholder="Ask Flowcast: describe what you want to do with this ${cabinet() ? "cabinet" : "room"}" ${asking ? "disabled" : ""}>${escape(draft)}</textarea>
      <div class="ask-suggestions">${profile.examples.map((e, i) => `<button class="suggestion" data-example="${i}" ${asking ? "disabled" : ""}>${escape(e)}</button>`).join("")}</div>
      <div class="ask-foot">
        <span class="muted small">A language model served on AMD GPUs plans the steps. Every figure comes from the airflow model.</span>
        <button id="ask" ${online && !asking ? "" : "disabled"}>${asking ? "Working…" : "Ask"}</button>
      </div>
    </div>`;
  const question = askBar.querySelector<HTMLTextAreaElement>("#question")!;
  question.addEventListener("input", () => (draft = question.value));
  question.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void ask(question.value);
    }
  });
  askBar.querySelector<HTMLButtonElement>("#ask")!.addEventListener("click", () => void ask(question.value));
  askBar.querySelectorAll<HTMLButtonElement>("[data-example]").forEach((button) =>
    button.addEventListener("click", () => void ask(profile.examples[Number(button.dataset.example)])),
  );
}

const TOOL_NAMES: Record<string, string> = {
  look: "Looked at the room",
  move_item: "Moved an item",
  turn_item: "Turned an item",
  set_running: "Switched an item",
  add_item: "Added an item",
  remove_item: "Removed an item",
  clear_room: "Cleared the room",
  set_fan: "Set the fan",
  find_lowest_safe_fan: "Searched for the lowest safe fan setting",
  find_best_position: "Searched the floor for the best position",
};

/** One line per thing the agent did, with the figure that came back. */
function stepHtml(step: AgentStep): string {
  const outcome = step.outcome as {
    error?: string; positions_tried?: number; settings_tested?: number;
    result?: { worst_point_percent_of_limit?: number; fan_setting?: number; hottest_air_c?: number; rise_percent_of_allowed?: number; fan_airflow_m3_per_hour?: number };
  };
  const tried = outcome.positions_tried ? `${outcome.positions_tried} positions tried, ` : outcome.settings_tested ? `${outcome.settings_tested} settings tested, ` : "";
  const detail = outcome.error
    ? `<span class="bad-text">not possible: ${escape(outcome.error)}</span>`
    : outcome.result
      ? outcome.result.hottest_air_c !== undefined
        ? `${tried}hottest air ${outcome.result.hottest_air_c} °C (${outcome.result.rise_percent_of_allowed}% of the allowed rise) at ${outcome.result.fan_airflow_m3_per_hour} m³/h`
        : `${tried}worst point ${outcome.result.worst_point_percent_of_limit}% of limit at ${outcome.result.fan_setting} air changes`
      : "";
  return `<li><b>${TOOL_NAMES[step.tool] ?? escape(step.tool)}</b><small>${detail}</small></li>`;
}

async function ask(text: string): Promise<void> {
  const question = text.trim();
  if (!question) return;
  asking = true;
  answer = null;
  note = "";
  draft = question;
  render();
  try {
    conversation = [...conversation.slice(-6), { role: "user", content: question }];
    const result = await api.ask(state, conversation);
    conversation = [...conversation, { role: "assistant", content: result.reply }];
    answer = result;
    draft = "";
    state = { ...state, ...result.state };
    scene!.setMachines(state.machines);
    verification = null;
    explanation = null;
    void refresh();
  } catch (error) {
    note = `Flowcast could not carry that out: ${(error as Error).message}`;
  }
  asking = false;
  render();
}

/** Who answered: the full detail sits in the tooltip, for anyone checking how AMD hardware is used. */
function computeBadge(): string {
  if (!payload || payload.source !== "model" || !payload.compute) return `<p class="compute">OpenFOAM simulation</p>`;
  const c = payload.compute;
  const detail = `${c.models} models on ${c.hardware}, ${number(c.seconds * 1000)} ms for this prediction`;
  return `<p class="compute" title="${escape(detail)}">${c.gpu ? "Powered by AMD" : "Running on a processor"}</p>`;
}

function escape(text: string): string {
  // Language models sometimes add emphasis marks; the page shows plain text.
  text = text.replace(/\*\*|__/g, "");
  return text.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}

async function explain(): Promise<void> {
  explaining = true;
  explanation = null;
  render();
  try {
    explanation = await api.explain(state);
  } catch (error) {
    note = `The explanation is not available: ${(error as Error).message}`;
  }
  explaining = false;
  render();
}

function dayHtml(): string {
  if (!day) return "";
  const [low, high] = fanRange();
  const bars = day.periods.map((p, i) => {
    const height = 18 + 82 * ((p.ach - low) / (high - low));
    return `<button class="bar" data-period="${i}" style="flex:${p.hours};height:${height}%" title="${p.start} to ${p.end}: ${number(p.ach, 1)} air changes"></button>`;
  }).join("");
  const rows = day.periods.map((p, i) => {
    const who = p.kind === "lead" ? "fans up before staff arrive" : p.kind === "clean-up" ? "clean-up after work"
      : p.on.map((n) => nameOf(state.machines[n - 1] ?? state.machines[0])).join(", ") || "nothing running, nobody in";
    return `<tr data-period="${i}" class="${p.kind}"><td>${p.start}–${p.end}</td><td>${escape(who)}<small>${p.kind === "plan" ? ` ${p.state}` : ""}</small></td><td>${number(p.ach, 1)}${p.feasible ? "" : " *"}</td><td>${number(p.power_kw, 2)}</td></tr>`;
  }).join("");
  return `
    <div class="day"><div class="today" style="bottom:${18 + 82 * ((day.today_ach - low) / (high - low))}%"><span>today: ${number(day.today_ach)} all day</span></div>${bars}</div>
    <div class="day-axis"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span></div>
    <table class="schedule"><thead><tr><th>When</th><th>In the room</th><th>Fan</th><th>kW</th></tr></thead><tbody>${rows}</tbody></table>
    ${day.periods.some((p) => !p.feasible) ? `<p class="muted small">* No setting in range is safe for this state; the highest is shown.</p>` : ""}
    <div class="status ok">${number(day.kwh_per_day, 1)} kWh for the day, against ${number(day.kwh_per_day_today, 1)} at today's setting: ${number(day.saving_percent)}% less, about $${number(day.saving_per_year)} a year</div>
    <p class="muted small">Held to ${escape(day.standard.name)}: the looser limit while the room is in operation and the stricter one at rest. The fans come up ${day.standard.lead_minutes} minutes before staff arrive and stay up for a ${day.standard.cleanup_minutes}-minute clean-up after work, and never go below the site minimum of ${number(day.standard.minimum_ach)}.</p>
    <p class="muted small">Click a row to see that part of the day in the room. ${day.room_states} different room states, ${day.settings_tested} fan settings tested by the model. These are the model's settings; confirm each by simulation before using them.</p>
    <p class="compute blue">Plan read by ${escape(day.model)} on ${escape(day.hosted_on)}</p>`;
}

async function buildSchedule(): Promise<void> {
  planning = true;
  day = null;
  note = "";
  render();
  try {
    day = await api.schedule(state, plan);
  } catch (error) {
    note = `The schedule could not be built: ${(error as Error).message}`;
  }
  planning = false;
  render();
}

/** Show one part of the day in the room: who and what is on, and its fan setting. */
function showPeriod(index: number): void {
  if (!day) return;
  const period = day.periods[index];
  state = { ...state, ach: period.ach, machines: state.machines.map((m, i) => ({ ...m, on: period.on.includes(i + 1) })) };
  scene!.setMachines(state.machines);
  verification = null;
  confirmation = null;
  explanation = null;
  render();
  void refresh();
}

function confirmationHtml(): string {
  const c = confirmation;
  if (!c) return "";
  const lines = c.trail.map((step) => {
    const outcome = step.simulated_percent === null
      ? "simulating…"
      : `simulation ${step.simulated_percent}% of the limit: ${step.passed ? "passes" : "too high"}`;
    return `<li><b>${fanText(step.ach)}</b><small>model ${step.predicted_percent}% of the limit, ${outcome}</small></li>`;
  }).join("");
  const done = c.status === "done";
  const verdict = c.status === "failed" ? `<div class="status bad">The simulation failed.</div>`
    : !done ? ""
    : c.confirmed ? `<div class="status ok">Confirmed by simulation at ${fanText(c.ach ?? 0)}</div>`
    : `<div class="status bad">${escape(c.note ?? "Not confirmed.")}</div>`;
  return `<ol class="steps">${lines}</ol>${verdict}${done && c.confirmed && c.model_ach !== c.ach ? `<p class="muted small">The model first proposed ${fanText(c.model_ach ?? 0)}; the simulation moved it up.</p>` : ""}`;
}

async function confirmFan(): Promise<void> {
  busy = "Asking the model, then checking with real simulations…";
  searchNote = "";
  confirmation = null;
  render();
  try {
    confirmation = await api.confirmFan(state);
    while (confirmation.status === "queued" || confirmation.status === "running") {
      render();
      await new Promise((resolve) => setTimeout(resolve, 2000));
      confirmation = await api.job<Confirmation>(confirmation.id);
    }
    if (confirmation.confirmed && confirmation.ach !== undefined) {
      state = { ...state, ach: confirmation.ach };
      void refresh();
    }
  } catch (error) {
    searchNote = `The check failed: ${(error as Error).message}`;
  }
  busy = "";
  render();
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
  for (const [name, [sx, sy, sz]] of Object.entries(profile.catalogue)) {
    if (sz === m.sz && ((sx === m.sx && sy === m.sy) || (sx === m.sy && sy === m.sx))) return name;
  }
  return cabinet() ? "Component" : "Machine";
}

function bind(): void {
  const ach = panel.querySelector<HTMLInputElement>("#ach");
  ach?.addEventListener("input", () => {
    state = { ...state, ach: Number(ach.value) };
    // Update the label in place so the slider keeps the pointer while it is dragged.
    ach.previousElementSibling!.querySelector("b")!.textContent = number(state.ach, 1);
    verification = null;
    explanation = null;
    void refresh();
  });
  ach?.addEventListener("change", () => render());
  panel.querySelectorAll<HTMLInputElement>("[data-toggle]").forEach((box) =>
    box.addEventListener("change", () => {
      const i = Number(box.dataset.toggle);
      const before = inOperation(state.machines);
      state = { ...state, machines: state.machines.map((m, k) => (k === i ? { ...m, on: box.checked } : m)) };
      scene!.setMachines(state.machines);
      // The limit differs between a working room and an empty one, so crossing over asks the service again.
      changed(before !== inOperation(state.machines));
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
  const height = panel.querySelector<HTMLInputElement>("#height");
  height?.addEventListener("input", () => {
    sliceHeight = Number(height.value);
    height.previousElementSibling!.querySelector("b")!.textContent = number(sliceHeight, 1);
    scene!.setSlice(sliceMode, sliceHeight);
  });
  panel.querySelector<HTMLButtonElement>("#optimise")?.addEventListener("click", () => void optimise());
  panel.querySelector<HTMLButtonElement>("#confirm-fan")?.addEventListener("click", () => void confirmFan());
  const planBox = panel.querySelector<HTMLTextAreaElement>("#plan");
  planBox?.addEventListener("input", () => (plan = planBox.value));
  panel.querySelector<HTMLButtonElement>("#schedule")?.addEventListener("click", () => void buildSchedule());
  panel.querySelectorAll<HTMLElement>("[data-period]").forEach((element) =>
    element.addEventListener("click", () => showPeriod(Number(element.dataset.period))),
  );
  panel.querySelector<HTMLButtonElement>("#verify")?.addEventListener("click", () => void verify());
  panel.querySelector<HTMLButtonElement>("#explain")?.addEventListener("click", () => void explain());
  const standard = panel.querySelector<HTMLSelectElement>("#standard");
  standard?.addEventListener("change", () => {
    state = { ...state, standard: standard.value };
    day = null;
    changed(true);
  });
  const minimum = panel.querySelector<HTMLInputElement>("#minimum");
  minimum?.addEventListener("change", () => {
    const [low, high] = payload?.room.ach_range ?? [6, 40];
    const value = Math.min(high, Math.max(low, Number(minimum.value) || 0));
    state = { ...state, minimum_ach: value, ach: Math.max(state.ach, value) };
    day = null;
    changed(true);
  });
  panel.querySelectorAll<HTMLButtonElement>("[data-design]").forEach((button) =>
    button.addEventListener("click", () => setDesign(button.dataset.design!)),
  );
  const limit = panel.querySelector<HTMLSelectElement>("#limit");
  limit?.addEventListener("change", () => {
    state = { ...state, limit: limit.value };
    changed(true);
  });
  const air = panel.querySelector<HTMLInputElement>("#ambient");
  air?.addEventListener("change", () => {
    state = { ...state, ambient: Math.min(45, Math.max(15, Number(air.value) || 35)) };
    changed(true);
  });
  const picker = panel.querySelector<HTMLSelectElement>("#task");
  picker?.addEventListener("change", () => setTask(picker.value as Task));
  const item = panel.querySelector<HTMLSelectElement>("#position-item");
  item?.addEventListener("change", () => (positionItem = Number(item.value)));
  const thenFan = panel.querySelector<HTMLInputElement>("#position-fan");
  thenFan?.addEventListener("change", () => (positionThenFan = thenFan.checked));
  panel.querySelector<HTMLButtonElement>("#position")?.addEventListener("click", () => void findPosition());
  panel.querySelector<HTMLButtonElement>("#tour")?.addEventListener("click", () => tour());
}

function setTask(next: Task): void {
  task = next;
  render();
}

function tour(): void {
  startTutorial(document.querySelector<HTMLElement>("#demo")!, view, setTask);
}

async function findPosition(): Promise<void> {
  busy = "Trying positions across the floor…";
  searchNote = "";
  render();
  try {
    const result = await api.bestPosition(state, positionItem + 1, positionThenFan);
    state = { ...state, ...result.state };
    scene!.setMachines(state.machines);
    verification = null;
    explanation = null;
    const fan = result.fan?.found ? ` The lowest safe fan setting is now ${fanText(result.fan.lowest_safe_fan_setting ?? 0)}.` : result.fan ? " No fan setting in range is safe for this layout." : "";
    searchNote = `Tried the ${result.item} at ${result.positions_tried} positions in ${number(result.seconds, 1)} s on ${result.hardware}. At the same fan setting the worst point went from ${result.before_percent}% of the limit to ${result.after_percent}%; the worst position tried gave ${result.worst_tried_percent}%.${fan}`;
    void refresh();
  } catch (error) {
    searchNote = `The search failed: ${(error as Error).message}`;
  }
  busy = "";
  render();
}

async function optimise(): Promise<void> {
  busy = "Searching the fan settings…";
  searchNote = "";
  render();
  try {
    const best = await api.lowestSafe(state);
    busy = "";
    searchNote = best.feasible
      ? `Lowest safe setting: ${fanText(best.ach)}. ${number(best.tested)} settings tested in ${number(best.seconds, 2)} s on ${best.hardware}.`
      : `No setting up to ${fanText(fanRange()[1])} keeps this layout within the limit.`;
    state = { ...state, ach: best.ach };
    render();
    void refresh();
  } catch (error) {
    busy = "";
    searchNote = `The search failed: ${(error as Error).message}`;
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
  payload = null;
  fields = null;
  online = false;
  render();
  const sample = await api.sample(profile.sample);
  const design = sample.room.design ?? profile.designs[0].id;
  state = cabinet()
    ? { machines: sample.machines, ach: sample.metrics.ach, room: design, minimum_ach: 0, limit: sample.standard?.id, ambient: sample.standard?.ambient }
    : { machines: sample.machines, ach: Math.max(sample.metrics.ach, 10), room: design, standard: "gmp-c", minimum_ach: 10 };
  sliceHeight = profile.sliceHeight;
  drawnDesign = "";
  scene!.setMachines(state.machines);
  apply(sample, true);
  try {
    const health = await api.health();
    people = health.people === true;
    trained = health.designs ?? null;
    languageModel = health.language_model ?? null;
    apply(await api.predict(state), true);
    online = true;
  } catch {
    online = false;
  }
  render();
  if (!cabinet() && !localStorage.getItem(TOUR_SEEN)) {
    localStorage.setItem(TOUR_SEEN, "1");
    tour();
  }
}
