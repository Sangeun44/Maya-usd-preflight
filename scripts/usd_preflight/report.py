"""Issues, and the report that carries them."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Optional

ERROR = "error"
WARNING = "warning"
SEVERITIES = (ERROR, WARNING)


@dataclass
class Issue:
    check: str                     # check id, e.g. "mesh.nonmanifold"
    severity: str
    node: str                      # DAG path, shading group or file node; "" for the scene
    message: str
    # Optional components on `node`, so a UI can select exactly what is wrong.
    component: Optional[str] = None            # "f", "e" or "vtx"
    indices: list[int] = field(default_factory=list)

    def selection(self) -> list[str]:
        """What to hand to `cmds.select` to show this issue."""
        if not self.node:
            return []
        if self.component and self.indices:
            return ["%s.%s[%d]" % (self.node, self.component, i) for i in self.indices]
        return [self.node]


@dataclass
class Report:
    scene: str = ""
    up_axis: str = ""
    linear_unit: str = ""
    issues: list[Issue] = field(default_factory=list)
    exported: str = ""             # path of the USD file, once one has been written

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        return "%s, %s" % (_count(len(self.errors), "error"), _count(len(self.warnings), "warning"))

    def to_json(self, indent: Optional[int] = 2) -> str:
        data = asdict(self)
        data["errors"] = len(self.errors)
        data["warnings"] = len(self.warnings)
        return json.dumps(data, indent=indent)

    def format_text(self) -> str:
        name = self.scene.replace("\\", "/").rsplit("/", 1)[-1] or "(untitled scene)"
        lines = ["%s: %s  (%s up, %s)" % (name, self.summary(), self.up_axis.upper(), self.linear_unit)]
        ordered = sorted(self.issues, key=lambda i: (SEVERITIES.index(i.severity), i.check, i.node))
        width_check = max([len(i.check) for i in ordered] or [0])
        width_node = min(max([len(i.node) for i in ordered] or [0]), 40)
        for issue in ordered:
            lines.append("  %-7s  %-*s  %-*s  %s" % (
                issue.severity.upper(), width_check, issue.check,
                width_node, issue.node or "(scene)", issue.message))
        return "\n".join(lines)


def _count(n: int, noun: str) -> str:
    return "%d %s%s" % (n, noun, "" if n == 1 else "s")
