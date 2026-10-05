"""Generate the complete dataset on 109-32cpu; external library stays external."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from water20.dataset import generate

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True)
    parser.add_argument("--config", type=Path, default=ROOT/"configs/dataset.json")
    parser.add_argument("--output", type=Path, default=ROOT/"dataset_water20_mbpol_v1")
    args = parser.parse_args()
    generate(args.config, args.library, args.output)
