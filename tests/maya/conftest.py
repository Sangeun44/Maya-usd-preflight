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


def _annotation(level, title, text):
    """A GitHub Actions annotation, so a failure shows on the commit page."""
    text = text[-6000:].replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return "::%s title=%s::%s" % (level, title, text)


def pytest_terminal_summary(terminalreporter):
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    for level, outcomes in (("error", ("failed", "error")), ("notice", ("skipped",))):
        for outcome in outcomes:
            for report in terminalreporter.stats.get(outcome, []):
                name = getattr(report, "nodeid", "").split("::")[-1] or outcome
                terminalreporter.write_line(_annotation(level, name, str(report.longrepr)))


def pytest_unconfigure(config):
    # mayapy can hang or crash while shutting Maya down, which would turn a
    # green run red. Everything has been reported by now, so leave directly.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_status[0])
