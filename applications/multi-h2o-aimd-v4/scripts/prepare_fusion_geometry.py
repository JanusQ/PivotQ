"""Export training geometries only; no test labels, split changes or refitting."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from water10_v4.data import load_panel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample-id', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    panel = load_panel(args.sample_id, split='train')
    payload = dict(atomic_numbers=[8, 1, 1]*10, pbc=False, position_unit='angstrom',
        sample_ids=args.sample_id, source='frozen training split',
        molecular_geometries_A=panel['positions_angstrom'].tolist())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(payload, stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
