"""Strict shot-table decoder, in the actual 005 example HTTP envelope.

No 2**60 distribution is allocated; only observed joint states are retained.
"""
from collections import Counter
import configparser
import csv
import io
import math
from numbers import Real

import numpy as np


def integer(value, name):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or value != int(value):
        raise ValueError(f"{name} must be a finite integer")
    return int(value)


def table_from_csv_ini(table):
    ini = configparser.ConfigParser(interpolation=None)
    ini.read_string(table["ini"].lstrip("\ufeff"))
    if ini.getint("General", "independent") != 2 or ini.getint("General", "dependent") != 60:
        raise ValueError("Expected two indices and 60 shot readouts")
    columns = [ini[f"Independent {i}"]["label"].strip() for i in range(1, 3)]
    columns += [ini[f"Dependent {i}"]["label"].strip() for i in range(1, 61)]
    rows = [[float(v) for v in row] for row in csv.reader(io.StringIO(table["csv"].lstrip("\ufeff"))) if row]
    return dict(columns=columns, data=rows)


def decode(record, requests, shots, job_id, shot_index_base=0):
    if type(shots) is not int or shots <= 0:
        raise ValueError("Positive integer shots required")
    if record.get("job_id") != job_id or record.get("status") != "succeeded" or record.get("backend") != "circuit" or record.get("error") is not None:
        raise ValueError("Invalid successful physical-device envelope")
    parameters = record.get("parameters", {})
    if parameters.get("measure_base") != "Z" or type(parameters.get("reps")) is not int or parameters["reps"] != shots:
        raise ValueError("Server must confirm requested reps and terminal Z readout")
    manifest = record.get("files")
    wanted = {r.filename: r for r in requests}
    if not isinstance(manifest, list) or len(manifest) != len(requests):
        raise ValueError("Missing file manifest")
    by_index, names = {}, set()
    for file in manifest:
        index, name = integer(file.get("index"), "file index"), file.get("name")
        if index < 0 or index in by_index or name not in wanted or name in names:
            raise ValueError("Invalid/duplicate file association")
        by_index[index] = wanted[name]
        names.add(name)
    if names != set(wanted):
        raise ValueError("Missing filename association")
    table = record.get("result")
    if not isinstance(table, dict):
        raise ValueError("Missing actual shot table; dense ideal probabilities are unsupported")
    if "csv" in table and "ini" in table:
        table = table_from_csv_ini(table)
    columns, rows = table.get("columns"), table.get("data")
    if not isinstance(columns, list) or any(not isinstance(c, str) for c in columns):
        raise ValueError("Invalid shot columns")
    columns = [c.removeprefix("result_") for c in columns]
    labels = set(requests[0].logical_readout_labels)
    if len(columns) != 62 or len(set(columns)) != 62 or set(columns) != {"shots", "circuits", *labels}:
        raise ValueError("Exactly 60 configured physical columns plus shot/circuit indices required")
    if any(set(r.logical_readout_labels) != labels for r in requests):
        raise ValueError("Batch contains incompatible physical mappings")
    if not isinstance(rows, list):
        raise ValueError("Missing shot rows")
    column_index = {c: i for i, c in enumerate(columns)}
    seen = {index: set() for index in by_index}
    counts = {index: Counter() for index in by_index}
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            raise ValueError("Shot width mismatch")
        circuit = integer(row[column_index["circuits"]], "circuits")
        shot = integer(row[column_index["shots"]], "shots")
        if circuit not in by_index or not shot_index_base <= shot < shot_index_base+shots or shot in seen[circuit]:
            raise ValueError("Unknown circuit, missing-range or duplicate shot index")
        bits = [integer(row[column_index[q]], q) for q in by_index[circuit].logical_readout_labels]
        if any(bit not in (0, 1) for bit in bits):
            raise ValueError("Shot outcomes must be binary")
        seen[circuit].add(shot)
        counts[circuit]["".join(map(str, bits))] += 1
    if any(len(value) != shots for value in seen.values()):
        raise ValueError("Incomplete shots; partial data cannot be treated as zeros")
    output = {}
    for index, request in by_index.items():
        expectation = sum(count*np.array([1-2*int(b) for b in bits], float) for bits, count in counts[index].items())/shots
        standard_error = np.sqrt(np.maximum(0, 1-expectation**2)/max(1, shots-1))
        output[request.circuit_id] = dict(schema_version=1, circuit_id=request.circuit_id,
            job_id=job_id, filename=request.filename, basis=request.basis, requested_shots=shots, actual_shots=shots,
            n_qubits=60, bit_order="q0..q59", physical_readout_columns=list(request.logical_readout_labels),
            mapping_version=request.mapping_version, complete=True, counts=dict(counts[index]),
            expectations=expectation.tolist(), standard_error=standard_error.tolist(),
            zero_variance_note="A zero sample variance at all-equal outcomes is not proof of zero hardware uncertainty")
    return [output[r.circuit_id] for r in requests]
