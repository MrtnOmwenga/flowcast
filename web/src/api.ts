import type { Payload, RoomState } from "./types";

const BASE = import.meta.env.VITE_API_URL ?? "";

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${path} failed: ${response.status} ${await response.text()}`);
  return response.json();
}

export interface Optimum {
  ach: number;
  tested: number;
  seconds: number;
  feasible: boolean;
  hardware: string;
}

export interface Verification {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  predicted?: { worst_level: number; mean_level: number };
  simulated?: { worst_level: number; mean_level: number };
  field_error?: number;
  agrees?: boolean;
  seconds?: number;
  payload?: Payload;
}

export interface Health {
  models: number;
  device: string;
  people?: boolean;
  /** Which room designs have trained models behind the service */
  designs?: Record<string, boolean>;
  language_model?: string | null;
}

export interface Explanation {
  text: string;
  model: string;
  hosted_on: string;
}

export interface AgentStep {
  tool: string;
  arguments: Record<string, unknown>;
  outcome: Record<string, unknown>;
}

export interface AgentAnswer {
  reply: string;
  steps: AgentStep[];
  state: RoomState;
  model: string;
  hosted_on: string;
}

export interface PositionResult {
  state: RoomState;
  item: string;
  positions_tried: number;
  before_percent: number;
  after_percent: number;
  worst_tried_percent: number;
  fan: { found: boolean; lowest_safe_fan_setting?: number; settings_tested: number } | null;
  seconds: number;
  hardware: string;
}

export interface Confirmation {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  trail: { ach: number; predicted_percent: number; simulated_percent: number | null; passed: boolean | null }[];
  predictions?: number;
  confirmed?: boolean;
  ach?: number;
  model_ach?: number;
  seconds?: number;
  note?: string;
  payload?: Payload;
}

export interface DayPeriod {
  start: string;
  end: string;
  hours: number;
  label: string;
  on: number[];
  ach: number;
  power_kw: number;
  feasible: boolean;
  kind: "plan" | "lead" | "clean-up";
  state: "in operation" | "at rest";
  limit: number;
}

export interface DaySchedule {
  periods: DayPeriod[];
  kwh_per_day: number;
  kwh_per_day_today: number;
  saving_percent: number;
  saving_per_year: number;
  room_states: number;
  settings_tested: number;
  today_ach: number;
  standard: { name: string; lead_minutes: number; cleanup_minutes: number; minimum_ach: number };
  model: string;
  hosted_on: string;
}

export const api = {
  schedule: (state: RoomState, plan: string) => post<DaySchedule>("/api/schedule", { state, plan }),
  confirmFan: (state: RoomState) => post<Confirmation>("/api/confirm-fan", state),
  job: async <T>(id: string): Promise<T> => (await fetch(`${BASE}/api/verify/${id}`)).json(),
  bestPosition: (state: RoomState, item: number, thenFan: boolean) =>
    post<PositionResult>("/api/best-position", { state, item, then_fan: thenFan }),
  ask: (state: RoomState, conversation: { role: string; content: string }[]) =>
    post<AgentAnswer>("/api/assistant", { state, conversation }),
  explain: (state: RoomState) => post<Explanation>("/api/explain", state),
  health: async (): Promise<Health> => (await fetch(`${BASE}/api/health`)).json(),
  /** A stored simulation, used to start the page before the service answers. */
  sample: async (path = "/sample.json"): Promise<Payload> => (await fetch(path)).json(),
  predict: (state: RoomState) => post<Payload>("/api/predict", state),
  lowestSafe: (state: RoomState) => post<Optimum>("/api/optimise", state),
  verify: (state: RoomState) => post<Verification>("/api/verify", state),
  verification: async (id: string): Promise<Verification> => (await fetch(`${BASE}/api/verify/${id}`)).json(),
};
