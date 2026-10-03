import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import type { Frame } from './aimd-data';

/** Ball-and-stick geometry preserves the recorded coordinates and equal axis scales. */
export function moleculeView(canvas: HTMLCanvasElement, frames: Frame[]) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  const scene = new THREE.Scene(); scene.background = new THREE.Color('#081522');
  const bounds = new THREE.Box3();
  frames.forEach(frame => frame.atoms.forEach(atom => bounds.expandByPoint(new THREE.Vector3(...atom))));
  const center = bounds.getCenter(new THREE.Vector3());
  const extent = Math.max(...bounds.getSize(new THREE.Vector3()).toArray(), 1);
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, .01, extent * 30);
  const home = new THREE.Vector3(1.5, 3.4, 2.6).multiplyScalar(extent);
  camera.position.copy(home); camera.lookAt(0, 0, 0);
  const controls = new OrbitControls(camera, canvas);
  controls.enablePan = false; controls.minZoom = .65; controls.maxZoom = 2.8;
  controls.rotateSpeed = .65; controls.zoomSpeed = .65;
  const colors = ['#ef665b', '#45d7ff', '#ffd166'];
  const group = new THREE.Group(); scene.add(group);
  scene.add(new THREE.HemisphereLight('#c3e8ff', '#122332', 2));
  const key = new THREE.DirectionalLight('#fff4e6', 4);
  key.position.set(-3, 5, 4).multiplyScalar(extent); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.camera.left = key.shadow.camera.bottom = -extent * 2;
  key.shadow.camera.right = key.shadow.camera.top = extent * 2;
  key.shadow.camera.far = extent * 20; key.shadow.normalBias = .025; key.shadow.bias = -.0001; key.shadow.radius = 5;
  scene.add(key);
  const rim = new THREE.DirectionalLight('#5ebaff', 3);
  rim.position.set(3, 1, -3).multiplyScalar(extent); scene.add(rim);
  const fill = new THREE.DirectionalLight('#9effe4', .7);
  fill.position.set(-2, -1, 2).multiplyScalar(extent); scene.add(fill);
  const floorY = bounds.min.y - center.y - extent * .48;
  const floorGeometry = new THREE.PlaneGeometry(extent * 8, extent * 8);
  const floor = new THREE.Mesh(floorGeometry, new THREE.MeshBasicMaterial({ color: '#0c1929' }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = floorY; scene.add(floor);
  const shadow = new THREE.Mesh(floorGeometry, new THREE.ShadowMaterial({ opacity: .24, depthWrite: false }));
  shadow.rotation.x = -Math.PI / 2; shadow.position.y = floorY + .001; shadow.receiveShadow = true; scene.add(shadow);
  const grid = new THREE.GridHelper(extent * 2.6, 16, '#31556b', '#20364a');
  grid.position.y = floorY + .002;
  const gridMaterial = grid.material as THREE.LineBasicMaterial;
  gridMaterial.transparent = true; gridMaterial.opacity = .38; scene.add(grid);

  function textSprite(text: string, color: string, scale = .28) {
    const textureCanvas = document.createElement('canvas'); textureCanvas.width = 256; textureCanvas.height = 128;
    const ctx = textureCanvas.getContext('2d')!;
    ctx.font = '500 50px "Segoe UI",sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillStyle = color; ctx.fillText(text, 128, 64);
    const texture = new THREE.CanvasTexture(textureCanvas); texture.colorSpace = THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false, toneMapped: false }));
    sprite.scale.set(scale * 2, scale, 1); sprite.renderOrder = 10; return sprite;
  }
  const sphereGeometry = new THREE.SphereGeometry(1, 64, 48);
  const atoms = colors.map((color, index) => {
    const material = new THREE.MeshPhysicalMaterial({ color, roughness: .22, metalness: .12, clearcoat: 1, clearcoatRoughness: .18 });
    const sphere = new THREE.Mesh(sphereGeometry, material); sphere.scale.setScalar(index === 0 ? .21 : .14);
    sphere.castShadow = sphere.receiveShadow = true; group.add(sphere); return sphere;
  });
  const labels = ['O', 'H₁', 'H₂'].map((name, index) => { const label = textSprite(name, colors[index], .20); group.add(label); return label; });
  const cylinderGeometry = new THREE.CylinderGeometry(.043, .043, 1, 32);
  const bondMaterials = ['#ae655f', '#c7e6f5', '#ecd5a1'].map(color => new THREE.MeshPhysicalMaterial({ color, roughness: .3, metalness: .3, clearcoat: .65 }));
  const bonds = [1, 2].map(index => [0, index].map(color => {
    const cylinder = new THREE.Mesh(cylinderGeometry, bondMaterials[color]); cylinder.castShadow = cylinder.receiveShadow = true; group.add(cylinder); return cylinder;
  }));
  const up = new THREE.Vector3(0, 1, 0), trailLength = 300;
  // Screen-space widths keep the recorded hydrogen paths legible at every zoom.
  // Draw the paths as an overlay so the atom spheres do not conceal small motions.
  const trails = colors.map((color, atom) => {
    const geometry = new LineGeometry();
    geometry.setPositions(new Float32Array(trailLength * 3));
    geometry.setColors(new Float32Array(trailLength * 3));
    geometry.instanceCount = 0;
    const material = new LineMaterial({ vertexColors: true, linewidth: atom === 0 ? 1.25 : 1.5, transparent: true, opacity: atom === 0 ? .3 : 1, depthTest: false, depthWrite: false, toneMapped: false });
    const line = new Line2(geometry, material); line.frustumCulled = false; line.renderOrder = 2; group.add(line);
    const halo = new Line2(geometry, new LineMaterial({ color, linewidth: 4, transparent: true, opacity: .08, depthTest: false, depthWrite: false, toneMapped: false }));
    halo.frustumCulled = false; halo.renderOrder = 1; group.add(halo);
    return { line, halo, color: new THREE.Color(color) };
  });
  const angleGeometry = new THREE.BufferGeometry();
  angleGeometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(49 * 3), 3));
  const angleArc = new THREE.Line(angleGeometry, new THREE.LineBasicMaterial({ color: '#9dc5de', transparent: true, opacity: .45 }));
  angleArc.frustumCulled = false; group.add(angleArc);
  // A coordinate triad follows the camera while staying separate from the molecular scene.
  const axesScene = new THREE.Scene(), axesCamera = new THREE.OrthographicCamera(-1.8, 1.8, 1.8, -1.8, .1, 20);
  ['x', 'y', 'z'].forEach((name, axis) => {
    const direction = new THREE.Vector3().setComponent(axis, 1);
    axesScene.add(new THREE.ArrowHelper(direction, new THREE.Vector3(), .85, ['#ef837a', '#8bdfc5', '#87c7ef'][axis], .14, .08));
    const label = textSprite(name, '#adbdcb', .40); label.position.copy(direction.multiplyScalar(1.15)); axesScene.add(label);
  });
  let current = 0, showTrails = true, width = 0, height = 0;
  function draw() {
    if (!width || !height) return;
    renderer.setViewport(0, 0, width, height); renderer.render(scene, camera);
    renderer.autoClear = false; renderer.clearDepth();
    const size = Math.min(90, width * .22); renderer.setViewport(10, 10, size, size);
    axesCamera.position.copy(camera.position).sub(controls.target).normalize().multiplyScalar(5);
    axesCamera.up.copy(camera.up); axesCamera.lookAt(0, 0, 0); renderer.render(axesScene, axesCamera);
    renderer.autoClear = true; renderer.setViewport(0, 0, width, height);
    canvas.dataset.frame = String(frames[current].step);
    canvas.dataset.camera = `${camera.position.toArray().map(value => value.toFixed(2)).join(',')},${camera.zoom.toFixed(2)}`;
  }
  function setFrame(index: number) {
    current = Math.max(0, Math.min(frames.length - 1, index));
    const positions = frames[current].atoms.map(atom => new THREE.Vector3(...atom).sub(center));
    atoms.forEach((atom, i) => { atom.position.copy(positions[i]); labels[i].position.copy(positions[i]).add(new THREE.Vector3(0, i === 0 ? .32 : .25, 0)); });
    bonds.forEach((segments, index) => {
      const start = positions[0], end = positions[index + 1], middle = start.clone().lerp(end, .5);
      [[start, middle], [middle, end]].forEach(([a, b], segment) => {
        const cylinder = segments[segment], direction = b.clone().sub(a);
        cylinder.position.copy(a).lerp(b, .5); cylinder.scale.y = direction.length(); cylinder.quaternion.setFromUnitVectors(up, direction.normalize());
      });
    });
    trails.forEach(({ line, halo, color }, atom) => {
      const start = Math.max(0, current - trailLength + 1), count = current - start + 1;
      line.visible = showTrails && count > 1;
      halo.visible = line.visible && atom > 0;
      if (count < 2) return;
      const starts = line.geometry.getAttribute('instanceStart'), ends = line.geometry.getAttribute('instanceEnd');
      const colorStarts = line.geometry.getAttribute('instanceColorStart'), colorEnds = line.geometry.getAttribute('instanceColorEnd');
      for (let i = 0; i < count - 1; i++) {
        const a = new THREE.Vector3(...frames[start + i].atoms[atom]).sub(center);
        const b = new THREE.Vector3(...frames[start + i + 1].atoms[atom]).sub(center);
        starts.setXYZ(i, a.x, a.y, a.z); ends.setXYZ(i, b.x, b.y, b.z);
        const shadeA = color.clone().multiplyScalar(.65 + .35 * i / (count - 1));
        const shadeB = color.clone().multiplyScalar(.65 + .35 * (i + 1) / (count - 1));
        colorStarts.setXYZ(i, shadeA.r, shadeA.g, shadeA.b); colorEnds.setXYZ(i, shadeB.r, shadeB.g, shadeB.b);
      }
      starts.needsUpdate = ends.needsUpdate = colorStarts.needsUpdate = colorEnds.needsUpdate = true;
      line.geometry.instanceCount = count - 1;
    });
    const a = positions[1].clone().sub(positions[0]).normalize(), b = positions[2].clone().sub(positions[0]).normalize();
    const angle = Math.acos(THREE.MathUtils.clamp(a.dot(b), -1, 1)), tangent = b.clone().addScaledVector(a, -a.dot(b)).normalize();
    const arcPositions = angleGeometry.getAttribute('position');
    for (let i = 0; i <= 48; i++) {
      const theta = angle * i / 48;
      const point = positions[0].clone().addScaledVector(a, .36 * Math.cos(theta)).addScaledVector(tangent, .36 * Math.sin(theta)); arcPositions.setXYZ(i, point.x, point.y, point.z);
    }
    arcPositions.needsUpdate = true; draw();
  }
  function resize() {
    const rect = canvas.getBoundingClientRect(); width = rect.width; height = rect.height;
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    trails.forEach(({ line, halo }) => { line.material.resolution.set(width, height); halo.material.resolution.set(width, height); });
    const halfHeight = extent * .69 * Math.max(1, height / width);
    camera.left = -halfHeight * width / height; camera.right = -camera.left; camera.top = halfHeight; camera.bottom = -halfHeight;
    camera.updateProjectionMatrix(); draw();
  }
  function reset() { camera.position.copy(home); camera.zoom = 1; controls.target.set(0, 0, 0); camera.updateProjectionMatrix(); controls.update(); draw(); }
  controls.addEventListener('change', draw);
  canvas.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', '+', '-', 'Home'].includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'Home') { reset(); return; }
    if (event.key === '+' || event.key === '-') camera.zoom = THREE.MathUtils.clamp(camera.zoom * (event.key === '+' ? 1.1 : 1 / 1.1), .65, 2.8);
    else {
      const spherical = new THREE.Spherical().setFromVector3(camera.position);
      if (event.key === 'ArrowLeft') spherical.theta -= .12;
      if (event.key === 'ArrowRight') spherical.theta += .12;
      if (event.key === 'ArrowUp') spherical.phi -= .12;
      if (event.key === 'ArrowDown') spherical.phi += .12;
      spherical.makeSafe(); camera.position.setFromSpherical(spherical);
    }
    camera.updateProjectionMatrix(); controls.update(); draw();
  });
  const observer = new ResizeObserver(resize); observer.observe(canvas);
  window.addEventListener('pagehide', () => {
    observer.disconnect(); controls.dispose();
    const geometries = new Set<THREE.BufferGeometry>(), materials = new Set<THREE.Material>();
    [scene, axesScene].forEach(value => value.traverse(object => {
      const renderable = object as THREE.Mesh;
      if (renderable.geometry) geometries.add(renderable.geometry);
      if (renderable.material) (Array.isArray(renderable.material) ? renderable.material : [renderable.material]).forEach(material => materials.add(material));
    }));
    geometries.forEach(geometry => geometry.dispose());
    materials.forEach(material => { const map = (material as THREE.SpriteMaterial).map; map?.dispose(); material.dispose(); }); renderer.dispose();
  }, { once: true });
  setFrame(0); resize();
  return { setFrame, setTrails(value: boolean) { showTrails = value; setFrame(current); }, reset, resize };
}
