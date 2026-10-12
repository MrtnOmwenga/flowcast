import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Fields } from "./field";
import type { Machine, RoomInfo } from "./types";

export type SliceMode = "particles" | "age" | "off";

const SNAP = 0.2;
const TRACERS = 7000;
// A white room: tracer and marker colours are chosen to read against light surfaces.
const CLEAN = new THREE.Color(0x1f7ae0);
const DIRTY = new THREE.Color(0xe0401f);
const BACKGROUND = 0xeef1f5;
const MARKER = 0xd92d20;

/**
 * The room is simulated with x along its length, y across it and z up. three.js has y up,
 * so a simulation point (x, y, z) is drawn at (x, z, y), shifted to centre the room.
 */
export class RoomScene {
  onMove: (machines: Machine[], finished: boolean) => void = () => {};
  onSelect: (index: number | null) => void = () => {};

  private renderer = new THREE.WebGLRenderer({ antialias: true });
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  private controls: OrbitControls;
  private size: [number, number, number] = [6, 4, 3];
  private machines: Machine[] = [];
  private machineMeshes: THREE.Mesh[] = [];
  private roomGroup = new THREE.Group();
  private fields: Fields | null = null;

  private tracerPositions = new Float32Array(TRACERS * 3);
  private tracerColors = new Float32Array(TRACERS * 3);
  private tracerSim = new Float32Array(TRACERS * 3);
  private tracerAge = new Float32Array(TRACERS);
  private tracers: THREE.Points;
  private supplies: RoomInfo["supplies"] = [];

  private slice: THREE.Mesh;
  private sliceTexture: THREE.DataTexture | null = null;
  private sliceMode: SliceMode = "particles";
  private sliceHeight = 1.1;
  private marker: THREE.Group;

  private raycaster = new THREE.Raycaster();
  private pointer = new THREE.Vector2();
  private floor = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  private dragging: { index: number; dx: number; dy: number; start: Machine } | null = null;
  private clock = new THREE.Clock();
  speedUp = 6;

  constructor(private container: HTMLElement) {
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.scene.background = new THREE.Color(BACKGROUND);
    container.appendChild(this.renderer.domElement);
    this.camera.position.set(6.5, 5.5, 7.5);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.02;
    this.controls.minDistance = 3;
    this.controls.maxDistance = 22;

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0xcfd6df, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.1);
    sun.position.set(4, 8, 3);
    this.scene.add(sun);
    this.scene.add(this.roomGroup);

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(this.tracerPositions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(this.tracerColors, 3));
    this.tracers = new THREE.Points(
      geometry,
      new THREE.PointsMaterial({ size: 0.05, vertexColors: true, transparent: true, opacity: 0.85, depthWrite: false }),
    );
    this.tracers.frustumCulled = false;
    this.scene.add(this.tracers);

    this.slice = new THREE.Mesh(
      new THREE.PlaneGeometry(1, 1),
      new THREE.MeshBasicMaterial({ transparent: true, side: THREE.DoubleSide, depthWrite: false }),
    );
    this.slice.rotation.x = -Math.PI / 2;
    this.scene.add(this.slice);

    this.marker = new THREE.Group();
    const pin = new THREE.Mesh(new THREE.SphereGeometry(0.09, 20, 20), new THREE.MeshBasicMaterial({ color: MARKER }));
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(0.2, 0.012, 8, 40),
      new THREE.MeshBasicMaterial({ color: MARKER }),
    );
    ring.rotation.x = Math.PI / 2;
    this.marker.add(pin, ring);
    this.marker.visible = false;
    this.scene.add(this.marker);

    const element = this.renderer.domElement;
    element.addEventListener("pointerdown", (e) => this.pointerDown(e));
    element.addEventListener("pointermove", (e) => this.pointerMove(e));
    element.addEventListener("pointerup", () => this.pointerUp());
    element.addEventListener("pointerleave", () => this.pointerUp());
    new ResizeObserver(() => this.resize()).observe(container);
    this.resize();
    this.setActive(true);
  }

  /** Stop drawing while the demo is not on screen, and resume when it is. */
  setActive(active: boolean): void {
    this.clock.getDelta();
    this.renderer.setAnimationLoop(active ? () => this.frame() : null);
    if (active) this.resize();
  }

  private toWorld(x: number, y: number, z: number, out = new THREE.Vector3()): THREE.Vector3 {
    return out.set(x - this.size[0] / 2, z, y - this.size[1] / 2);
  }

  setRoom(size: [number, number, number], room: RoomInfo): void {
    this.size = size;
    this.supplies = room.supplies;
    this.roomGroup.clear();
    const [lx, ly, lz] = size;

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(lx, ly),
      new THREE.MeshStandardMaterial({ color: 0xe3e8ee, roughness: 0.85 }),
    );
    floor.rotation.x = -Math.PI / 2;
    this.roomGroup.add(floor);
    // Walls and ceiling are drawn from the inside only, so the ones nearest the camera
    // disappear and the room reads as a white box you can look into.
    const shell = new THREE.Mesh(
      new THREE.BoxGeometry(lx, lz, ly),
      new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.95, side: THREE.BackSide }),
    );
    shell.position.y = lz / 2 + 0.001;
    this.roomGroup.add(shell);
    const grid = new THREE.GridHelper(Math.max(lx, ly), Math.max(lx, ly) / 0.5, 0xb9c2cf, 0xcdd4de);
    grid.position.y = 0.004;
    grid.scale.set(lx / Math.max(lx, ly), 1, ly / Math.max(lx, ly));
    this.roomGroup.add(grid);

    const box = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(lx, lz, ly)),
      new THREE.LineBasicMaterial({ color: 0x8793a5 }),
    );
    box.position.y = lz / 2;
    this.roomGroup.add(box);

    const supplyMaterial = new THREE.MeshBasicMaterial({ color: 0x1f7ae0, transparent: true, opacity: 0.35, side: THREE.DoubleSide });
    for (const [x, y, sx, sy] of room.supplies) {
      const panel = new THREE.Mesh(new THREE.PlaneGeometry(sx, sy), supplyMaterial);
      panel.rotation.x = Math.PI / 2;
      this.toWorld(x + sx / 2, y + sy / 2, lz - 0.02, panel.position);
      this.roomGroup.add(panel);
    }
    const extractMaterial = new THREE.MeshBasicMaterial({ color: 0x5f6b7d, transparent: true, opacity: 0.55, side: THREE.DoubleSide });
    const [y0, y1] = room.extract_y;
    const walls: [string, number][] = [["x0", 0.02], ["x1", lx - 0.02]];
    for (const [name, x] of walls) {
      if (!room.extract_walls.includes(name)) continue;
      const vent = new THREE.Mesh(new THREE.PlaneGeometry(y1 - y0, room.extract_height), extractMaterial);
      vent.rotation.y = Math.PI / 2;
      this.toWorld(x, (y0 + y1) / 2, room.extract_height / 2, vent.position);
      this.roomGroup.add(vent);
    }
    this.slice.scale.set(lx, ly, 1);
    this.controls.target.set(0, lz * 0.35, 0);
  }

  setMachines(machines: Machine[]): void {
    this.machines = machines.map((m) => ({ ...m }));
    for (const mesh of this.machineMeshes) this.scene.remove(mesh);
    this.machineMeshes = this.machines.map((m) => {
      const person = m.kind === "person";
      const mesh = new THREE.Mesh(
        person ? new THREE.CapsuleGeometry(Math.min(m.sx, m.sy) / 2, m.sz - Math.min(m.sx, m.sy), 6, 16) : new THREE.BoxGeometry(m.sx, m.sz, m.sy),
        new THREE.MeshStandardMaterial(
          person ? { color: 0x8fb8e6, roughness: 0.7 } : { color: 0xd4dae2, roughness: 0.45, metalness: 0.25 },
        ),
      );
      if (!person) {
        mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry), new THREE.LineBasicMaterial({ color: 0x66717f })));
      }
      this.scene.add(mesh);
      return mesh;
    });
    this.refreshMachines();
  }

  private refreshMachines(): void {
    this.machines.forEach((m, i) => {
      const mesh = this.machineMeshes[i];
      this.toWorld(m.x + m.sx / 2, m.y + m.sy / 2, m.sz / 2, mesh.position);
      const material = mesh.material as THREE.MeshStandardMaterial;
      material.emissive.setHex(m.on ? 0xff7a2f : 0x000000);
      material.emissiveIntensity = m.on ? 0.3 : 0;
    });
  }

  setFields(fields: Fields): void {
    const first = this.fields === null;
    this.fields = fields;
    if (first) for (let i = 0; i < TRACERS; i++) this.respawn(i, true);
    this.updateSlice();
  }

  setSlice(mode: SliceMode, height: number): void {
    this.sliceMode = mode;
    this.sliceHeight = height;
    this.updateSlice();
  }

  setMarker(position: [number, number, number] | null): void {
    this.marker.visible = position !== null;
    if (position) this.toWorld(position[0], position[1], position[2], this.marker.position);
  }

  /** Redraw the coloured slice after the fields or the set of running machines change. */
  updateSlice(): void {
    const fields = this.fields;
    this.slice.visible = fields !== null && this.sliceMode !== "off";
    if (!fields || this.sliceMode === "off") return;
    const [nx, ny, nz] = fields.shape;
    if (!this.sliceTexture || this.sliceTexture.image.width !== nx) {
      this.sliceTexture = new THREE.DataTexture(new Uint8Array(nx * ny * 4), nx, ny, THREE.RGBAFormat);
      this.sliceTexture.magFilter = THREE.LinearFilter;
      this.sliceTexture.minFilter = THREE.LinearFilter;
      this.sliceTexture.flipY = true;
      (this.slice.material as THREE.MeshBasicMaterial).map = this.sliceTexture;
      (this.slice.material as THREE.MeshBasicMaterial).needsUpdate = true;
    }
    const iz = Math.min(nz - 1, Math.max(0, Math.floor(this.sliceHeight / fields.cell)));
    const pixels = this.sliceTexture.image.data as Uint8Array;
    const limit = fields.payload.assumptions.particle_limit;
    const ideal = fields.payload.metrics.ideal_age;
    const stale = fields.payload.assumptions.stagnant_age_factor;
    const color = new THREE.Color();
    for (let iy = 0; iy < ny; iy++) {
      for (let ix = 0; ix < nx; ix++) {
        const i = fields.index(ix, iy, iz);
        const p = (iy * nx + ix) * 4;
        if (fields.fluid[i] < 0.5) {
          pixels[p + 3] = 0;
          continue;
        }
        let t: number;
        if (this.sliceMode === "particles") {
          // Two decades below the limit to half a decade above it
          t = (Math.log10(Math.max(fields.level[i], 1) / limit) + 2) / 2.5;
        } else {
          t = fields.age[i] / ideal / (stale * 1.25);
        }
        heat(Math.min(1, Math.max(0, t)), color);
        pixels[p] = color.r * 255;
        pixels[p + 1] = color.g * 255;
        pixels[p + 2] = color.b * 255;
        pixels[p + 3] = 165;
      }
    }
    this.sliceTexture.needsUpdate = true;
    this.slice.position.y = (iz + 0.5) * fields.cell;
  }

  private respawn(i: number, anywhere: boolean): void {
    const fields = this.fields;
    if (!fields) return;
    const [lx, ly, lz] = this.size;
    let x = 0, y = 0, z = 0;
    if (anywhere || this.supplies.length === 0 || Math.random() < 0.15) {
      for (let attempt = 0; attempt < 20; attempt++) {
        x = Math.random() * lx;
        y = Math.random() * ly;
        z = Math.random() * lz;
        if (fields.isAir(x, y, z)) break;
      }
    } else {
      const [sx0, sy0, sw, sh] = this.supplies[Math.floor(Math.random() * this.supplies.length)];
      x = sx0 + Math.random() * sw;
      y = sy0 + Math.random() * sh;
      z = lz - 0.02 - Math.random() * 0.2;
    }
    this.tracerSim.set([x, y, z], i * 3);
    this.tracerAge[i] = anywhere ? Math.random() * 40 : 0;
  }

  private advect(dt: number): void {
    const fields = this.fields;
    if (!fields) return;
    const v: [number, number, number] = [0, 0, 0];
    const limit = fields.payload.assumptions.particle_limit;
    const world = new THREE.Vector3();
    const color = new THREE.Color();
    for (let i = 0; i < TRACERS; i++) {
      const o = i * 3;
      let x = this.tracerSim[o], y = this.tracerSim[o + 1], z = this.tracerSim[o + 2];
      fields.velocityAt(x, y, z, v);
      x += v[0] * dt;
      y += v[1] * dt;
      z += v[2] * dt;
      this.tracerAge[i] += dt;
      if (!fields.isAir(x, y, z) || this.tracerAge[i] > 90) {
        this.respawn(i, false);
        x = this.tracerSim[o];
        y = this.tracerSim[o + 1];
        z = this.tracerSim[o + 2];
      } else {
        this.tracerSim[o] = x;
        this.tracerSim[o + 1] = y;
        this.tracerSim[o + 2] = z;
      }
      this.toWorld(x, y, z, world);
      this.tracerPositions[o] = world.x;
      this.tracerPositions[o + 1] = world.y;
      this.tracerPositions[o + 2] = world.z;
      const t = (Math.log10(Math.max(fields.level[fields.cellAt(x, y, z)], 1) / limit) + 2) / 2.5;
      color.lerpColors(CLEAN, DIRTY, Math.min(1, Math.max(0, t)));
      this.tracerColors[o] = color.r;
      this.tracerColors[o + 1] = color.g;
      this.tracerColors[o + 2] = color.b;
    }
    this.tracers.geometry.attributes.position.needsUpdate = true;
    this.tracers.geometry.attributes.color.needsUpdate = true;
  }

  private setPointer(event: PointerEvent): void {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
  }

  private floorPoint(): { x: number; y: number } | null {
    const hit = new THREE.Vector3();
    if (!this.raycaster.ray.intersectPlane(this.floor, hit)) return null;
    return { x: hit.x + this.size[0] / 2, y: hit.z + this.size[1] / 2 };
  }

  private pointerDown(event: PointerEvent): void {
    this.setPointer(event);
    const hits = this.raycaster.intersectObjects(this.machineMeshes, false);
    if (hits.length === 0) {
      this.onSelect(null);
      return;
    }
    const index = this.machineMeshes.indexOf(hits[0].object as THREE.Mesh);
    const point = this.floorPoint();
    if (!point) return;
    const m = this.machines[index];
    this.dragging = { index, dx: point.x - m.x, dy: point.y - m.y, start: { ...m } };
    this.controls.enabled = false;
    this.onSelect(index);
  }

  private pointerMove(event: PointerEvent): void {
    if (!this.dragging) return;
    this.setPointer(event);
    const point = this.floorPoint();
    if (!point) return;
    const m = this.machines[this.dragging.index];
    const x = clamp(snap(point.x - this.dragging.dx), 0, snap(this.size[0] - m.sx));
    const y = clamp(snap(point.y - this.dragging.dy), 0, snap(this.size[1] - m.sy));
    if (x === m.x && y === m.y) return;
    const moved = { ...m, x, y };
    if (this.machines.some((other, i) => i !== this.dragging!.index && overlaps(moved, other))) return;
    this.machines[this.dragging.index] = moved;
    this.refreshMachines();
    this.onMove(this.machines.map((k) => ({ ...k })), false);
  }

  private pointerUp(): void {
    if (!this.dragging) return;
    this.dragging = null;
    this.controls.enabled = true;
    this.onMove(this.machines.map((k) => ({ ...k })), true);
  }

  private resize(): void {
    const { clientWidth, clientHeight } = this.container;
    if (clientWidth === 0 || clientHeight === 0) return;
    this.renderer.setSize(clientWidth, clientHeight);
    this.camera.aspect = clientWidth / clientHeight;
    this.camera.updateProjectionMatrix();
  }

  private frame(): void {
    const dt = Math.min(this.clock.getDelta(), 0.05);
    this.advect(dt * this.speedUp);
    this.marker.rotation.y += dt * 1.5;
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}

function snap(value: number): number {
  return Math.round(Math.round(value / SNAP) * SNAP * 1000) / 1000;
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, value));
}

export function overlaps(a: Machine, b: Machine): boolean {
  const eps = 1e-6;
  return a.x < b.x + b.sx - eps && b.x < a.x + a.sx - eps && a.y < b.y + b.sy - eps && b.y < a.y + a.sy - eps;
}

/** Blue through green and yellow to red, for values from 0 to 1. */
function heat(t: number, out: THREE.Color): void {
  out.setHSL(0.62 * (1 - t), 0.9, 0.5);
}
