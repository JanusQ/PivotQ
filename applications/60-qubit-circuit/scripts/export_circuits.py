"""Export symbolic circuit illustrations, plus separately bound native QASM.

The transpile figure is explicitly basis-only until a real profile is supplied.
Logical panels show the owner's 3/6/9 wires; global wire IDs preserve continuity.
"""
from collections import OrderedDict
from html import escape
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import h5py
import numpy as np
from qiskit import QuantumCircuit, qasm3
from qiskit.circuit import Parameter
from water20.circuit import append_rotation, build, native
from water20.model import Model

PALETTE = ["#c8e1f4", "#f7cfb8", "#d1e8c4", "#ead9f5", "#f5e6aa"]


class SVG:
    def __init__(self, width):
        self.width, self.items = width, []

    def rect(self, x, y, width, height, fill="white", stroke="#56616e", **attributes):
        other = " ".join(f'{k.replace("_", "-")}="{escape(str(v))}"' for k, v in attributes.items())
        self.items.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{fill}" stroke="{stroke}" {other}/>')

    def text(self, x, y, text, size=12, anchor="start", weight="normal"):
        self.items.append(f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}" fill="#22303d">{escape(text)}</text>')

    def line(self, x1, y1, x2, y2, color="#56616e", width=1):
        self.items.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"/>')

    def gate(self, x, rows, operation, angle=None, parameter=None):
        if operation == "cz":
            self.line(x, min(rows), x, max(rows), "#24313d", 1.5)
            for y in rows:
                self.items.append(f'<circle cx="{x}" cy="{y}" r="3.8" fill="#24313d"/>')
        else:
            for y in rows:
                self.items.append(f'<g data-parameters="{escape(parameter or "")}">')
                self.rect(x-28, y-11, 56, 22, "#f1e8fa" if parameter else "white", "#334451", rx=2)
                self.text(x, y-1, operation.upper(), 10, "middle")
                if parameter:
                    self.text(x, y+8, parameter, 10, "middle", "bold")
                elif angle is not None:
                    self.text(x, y+8, f"{angle:.3f}", 9, "middle")
                self.items.append('</g>')

    def save(self, path, height):
        content = '<svg xmlns="http://www.w3.org/2000/svg" width="'+str(self.width)+'" height="'+str(height)+'" viewBox="0 0 '+str(self.width)+' '+str(height)+'">\n'
        content += '<rect width="100%" height="100%" fill="white"/>\n'+"\n".join(self.items)+"\n</svg>\n"
        path.write_text(content)
        ET.fromstring(content)


def primitives(gates):
    result = []
    for g in gates:
        circuit = QuantumCircuit(60)
        append_rotation(circuit, g["axis"], g["qubits"], g["angle"])
        for item in circuit.data:
            result.append(dict(operation=item.operation.name,
                qubits=[circuit.find_bit(q).index for q in item.qubits],
                angle=float(item.operation.params[0]) if item.operation.params else None,
                block_id=g["block_id"], feature=g["feature"], stage=g["stage"], body=g["body"],
                molecules=g["molecules"], parameter=g["parameter"]))
    return result


def parameter_ids(gates):
    return {key: f"θ{i+1}" for i, key in enumerate(dict.fromkeys(g["parameter"] for g in gates if g["parameter"]))}


def symbolic_native(gates, theta):
    """Compile real symbolic angles; hide coefficients only in the drawing.

    This preserves parameter provenance through native decomposition. Fixed
    basis rotations keep numeric labels and are never mistaken for theta.
    The bound execution QASM is exported separately without changing it.
    """
    parameters = {key: Parameter(name) for key, name in parameter_ids(gates).items()}
    circuit = QuantumCircuit(60)
    for gate in gates:
        key = gate["parameter"]
        angle = gate["angle"] if key is None else (gate["angle"]/theta[key])*parameters[key]
        append_rotation(circuit, gate["axis"], gate["qubits"], angle)
    return native(circuit), parameters


def logical_figure(gates, path, sample):
    primitive = primitives(gates)
    modules = OrderedDict()
    for p in primitive:
        key = (p["stage"], p["body"], tuple(p["molecules"]))
        modules.setdefault(key, OrderedDict()).setdefault(p["block_id"], []).append(p)
    widths = [110+sum(max(100, 64*len(block)+24) for block in blocks.values()) for blocks in modules.values()]
    scene = SVG(max(1600, max(widths)+30))
    scene.text(24, 30, "Twenty-water / 60-qubit circuit | colored semantic blocks", 23, weight="bold")
    scene.text(24, 54, f"Sample {sample} | θ1-θ48: shared trainable parameters (coefficients hidden); numeric labels: fixed/encoding angles", 15)
    scene.text(24, 76, "Encoding 1B -> 2B -> 3B, then trainable 1B -> 2B -> 3B; one global state; no intermediate reset or measurement.", 14)
    scene.text(24, 98, "Panels continue in execution order. Scope views retain global q IDs. Dots joined vertically are CZ gates.", 14)
    scene.text(24, 120, "AIMD encoding: centered Oxyz, continuous bx/by orientation slot, bz; no hard 0.1-rad floor. 48 shared parameters.", 14)
    y, row_height, panel_x = 150, 0, 16
    symbols = parameter_ids(gates)
    previous_stage_body = None
    for panel, ((stage, body, mols), blocks) in enumerate(modules.items(), 1):
        panel_width = 110+sum(max(100, 64*len(block)+24) for block in blocks.values())
        if panel_x > 16 and (panel_x+panel_width > scene.width-16 or (stage, body) != previous_stage_body):
            y, panel_x, row_height = y+row_height+18, 16, 0
        previous_stage_body = (stage, body)
        scope = [3*m+q for m in mols for q in range(3)]
        row = {q: y+72+i*30 for i, q in enumerate(scope)}
        height = 95+len(scope)*30
        scene.rect(panel_x, y, panel_width, height, "#fcfcfd", "#aeb8c2")
        scene.text(panel_x+10, y+24, f"Panel {panel:03d} | {stage.upper()} {body}B | "+", ".join(f"W{m+1}" for m in mols), 16, weight="bold")
        x = panel_x+89
        for block in blocks.values():
            feature = block[0]["feature"]
            width = max(100, 64*len(block)+24)
            scene.rect(x, y+35, width, height-45, PALETTE[feature % 5], "#b5bcc2")
            owner = mols[feature//5] if body > 1 else mols[0]
            channel = (("OH1", "OH2", "HOH")[feature] if body == 1 else ("Ox", "Oy", "Oz", "bx/by", "bz")[feature%5])
            scene.text(x+5, y+51, f"f{feature+1:02d} W{owner+1} {channel}", 11, weight="bold")
            for q in scope:
                scene.line(x, row[q], x+width, row[q])
            for i, p in enumerate(block):
                scene.gate(x+44+i*64, [row[q] for q in p["qubits"]], p["operation"], p["angle"], symbols.get(p["parameter"]))
            x += width
        for q in scope:
            scene.text(panel_x+72, row[q]+4, f"q{q}", 12, "end")
        panel_x += panel_width+12
        row_height = max(row_height, height)
    y += row_height+18
    scene.text(24, y+25, "TERMINAL READOUT: two full 60-wire settings X and Z -> 120 expectations -> 120-64-32-1 tanh head -> total E (eV).", 15, weight="bold")
    scene.save(path, y+50)
    return dict(panels=len(modules), primitive_gates=len(primitive), width=scene.width, height=y+50)


def transpile_figure(circuit, path, sample):
    # ASAP drawing of the actual compiled gates. Preserve every wire's gate
    # order; independent gates can share columns. Reserve CZ vertical spans
    # so unrelated gate boxes never sit on top of a CZ connection.
    columns, occupied = [], []
    next_column = [0]*60
    for item in circuit.data:
        qubits = [circuit.find_bit(q).index for q in item.qubits]
        span = set(range(min(qubits), max(qubits)+1))
        col = max(next_column[q] for q in qubits)
        while col < len(occupied) and occupied[col] & span:
            col += 1
        while len(columns) <= col:
            columns.append([])
            occupied.append(set())
        expression = item.operation.params[0] if item.operation.params else None
        dependencies = getattr(expression, "parameters", set())
        symbol = ",".join(p.name for p in sorted(dependencies, key=lambda p: int(p.name[1:]))) or None
        angle = float(expression) if expression is not None and not dependencies else None
        columns[col].append((item.operation.name, qubits, angle, symbol))
        occupied[col] |= span
        for q in qubits:
            next_column[q] = col+1
    displayed_qubits = list(range(circuit.num_qubits))
    width = 180+65*len(columns)
    scene = SVG(width)
    scene.text(22, 30, "Twenty-water / 60-qubit application | full transpile circuit q0-q59 (W1-W20)", 23, weight="bold")
    scene.text(22, 55, f"Sample {sample} | {len(circuit.data)} symbolically compiled gates | depth {circuit.depth()} | initialized, untrained", 15)
    scene.text(22, 80, "BASIS-ONLY transpilation: physical 60-qubit coupling/map is not supplied. This is not a hardware-routed acceptance figure.", 15)
    scene.text(22, 105, "One continuous left-to-right row: all 60 wires, all compiled gates and both endpoints of every CZ are displayed.", 15)
    scene.text(22, 128, "Purple θ1-θ48 gates depend on shared trainable parameters (coefficients hidden); numeric labels are fixed/encoding angles.", 14)
    row = {q: 180+q*26 for q in displayed_qubits}
    bottom = row[displayed_qubits[-1]]+48
    height = bottom+72
    scene.rect(12, 150, width-24, bottom-134, "#fcfcfd", "#aeb8c2")
    for q in displayed_qubits:
        scene.text(86, row[q]+4, f"W{q//3+1}:q{q}", 10, "end")
        scene.line(100, row[q], width-20, row[q], "#aab6c1")
    for i, col in enumerate(columns):
        x = 135+i*65
        for operation, qubits, angle, symbol in col:
            scene.gate(x, [row[q] for q in qubits], operation, angle, symbol)
    scene.text(22, height-20, "State preparation view. Terminal X basis adds H; server performs final Z readout. Full state preparation remains in models/stateprep.rx-rz-cz.qasm.", 14)
    scene.save(path, height)
    return dict(panels=1, layout="continuous_horizontal_full_60_wire_circuit", displayed_qubits=displayed_qubits,
                gates=len(circuit.data), displayed_gates=len(circuit.data),
                columns=len(columns), displayed_columns=len(columns), depth=circuit.depth(),
                width=scene.width, height=height, parameter_representation="symbolic_theta_coefficients_hidden",
                compilation_scope="symbolic_native_basis_only_no_physical_topology")


def previews(path, width=1500, crop_height=1800, crop_width=None):
    """Preview a readable leading viewport; full SVG remains authoritative."""
    import cairosvg
    tree = ET.fromstring(path.read_text())
    full_width = min(float(tree.attrib["width"]), crop_width) if crop_width else float(tree.attrib["width"])
    tree.set("width", str(full_width))
    tree.set("height", str(crop_height))
    tree.set("viewBox", f"0 0 {full_width} {crop_height}")
    cairosvg.svg2png(bytestring=ET.tostring(tree), write_to=str(path.with_suffix(".preview.png")),
                    output_width=width, output_height=int(width*crop_height/full_width))


if __name__ == "__main__":
    model = Model()
    with h5py.File(ROOT/"dataset_water20_mbpol_v1/water20.h5") as dataset:
        positions = dataset["positions_angstrom"][0]
        sample = dataset["sample_id"].asstr()[0]
    gates, groups = model.gates(positions)
    out = ROOT/"docs"
    out.mkdir(exist_ok=True)
    logical_path, native_path = out/"20 分子电路彩色逻辑图.svg", out/"20 分子电路transpile图.svg"
    logical = logical_figure(gates, logical_path, sample)
    compiled = native(build(gates))
    symbolic, _ = symbolic_native(gates, model.metadata["theta"])
    transformed = transpile_figure(symbolic, native_path, sample)
    (ROOT/"models/stateprep.rx-rz-cz.qasm").write_text(qasm3.dumps(compiled))
    report = dict(sample_id=sample, logical=logical, transpiled=transformed,
                  active_groups={str(k): [list(g) for g in v] for k, v in groups.items()},
                  logical_rotations=len(gates), shared_parameters=48, feature_count=120,
                  parameter_ids={symbol: key for key, symbol in parameter_ids(gates).items()},
                  execution_qasm=dict(gates=len(compiled.data), depth=compiled.depth(), parameter_representation="bound_numeric"),
                  initialized_untrained=True, training_updates=0, real_qpu_validated=False,
                  circuit_config_sha256=model.metadata["circuit_config_sha256"],
                  artifact_hashes={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (logical_path, native_path)})
    (ROOT/"reports/circuit_export.json").write_text(json.dumps(report, indent=2)+"\n")
    try:
        previews(logical_path, crop_height=1300)
        previews(native_path, crop_height=transformed["height"], crop_width=2300)
    except ImportError:
        print("Install optional cairosvg to generate compact previews")
    print(json.dumps(report, indent=2))
