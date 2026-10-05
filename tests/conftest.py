"""tests/maya only runs inside Maya (mayapy -m pytest tests/maya); skip it elsewhere."""
import importlib.util

try:
    _in_maya = importlib.util.find_spec("maya.standalone") is not None
except ImportError:
    _in_maya = False

collect_ignore = [] if _in_maya else ["maya"]
