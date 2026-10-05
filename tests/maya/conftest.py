"""Start Maya once for the whole test run. Run with: mayapy -m pytest tests/maya"""
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Install the plug-in the way a user would: through the module file. Maya then
# finds plug-ins/ and puts scripts/ on the Python path by itself.
os.environ["MAYA_MODULE_PATH"] = REPO + os.pathsep + os.environ.get("MAYA_MODULE_PATH", "")

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")
sys.path.insert(0, os.path.join(REPO, "examples"))

_status = [0]


def pytest_sessionfinish(session, exitstatus):
    _status[0] = int(exitstatus)


def pytest_unconfigure(config):
    # mayapy can hang or crash while shutting Maya down, which would turn a
    # green run red. Everything has been reported by now, so leave directly.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_status[0])
