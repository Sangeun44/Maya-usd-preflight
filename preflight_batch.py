"""Batch mode launcher: `mayapy preflight_batch.py scenes/ --out out/ --export`.

Same as `mayapy -m usd_preflight.batch`, without having to put scripts/ on
PYTHONPATH first.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

from usd_preflight.batch import main  # noqa: E402

if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)   # mayapy can hang while shutting Maya down
