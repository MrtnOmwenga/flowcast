import { api, type AgentAnswer, type AgentStep, type Explanation, type Verification } from "./api";
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
const TOUR_SEEN = "flowcast-tour-seen";

type Task = "explore" | "optimise" | "confirm";
const TASKS: { id: Task; name: string; about: string }[] = [
  { id: "explore", name: "Explore", about: "Change the room by hand and watch the air respond. Each change is predicted by the model in about a tenth of a second." },
  { id: "optimise", name: "Optimise", about: "Let Flowcast search. The model is run many times to find the best fan setting or the best place for an item." },
  { id: "confirm", name: "Confirm", about: "Check the model against a real OpenFOAM simulation of the room exactly as it is set. This takes about a minute." },
];

let view: HTMLElement;
let panel: HTMLElement;
let askBar: HTMLElement;
let task: Task = "explore";
let positionItem = 0;
let positionThenFan = true;
let searchNote = "";
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
let conversation: { role: string; content: string }[] = [];
let answer: AgentAnswer | null = null;
let asking = false;
let draft = "";
const EXAMPLES = [
  "What is the lowest fan setting I can safely run, and what does it save?",
  "Move whichever item does the most harm to a better place, then find the lowest safe setting.",
  "The operators have gone home. What can the fans drop to overnight?",
];
let explanation: Explanation | null = null;
let explaining = false;
let languageModel: string | null = null;
let people = false; // whether the served models were trained on rooms with people

// Only one prediction request runs at a time; a newer state replaces any that is waiting.
let inFlight = false;
let queued = false;

export function mount(root: HTMLElement): void {
  if (scene) return;
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
  return payload?.room.ach_range ?? [6, 40];
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
  renderAsk();
  if (!fields || !payload) {
    panel.innerHTML = `<h1>Cleanroom demo</h1><p class="muted">Loading the room…</p>`;
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

  panel.innerHTML = `
    <div class="title">
      <h1>Cleanroom demo</h1>
      <button class="ghost" id="tour">How to use this</button>
    </div>
    ${online ? "" : `<p class="warn">Showing one stored simulation. The prediction service is not connected.</p>`}
    ${note ? `<p class="warn">${escape(note)}</p>` : ""}

    <section class="readouts" data-tour="readouts">
      <h2>The room now</h2>
      <div class="status ${verdict}">${verdict === "ok" ? "Within the particle limit" : verdict === "close" ? "Too close to the limit to call: verify" : "Over the particle limit"}${stale ? " (updating…)" : ""}</div>
      <div class="meter"><div class="fill ${verdict}" style="width:${bar}%"></div><div class="tick"></div></div>
      <dl class="grid">
        <div><dt>Worst point</dt><dd>${number(ratio * 100)}% <small>of the limit</small></dd></div>
        <div><dt>Fan setting</dt><dd>${number(state.ach, 1)} <small>air changes an hour</small></dd></div>
        <div><dt>Fan power</dt><dd>${number(power, 2)} kW</dd></div>
        <div><dt>${saving >= 0 ? "Saving" : "Extra cost"}</dt><dd>${number((Math.abs(saving) / a.full_fan_power_kw) * 100)}% <small>$${number(Math.abs(saving) * a.hours_per_year * a.electricity_price)} a year</small></dd></div>
        <div><dt>Stagnant air</dt><dd>${number(payload.metrics.stagnant_fraction * 100, 1)}% <small>of the room</small></dd></div>
        ${confidence === undefined ? "" : `<div><dt>Model confidence</dt><dd class="${confidence < 0.6 ? "amber" : ""}">${confidence < 0.6 ? "Low" : "Good"}</dd></div>`}
      </dl>
      ${confidence !== undefined && confidence < 0.6 ? `<p class="muted small">The models disagree about this layout. Confirm it by simulation before relying on it.</p>` : ""}
      ${languageModel ? `<div class="row"><button class="ghost" id="explain" ${online && !explaining ? "" : "disabled"}>${explaining ? "Writing…" : "Explain this result"}</button></div>` : ""}
      ${explanation ? `<div class="explanation">${explanation.text.split(/\n+/).map((p) => `<p>${escape(p)}</p>`).join("")}<p class="compute">${escape(explanation.model)} on ${escape(explanation.hosted_on)}</p></div>` : ""}
      <p class="compute">${payload.source !== "model" || !payload.compute ? "OpenFOAM simulation" : `${payload.compute.models} models on ${payload.compute.hardware} · ${number(payload.compute.seconds * 1000)} ms`}</p>
    </section>

    <div class="tabs" data-tour="tasks">
      ${TASKS.map((k) => `<button class="tab ${k.id === task ? "active" : ""}" data-task="${k.id}">${k.name}</button>`).join("")}
    </div>
    <p class="muted small about">${current.about}</p>

    ${task === "explore" ? `
    <section data-tour="fan">
      <label>Fan setting <b>${number(state.ach, 1)}</b> air changes an hour</label>
      <input id="ach" type="range" min="${low}" max="${high}" step="0.5" value="${state.ach}" />
      <p class="muted small">The room runs at ${number(a.full_ach)} today. Less air costs far less to move, but particles build up.</p>
    </section>

    <section data-tour="equipment">
      <h2>What is in the room</h2>
      <p class="muted small">Drag an item in the picture to move it.</p>
      ${state.machines.map((m, i) => `
        <div class="machine">
          <label><input type="checkbox" data-toggle="${i}" ${m.on ? "checked" : ""}/> ${nameOf(m)} <small>${m.kind === "person" ? (m.on ? "present" : "away") : m.on ? "running" : "off"}</small></label>
          <span>${m.sx === m.sy ? "" : `<button class="link" data-rotate="${i}">turn</button> `}<button class="link" data-remove="${i}">remove</button></span>
        </div>`).join("") || `<p class="muted small">The room is empty.</p>`}
      ${state.machines.length < maxItems() ? `<select id="add"><option value="">Add ${people ? "equipment or a person" : "equipment"}…</option>${choices().map((k) => `<option>${k}</option>`).join("")}</select>` : `<p class="muted small">The model was trained on rooms with up to ${maxItems()} items.</p>`}
    </section>

    <section data-tour="view">
      <h2>What the picture shows</h2>
      <div class="row">
        ${(["particles", "age", "off"] as SliceMode[]).map((m) => `<button class="chip ${sliceMode === m ? "active" : ""}" data-slice="${m}">${m === "particles" ? "Particle level" : m === "age" ? "Stagnant air" : "No slice"}</button>`).join("")}
      </div>
      <label>Slice height <b>${number(sliceHeight, 1)}</b> m</label>
      <input id="height" type="range" min="0.1" max="${fields.size[2] - 0.1}" step="0.2" value="${sliceHeight}" />
      <p class="muted small">The red marker is the worst point: the place for a particle counter.</p>
    </section>` : ""}

    ${task === "optimise" ? `
    <section data-tour="optimise">
      <h2>The fan setting</h2>
      <p class="muted small">Finds the lowest setting that keeps the worst point ${number(a.safety_margin * 100)}% under the limit, for the room as it stands.</p>
      <div class="row"><button id="optimise" ${online && !busy ? "" : "disabled"}>Find the lowest safe setting</button></div>
    </section>
    <section>
      <h2>Where an item stands</h2>
      <p class="muted small">Tries one item at positions across the whole floor and moves it to where the worst point is lowest.</p>
      ${state.machines.length ? `
      <select id="position-item">${state.machines.map((m, i) => `<option value="${i}" ${i === positionItem ? "selected" : ""}>${i + 1}. ${nameOf(m)}</option>`).join("")}</select>
      <label class="check"><input type="checkbox" id="position-fan" ${positionThenFan ? "checked" : ""}/> then find the lowest safe fan setting</label>
      <div class="row"><button id="position" ${online && !busy ? "" : "disabled"}>Find its best position</button></div>` : `<p class="muted small">Add an item first.</p>`}
    </section>
    ${busy ? `<p class="muted small">${busy}</p>` : ""}
    ${searchNote ? `<div class="explanation"><p>${escape(searchNote)}</p></div>` : ""}` : ""}

    ${task === "confirm" ? `
    <section data-tour="verify">
      <h2>A real simulation of this room</h2>
      <p class="muted small">If the simulation and the model differ by more than 30% at the worst point, or fall on different sides of the limit, the page says so.</p>
      <div class="row"><button id="verify" ${online && !busy ? "" : "disabled"}>Verify by simulation</button></div>
      ${busy ? `<p class="muted small">${busy}</p>` : ""}
      ${verificationHtml()}
    </section>` : ""}

    <details>
      <summary>Assumptions</summary>
      <p class="muted small">A running machine releases ${number(a.machine_emission)} particles a second${people ? ` and a person ${number(a.person_emission)}` : ""}. The limit is ISO class 7 (${number(a.particle_limit)} per m³), applied at the worst point up to ${number(a.occupied_height, 1)} m, which is ${number(worst.level)} per m³ now. The room runs at ${number(a.full_ach)} air changes an hour today, using ${number(a.full_fan_power_kw, 1)} kW of fan power. Power follows the cube of airflow, with ${number(a.fan_fixed_loss * 100)}% that does not fall as the fans slow. Electricity at $${number(a.electricity_price, 2)} per kWh.</p>
    </details>
  `;
  panel.scrollTop = scroll;
  bind();
}

/** The request box under the picture. Drawn apart from the panel so typing is never interrupted. */
function renderAsk(): void {
  if (!languageModel) {
    askBar.innerHTML = "";
    askBar.hidden = true;
    return;
  }
  askBar.hidden = false;
  askBar.innerHTML = `
    <div class="ask-input" data-tour="ask">
      <h2>Ask Flowcast</h2>
      <textarea id="question" rows="2" placeholder="Describe what you want to do with this room" ${asking ? "disabled" : ""}>${escape(draft)}</textarea>
      <div class="row">
        <button id="ask" ${online && !asking ? "" : "disabled"}>${asking ? "Working…" : "Ask"}</button>
        <span class="compute blue">A language model served on AMD GPUs</span>
      </div>
    </div>
    <div class="ask-output">
      ${asking ? `<p class="muted small">Planning, and testing each step with the airflow model…</p>` : ""}
      ${answer ? `<ol class="steps">${answer.steps.map(stepHtml).join("")}</ol>
        <div class="explanation">${answer.reply.split(/\n+/).map((p) => `<p>${escape(p)}</p>`).join("")}<p class="compute blue">${escape(answer.model)} on ${escape(answer.hosted_on)}</p></div>`
      : asking ? "" : `<p class="muted small">Try one of these:</p><div class="examples">${EXAMPLES.map((e, i) => `<button class="link" data-example="${i}">${escape(e)}</button>`).join("")}</div>`}
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
    button.addEventListener("click", () => void ask(EXAMPLES[Number(button.dataset.example)])),
  );
}

const TOOL_NAMES: Record<string, string> = {
  look: "Looked at the room",
  move_item: "Moved an item",
  turn_item: "Turned an item",
  set_running: "Switched an item",
  add_item: "Added an item",
  remove_item: "Removed an item",
  set_fan: "Set the fan",
  find_lowest_safe_fan: "Searched for the lowest safe fan setting",
  find_best_position: "Searched the floor for the best position",
};

/** One line per thing the agent did, with the figure that came back. */
function stepHtml(step: AgentStep): string {
  const outcome = step.outcome as { error?: string; result?: { worst_point_percent_of_limit: number; fan_setting: number }; positions_tried?: number; settings_tested?: number };
  const tried = outcome.positions_tried ? `${outcome.positions_tried} positions tried, ` : outcome.settings_tested ? `${outcome.settings_tested} settings tested, ` : "";
  const detail = outcome.error
    ? `<span class="bad-text">not possible: ${escape(outcome.error)}</span>`
    : outcome.result
      ? `${tried}worst point ${outcome.result.worst_point_percent_of_limit}% of limit at ${outcome.result.fan_setting} air changes`
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
    state = result.state;
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
  const height = panel.querySelector<HTMLInputElement>("#height");
  height?.addEventListener("input", () => {
    sliceHeight = Number(height.value);
    height.previousElementSibling!.querySelector("b")!.textContent = number(sliceHeight, 1);
    scene!.setSlice(sliceMode, sliceHeight);
  });
  panel.querySelector<HTMLButtonElement>("#optimise")?.addEventListener("click", () => void optimise());
  panel.querySelector<HTMLButtonElement>("#verify")?.addEventListener("click", () => void verify());
  panel.querySelector<HTMLButtonElement>("#explain")?.addEventListener("click", () => void explain());
  panel.querySelectorAll<HTMLButtonElement>("[data-task]").forEach((button) =>
    button.addEventListener("click", () => setTask(button.dataset.task as Task)),
  );
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
    state = result.state;
    scene!.setMachines(state.machines);
    verification = null;
    explanation = null;
    const fan = result.fan?.found ? ` The lowest safe fan setting is now ${number(result.fan.lowest_safe_fan_setting ?? 0, 1)} air changes an hour.` : result.fan ? " No fan setting in range is safe for this layout." : "";
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
      ? `Lowest safe setting: ${number(best.ach, 1)} air changes an hour. ${number(best.tested)} settings tested in ${number(best.seconds, 2)} s on ${best.hardware}.`
      : `No setting up to ${fanRange()[1]} air changes an hour keeps this layout within the limit.`;
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
  render();
  const sample = await api.sample();
  state = { machines: sample.machines, ach: sample.metrics.ach };
  scene!.setRoom(sample.grid.size, sample.room);
  scene!.setMachines(state.machines);
  scene!.setSlice(sliceMode, sliceHeight);
  apply(sample, true);
  try {
    const health = await api.health();
    people = health.people === true;
    languageModel = health.language_model ?? null;
    apply(await api.predict(state), true);
    online = true;
  } catch {
    online = false;
  }
  render();
  if (!localStorage.getItem(TOUR_SEEN)) {
    localStorage.setItem(TOUR_SEEN, "1");
    tour();
  }
}
