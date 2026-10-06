import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

export type HardwareKind = 'cpu' | 'qpu' | 'gpu';

export interface HardwareSceneOptions {
  initialFocus?: HardwareKind;
  onReady?: () => void;
  onLabels?: (positions: Record<HardwareKind, { x: number; y: number; visible: boolean }>) => void;
}

export interface HardwareSceneHandle {
  setFocus: (kind: HardwareKind) => void;
  reset: () => void;
  dispose: () => void;
}

type Equipment = {
  group: THREE.Group;
  accent: THREE.MeshStandardMaterial;
  marker: THREE.MeshBasicMaterial;
};

type FlowRoute = {
  curve: THREE.CatmullRomCurve3;
  pulse: THREE.Mesh;
};

const PALETTE = {
  shell: 0x243548,
  shellDark: 0x152331,
  graphite: 0x1a2d3e,
  trim: 0x91a9bb,
  silver: 0xb8c8d1,
  brass: 0xbd9160,
  copper: 0xc88756,
  blue: 0x258de8,
  teal: 0x0eafa4,
  gold: 0xd2ad73,
};

const EQUIPMENT_X: Record<HardwareKind, number> = { cpu: -2.38, qpu: 0, gpu: 2.38 };
const FOCUS_AZIMUTH: Record<HardwareKind, number> = { cpu: -0.75, qpu: Math.atan2(6.8, 11.8), gpu: 0.86 };

function standard(color: number, metalness = 0.35, roughness = 0.42): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({ color, metalness, roughness });
}

function box(
  parent: THREE.Object3D,
  size: [number, number, number],
  position: [number, number, number],
  material: THREE.Material,
  radius = 0,
  castShadow = false,
): THREE.Mesh {
  const [width, height, depth] = size;
  const geometry = radius > 0
    ? new RoundedBoxGeometry(width, height, depth, 2, radius)
    : new THREE.BoxGeometry(width, height, depth);
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.set(...position);
  mesh.castShadow = castShadow;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

function cylinder(
  parent: THREE.Object3D,
  radii: [number, number, number],
  position: [number, number, number],
  material: THREE.Material,
  segments = 32,
  castShadow = false,
): THREE.Mesh {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radii[0], radii[1], radii[2], segments), material);
  mesh.position.set(...position);
  mesh.castShadow = castShadow;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

function tube(
  parent: THREE.Object3D,
  points: THREE.Vector3[],
  radius: number,
  material: THREE.Material,
): THREE.Mesh {
  const curve = new THREE.CatmullRomCurve3(points);
  const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, Math.max(16, points.length * 8), radius, 6, false), material);
  parent.add(mesh);
  return mesh;
}

function ring(
  parent: THREE.Object3D,
  radius: number,
  tubeRadius: number,
  y: number,
  material: THREE.Material,
): THREE.Mesh {
  const mesh = new THREE.Mesh(new THREE.TorusGeometry(radius, tubeRadius, 8, 48), material);
  mesh.rotation.x = Math.PI / 2;
  mesh.position.y = y;
  parent.add(mesh);
  return mesh;
}

function makeLabel(parent: THREE.Object3D, text: string, x: number, y: number, z: number, width: number): void {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 80;
  const context = canvas.getContext('2d');
  if (!context) return;
  context.clearRect(0, 0, 512, 80);
  context.fillStyle = '#d9e5ed';
  context.font = '600 32px Arial, sans-serif';
  context.textBaseline = 'middle';
  context.fillText(text, 2, 40);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const material = new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false, side: THREE.DoubleSide });
  const label = new THREE.Mesh(new THREE.PlaneGeometry(width, width * 80 / 512), material);
  label.position.set(x, y, z);
  parent.add(label);
}

function statusMarker(parent: THREE.Object3D, color: number, width: number): THREE.MeshBasicMaterial {
  const material = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.24, depthWrite: false });
  const marker = new THREE.Mesh(new THREE.RingGeometry(width * 0.62, width * 0.64, 64), material);
  marker.rotation.x = -Math.PI / 2;
  marker.position.y = 0.025;
  parent.add(marker);
  return material;
}

function contactShadow(parent: THREE.Object3D, width: number, depth: number, opacity = 0.26): void {
  const canvas = document.createElement('canvas');
  canvas.width = 128;
  canvas.height = 128;
  const context = canvas.getContext('2d');
  if (!context) return;
  const gradient = context.createRadialGradient(64, 64, 10, 64, 64, 63);
  gradient.addColorStop(0, `rgba(24, 42, 56, ${opacity})`);
  gradient.addColorStop(0.44, `rgba(24, 42, 56, ${opacity * 0.55})`);
  gradient.addColorStop(1, 'rgba(24, 42, 56, 0)');
  context.fillStyle = gradient;
  context.fillRect(0, 0, 128, 128);
  const texture = new THREE.CanvasTexture(canvas);
  const material = new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false, opacity: 1 });
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(width, depth), material);
  plane.rotation.x = -Math.PI / 2;
  plane.position.y = 0.004;
  parent.add(plane);
}

/** Build a five-sled control rack whose trays, vents and indicators remain legible at hero scale. */
function buildCpu(): Equipment {
  const group = new THREE.Group();
  group.position.x = EQUIPMENT_X.cpu;
  const cabinet = standard(0x526a7d, 0.58, 0.3);
  const bezel = standard(PALETTE.shellDark, 0.42, 0.48);
  const slot = standard(0x0d1b29, 0.25, 0.7);
  const tray = standard(0x32485b, 0.55, 0.4);
  const trim = standard(PALETTE.trim, 0.66, 0.28);
  const accent = new THREE.MeshStandardMaterial({ color: PALETTE.blue, emissive: PALETTE.blue, emissiveIntensity: 0.42, metalness: 0.25, roughness: 0.32 });

  box(group, [1.68, 3.18, 1.23], [0, 1.69, 0], cabinet, 0.065, true);
  box(group, [1.48, 2.83, 0.055], [0, 1.65, 0.637], bezel, 0.022);
  box(group, [1.77, 0.11, 1.32], [0, 3.29, 0], trim, 0.025);
  box(group, [1.82, 0.14, 1.37], [0, 0.09, 0], bezel, 0.03, true);
  box(group, [0.018, 2.61, 0.79], [0.851, 1.68, -0.05], trim, 0.007);
  box(group, [0.024, 2.48, 0.69], [0.864, 1.68, -0.05], cabinet, 0.007);
  for (let vent = 0; vent < 17; vent += 1) {
    box(group, [0.012, 0.023, 0.48], [0.882, 0.57 + vent * 0.135, -0.08], bezel);
  }
  for (const y of [0.42, 2.94]) for (const z of [-0.43, 0.31]) {
    cylinder(group, [0.018, 0.018, 0.015], [0.884, y, z], trim, 12).rotation.z = Math.PI / 2;
  }
  for (const x of [-0.77, 0.77]) {
    box(group, [0.035, 2.81, 0.065], [x, 1.65, 0.67], trim);
    for (const z of [-0.42, 0.42]) cylinder(group, [0.045, 0.045, 0.13], [x, 0.09, z], slot, 10);
  }

  for (let index = 0; index < 5; index += 1) {
    const y = 0.49 + index * 0.515;
    box(group, [1.36, 0.42, 0.08], [0, y, 0.69], tray, 0.015);
    box(group, [1.28, 0.035, 0.014], [0, y + 0.17, 0.739], trim);
    for (let vent = 0; vent < 14; vent += 1) {
      box(group, [0.025, 0.095, 0.01], [-0.54 + vent * 0.064, y - 0.035, 0.739], slot);
    }
    box(group, [0.065, 0.13, 0.018], [0.52, y - 0.028, 0.75], trim, 0.006);
    box(group, [0.028, 0.028, 0.012], [0.57, y + 0.112, 0.753], accent, 0.006);
  }
  box(group, [0.2, 0.045, 0.025], [-0.49, 3.12, 0.66], accent, 0.012);
  makeLabel(group, 'CPU  /  CONTROL', -0.5, 3.08, 0.669, 0.87);
  contactShadow(group, 2.65, 2.28);
  const marker = statusMarker(group, PALETTE.blue, 1.7);
  return { group, accent, marker };
}

function addFan(parent: THREE.Object3D, x: number, y: number, z: number, dark: THREE.Material, blade: THREE.Material, trim: THREE.Material): THREE.Group {
  const fan = new THREE.Group();
  fan.position.set(x, y, z);
  parent.add(fan);
  const outer = new THREE.Mesh(new THREE.TorusGeometry(0.24, 0.018, 8, 32), trim);
  fan.add(outer);
  const inner = new THREE.Mesh(new THREE.TorusGeometry(0.19, 0.008, 6, 32), dark);
  fan.add(inner);
  const bladeShape = new THREE.Shape();
  bladeShape.moveTo(0.035, 0.015);
  bladeShape.lineTo(0.17, 0.085);
  bladeShape.lineTo(0.155, -0.03);
  bladeShape.lineTo(0.055, -0.04);
  bladeShape.closePath();
  const bladeGeometry = new THREE.ShapeGeometry(bladeShape);
  for (let index = 0; index < 6; index += 1) {
    const spoke = new THREE.Mesh(bladeGeometry, blade);
    spoke.rotation.z = index * Math.PI / 3;
    spoke.position.z = 0.008;
    fan.add(spoke);
  }
  const hub = new THREE.Mesh(new THREE.CircleGeometry(0.055, 20), trim);
  hub.position.z = 0.019;
  fan.add(hub);
  return fan;
}

/** Build the dark accelerator rack with visible cooling fans and replaceable GPU sleds. */
function buildGpu(fans: THREE.Group[]): Equipment {
  const group = new THREE.Group();
  group.position.x = EQUIPMENT_X.gpu;
  const cabinet = standard(0x1e3445, 0.58, 0.37);
  const bezel = standard(0x0d1d29, 0.34, 0.55);
  const module = standard(0x253c4a, 0.55, 0.32);
  const blade = standard(0x597487, 0.64, 0.29);
  const trim = standard(0x849daa, 0.65, 0.31);
  const accent = new THREE.MeshStandardMaterial({ color: PALETTE.teal, emissive: PALETTE.teal, emissiveIntensity: 0.35, metalness: 0.18, roughness: 0.31 });

  box(group, [1.75, 3.15, 1.34], [0, 1.67, 0], cabinet, 0.06, true);
  box(group, [1.59, 2.82, 0.055], [0, 1.69, 0.693], bezel, 0.02);
  box(group, [1.81, 0.09, 1.4], [0, 3.29, 0], trim, 0.02);
  box(group, [1.86, 0.14, 1.47], [0, 0.09, 0], bezel, 0.03, true);
  box(group, [0.025, 2.55, 0.95], [0.889, 1.65, -0.025], trim, 0.006);
  box(group, [0.029, 2.46, 0.85], [0.904, 1.65, -0.025], cabinet, 0.006);
  for (let vent = 0; vent < 23; vent += 1) {
    box(group, [0.013, 0.018, 0.64], [0.923, 0.52 + vent * 0.105, -0.02], bezel);
  }
  for (let port = 0; port < 3; port += 1) {
    box(group, [0.048, 0.11, 0.13], [0.937, 2.51 - port * 0.2, -0.27], trim, 0.006);
    box(group, [0.017, 0.057, 0.08], [0.966, 2.51 - port * 0.2, -0.27], bezel);
  }
  for (const x of [-0.8, 0.8]) {
    box(group, [0.035, 2.83, 0.07], [x, 1.69, 0.72], trim);
  }

  for (let index = 0; index < 3; index += 1) {
    const y = 0.82 + index * 0.79;
    box(group, [1.48, 0.68, 0.085], [0, y, 0.755], module, 0.016);
    box(group, [1.4, 0.025, 0.015], [0, y - 0.305, 0.805], accent);
    for (const x of [-0.37, 0.37]) {
      const fan = addFan(group, x, y, 0.809, bezel, blade, trim);
      fans.push(fan);
    }
    box(group, [0.025, 0.05, 0.012], [0.675, y + 0.27, 0.812], accent, 0.005);
  }
  makeLabel(group, 'GPU  /  ACCELERATOR', -0.56, 3.10, 0.716, 1.0);
  contactShadow(group, 2.77, 2.44);
  const marker = statusMarker(group, PALETTE.teal, 1.78);
  return { group, accent, marker };
}

/** Build an open dilution-refrigerator silhouette with nested cold stages and coaxial lines. */
function buildQpu(): Equipment {
  const group = new THREE.Group();
  group.position.x = EQUIPMENT_X.qpu;
  const dark = standard(0x203348, 0.5, 0.37);
  const silver = standard(PALETTE.silver, 0.78, 0.2);
  const satin = standard(0x8199a6, 0.64, 0.34);
  const gold = standard(PALETTE.gold, 0.75, 0.24);
  const copper = standard(PALETTE.copper, 0.72, 0.28);
  const accent = new THREE.MeshStandardMaterial({ color: PALETTE.blue, emissive: PALETTE.blue, emissiveIntensity: 0.36, metalness: 0.3, roughness: 0.28 });

  box(group, [1.85, 0.17, 1.68], [0, 0.14, 0], dark, 0.035, true);
  for (const x of [-0.72, 0.72]) for (const z of [-0.58, 0.58]) {
    cylinder(group, [0.034, 0.034, 3.13], [x, 1.82, z], satin, 12);
    cylinder(group, [0.052, 0.052, 0.07], [x, 0.29, z], silver, 12);
  }

  // The silver top plate and descending copper stages follow the actual visual hierarchy of an open cryostat.
  cylinder(group, [0.88, 0.88, 0.17], [0, 3.45, 0], silver, 64, true);
  cylinder(group, [0.73, 0.73, 0.21], [0, 3.64, 0], dark, 64, true);
  cylinder(group, [0.68, 0.68, 0.055], [0, 3.78, 0], silver, 64);
  ring(group, 0.83, 0.025, 3.53, satin);
  ring(group, 0.72, 0.014, 3.32, accent);

  const stageData: Array<[number, number, number]> = [
    [2.99, 0.76, 0.13],
    [2.55, 0.67, 0.13],
    [2.12, 0.56, 0.13],
    [1.73, 0.44, 0.13],
    [1.36, 0.34, 0.14],
  ];
  stageData.forEach(([y, radius, height], index) => {
    cylinder(group, [radius, radius, height], [0, y, 0], index < 2 ? gold : copper, 64, true);
    cylinder(group, [radius * 0.91, radius * 0.91, 0.024], [0, y + height / 2 + 0.014, 0], silver, 64);
    ring(group, radius * 0.97, 0.011, y - height / 2, satin);
  });

  cylinder(group, [0.16, 0.16, 0.96], [0, 1.7, 0], gold, 32);
  cylinder(group, [0.2, 0.16, 0.49], [0, 1.02, 0], copper, 32, true);
  cylinder(group, [0.28, 0.28, 0.07], [0, 0.76, 0], silver, 32);
  for (let index = 0; index < 8; index += 1) {
    const angle = index * Math.PI / 4;
    const x = Math.cos(angle);
    const z = Math.sin(angle);
    tube(group, [
      new THREE.Vector3(x * 0.59, 3.4, z * 0.59),
      new THREE.Vector3(x * 0.58, 2.92, z * 0.58),
      new THREE.Vector3(x * 0.48, 2.34, z * 0.48),
      new THREE.Vector3(x * 0.34, 1.7, z * 0.34),
      new THREE.Vector3(x * 0.20, 1.05, z * 0.20),
    ], 0.013, index % 2 ? gold : copper);
  }
  for (const x of [-0.36, 0.36]) {
    tube(group, [
      new THREE.Vector3(x, 3.8, -0.28),
      new THREE.Vector3(x, 4.03, -0.29),
      new THREE.Vector3(x * 1.5, 4.16, -0.35),
      new THREE.Vector3(x * 1.8, 4.0, -0.39),
    ], 0.025, silver);
  }
  for (let index = 0; index < 6; index += 1) {
    const angle = index * Math.PI / 3;
    const x = Math.cos(angle) * 0.55;
    const z = Math.sin(angle) * 0.55;
    cylinder(group, [0.036, 0.036, 0.095], [x, 3.83, z], copper, 12);
    cylinder(group, [0.024, 0.024, 0.033], [x, 3.9, z], dark, 12);
  }
  for (const x of [-0.47, 0.47]) {
    box(group, [0.045, 0.69, 0.052], [x, 1.6, -0.05], silver, 0.006);
  }
  contactShadow(group, 2.95, 2.58, 0.3);
  const marker = statusMarker(group, PALETTE.blue, 1.89);
  return { group, accent, marker };
}

/** Cable runs visibly connect the machine housings without masking the cryostat stages. */
function buildInterconnects(parent: THREE.Object3D): THREE.Group[] {
  const jacket = standard(0x253f52, 0.18, 0.65);
  const jacketBlue = standard(0x2b648a, 0.22, 0.58);
  const collar = standard(0xaabecb, 0.66, 0.3);
  const sides: THREE.Group[] = [];
  for (const side of [-1, 1]) {
    const rackX = side * 1.47;
    const stageX = side * 0.85;
    const cableGroup = new THREE.Group();
    cableGroup.position.x = stageX;
    parent.add(cableGroup);
    sides.push(cableGroup);
    const point = (x: number, y: number, z: number): THREE.Vector3 => new THREE.Vector3(x - stageX, y, z);
    for (let index = 0; index < 3; index += 1) {
      const y = 0.73 + index * 0.115;
      const z = 0.14 + index * 0.11;
      tube(cableGroup, [
        point(rackX, y, z),
        point(side * 1.3, y - 0.07, z + 0.05),
        point(side * 1.18, 0.27 + index * 0.03, z + 0.08),
        point(side * 1.0, 0.25 + index * 0.03, z + 0.09),
        point(stageX, 0.5 + index * 0.035, z + 0.06),
      ], index === 1 ? 0.025 : 0.019, index === 1 ? jacketBlue : jacket);
      const socket = cylinder(cableGroup, [0.038, 0.038, 0.08], [rackX - stageX, y, z], collar, 12);
      socket.rotation.z = Math.PI / 2;
      const ferrule = cylinder(cableGroup, [0.031, 0.031, 0.07], [0, 0.5 + index * 0.035, z + 0.06], collar, 12);
      ferrule.rotation.z = Math.PI / 2;
    }
  }
  return sides;
}

/** Trace the AIMD handoff from CPU setup through QPU readout and GPU energy prediction back to CPU integration. */
function buildFlowRoutes(parent: THREE.Object3D): { group: THREE.Group; routes: FlowRoute[] } {
  const group = new THREE.Group();
  parent.add(group);
  const routes: FlowRoute[] = [];
  const segments: Array<{ points: Array<[number, number, number]>; color: number }> = [
    {
      points: [
        [-2.38, 0.2, 1.03], [-1.93, 0.2, 1.66], [-1.12, 0.2, 2.03],
        [-0.42, 0.2, 1.91], [0, 0.2, 1.21],
      ],
      color: PALETTE.blue,
    },
    {
      points: [
        [0, 0.27, 1.21], [0.42, 0.27, 1.91], [1.12, 0.27, 2.03],
        [1.93, 0.27, 1.66], [2.38, 0.27, 1.03],
      ],
      color: PALETTE.brass,
    },
    {
      points: [
        [2.38, 0.13, 1.3], [2.2, 0.13, 2.48], [1.14, 0.13, 2.86],
        [0, 0.13, 2.98], [-1.14, 0.13, 2.86], [-2.2, 0.13, 2.48],
        [-2.38, 0.13, 1.3],
      ],
      color: PALETTE.teal,
    },
  ];
  const up = new THREE.Vector3(0, 1, 0);
  segments.forEach(({ points, color }) => {
    const curve = new THREE.CatmullRomCurve3(points.map(point => new THREE.Vector3(...point)));
    const line = new THREE.Mesh(
      new THREE.TubeGeometry(curve, 96, 0.023, 8, false),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.88 }),
    );
    group.add(line);
    for (const t of [0.34, 0.69, 0.91]) {
      const arrow = new THREE.Mesh(
        new THREE.ConeGeometry(0.08, 0.2, 9),
        new THREE.MeshBasicMaterial({ color }),
      );
      arrow.position.copy(curve.getPointAt(t));
      arrow.quaternion.setFromUnitVectors(up, curve.getTangentAt(t).normalize());
      group.add(arrow);
    }
    const pulse = new THREE.Mesh(
      new THREE.SphereGeometry(0.07, 12, 8),
      new THREE.MeshBasicMaterial({ color: 0xffffff }),
    );
    pulse.position.copy(curve.getPointAt(0.2));
    group.add(pulse);
    routes.push({ curve, pulse });
  });
  return { group, routes };
}

/**
 * Mount the hero's product visualization on an existing canvas. The scene owns its WebGL
 * resources and observers; callers must dispose it when replacing the canvas or page.
 * Returns null when WebGL is unavailable, leaving the caller free to show a static fallback.
 */
export function mountHardwareScene(canvas: HTMLCanvasElement, options: HardwareSceneOptions = {}): HardwareSceneHandle | null {
  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
  } catch {
    canvas.dataset.sceneReady = 'failed';
    return null;
  }

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-5, 5, 3, -3, 0.1, 80);
  const root = new THREE.Group();
  scene.add(root);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.32;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;

  const pmrem = new THREE.PMREMGenerator(renderer);
  const roomEnvironment = new RoomEnvironment();
  const environment = pmrem.fromScene(roomEnvironment, 0.05);
  roomEnvironment.dispose();
  scene.environment = environment.texture;
  scene.environmentIntensity = 0.85;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x9fb4c3, 1.35));
  const key = new THREE.DirectionalLight(0xffffff, 2.7);
  key.position.set(-3, 8, 6);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.camera.left = -6;
  key.shadow.camera.right = 6;
  key.shadow.camera.top = 7;
  key.shadow.camera.bottom = -5;
  key.shadow.normalBias = 0.045;
  key.shadow.radius = 3;
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xa9d2ff, 1.6);
  rim.position.set(5, 5, -6);
  scene.add(rim);

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(200, 200), standard(0xe9f0f5, 0.08, 0.8));
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -0.025;
  floor.receiveShadow = true;
  scene.add(floor);
  const fans: THREE.Group[] = [];
  const equipment: Record<HardwareKind, Equipment> = {
    cpu: buildCpu(),
    qpu: buildQpu(),
    gpu: buildGpu(fans),
  };
  Object.values(equipment).forEach(({ group }) => root.add(group));
  const interconnects = buildInterconnects(root);
  const flowRoutes = buildFlowRoutes(root);

  let focus: HardwareKind = options.initialFocus ?? 'qpu';
  let targetAzimuth = FOCUS_AZIMUTH[focus];
  let baseHeight = 5.35;
  let frame = 0;
  let firstFrame = true;
  let disposed = false;
  let visible = true;
  let cssWidth = 0;
  let cssHeight = 0;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const viewOffset = new THREE.Vector3(6.8, 4.6, 11.8);
  const lookAt = new THREE.Vector3(0, 2.02, 0);
  const initialOrbit = new THREE.Spherical().setFromVector3(viewOffset);
  initialOrbit.theta = targetAzimuth;
  camera.position.copy(lookAt).add(new THREE.Vector3().setFromSpherical(initialOrbit));
  camera.lookAt(lookAt);
  const controls = new OrbitControls(camera, canvas);
  controls.target.copy(lookAt);
  controls.enableDamping = !reducedMotion.matches;
  controls.dampingFactor = 0.08;
  controls.enablePan = false;
  controls.enableZoom = false;
  controls.rotateSpeed = 0.65;
  controls.minPolarAngle = Math.PI / 3.1;
  controls.maxPolarAngle = Math.PI / 2.15;
  controls.minAzimuthAngle = -Math.PI / 2.8;
  controls.maxAzimuthAngle = Math.PI / 2.8;
  controls.touches.TWO = THREE.TOUCH.ROTATE;
  canvas.style.touchAction = 'pan-y';
  controls.update();
  const priorTabIndex = canvas.getAttribute('tabindex');
  if (priorTabIndex === null) canvas.tabIndex = 0;
  let updatingControls = false;

  const updateFocusAppearance = (): void => {
    for (const kind of ['cpu', 'qpu', 'gpu'] as const) {
      equipment[kind].accent.emissiveIntensity = kind === focus ? 1.2 : 0.34;
      equipment[kind].marker.opacity = kind === focus ? 0.63 : 0.15;
    }
    canvas.dataset.focus = focus;
  };

  const updateCamera = (): void => {
    const orbit = new THREE.Spherical().setFromVector3(camera.position.clone().sub(controls.target));
    const difference = targetAzimuth - orbit.theta;
    orbit.theta += firstFrame || reducedMotion.matches ? difference : difference * 0.085;
    camera.position.copy(controls.target).add(new THREE.Vector3().setFromSpherical(orbit));
    if (camera.zoom !== 1) {
      camera.zoom = 1;
      camera.updateProjectionMatrix();
    }
    updatingControls = true;
    controls.update();
    updatingControls = false;
  };

  const labelAnchors: Record<HardwareKind, THREE.Vector3> = {
    cpu: new THREE.Vector3(0, 3.37, 0.1),
    qpu: new THREE.Vector3(0, 3.83, 0.1),
    gpu: new THREE.Vector3(0, 3.37, 0.1),
  };
  const projected = new THREE.Vector3();
  const publishLabels = (): void => {
    if (!options.onLabels || !cssWidth || !cssHeight) return;
    const positions = {} as Record<HardwareKind, { x: number; y: number; visible: boolean }>;
    camera.updateMatrixWorld();
    for (const kind of ['cpu', 'qpu', 'gpu'] as const) {
      const group = equipment[kind].group;
      group.updateWorldMatrix(true, false);
      projected.copy(labelAnchors[kind]);
      group.localToWorld(projected);
      projected.project(camera);
      const x = (projected.x + 1) * cssWidth / 2;
      const y = (1 - projected.y) * cssHeight / 2;
      positions[kind] = {
        x: THREE.MathUtils.clamp(x, Math.min(44, cssWidth * 0.12), cssWidth - Math.min(44, cssWidth * 0.12)),
        y: THREE.MathUtils.clamp(y, Math.min(34, cssHeight * 0.25), cssHeight - 18),
        visible: projected.z >= -1 && projected.z <= 1 && projected.x >= -1 && projected.x <= 1 && projected.y >= -1 && projected.y <= 1,
      };
    }
    options.onLabels(positions);
  };

  const render = (timestamp = 0): void => {
    if (disposed) return;
    frame = 0;
    if (!reducedMotion.matches) {
      const rotation = timestamp * 0.00012;
      fans.forEach(fan => { fan.rotation.z = rotation; });
      flowRoutes.routes.forEach(({ curve, pulse }, index) => {
        pulse.position.copy(curve.getPointAt((timestamp * 0.00017 + index * 0.42) % 1));
      });
    }
    updateCamera();
    renderer.render(scene, camera);
    canvas.dataset.cameraDistance = camera.position.distanceTo(controls.target).toFixed(3);
    canvas.dataset.sceneRotation = controls.getAzimuthalAngle().toFixed(3);
    publishLabels();
    if (firstFrame) {
      firstFrame = false;
      canvas.dataset.sceneReady = 'true';
      options.onReady?.();
    }
    if (visible && !document.hidden && !reducedMotion.matches) frame = requestAnimationFrame(render);
  };

  const requestRender = (): void => {
    if (frame || disposed) return;
    frame = requestAnimationFrame(render);
  };

  const onControlsChange = (): void => {
    if (updatingControls) return;
    targetAzimuth = controls.getAzimuthalAngle();
    requestRender();
  };
  controls.addEventListener('change', onControlsChange);

  const reset = (): void => {
    if (disposed) return;
    const damping = controls.enableDamping;
    controls.enableDamping = false;
    updatingControls = true;
    controls.update();
    focus = 'qpu';
    targetAzimuth = FOCUS_AZIMUTH.qpu;
    controls.target.set(0, 2.02, 0);
    camera.position.copy(controls.target).add(viewOffset);
    camera.zoom = 1;
    camera.updateProjectionMatrix();
    controls.update();
    controls.enableDamping = damping;
    updatingControls = false;
    updateFocusAppearance();
    requestRender();
  };

  const onCanvasKeyDown = (event: KeyboardEvent): void => {
    if (event.key === 'Home' || event.key === '0') {
      event.preventDefault();
      reset();
      return;
    }
    const angle = Math.PI / 30;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight' || event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault();
      const spherical = new THREE.Spherical().setFromVector3(camera.position.clone().sub(controls.target));
      if (event.key === 'ArrowLeft') spherical.theta -= angle;
      if (event.key === 'ArrowRight') spherical.theta += angle;
      if (event.key === 'ArrowUp') spherical.phi -= angle;
      if (event.key === 'ArrowDown') spherical.phi += angle;
      spherical.theta = THREE.MathUtils.clamp(spherical.theta, controls.minAzimuthAngle, controls.maxAzimuthAngle);
      spherical.phi = THREE.MathUtils.clamp(spherical.phi, controls.minPolarAngle, controls.maxPolarAngle);
      camera.position.copy(controls.target).add(new THREE.Vector3().setFromSpherical(spherical));
      targetAzimuth = spherical.theta;
      updatingControls = true;
      controls.update();
      updatingControls = false;
      requestRender();
    } else if (event.key === '+' || event.key === '=' || event.key === '-') {
      event.preventDefault();
    }
  };
  canvas.addEventListener('keydown', onCanvasKeyDown);

  const resize = (): void => {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (width < 2 || height < 2) return;
    cssWidth = width;
    cssHeight = height;
    const aspect = width / height;
    const spread = Math.min(1.2, Math.max(0, (aspect - 1.75) * 1.25));
    equipment.cpu.group.position.x = EQUIPMENT_X.cpu - spread;
    equipment.gpu.group.position.x = EQUIPMENT_X.gpu + spread;
    interconnects.forEach(group => { group.scale.x = 1 + spread / 0.62; });
    flowRoutes.group.scale.x = 1 + spread / EQUIPMENT_X.gpu;
    baseHeight = Math.max(height < 200 ? 5.65 : 5.1, 8.35 / aspect);
    camera.left = -baseHeight * aspect / 2;
    camera.right = baseHeight * aspect / 2;
    camera.top = baseHeight / 2;
    camera.bottom = -baseHeight / 2;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, width < 700 ? 1.5 : 2));
    renderer.setSize(width, height, false);
    requestRender();
  };

  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  const visibility = new IntersectionObserver(entries => {
    visible = entries.some(entry => entry.isIntersecting);
    if (!visible && frame) {
      cancelAnimationFrame(frame);
      frame = 0;
    }
    if (visible) requestRender();
  }, { threshold: 0 });
  visibility.observe(canvas);
  const onMotionChange = (): void => {
    controls.enableDamping = !reducedMotion.matches;
    requestRender();
  };
  reducedMotion.addEventListener('change', onMotionChange);
  const onVisibilityChange = (): void => {
    if (document.hidden && frame) {
      cancelAnimationFrame(frame);
      frame = 0;
    } else if (!document.hidden) {
      requestRender();
    }
  };
  document.addEventListener('visibilitychange', onVisibilityChange);
  updateFocusAppearance();
  resize();

  return {
    setFocus(kind) {
      if (disposed || !Object.hasOwn(equipment, kind)) return;
      focus = kind;
      targetAzimuth = FOCUS_AZIMUTH[kind];
      updateFocusAppearance();
      requestRender();
    },
    reset,
    dispose() {
      if (disposed) return;
      disposed = true;
      observer.disconnect();
      visibility.disconnect();
      reducedMotion.removeEventListener('change', onMotionChange);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      canvas.removeEventListener('keydown', onCanvasKeyDown);
      if (priorTabIndex === null) canvas.removeAttribute('tabindex');
      controls.removeEventListener('change', onControlsChange);
      controls.dispose();
      if (frame) cancelAnimationFrame(frame);
      const geometries = new Set<THREE.BufferGeometry>();
      const materials = new Set<THREE.Material>();
      const textures = new Set<THREE.Texture>();
      scene.traverse(object => {
        if (!(object instanceof THREE.Mesh)) return;
        geometries.add(object.geometry);
        for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
          materials.add(material);
          const mapped = (material as THREE.MeshBasicMaterial).map;
          if (mapped) textures.add(mapped);
        }
      });
      geometries.forEach(geometry => geometry.dispose());
      textures.forEach(texture => texture.dispose());
      materials.forEach(material => material.dispose());
      environment.dispose();
      pmrem.dispose();
      renderer.dispose();
      delete canvas.dataset.sceneReady;
      delete canvas.dataset.focus;
      delete canvas.dataset.cameraDistance;
      delete canvas.dataset.sceneRotation;
    },
  };
}
