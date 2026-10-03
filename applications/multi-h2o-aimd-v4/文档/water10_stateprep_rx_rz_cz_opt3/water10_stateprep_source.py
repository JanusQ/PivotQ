"""Export the frozen 30q state preparation to RX/RZ/CZ and one unbroken strip.

Run in codex-figures. Diagram exports come from the native editable draw.io file.
No measurements, readout basis changes, device topology, or parameter refitting.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import qiskit
from qiskit import qpy, transpile, qasm2

STEM = 'water10_stateprep_rx_rz_cz_opt3'
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SOURCE = ROOT/'models/final/circuit_source'
DRAWIO = '/Applications/draw.io.app/Contents/MacOS/draw.io'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def operations(circuit):
    return [dict(index=i, name=inst.operation.name,
                 qubits=[circuit.find_bit(q).index for q in inst.qubits],
                 angles_rad=[float(v) for v in inst.operation.params])
            for i, inst in enumerate(circuit.data)]


def schedule(ops):
    # Reserve entire CZ span, so no gate/connector in its column crosses another.
    # Disjoint operations may share columns; order on every physical wire is kept.
    available = [0]*30
    result = []
    for op in ops:
        lo, hi = min(op['qubits']), max(op['qubits'])
        span = range(lo, hi+1)
        column = max(available[q] for q in span)
        for q in span:
            available[q] = column+1
        result.append(dict(op, column=column))
    return result, max(available)


def diagram(ops, columns, meta):
    pitch, left, top, dy = meta.get('column_pitch',144), 170, 215, 48
    width, height = left+columns*pitch+150, top+30*dy+96
    mxfile = ET.Element('mxfile', host='app.diagrams.net', version='31.1.8')
    page = ET.SubElement(mxfile, 'diagram', id=STEM, name='30q continuous strip')
    model = ET.SubElement(page, 'mxGraphModel', dx=str(width), dy=str(height), grid='0',
        page='1', pageScale='1', pageWidth=str(width), pageHeight=str(height),
        background='#FFFFFF', math='0', shadow='0')
    root = ET.SubElement(model, 'root')
    ET.SubElement(root, 'mxCell', id='0')
    ET.SubElement(root, 'mxCell', id='1', parent='0')
    counter = 0

    def box(key, value, x, y, w, h, style):
        cell = ET.SubElement(root, 'mxCell', id=key, value=value, vertex='1', parent='1',
            style='fontFamily=Arial;whiteSpace=wrap;html=0;'+style)
        ET.SubElement(cell, 'mxGeometry', x=str(x), y=str(y), width=str(w), height=str(h), attrib={'as': 'geometry'})
        return cell

    def label(key, value, x, y, w, h, size=14, bold=False, align='left', color='#24364B'):
        return box(key, value, x, y, w, h, f'text;strokeColor=none;fillColor=none;align={align};verticalAlign=middle;fontSize={size};fontStyle={int(bold)};fontColor={color};spacing=0;')

    def line(key, x1, y1, x2, y2, color='#748091', stroke=1):
        cell = ET.SubElement(root, 'mxCell', id=key, value='', edge='1', parent='1',
            style=f'endArrow=none;startArrow=none;rounded=0;strokeColor={color};strokeWidth={stroke};')
        geom = ET.SubElement(cell, 'mxGeometry', relative='1', attrib={'as': 'geometry'})
        ET.SubElement(geom, 'mxPoint', x=str(x1), y=str(y1), attrib={'as': 'sourcePoint'})
        ET.SubElement(geom, 'mxPoint', x=str(x2), y=str(y2), attrib={'as': 'targetPoint'})

    box('background', '', 0, 0, width, height, 'fillColor=#FFFFFF;strokeColor=none;')
    for molecule in range(10):
        y = top+3*molecule*dy-dy/2
        if molecule % 2 == 0:
            box(f'band-{molecule}', '', 12, y, width-24, 3*dy, 'fillColor=#F5F8FC;strokeColor=none;')
        label(f'molecule-{molecule}', f'H2O {molecule+1:02d}', 20, y+dy, 64, 24, size=12, color='#64748B')
    label('title', '10 H2O | 30-qubit state preparation', 24, 18, 1350, 42, size=28, bold=True)
    label('subtitle', 'RX / RZ / CZ  |  Qiskit transpile: optimization_level=3, approximation_degree=1.0  |  No fold / no measurement',
          24, 65, 1900, 30, size=17)
    counts = meta['compiled']['count_ops']
    label('details', f"Frozen best epoch 6  |  Input: {meta['sample_id']}  |  {sum(counts.values())} gates: {counts['rx']} RX + {counts['rz']} RZ + {counts['cz']} CZ  |  Depth {meta['compiled']['depth']}",
          24, 99, 2200, 26, size=15)
    label('note', meta.get('angle_note', f"Angles shown in radians (6 decimals); exact angles and global phase in QPY/CSV. Logical qubits; no hardware routing. Global phase: {meta['compiled']['global_phase_rad']:.12f} rad."),
          24, 132, 2200, 26, size=14, color='#53677D')
    for column in range(0, columns, 10):
        x = left+column*pitch+pitch/2
        label(f'column-{column}', f'col {column:03d}', x-45, top-50, 90, 20, size=11, align='center', color='#64748B')
    for q in range(30):
        y = top+q*dy
        line(f'wire-{q}', left-25, y, width-90, y)
        label(f'qubit-{q}', f'q{q:02d} |0>', 84, y-14, 72, 28, size=15)
        label(f'qubit-right-{q}', f'q{q:02d}', width-77, y-14,  60, 28, size=15)
    for op in ops:
        x = left+op['column']*pitch+pitch/2
        key = f'gate-{op["index"]:04d}'
        if op['name'] == 'cz':
            ys = [top+q*dy for q in op['qubits']]
            line(key+'-connector', x, min(ys), x, max(ys), '#25374E', 1.5)
            for j, y in enumerate(ys):
                box(key+f'-dot-{j}', '', x-5, y-5, 10, 10,
                    'ellipse;aspect=fixed;fillColor=#25374E;strokeColor=#25374E;')
        else:
            color = '#E2ECF8' if op['name'] == 'rx' else '#FFF0DE'
            stroke = '#6B8CAD' if op['name'] == 'rx' else '#BB9464'
            angle = op['angles_rad'][0]
            label_text = f"{op['name'].upper()}({angle})" if isinstance(angle,str) else f"{op['name'].upper()}({angle:+.6f})"
            box(key, label_text, x-(pitch-16)/2, top+op['qubits'][0]*dy-17, pitch-16, 34,
                f'rounded=0;fillColor={color};strokeColor={stroke};strokeWidth=1;align=center;verticalAlign=middle;fontSize=13;fontColor=#1C2F44;')
    label('footer', 'Single continuous state-preparation strip. CZ is drawn with two connected filled dots. Display columns avoid connector overlaps and are not calibrated hardware time slots.',
          24, height-49, 2100, 26, size=14, color='#53677D')
    path = OUT/f'{STEM}.drawio'
    ET.indent(mxfile)
    ET.ElementTree(mxfile).write(path, encoding='utf-8', xml_declaration=True)
    return path, width, height


def vector_text(svg_path, drawio_path):
    """Keep draw.io-exported geometry; replace raster label fallbacks with live SVG text.

    Some draw.io versions emit foreignObject + embedded PNG text. Labels here
    are single lines; restoring their native-cell center/size preserves layout.
    """
    ns = 'http://www.w3.org/2000/svg'
    ET.register_namespace('', ns)
    tree = ET.parse(svg_path)
    root = tree.getroot()
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag.rsplit('}',1)[-1] in ('switch', 'foreignObject', 'image'):
                parent.remove(child)
    layer = ET.SubElement(root, '{'+ns+'}g', id='editable-native-cell-labels')
    for cell in ET.parse(drawio_path).getroot().iter('mxCell'):
        value = cell.get('value','')
        if not value or cell.get('vertex') != '1':
            continue
        style = dict(part.split('=',1) for part in cell.get('style','').split(';') if '=' in part)
        geom = cell.find('mxGeometry')
        x,y,w,h = [float(geom.get(key,'0')) for key in ('x','y','width','height')]
        align = style.get('align','center')
        text = ET.SubElement(layer, '{'+ns+'}text', {
            'x':str(x if align=='left' else x+w/2), 'y':str(y+h/2),
            'text-anchor':'start' if align=='left' else 'middle',
            'dominant-baseline':'central','font-family':'Arial, Helvetica, sans-serif',
            'font-size':style.get('fontSize','14'),
            'font-weight':'bold' if style.get('fontStyle')=='1' else 'normal',
            'fill':style.get('fontColor','#1C2F44'), 'data-cell-id':cell.get('id')})
        text.text = value
    assert not any(n.tag.rsplit('}',1)[-1] in ('image','foreignObject') for n in root.iter())
    tree.write(svg_path,encoding='utf-8',xml_declaration=True)



if __name__ == '__main__':
    raise SystemExit('Use water10_stateprep_symbolic_source.py to generate the current figure.')
