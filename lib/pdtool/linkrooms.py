# -*- coding: utf-8 -*-
"""The room an element stands in, from the rooms of this model or of a linked model (15/10/2026). Needs Revit.

PD models hold no rooms of their own: the rooms are in the architect's linked model (on one PD project model, a
link with 601 rooms). Edit Values uses this for {Room Number} and {Room Name}, and Number Devices
will use it to number by room (C:\\Dev\\PD-Revit-DeviceTools-PLAN-2026-10-15.md, sections 5 and 6).

    from pdtool import linkrooms

    sources = linkrooms.sources(doc)              # [Source], the models that hold placed rooms
    finder = linkrooms.RoomFinder(sources[0])
    room = finder.room(element)                   # the Room, or None
    linkrooms.number(room), linkrooms.name(room)

The element's point is moved into the link's coordinates, then tried as it is, a short way to each side of the face
it is fixed to (a socket on a wall stands on the wall face, between two rooms), and lower down (a light fitting in a
ceiling void can be above the top of the room). A room found lower down is not used where a different room is found
just above the point, because the lower one may be on the floor below.
"""
from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, FamilyInstance, FilteredElementCollector,
                               LocationCurve, LocationPoint, RevitLinkInstance, Transform, XYZ)

from pdtool import id_value

THIS_MODEL = u"This model"
# Revit works in feet: half a foot is about 150 mm.
_SIDEWAYS = 0.5
_LOWER = (2.0, 4.0, 8.0)
_HIGHER = (1.0,)


class Source(object):
    """A model that holds placed rooms: this model, or one loaded link instance."""

    def __init__(self, label, doc, link=None, count=0):
        self.label = label
        self.doc = doc
        self.link = link
        self.count = count
        self.transform = link.GetTotalTransform() if link is not None else Transform.Identity
        self.inverse = self.transform.Inverse


def _placed_rooms(doc):
    rooms = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()
    return sum(1 for r in rooms if r.Location is not None and r.Area > 0)


def _link_label(link):
    """The link's name as Revit shows it in the project browser, without " : 1 : location"."""
    try:
        from Autodesk.Revit.DB import Element
        text = Element.Name.GetValue(link)
    except Exception:
        text = link.Name
    return text.split(u" : ")[0]


def sources(doc):
    """The models that hold placed rooms: this model first, then each loaded link, with their room counts."""
    out = []
    count = _placed_rooms(doc)
    if count:
        out.append(Source(THIS_MODEL, doc, None, count))
    seen = set()
    for link in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        link_doc = link.GetLinkDocument()
        if link_doc is None:
            continue
        label = _link_label(link)
        if label in seen:
            label = u"{} ({})".format(label, link.Id)
        seen.add(label)
        count = _placed_rooms(link_doc)
        if count:
            out.append(Source(label, link_doc, link, count))
    return out


def point_of(element):
    """The element's point in this model: its insertion point, the middle of its line, or the middle of its box."""
    location = element.Location
    if isinstance(location, LocationPoint):
        return location.Point
    if isinstance(location, LocationCurve):
        return location.Curve.Evaluate(0.5, True)
    box = element.get_BoundingBox(None)
    if box is not None:
        return (box.Min + box.Max) / 2.0
    return None


class RoomFinder(object):
    """Finds rooms in one source, keeping each answer by element id."""

    def __init__(self, source):
        self.source = source
        self._found = {}

    def _at(self, point):
        try:
            return self.source.doc.GetRoomAtPoint(self.source.inverse.OfPoint(point))
        except Exception:
            return None

    def _tries(self, element, point):
        yield point
        if isinstance(element, FamilyInstance):
            try:
                facing = element.FacingOrientation
            except Exception:
                facing = None
            if facing is not None and not facing.IsZeroLength():
                yield point + facing * _SIDEWAYS
                yield point - facing * _SIDEWAYS
        for drop in _LOWER:
            yield point - XYZ(0, 0, drop)
        for lift in _HIGHER:
            yield point + XYZ(0, 0, lift)

    def _above(self, point):
        for lift in _HIGHER:
            found = self._at(point + XYZ(0, 0, lift))
            if found is not None:
                return found
        return None

    def room(self, element):
        key = id_value(element.Id)
        if key in self._found:
            return self._found[key]
        found = None
        point = point_of(element)
        if point is not None:
            for p in self._tries(element, point):
                found = self._at(p)
                if found is not None:
                    # A room found lower down may be on the floor below (a floor box just under its own room's
                    # floor). Where a different room is found just above, the right one cannot be told: none is used.
                    if p.Z < point.Z - 0.01:
                        above = self._above(point)
                        if above is not None and id_value(above.Id) != id_value(found.Id):
                            found = None
                    break
        self._found[key] = found
        return found


def number(room):
    return (room.Number or u"") if room is not None else u""


def name(room):
    """The room's name alone (Room.Name gives the name and the number together)."""
    if room is None:
        return u""
    p = room.get_Parameter(BuiltInParameter.ROOM_NAME)
    return (p.AsString() or u"") if p is not None else u""
