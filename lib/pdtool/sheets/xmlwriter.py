# -*- coding: utf-8 -*-
"""PD's own XML export: one small XML file per sheet or view, holding the parameter values chosen in the profile.

    <?xml version="1.0" encoding="utf-8"?>
    <Sheet>
      <SheetNumber>E-100</SheetNumber>
      ...
    </Sheet>

The profile lists the fields for sheets and for views separately. A field is a parameter of the sheet or view or of
project information, {"param", "source", "element"}, or a fixed text written the same in every file, {"value",
"element"}. UTF-8 without a byte order mark, Windows line endings. Plain Python, so the library tests run without
Revit.
"""
import io
import re

ROOTS = {u"sheet": u"Sheet", u"view": u"View"}

# Characters XML 1.0 does not allow at all: control characters other than tab, line feed and carriage return, and
# U+FFFE and U+FFFF. A parameter value holding one would make the file unreadable, so they are left out.
_NOT_ALLOWED = re.compile(u"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
# An element name: a letter or "_" first, then letters, digits, "_", "-" or ".". Letters outside A to Z are allowed.
_NAME = re.compile(u"^[^\\W\\d][\\w.\\-]*$", re.UNICODE)


def text(value):
    """The value as XML text: & < > escaped, characters XML does not allow left out."""
    if value is None:
        return u""
    out = _NOT_ALLOWED.sub(u"", u"{}".format(value))
    return out.replace(u"&", u"&amp;").replace(u"<", u"&lt;").replace(u">", u"&gt;")


def name_problem(name):
    """None when name can be used as an element name, or what is wrong with it."""
    if not name:
        return u"The element name is empty."
    if not _NAME.match(name):
        return (u"\"{}\" cannot be used as an element name. Start it with a letter and use only letters, digits, "
                u"\"_\", \"-\" and \".\".").format(name)
    if name[:3].lower() == u"xml":
        return u"\"{}\" cannot be used as an element name: names starting with \"xml\" are kept by XML.".format(name)
    return None


def element_name(param):
    """An element name made from a parameter name: "Current Revision Date" gives "CurrentRevisionDate", and any
    character an element name cannot hold is left out. "_" is put first when the name would start with a digit,
    with "xml", or would be empty."""
    words = re.split(u"\\s+", (param or u"").strip())
    joined = u"".join(w[:1].upper() + w[1:] for w in words if w)
    out = u"".join(c for c in joined if re.match(u"[\\w.\\-]", c, re.UNICODE))
    if not out or not re.match(u"[^\\W\\d]", out[0], re.UNICODE) or out[:3].lower() == u"xml":
        out = u"_" + out
    return out


def field(param, source=u"sheet", element=None):
    return {"param": param, "source": source, "element": element or element_name(param)}


def fixed(element, value):
    return {"param": u"", "value": value, "element": element}


def problems(fields):
    """Messages for fields that cannot be written: a bad element name, a field with neither a parameter nor a text,
    and an element name used twice (a reader of the file would find only one of them)."""
    out = []
    seen = set()
    for f in fields or []:
        el = f.get("element") or u""
        p = name_problem(el)
        if p:
            out.append(p)
        if not f.get("param") and f.get("value") is None:
            out.append(u"The field {} has no parameter and no text.".format(el or u"with no name"))
        if el in seen:
            out.append(u"The element name {} is used twice. Change one of them.".format(el))
        seen.add(el)
    return out


def values(fields, value_of):
    """[(element, value)] for one sheet or view. value_of(field) returns the parameter's text, or None when the
    parameter does not exist, as model.value_getter gives it. A parameter that does not exist is written empty."""
    out = []
    for f in fields or []:
        if f.get("param"):
            v = value_of(f)
        else:
            v = f.get("value")
        out.append((f.get("element"), u"" if v is None else u"{}".format(v)))
    return out


def lines(kind, pairs):
    root = ROOTS.get(kind, u"Sheet")
    out = [u'<?xml version="1.0" encoding="utf-8"?>', u"<{}>".format(root)]
    for element, value in pairs:
        if value == u"":
            out.append(u"  <{}/>".format(element))
        else:
            out.append(u"  <{0}>{1}</{0}>".format(element, text(value)))
    out.append(u"</{}>".format(root))
    return out


def write(path, kind, pairs):
    with io.open(path, "w", encoding="utf-8", newline=u"") as f:
        f.write(u"\r\n".join(lines(kind, pairs)) + u"\r\n")
    return path
