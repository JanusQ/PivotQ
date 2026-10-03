#!/usr/bin/env python3
"""Generate the frozen H2O F2/A2 parameterized logical circuit.

Running this file creates exactly three artifacts beside the script:

* circuit.qpy  - lossless Qiskit serialization
* circuit.qasm - OpenQASM 3 text export
* circuit.png  - circuit diagram for visual inspection

The circuit is intentionally unbound and contains 14 parameters:
``enc[0:3]`` are the three geometry-dependent Ry angles, while
``theta[0:11]`` are the trainable quantum-model parameters.
"""

from __future__ import annotations

import math
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from qiskit import QuantumCircuit, qasm3, qpy
from qiskit.circuit import Parameter


ADAPT_OPERATORS = ("IYZ", "YII", "YZI", "IIX", "YII")


def _parameter(name: str) -> Parameter:
    """Create a stable parameter identity so repeated exports are reproducible."""
    return Parameter(name, uuid=uuid5(NAMESPACE_URL, f"qhai-h2o-f2a2/{name}"))


def _native_h(circuit: QuantumCircuit, qubit: int) -> None:
    circuit.rz(math.pi, qubit)
    circuit.ry(math.pi / 2.0, qubit)


def _native_h_inverse(circuit: QuantumCircuit, qubit: int) -> None:
    circuit.ry(-math.pi / 2.0, qubit)
    circuit.rz(-math.pi, qubit)


def _native_rx(circuit: QuantumCircuit, angle, qubit: int) -> None:
    circuit.rz(math.pi / 2.0, qubit)
    circuit.ry(angle, qubit)
    circuit.rz(-math.pi / 2.0, qubit)


def _native_rx_inverse(circuit: QuantumCircuit, angle, qubit: int) -> None:
    circuit.rz(math.pi / 2.0, qubit)
    circuit.ry(-angle, qubit)
    circuit.rz(-math.pi / 2.0, qubit)


def _native_cnot(circuit: QuantumCircuit, control: int, target: int) -> None:
    _native_h(circuit, target)
    circuit.cz(control, target)
    _native_h(circuit, target)


def _native_cnot_inverse(
    circuit: QuantumCircuit, control: int, target: int
) -> None:
    _native_h_inverse(circuit, target)
    circuit.cz(control, target)
    _native_h_inverse(circuit, target)


def _pauli_rotation(circuit: QuantumCircuit, word: str, angle) -> None:
    """Compile exp(-i angle P/2) into the frozen Ry/Rz/CZ gate set."""
    support = [qubit for qubit, symbol in enumerate(word) if symbol != "I"]
    if not support:
        raise ValueError("Identity is not a parameterized operator")
    if len(support) == 2 and support == [0, 2]:
        raise ValueError("Direct q0-q2 Pauli rotations are not allowed")

    for qubit in support:
        symbol = word[qubit]
        if symbol == "X":
            _native_h(circuit, qubit)
        elif symbol == "Y":
            _native_rx(circuit, math.pi / 2.0, qubit)
        elif symbol != "Z":
            raise ValueError(f"Unsupported Pauli symbol: {symbol}")

    for first, second in zip(support[:-1], support[1:]):
        _native_cnot(circuit, first, second)
    circuit.rz(angle, support[-1])
    for first, second in reversed(list(zip(support[:-1], support[1:]))):
        _native_cnot_inverse(circuit, first, second)

    for qubit in reversed(support):
        symbol = word[qubit]
        if symbol == "X":
            _native_h_inverse(circuit, qubit)
        elif symbol == "Y":
            _native_rx_inverse(circuit, math.pi / 2.0, qubit)


def build_circuit() -> QuantumCircuit:
    """Return the project's frozen, unbound three-qubit logical circuit."""
    circuit = QuantumCircuit(3, name="h2o_f2a2")
    encoding = tuple(_parameter(f"enc[{index}]") for index in range(3))
    theta = tuple(_parameter(f"theta[{index}]") for index in range(11))

    # Geometry encoding: angles from angles.csv map one-to-one to q0, q1, q2.
    for qubit, angle in enumerate(encoding):
        circuit.ry(angle, qubit)

    # Native seed: three Ry rotations, linear CZ connectivity, three native Rx.
    for qubit in range(3):
        circuit.ry(theta[qubit], qubit)
    circuit.cz(0, 1)
    circuit.cz(1, 2)
    for qubit in range(3):
        _native_rx(circuit, theta[3 + qubit], qubit)

    # Frozen ADAPT sequence: IYZ -> YII -> YZI -> IIX -> YII.
    for index, word in enumerate(ADAPT_OPERATORS):
        _pauli_rotation(circuit, word, theta[6 + index])

    circuit.metadata = {
        "model": "H2O_F2A2_R1_DROP_XXX_MLP_ONLY",
        "logical_qubit_order": (
            "q0,q1,q2 correspond to Pauli word characters left-to-right"
        ),
        "adapt_operators": list(ADAPT_OPERATORS),
    }
    return circuit


def _save_png(circuit: QuantumCircuit, path: Path) -> None:
    """Save an MPL diagram, with a dependency-light text-render fallback."""
    try:
        figure = circuit.draw(
            output="mpl",
            fold=32,
            idle_wires=False,
        )
        figure.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
        return
    except Exception as exc:
        # Qiskit's MPL drawer may require the optional pylatexenc package.
        mpl_error = exc

    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "Generating circuit.png requires matplotlib or "
            "Qiskit's visualization extras"
        ) from exc

    drawing = str(
        circuit.draw(
            output="text",
            fold=118,
            vertical_compression="low",
        )
    )
    lines = drawing.splitlines()
    width = max(len(line) for line in lines)
    figure = plt.figure(
        figsize=(max(12.0, width * 0.075), max(3.0, len(lines) * 0.16))
    )
    figure.patch.set_facecolor("white")
    figure.text(
        0.01,
        0.99,
        drawing,
        va="top",
        ha="left",
        family="DejaVu Sans Mono",
        fontsize=7.5,
        color="black",
    )
    figure.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    print(f"MPL circuit drawer unavailable ({mpl_error}); used text-rendered PNG")


def export_circuit(output_dir: str | Path | None = None) -> tuple[Path, Path, Path]:
    """Build and export circuit.qpy, circuit.qasm, and circuit.png."""
    destination = (
        Path(output_dir).expanduser().resolve()
        if output_dir is not None
        else Path(__file__).resolve().parent
    )
    destination.mkdir(parents=True, exist_ok=True)
    qpy_path = destination / "circuit.qpy"
    qasm_path = destination / "circuit.qasm"
    png_path = destination / "circuit.png"

    circuit = build_circuit()
    with qpy_path.open("wb") as handle:
        qpy.dump([circuit], handle)
    qasm_path.write_text(qasm3.dumps(circuit), encoding="utf-8")
    _save_png(circuit, png_path)
    return qpy_path, qasm_path, png_path


# Importing this module exposes the same QuantumCircuit object used for export.
circuit = build_circuit()


if __name__ == "__main__":
    for artifact in export_circuit():
        print(artifact)
