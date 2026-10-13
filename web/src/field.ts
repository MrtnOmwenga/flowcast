import type { Machine, Payload } from "./types";

function decode(text: string): Float32Array {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Float32Array(bytes.buffer);
}

/** The fields of one room state on its regular grid, with x slowest and z fastest. */
export class Fields {
  readonly shape: [number, number, number];
  readonly cell: number;
  readonly size: [number, number, number];
  readonly cells: number;
  readonly fluid: Float32Array;
  readonly velocity: Float32Array;
  readonly age: Float32Array;
  readonly uncertainty: Float32Array | null;
  /** Particle level per cell for the machines currently on, in particles per cubic metre. */
  level: Float32Array;
  private readonly perMachine: Float32Array;

  constructor(readonly payload: Payload) {
    this.shape = payload.grid.shape;
    this.cell = payload.grid.cell;
    this.size = payload.grid.size;
    this.cells = this.shape[0] * this.shape[1] * this.shape[2];
    this.fluid = decode(payload.fields.fluid);
    this.velocity = decode(payload.fields.velocity);
    this.age = decode(payload.fields.age);
    this.perMachine = decode(payload.fields.particles);
    this.uncertainty = payload.fields.uncertainty ? decode(payload.fields.uncertainty) : null;
    this.level = new Float32Array(this.cells);
    this.combine(payload.machines);
  }

  /** Add up the fields of the machines that are on. Particles do not change the airflow, so this is exact. */
  combine(machines: Machine[]): void {
    this.level.fill(0);
    const a = this.payload.assumptions;
    machines.forEach((machine, m) => {
      if (!machine.on) return;
      const usual = machine.kind === "person" ? a.person_emission
        : machine.kind === "component" ? a.machine_emission * this.powerOf(machine) : a.machine_emission;
      const weight = usual * machine.emission;
      const offset = m * this.cells;
      for (let i = 0; i < this.cells; i++) this.level[i] += weight * this.perMachine[offset + i];
    });
  }

  /** Watts a cabinet component gives off, from the table the service sends; an unknown size counts as a drive. */
  powerOf(m: Machine): number {
    const table = this.payload.standard?.components ?? [];
    const near = (a: number, b: number) => Math.abs(a - b) < 1e-3;
    const found = table.find(({ size: [sx, sy, sz] }) =>
      near(sz, m.sz) && ((near(sx, m.sx) && near(sy, m.sy)) || (near(sx, m.sy) && near(sy, m.sx))));
    return (found ?? table.find((c) => c.name === "drive"))?.power ?? 120;
  }

  index(ix: number, iy: number, iz: number): number {
    return (ix * this.shape[1] + iy) * this.shape[2] + iz;
  }

  private clampCell(p: number, axis: number): number {
    return Math.min(this.shape[axis] - 1, Math.max(0, Math.floor(p / this.cell)));
  }

  cellAt(x: number, y: number, z: number): number {
    return this.index(this.clampCell(x, 0), this.clampCell(y, 1), this.clampCell(z, 2));
  }

  isAir(x: number, y: number, z: number): boolean {
    if (x < 0 || y < 0 || z < 0 || x >= this.size[0] || y >= this.size[1] || z >= this.size[2]) return false;
    return this.fluid[this.cellAt(x, y, z)] > 0.5;
  }

  /** Air velocity at a point, blended between the surrounding cell centres. */
  velocityAt(x: number, y: number, z: number, out: [number, number, number]): void {
    const [nx, ny, nz] = this.shape;
    const gx = Math.min(nx - 1.001, Math.max(0, x / this.cell - 0.5));
    const gy = Math.min(ny - 1.001, Math.max(0, y / this.cell - 0.5));
    const gz = Math.min(nz - 1.001, Math.max(0, z / this.cell - 0.5));
    const ix = Math.floor(gx), iy = Math.floor(gy), iz = Math.floor(gz);
    const fx = gx - ix, fy = gy - iy, fz = gz - iz;
    out[0] = out[1] = out[2] = 0;
    for (let dx = 0; dx < 2; dx++) {
      for (let dy = 0; dy < 2; dy++) {
        for (let dz = 0; dz < 2; dz++) {
          const weight = (dx ? fx : 1 - fx) * (dy ? fy : 1 - fy) * (dz ? fz : 1 - fz);
          const i = this.index(ix + dx, iy + dy, iz + dz);
          for (let c = 0; c < 3; c++) out[c] += weight * this.velocity[c * this.cells + i];
        }
      }
    }
  }

  /** Highest particle level in the occupied zone, leaving out the cells where machines release particles. */
  worst(machines: Machine[]): { level: number; position: [number, number, number] } {
    const [nx, ny] = this.shape;
    const top = Math.min(this.shape[2], Math.round(this.payload.assumptions.occupied_height / this.cell));
    const excluded = new Uint8Array(this.cells);
    for (const m of machines) {
      // The release cells grown by one: above a machine, all around a person or a cabinet component.
      const round = m.kind === "person" || m.kind === "component";
      const reach = round ? 2 : 1;
      const x0 = Math.round(m.x / this.cell) - reach, x1 = Math.round((m.x + m.sx) / this.cell) + reach;
      const y0 = Math.round(m.y / this.cell) - reach, y1 = Math.round((m.y + m.sy) / this.cell) + reach;
      const top = Math.round(m.sz / this.cell);
      const z0 = round ? 0 : top - 1, z1 = round ? top + 2 : top + 3;
      for (let ix = Math.max(0, x0); ix < Math.min(nx, x1); ix++)
        for (let iy = Math.max(0, y0); iy < Math.min(ny, y1); iy++)
          for (let iz = Math.max(0, z0); iz < Math.min(this.shape[2], z1); iz++) excluded[this.index(ix, iy, iz)] = 1;
    }
    let best = -1;
    let at = 0;
    for (let ix = 0; ix < nx; ix++)
      for (let iy = 0; iy < ny; iy++)
        for (let iz = 0; iz < top; iz++) {
          const i = this.index(ix, iy, iz);
          if (this.fluid[i] > 0.5 && !excluded[i] && this.level[i] > best) {
            best = this.level[i];
            at = i;
          }
        }
    const iz = at % this.shape[2];
    const iy = Math.floor(at / this.shape[2]) % ny;
    const ix = Math.floor(at / (this.shape[2] * ny));
    return { level: Math.max(best, 0), position: [(ix + 0.5) * this.cell, (iy + 0.5) * this.cell, (iz + 0.5) * this.cell] };
  }
}
