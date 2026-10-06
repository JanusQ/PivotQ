import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Frame } from "../api/types";
import s from "../App.module.css";
export default function Molecule({
  frames,
  symbols,
  index,
  onIndex,
  complete,
}: {
  frames: Frame[];
  symbols: string[];
  index: number;
  onIndex: (index: number) => void;
  complete: boolean;
}) {
  const host = useRef<HTMLDivElement>(null),
    stage = useRef<{
      atoms: THREE.Mesh[];
      bonds: THREE.Mesh[];
      render: () => void;
      reset: () => void;
      fit: () => void;
    } | null>(null),
    [fallback, setFallback] = useState(false),
    [playing, setPlaying] = useState(false),
    [speed, setSpeed] = useState(1);
  const frame = frames[index] || frames[0];
  useEffect(() => {
    if (!host.current) return;
    const element = host.current;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setFallback(true);
      return;
    }
    setFallback(false);
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setClearColor(0xf7f9fd, 1);
    element.appendChild(renderer.domElement);
    renderer.domElement.setAttribute(
      "aria-label",
      "水分子三维轨迹，可拖动旋转、滚轮缩放",
    );
    renderer.domElement.setAttribute("role", "img");
    const scene = new THREE.Scene(),
      camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100);
    camera.position.set(0, 3, 0);
    let controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = false;
    controls.minDistance = 0.8;
    controls.maxDistance = 12;
    controls.enablePan = false;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x62799d, 2.5));
    const light = new THREE.DirectionalLight(0xffffff, 3);
    light.position.set(-2, 4, 4);
    scene.add(light);
    const sphere = new THREE.SphereGeometry(1, 40, 24),
      cylinder = new THREE.CylinderGeometry(0.055, 0.055, 1, 18);
    const materials = [
      new THREE.MeshStandardMaterial({ color: 0xdb454e, roughness: 0.3 }),
      new THREE.MeshStandardMaterial({ color: 0xf4f6fa, roughness: 0.38 }),
      new THREE.MeshStandardMaterial({ color: 0xa2b4cc, roughness: 0.4 }),
    ];
    const atoms = symbols.map((symbol) => {
        const atom = new THREE.Mesh(sphere, materials[symbol === "O" ? 0 : 1]);
        atom.scale.setScalar(symbol === "O" ? 0.3 : 0.19);
        scene.add(atom);
        return atom;
      }),
      bonds = Array.from({ length: Math.max(0, symbols.length - 1) }, () => {
        const mesh = new THREE.Mesh(cylinder, materials[2]);
        scene.add(mesh);
        return mesh;
      });
    const render = () => renderer.render(scene, camera);
    let fitted = false;
    const reset = () => {
      if (atoms.length < 3) return;
      // Look at the recorded molecular plane. Coordinates themselves are unchanged.
      const firstBond = atoms[1].position.clone().sub(atoms[0].position);
      const secondBond = atoms[2].position.clone().sub(atoms[0].position);
      const normal = new THREE.Vector3().crossVectors(firstBond, secondBond);
      if (normal.lengthSq() < 1e-10) normal.set(0, 0, 1);
      normal.normalize();
      const up = firstBond
        .clone()
        .normalize()
        .add(secondBond.clone().normalize())
        .negate();
      if (up.lengthSq() < 1e-10) up.set(0, 1, 0);
      up.normalize();
      const direction = normal.clone().addScaledVector(up, 0.12).normalize();
      const right = new THREE.Vector3().crossVectors(up, direction).normalize();
      const vertical = new THREE.Vector3()
        .crossVectors(direction, right)
        .normalize();
      const extent = {
        minX: Infinity,
        maxX: -Infinity,
        minY: Infinity,
        maxY: -Infinity,
        minZ: Infinity,
        maxZ: -Infinity,
      };
      atoms.forEach((atom) => {
        const x = atom.position.dot(right),
          y = atom.position.dot(vertical),
          z = atom.position.dot(direction),
          radius = atom.scale.x;
        extent.minX = Math.min(extent.minX, x - radius);
        extent.maxX = Math.max(extent.maxX, x + radius);
        extent.minY = Math.min(extent.minY, y - radius);
        extent.maxY = Math.max(extent.maxY, y + radius);
        extent.minZ = Math.min(extent.minZ, z - radius);
        extent.maxZ = Math.max(extent.maxZ, z + radius);
      });
      const target = right
        .clone()
        .multiplyScalar((extent.minX + extent.maxX) / 2)
        .addScaledVector(vertical, (extent.minY + extent.maxY) / 2)
        .addScaledVector(direction, (extent.minZ + extent.maxZ) / 2);
      const halfWidth = (extent.maxX - extent.minX) / 2,
        halfHeight = (extent.maxY - extent.minY) / 2,
        halfDepth = (extent.maxZ - extent.minZ) / 2;
      const { width, height } = element.getBoundingClientRect();
      camera.aspect = width / Math.max(1, height);
      const verticalTangent = Math.tan(
        THREE.MathUtils.degToRad(camera.fov / 2),
      );
      const distance =
        Math.max(
          halfHeight / (verticalTangent * 0.8),
          halfWidth / (verticalTangent * camera.aspect * 0.55),
        ) +
        halfDepth * 0.5;
      camera.up.copy(vertical);
      camera.position.copy(target).addScaledVector(direction, distance);
      camera.updateProjectionMatrix();
      controls.dispose();
      controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = false;
      controls.enablePan = false;
      controls.addEventListener("change", render);
      controls.target.copy(target);
      controls.minDistance = Math.max(0.5, halfDepth * 2);
      controls.maxDistance = Math.max(12, distance * 4);
      controls.update();
      fitted = true;
      render();
    };
    const fit = () => {
      if (!fitted) reset();
    };
    stage.current = { atoms, bonds, render, reset, fit };
    const resize = new ResizeObserver(() => {
      const { width, height } = element.getBoundingClientRect();
      renderer.setSize(width, height);
      camera.aspect = width / (height || 1);
      camera.updateProjectionMatrix();
      render();
    });
    resize.observe(element);
    controls.addEventListener("change", render);
    const lost = (event: Event) => {
      event.preventDefault();
      setFallback(true);
    };
    renderer.domElement.addEventListener("webglcontextlost", lost);
    return () => {
      resize.disconnect();
      controls.dispose();
      renderer.domElement.removeEventListener("webglcontextlost", lost);
      sphere.dispose();
      cylinder.dispose();
      materials.forEach((m) => m.dispose());
      renderer.dispose();
      renderer.forceContextLoss();
      element.removeChild(renderer.domElement);
      stage.current = null;
    };
  }, [symbols.join(",")]);
  useEffect(() => {
    const current = stage.current;
    if (!current || !frame) return;
    const center = new THREE.Vector3();
    frame.positions.forEach((p) => center.add(new THREE.Vector3(...p)));
    center.divideScalar(frame.positions.length || 1);
    current.atoms.forEach((atom, i) => {
      if (frame.positions[i])
        atom.position.fromArray(frame.positions[i]).sub(center);
    });
    current.bonds.forEach((bond, i) => {
      const start = current.atoms[0]?.position,
        end = current.atoms[i + 1]?.position;
      if (!start || !end) return;
      const direction = new THREE.Vector3().subVectors(end, start);
      bond.position.copy(start).add(end).multiplyScalar(0.5);
      bond.scale.y = direction.length();
      bond.quaternion.setFromUnitVectors(
        new THREE.Vector3(0, 1, 0),
        direction.normalize(),
      );
    });
    current.fit();
    current.render();
  }, [frame, symbols.join(",")]);
  useEffect(() => {
    if (!playing || frames.length < 2) return;
    const timer = setInterval(() => {
      if (index >= frames.length - 1) {
        setPlaying(false);
        return;
      }
      onIndex(index + 1);
    }, 200 / speed);
    return () => clearInterval(timer);
  }, [playing, index, frames.length, speed, onIndex]);
  useEffect(() => setPlaying(false), [frames[0]]);
  return (
    <div className={s.molecule}>
      <div className={s.moleculeHeader}>
        <h3>分子轨迹</h3>
        <span>
          {!complete && <b className={s.incomplete}>不完整</b>} O{" "}
          <i className={s.oxygen} /> H <i className={s.hydrogen} />
        </span>
      </div>
      <div
        ref={host}
        className={s.moleculeCanvas}
        style={fallback ? { display: "none" } : undefined}
      />
      {fallback && (
        <div className={s.webglFallback}>
          <span>当前浏览器无法显示三维视图</span>
          <table>
            <thead>
              <tr>
                <th>原子</th>
                <th>x (Å)</th>
                <th>y (Å)</th>
                <th>z (Å)</th>
              </tr>
            </thead>
            <tbody>
              {frame?.positions.map((p, i) => (
                <tr key={i}>
                  <td>{symbols[i]}</td>
                  {p.map((v, j) => (
                    <td key={j}>{v.toFixed(4)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className={s.frameInfo}>
        <span>第 {frame?.step ?? "—"} 步 / {frame?.time_fs.toFixed(3) ?? "—"} fs</span>

        <button onClick={() => stage.current?.reset()} disabled={fallback}>
          复位视角
        </button>
      </div>
      <p className={s.copyHint}>拖动时间滑块或点击播放，查看同一时间步的分子构型与总能量。</p>
      <div className={s.player}>
        <button
          aria-label={playing ? "暂停轨迹" : "播放轨迹"}
          disabled={frames.length < 2}
          onClick={() => {
            if (index === frames.length - 1) onIndex(0);
            setPlaying(!playing);
          }}
        >
          {playing ? "Ⅱ" : "▶"}
        </button>
        <input
          aria-label="轨迹帧"
          type="range"
          min="0"
          max={Math.max(0, frames.length - 1)}
          value={Math.min(index, Math.max(0, frames.length - 1))}
          onChange={(e) => {
            setPlaying(false);
            onIndex(Number(e.target.value));
          }}
        />
        <select
          aria-label="播放速度"
          value={speed}
          onChange={(e) => setSpeed(Number(e.target.value))}
        >
          <option value="0.5">0.5×</option>
          <option value="1">1×</option>
          <option value="2">2×</option>
          <option value="4">4×</option>
        </select>
      </div>
    </div>
  );
}
