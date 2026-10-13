import * as THREE from "three";
import type { Machine } from "./types";

/**
 * What each item looks like. The simulation treats every item as a block; these models are
 * drawn inside that block so the room reads as a room. Each is built with its floor at y = 0,
 * centred on its footprint, length along x and depth along z, and turned when the item is.
 */

export interface ItemModel {
  group: THREE.Group;
  /** Surfaces that glow while the item is running. */
  glow: THREE.MeshStandardMaterial[];
  /** The small light that shows whether the item is on. */
  lamp: THREE.MeshBasicMaterial;
}

const STEEL = { color: 0xd4dae2, roughness: 0.4, metalness: 0.35 };
const DARK = { color: 0x3a4350, roughness: 0.6, metalness: 0.2 };
const GLASS = { color: 0xbfdcef, roughness: 0.1, metalness: 0.1, transparent: true, opacity: 0.35 };
const GOWN = { color: 0xa9c9ec, roughness: 0.8 };
const SKIN = { color: 0xe8c4a8, roughness: 0.7 };
const LAMP_ON = 0x2fbf5b;
const LAMP_OFF = 0x9aa3ad;

// Footprints of the catalogue items, as simulated (length, depth, height)
const KINDS: Record<string, [number, number, number]> = {
  workbench: [1.6, 0.8, 1.0],
  cabinet: [0.8, 0.6, 1.8],
  filling: [1.2, 1.0, 1.4],
  small: [0.6, 0.6, 1.0],
  isolator: [2.0, 0.8, 1.6],
  shelving: [1.2, 0.4, 2.0],
  cart: [0.8, 0.6, 0.8],
};

export function lampColour(on: boolean): number {
  return on ? LAMP_ON : LAMP_OFF;
}

export function buildItem(m: Machine): ItemModel {
  const b = new Builder();
  if (m.kind === "person") {
    person(b, m.sz);
  } else {
    const [kind, turned] = identify(m);
    const [l, d, h] = turned ? [m.sy, m.sx, m.sz] : [m.sx, m.sy, m.sz];
    (BUILDERS[kind] ?? plainBox)(b, l, d, h);
    if (turned) b.group.rotation.y = Math.PI / 2;
  }
  return { group: b.group, glow: b.glow, lamp: b.lamp };
}

function identify(m: Machine): [string, boolean] {
  const near = (a: number, c: number) => Math.abs(a - c) < 0.01;
  for (const [kind, [l, d, h]] of Object.entries(KINDS)) {
    if (!near(m.sz, h)) continue;
    if (near(m.sx, l) && near(m.sy, d)) return [kind, false];
    if (near(m.sx, d) && near(m.sy, l)) return [kind, true];
  }
  if (m.kind === "component") return ["component", m.sy > m.sx];
  return ["box", false];
}

class Builder {
  group = new THREE.Group();
  glow: THREE.MeshStandardMaterial[] = [];
  lamp = new THREE.MeshBasicMaterial({ color: LAMP_OFF });
  private materials = new Map<object, THREE.MeshStandardMaterial>();

  material(spec: THREE.MeshStandardMaterialParameters): THREE.MeshStandardMaterial {
    let material = this.materials.get(spec);
    if (!material) {
      material = new THREE.MeshStandardMaterial(spec);
      this.materials.set(spec, material);
      if (spec === STEEL) this.glow.push(material);
    }
    return material;
  }

  /** A box from its centre and size, in the item's own frame. */
  box(x: number, y: number, z: number, sx: number, sy: number, sz: number, spec: THREE.MeshStandardMaterialParameters = STEEL): THREE.Mesh {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, sz), this.material(spec));
    mesh.position.set(x, y, z);
    this.group.add(mesh);
    return mesh;
  }

  /** An upright cylinder standing on y0. */
  post(x: number, y0: number, z: number, radius: number, height: number, spec: THREE.MeshStandardMaterialParameters = STEEL, top = radius): THREE.Mesh {
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(top, radius, height, 14), this.material(spec));
    mesh.position.set(x, y0 + height / 2, z);
    this.group.add(mesh);
    return mesh;
  }

  sphere(x: number, y: number, z: number, radius: number, spec: THREE.MeshStandardMaterialParameters): THREE.Mesh {
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(radius, 20, 16), this.material(spec));
    mesh.position.set(x, y, z);
    this.group.add(mesh);
    return mesh;
  }

  statusLamp(x: number, y: number, z: number): void {
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.03, 12, 10), this.lamp);
    mesh.position.set(x, y, z);
    this.group.add(mesh);
  }

  /** Four legs inset from the corners of an l by d footprint. */
  legs(l: number, d: number, height: number, inset = 0.06, radius = 0.025): void {
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) this.post(sx * (l / 2 - inset), 0, sz * (d / 2 - inset), radius, height);
  }
}

type Build = (b: Builder, l: number, d: number, h: number) => void;

const BUILDERS: Record<string, Build> = {
  workbench(b, l, d, h) {
    // the simulated block includes what stands on the bench, so the top sits below its height
    const top = 0.05;
    const surface = h - 0.24;
    b.box(0, surface - top / 2, 0, l, top, d);
    b.legs(l, d, surface - top);
    b.box(0, 0.18, 0, l - 0.12, 0.03, d - 0.12); // lower shelf
    // an instrument on the bench, with its screen facing the front
    b.box(-l * 0.22, surface + 0.11, -d * 0.1, 0.4, 0.22, 0.34, DARK);
    b.box(-l * 0.22, surface + 0.13, -d * 0.1 + 0.172, 0.28, 0.12, 0.005, GLASS);
    b.box(l * 0.2, surface + 0.04, 0.05, 0.3, 0.08, 0.2, STEEL); // a tray
    b.statusLamp(l / 2 - 0.1, surface + 0.03, d / 2 - 0.1);
  },
  cabinet(b, l, d, h) {
    b.box(0, 0.04, 0, l - 0.04, 0.08, d - 0.04, DARK); // plinth
    b.box(0, h / 2 + 0.04, 0, l, h - 0.08, d);
    b.box(0, h / 2 + 0.04, d / 2 + 0.003, 0.008, h - 0.16, 0.004, DARK); // door seam
    for (const s of [-1, 1]) b.box(s * 0.05, h * 0.55, d / 2 + 0.015, 0.02, 0.22, 0.02, DARK); // handles
    b.statusLamp(l / 2 - 0.08, h - 0.08, d / 2 + 0.01);
  },
  filling(b, l, d, h) {
    const base = h * 0.6;
    b.box(0, base / 2, 0, l, base, d);
    b.box(0, base + 0.03, 0, l * 0.98, 0.06, 0.18, DARK); // conveyor
    const guard = h - base;
    b.box(0, base + guard / 2, 0, l - 0.02, guard, d - 0.02, GLASS);
    b.box(0, h - 0.015, 0, l, 0.03, d); // guard frame top
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) b.box(sx * (l / 2 - 0.02), base + guard / 2, sz * (d / 2 - 0.02), 0.03, guard, 0.03);
    // filling heads above the conveyor
    for (let i = -1; i <= 1; i++) b.post(i * 0.18, base + 0.12, 0, 0.03, guard - 0.15, DARK);
    b.box(l / 2 - 0.15, base * 0.7, d / 2 + 0.01, 0.2, 0.15, 0.01, DARK); // control screen
    b.statusLamp(l / 2 - 0.05, base * 0.7 + 0.12, d / 2 + 0.02);
  },
  small(b, l, d, h) {
    b.legs(l, d, 0.06, 0.06, 0.02);
    b.box(0, 0.06 + (h - 0.06) / 2, 0, l, h - 0.06, d);
    b.box(0, h * 0.7, d / 2 + 0.005, l * 0.6, h * 0.35, 0.01, DARK); // front panel
    b.box(0, h * 0.75, d / 2 + 0.012, l * 0.4, h * 0.12, 0.005, GLASS); // display
    b.statusLamp(l * 0.22, h * 0.6, d / 2 + 0.015);
  },
  isolator(b, l, d, h) {
    const stand = h * 0.5;
    b.legs(l, d, stand, 0.08, 0.03);
    b.box(0, stand * 0.3, 0, l - 0.1, 0.03, d - 0.1); // lower brace
    const chamber = h * 0.38;
    b.box(0, stand + 0.02, 0, l, 0.04, d); // chamber floor
    b.box(0, stand + 0.04 + chamber / 2, -0.05, l, chamber, d - 0.1);
    b.box(0, stand + 0.04 + chamber / 2, d / 2 - 0.05, l - 0.04, chamber - 0.02, 0.012, GLASS); // window
    // glove ports in the window, two per operator position
    const ring = new THREE.TorusGeometry(0.075, 0.018, 10, 28);
    for (const x of [-l * 0.3, -l * 0.1, l * 0.1, l * 0.3]) {
      const port = new THREE.Mesh(ring, b.material(DARK));
      port.position.set(x, stand + 0.04 + chamber * 0.45, d / 2 - 0.04);
      b.group.add(port);
    }
    const filter = h - stand - 0.04 - chamber;
    b.box(0, h - filter / 2, -0.05, l * 0.9, filter, d * 0.8, DARK); // filter unit on top
    b.statusLamp(l / 2 - 0.1, h - filter / 2, d / 2 - 0.08);
  },
  shelving(b, l, d, h) {
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) b.post(sx * (l / 2 - 0.02), 0, sz * (d / 2 - 0.02), 0.015, h);
    const shelves = 5;
    for (let i = 0; i < shelves; i++) {
      const y = 0.12 + (i * (h - 0.2)) / (shelves - 1);
      b.box(0, y, 0, l, 0.02, d);
      if (i < shelves - 1) {
        // a few containers on each shelf
        for (let k = 0; k < 3; k++) {
          const w = 0.22 + ((i + k) % 3) * 0.05;
          b.box(-l / 2 + 0.2 + k * (l / 3), y + 0.11, 0, w, 0.2, d * 0.7, DARK);
        }
      }
    }
  },
  cart(b, l, d, h) {
    const wheel = 0.05;
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
      const caster = new THREE.Mesh(new THREE.CylinderGeometry(wheel, wheel, 0.025, 16), b.material(DARK));
      caster.rotation.x = Math.PI / 2;
      caster.position.set(sx * (l / 2 - 0.07), wheel, sz * (d / 2 - 0.07));
      b.group.add(caster);
    }
    b.legs(l, d, h * 0.82, 0.04, 0.015);
    b.box(0, 0.22, 0, l, 0.025, d);
    b.box(0, h * 0.62, 0, l, 0.025, d);
    b.box(-l * 0.15, 0.32, 0, l * 0.35, 0.18, d * 0.6, DARK); // a crate on the lower shelf
    // push handle
    b.post(l / 2 - 0.02, h * 0.62, -d / 2 + 0.06, 0.012, h * 0.38);
    b.post(l / 2 - 0.02, h * 0.62, d / 2 - 0.06, 0.012, h * 0.38);
    const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, d - 0.12, 12), b.material(STEEL));
    bar.rotation.x = Math.PI / 2;
    bar.position.set(l / 2 - 0.02, h - 0.01, 0);
    b.group.add(bar);
  },
  component(b, l, d, h) {
    // a drive or power unit on the mounting plate: dark body, cooling fins, a front label
    b.box(0, h * 0.4, 0, l, h * 0.8, d, DARK);
    const fins = Math.max(3, Math.round(l / 0.03));
    for (let i = 0; i < fins; i++) b.box(-l / 2 + (i + 0.5) * (l / fins), h * 0.9, 0, 0.006, h * 0.2, d * 0.95);
    b.box(0, h * 0.5, d / 2 + 0.003, l * 0.5, h * 0.25, 0.004, GLASS);
    b.statusLamp(l / 2 - 0.03, h * 0.65, d / 2 + 0.006);
  },
};

function plainBox(b: Builder, l: number, d: number, h: number): void {
  b.box(0, h / 2, 0, l, h, d);
  b.statusLamp(l / 2 - 0.06, h - 0.06, d / 2 + 0.01);
}

/** A gowned operator: hood, visor, coverall and overshoes, facing +z. */
function person(b: Builder, h: number): void {
  const s = h / 1.8;
  for (const x of [-0.09, 0.09]) {
    b.post(x, 0, 0.02, 0.065 * s, 0.82 * s, GOWN, 0.075 * s); // legs
    b.box(x, 0.03 * s, 0.04, 0.11 * s, 0.06 * s, 0.24 * s, DARK); // overshoes
  }
  b.post(0, 0.8 * s, 0, 0.17 * s, 0.6 * s, GOWN, 0.19 * s); // torso, wider at the shoulders
  for (const x of [-0.24, 0.24]) {
    const arm = b.post(x * s, 0.82 * s, 0.04, 0.045 * s, 0.56 * s, GOWN, 0.055 * s);
    arm.rotation.x = -0.35; // forearms reach forward, as at a bench
    b.sphere(x * s, 0.86 * s, 0.14, 0.05 * s, DARK); // gloves
  }
  b.post(0, 1.4 * s, 0, 0.06 * s, 0.08 * s, GOWN); // neck
  b.sphere(0, 1.6 * s, 0, 0.13 * s, GOWN); // hood
  const face = b.sphere(0, 1.58 * s, 0.05, 0.1 * s, SKIN);
  face.scale.set(0.9, 0.55, 0.9);
  const visor = b.box(0, 1.62 * s, 0.11 * s, 0.17 * s, 0.07 * s, 0.03 * s, GLASS);
  visor.material = b.material({ ...GLASS, color: 0x2a3440, opacity: 0.7 } as THREE.MeshStandardMaterialParameters);
  b.statusLamp(0.1 * s, 1.25 * s, 0.18 * s); // badge light
}
