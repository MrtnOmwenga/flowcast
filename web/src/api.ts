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
  language_model?: string | null;
}

export interface Explanation {
  text: string;
  model: string;
  hosted_on: string;
}

export const api = {
  explain: (state: RoomState) => post<Explanation>("/api/explain", state),
  health: async (): Promise<Health> => (await fetch(`${BASE}/api/health`)).json(),
  /** A stored simulation, used to start the page before the service answers. */
  sample: async (): Promise<Payload> => (await fetch("/sample.json")).json(),
  predict: (state: RoomState) => post<Payload>("/api/predict", state),
  lowestSafe: (state: RoomState) => post<Optimum>("/api/optimise", state),
  verify: (state: RoomState) => post<Verification>("/api/verify", state),
  verification: async (id: string): Promise<Verification> => (await fetch(`${BASE}/api/verify/${id}`)).json(),
};
