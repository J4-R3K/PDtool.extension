# -*- coding: utf-8 -*-
"""The PD category groups for the device tools (Edit Values, Hide in Views, Number Devices), 15/10/2026.

One list, so every tool offers the same groups, ticked as a group or one category at a time
(C:\\Dev\\PD-Revit-DeviceTools-PLAN-2026-10-15.md, section 4). Categories are named by their BuiltInCategory names, so
this module needs no Revit to be read or tested; resolve() turns a name into the Revit value inside Revit. Every name
below was checked in Revit 2024 through the MCP on 15/10/2026.

    from pdtool import mep

    for group in mep.groups(mep.EDIT):
        print(group.name, [mep.label(c) for c in group.categories])
"""

EDIT = u"edit"
NUMBER = u"number"
HIDE = u"hide"


class Group(object):
    """One PD group: its name, its categories (BuiltInCategory names) and the tools that offer it."""

    def __init__(self, name, categories, tools=(EDIT, NUMBER, HIDE)):
        self.name = name
        self.categories = tuple(categories)
        self.tools = tuple(tools)

    def __repr__(self):
        return "<Group {} {}>".format(self.name, len(self.categories))


# (BuiltInCategory name, the name Revit 2024 shows for it)
LABELS = (
    (u"OST_ElectricalEquipment", u"Electrical Equipment"),
    (u"OST_ElectricalFixtures", u"Electrical Fixtures"),
    (u"OST_LightingFixtures", u"Lighting Fixtures"),
    (u"OST_LightingDevices", u"Lighting Devices"),
    (u"OST_FireAlarmDevices", u"Fire Alarm Devices"),
    (u"OST_FireProtection", u"Fire Protection"),
    (u"OST_SecurityDevices", u"Security Devices"),
    (u"OST_DataDevices", u"Data Devices"),
    (u"OST_CommunicationDevices", u"Communication Devices"),
    (u"OST_TelephoneDevices", u"Telephone Devices"),
    (u"OST_NurseCallDevices", u"Nurse Call Devices"),
    (u"OST_AudioVisualDevices", u"Audio Visual Devices"),
    (u"OST_MechanicalEquipment", u"Mechanical Equipment"),
    (u"OST_MechanicalControlDevices", u"Mechanical Control Devices"),
    (u"OST_CableTray", u"Cable Trays"),
    (u"OST_CableTrayFitting", u"Cable Tray Fittings"),
    (u"OST_Conduit", u"Conduits"),
    (u"OST_ConduitFitting", u"Conduit Fittings"),
    (u"OST_ElectricalCircuit", u"Electrical Circuits"),
    (u"OST_Wire", u"Wires"),
    (u"OST_DuctCurves", u"Ducts"),
    (u"OST_PipeCurves", u"Pipes"),
    (u"OST_DuctTerminal", u"Air Terminals"),
    (u"OST_Sprinklers", u"Sprinklers"),
    (u"OST_PlumbingFixtures", u"Plumbing Fixtures"),
    (u"OST_GenericModel", u"Generic Models"),
    (u"OST_SpecialityEquipment", u"Specialty Equipment"),
)
_LABEL = dict(LABELS)

GROUPS = (
    Group(u"Power", (u"OST_ElectricalEquipment", u"OST_ElectricalFixtures")),
    Group(u"Lighting", (u"OST_LightingFixtures", u"OST_LightingDevices")),
    Group(u"Fire", (u"OST_FireAlarmDevices", u"OST_FireProtection")),
    Group(u"Security", (u"OST_SecurityDevices",)),
    Group(u"Data and communications", (u"OST_DataDevices", u"OST_CommunicationDevices", u"OST_TelephoneDevices",
                                       u"OST_NurseCallDevices", u"OST_AudioVisualDevices")),
    Group(u"Mechanical", (u"OST_MechanicalEquipment", u"OST_MechanicalControlDevices")),
    Group(u"Containment", (u"OST_CableTray", u"OST_CableTrayFitting", u"OST_Conduit", u"OST_ConduitFitting")),
    Group(u"Circuits and wiring", (u"OST_ElectricalCircuit", u"OST_Wire")),
    Group(u"Other services", (u"OST_DuctCurves", u"OST_PipeCurves", u"OST_DuctTerminal", u"OST_Sprinklers",
                              u"OST_PlumbingFixtures", u"OST_GenericModel", u"OST_SpecialityEquipment"),
          tools=(HIDE,)),
)


def groups(tool=EDIT):
    """The groups a tool offers, in the PD order."""
    return [g for g in GROUPS if tool in g.tools]


def categories(tool=EDIT):
    """Every category name a tool offers, in the PD order, each once."""
    out = []
    for g in groups(tool):
        for c in g.categories:
            if c not in out:
                out.append(c)
    return out


def group_of(category):
    """The name of the first group that holds a category, or None."""
    for g in GROUPS:
        if category in g.categories:
            return g.name
    return None


def label(category):
    """The name Revit shows for a category ("OST_DataDevices" gives "Data Devices")."""
    return _LABEL.get(category, category[4:] if category.startswith(u"OST_") else category)


def resolve(category):
    """The Revit BuiltInCategory for a name, or None where this Revit year has no such category. Needs Revit."""
    from Autodesk.Revit.DB import BuiltInCategory
    return getattr(BuiltInCategory, category, None)
