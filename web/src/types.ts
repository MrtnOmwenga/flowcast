export interface Machine {
  x: number;
  y: number;
  sx: number;
  sy: number;
  sz: number;
  on: boolean;
  emission: number;
  kind: "machine" | "person" | "component";
}

export interface Metrics {
  ach: number;
  flow_rate: number;
  fan_power_kw: number;
  saving_kw: number;
  saving_percent: number;
  saving_per_year: number;
  worst_level: number;
  worst_position: [number, number, number];
  mean_level: number;
  limit: number;
  within_limit: boolean;
  stagnant_fraction: number;
  ideal_age: number;
  confidence?: number;
}

export interface Assumptions {
  full_ach: number;
  full_fan_power_kw: number;
  fan_fixed_loss: number;
  particle_limit: number;
  machine_emission: number;
  person_emission: number;
  occupied_height: number;
  stagnant_age_factor: number;
  electricity_price: number;
  hours_per_year: number;
  safety_margin: number;
}

export interface RoomInfo {
  supplies: [number, number, number, number][];
  extract_y: [number, number];
  extract_height: number;
  extract_walls: string[];
  ach_range?: [number, number];
  /** Openings as (wall, u, v, su, sv); older payloads give only supplies and extracts. */
  inlets?: Opening[];
  outlets?: Opening[];
  design?: string;
  kind?: "cleanroom" | "cabinet";
}

export type Opening = [string, number, number, number, number];

export interface Payload {
  source: "model" | "simulation";
  compute?: { hardware: string; gpu: boolean; seconds: number; models: number };
  standard?: StandardInfo;
  grid: { shape: [number, number, number]; cell: number; size: [number, number, number] };
  room: RoomInfo;
  machines: Machine[];
  assumptions: Assumptions;
  metrics: Metrics;
  fields: {
    fluid: string;
    velocity: string;
    particles: string;
    age: string;
    uncertainty: string | null;
  };
}

export interface RoomState {
  machines: Machine[];
  ach: number;
  room?: string;
  standard?: string;
  minimum_ach?: number;
  limit?: string;
  ambient?: number;
}

export interface StandardInfo {
  id: string;
  name: string;
  source: string;
  in_operation: number;
  at_rest: number;
  state: "in operation" | "at rest" | "running" | "idle";
  minimum_ach: number;
  lead_minutes: number;
  cleanup_minutes: number;
  choices: { id: string; name: string; in_operation?: number; at_rest?: number; max_air?: number }[];
  // A cabinet's limit is a temperature rating rather than a cleanliness standard
  kind?: "heat";
  ambient?: number;
  max_air?: number;
  allowed_rise?: number;
  components?: { name: string; size: [number, number, number]; power: number }[];
}
