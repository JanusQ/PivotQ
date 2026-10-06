import { useState } from "react";
import type { Circuit } from "../api/types";
import s from "../App.module.css";
export default function CircuitDiagram({
  circuit,
  stale,
  compiling = false,
}: {
  circuit?: Circuit;
  stale: boolean;
  compiling?: boolean;
}) {
  const [basis, setBasis] = useState("Z");
  const displayed = basis === "X" ? circuit?.variants?.X || circuit : circuit;
  if (!displayed?.valid)
    return (
      <div className={s.circuitEmpty}>
        {compiling ? (
          <span>正在编译…</span>
        ) : stale ? (
          <span>程序已修改，请重新编译</span>
        ) : null}
      </div>
    );
  const width = Math.max(400, displayed.gates.length * 62 + 74),
    height = displayed.qubits * 48 + 32,
    y = (q: number) => 26 + q * 48;
  return (
    <>
      <div className={s.circuitMeta}>
        <span>
          {displayed.qubits} 个逻辑比特 / {displayed.gate_count} 条电路指令
          {stale ? " · 待重新编译" : ""}
        </span>
        {circuit?.variants && (
          <select
            aria-label="测量基"
            value={basis}
            onChange={(e) => setBasis(e.target.value)}
          >
            <option>Z</option>
            <option>X</option>
          </select>
        )}
      </div>
      <p className={s.copyHint}>按电路列表逐条计数，包含测量及列表中已有的屏障、分解指令。水分子 Z 基预览为 70 个基础门加 1 条测量；X 基另加 6 个换基旋转门。这里不增加设备映射指令。</p>
      <div className={s.circuitScroll} style={{ opacity: stale ? 0.45 : 1 }}>
        <svg
          width={width}
          height={height}
          role="img"
          aria-label="编译后的量子电路"
        >
          {Array.from({ length: displayed.qubits }, (_, q) => (
            <g key={q}>
              <text
                x="10"
                y={y(q) + 4}
                fill="#64748B"
                fontFamily="IBM Plex Mono"
                fontSize="12"
              >
                q{q}
              </text>
              <path d={`M45 ${y(q)}H${width - 12}`} stroke="#CBD6E5" />
            </g>
          ))}
          {displayed.gates.map((gate, i) => {
            const x = 76 + i * 62,
              args = gate.args;
            if (gate.name === "CX" || gate.name === "CZ") {
              const a = args[0] as number,
                b = args[1] as number;
              return (
                <g key={i}>
                  <title>
                    {gate.name}({args.join(", ")})
                  </title>
                  <path
                    d={`M${x} ${y(a)}V${y(b)}`}
                    stroke="#2458D3"
                    strokeWidth="1.5"
                  />
                  <circle cx={x} cy={y(a)} r="4" fill="#2458D3" />
                  <circle
                    cx={x}
                    cy={y(b)}
                    r="11"
                    fill="white"
                    stroke="#2458D3"
                  />
                  <text
                    x={x}
                    y={y(b) + 4}
                    textAnchor="middle"
                    fill="#2458D3"
                    fontSize="14"
                  >
                    {gate.name === "CX" ? "+" : "Z"}
                  </text>
                </g>
              );
            }
            const qubits =
              gate.name === "MEASURE"
                ? (args[0] as number[])
                : [args.at(-1) as number];
            return (
              <g key={i}>
                <title>
                  {gate.name}({args.join(", ")})
                </title>
                {qubits.map((q) => (
                  <g key={q}>
                    <rect
                      x={x - 17}
                      y={y(q) - 14}
                      width="34"
                      height="28"
                      rx="4"
                      fill={gate.name === "MEASURE" ? "#F0F4F8" : "#EDF2FE"}
                      stroke={gate.name === "MEASURE" ? "#B9C7D6" : "#9EB6EB"}
                    />
                    <text
                      x={x}
                      y={y(q) + 4}
                      textAnchor="middle"
                      fontSize="11"
                      fill="#2458D3"
                    >
                      {gate.name === "MEASURE" ? "M" : gate.name}
                    </text>
                    {/^R[XYZ]$/.test(gate.name) && (
                      <text
                        x={x}
                        y={y(q) + 24}
                        textAnchor="middle"
                        fontSize="9"
                        fill="#718096"
                      >
                        {Number(args[0]).toFixed(2)}
                      </text>
                    )}
                  </g>
                ))}
              </g>
            );
          })}
        </svg>
      </div>
    </>
  );
}
