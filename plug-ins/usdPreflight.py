"""usdPreflight: a Maya plug-in that checks a scene before it is exported to USD.

Loading it registers the `usdPreflight` command and adds a "USD Preflight"
menu to the main window.

    cmds.loadPlugin("usdPreflight")
    report = json.loads(cmds.usdPreflight())                       # whole scene
    cmds.usdPreflight(selection=True, export="/tmp/crate.usda")    # selection, then export

Flags:
    -sl / -selection          check what is under the selection, not the whole scene
    -p  / -profile  <path>    JSON profile: thresholds, disabled checks, severities
    -ex / -export   <path>    export to USD if no check fails, then verify the file
    -f  / -force              export even if a check fails
    -r  / -report   <path>    also write the report to a JSON file

The command returns the report as a JSON string.
"""
import os
import sys

import maya.api.OpenMaya as om
from maya import cmds, mel

MENU = "usdPreflightMenu"


def maya_useNewAPI():
    """Tell Maya this plug-in uses the Python API 2.0."""


class UsdPreflightCmd(om.MPxCommand):
    NAME = "usdPreflight"

    def __init__(self):
        om.MPxCommand.__init__(self)

    @staticmethod
    def creator():
        return UsdPreflightCmd()

    @staticmethod
    def new_syntax():
        syntax = om.MSyntax()
        syntax.addFlag("-sl", "-selection", om.MSyntax.kNoArg)
        syntax.addFlag("-p", "-profile", om.MSyntax.kString)
        syntax.addFlag("-ex", "-export", om.MSyntax.kString)
        syntax.addFlag("-f", "-force", om.MSyntax.kNoArg)
        syntax.addFlag("-r", "-report", om.MSyntax.kString)
        return syntax

    def doIt(self, args):
        from usd_preflight.run import preflight

        parser = om.MArgParser(self.syntax(), args)

        def text(flag):
            return parser.flagArgumentString(flag, 0) if parser.isFlagSet(flag) else None

        export_path = text("-ex")
        report = preflight(
            selection=parser.isFlagSet("-sl"),
            profile=text("-p"),
            export_path=export_path,
            force=parser.isFlagSet("-f"),
        )
        if text("-r"):
            with open(text("-r"), "w") as handle:
                handle.write(report.to_json())

        om.MGlobal.displayInfo(report.format_text())
        if export_path and not report.exported:
            om.MGlobal.displayWarning("usdPreflight: %s; not exported (use -force to export anyway)"
                                      % report.summary())
        elif not report.ok:
            om.MGlobal.displayWarning("usdPreflight: %s" % report.summary())
        self.setResult(report.to_json(indent=None))


def _add_menu():
    if cmds.about(batch=True):
        return
    _remove_menu()
    main_window = mel.eval("$usdPreflightTmp = $gMainWindow")
    cmds.menu(MENU, label="USD Preflight", parent=main_window, tearOff=True)
    cmds.menuItem(label="Open Panel", parent=MENU,
                  command=lambda *_: __import__("usd_preflight.ui", fromlist=["show"]).show())
    cmds.menuItem(divider=True, parent=MENU)
    cmds.menuItem(label="Check Scene", parent=MENU, command=lambda *_: cmds.usdPreflight())
    cmds.menuItem(label="Check Selection", parent=MENU, command=lambda *_: cmds.usdPreflight(selection=True))


def _remove_menu():
    if not cmds.about(batch=True) and cmds.menu(MENU, exists=True):
        cmds.deleteUI(MENU)


def initializePlugin(plugin):
    fn = om.MFnPlugin(plugin, "Sangeun Lee", "0.1.0", "Any")
    # The module file puts scripts/ on the Python path. If the plug-in was
    # loaded by browsing to this file instead, add it here.
    try:
        import usd_preflight  # noqa: F401
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(fn.loadPath()), "scripts"))
    fn.registerCommand(UsdPreflightCmd.NAME, UsdPreflightCmd.creator, UsdPreflightCmd.new_syntax)
    _add_menu()


def uninitializePlugin(plugin):
    _remove_menu()
    om.MFnPlugin(plugin).deregisterCommand(UsdPreflightCmd.NAME)
