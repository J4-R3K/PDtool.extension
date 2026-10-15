# -*- coding: utf-8 -*-
"""Make PD Sheets profiles from PD's own saved ProSheets profiles (XML files PD wrote with ProSheets).

Only these saved settings files are read; no DiRoots program file is opened or decompiled (CDPA 1988 s.50B(3)(d)).
The XML is read with regular expressions, not an XML parser, so it runs the same under IronPython 2.7 and CPython 3.

What is taken from each <Profile>:
- the naming rule for sheets (SelectSheetParameters), and for views (SelectViewParameters) where one is set. Each
  <ParameterModel> is one part; its xml:space_x003D_preserve attribute is the separator written AFTER that part,
  and the last part's separator is not used. Checked on all 11 shared profiles (14/10/2026): joining the parts this
  way gives each file's <CombineParameterName> exactly.
- the PDF settings from the tags directly under <TemplateInfo>, except raster quality (PD profiles use High). The same tag names (IsCenter, RasterQuality and
  others) also appear inside the DWF, IMG and other blocks, so those blocks are removed first.
- the export folder (CreateExportFolderPath), changed with folders.to_stored so no user name is kept.
<FilePath>, the profile's own location, is not kept (folders.py notes why).
"""
import io
import os
import re

from pdtool.sheets import folders, profiles

# Blocks inside <TemplateInfo> whose tags repeat the PDF settings' names or are not used.
_BLOCKS = (u"DWF", u"NWC", u"IFC", u"IMG", u"SelectionSheets", u"SelectionViews", u"SelectedProjectParameters",
           u"SelectSheetParameters", u"SelectViewParameters", u"CustomFileNameParameters", u"XmlExporter",
           u"CombinedFileDto", u"Formats")

_ENTITIES = ((u"&lt;", u"<"), (u"&gt;", u">"), (u"&quot;", u'"'), (u"&apos;", u"'"), (u"&amp;", u"&"))


def _unescape(text):
    for a, b in _ENTITIES:
        text = text.replace(a, b)
    return text


def _tag(text, name):
    """Text of the first <name>...</name>, None when absent, "" for <name />."""
    m = re.search(u"<{0}>(.*?)</{0}>".format(name), text, re.S)
    if m:
        return _unescape(m.group(1))
    if re.search(u"<{0}\\s*/>".format(name), text):
        return u""
    return None


def _block(text, name):
    m = re.search(u"<{0}>(.*?)</{0}>".format(name), text, re.S)
    return m.group(1) if m else u""


def _without_blocks(text):
    for name in _BLOCKS:
        text = re.sub(u"<{0}(\\s[^>]*)?>.*?</{0}>".format(name), u"", text, flags=re.S)
        text = re.sub(u"<{0}(\\s[^>]*)?/>".format(name), u"", text)
    return text


def _bool(value, default):
    if value is None:
        return default
    return value.strip().lower() == u"true"


def _mm(value):
    """ "0.00mm" -> 0.0"""
    m = re.match(u"\\s*(-?[0-9.]+)", value or u"")
    return float(m.group(1)) if m else 0.0


def read_rule(block):
    """(parts, combined name) from a SelectSheetParameters or similar block."""
    combined = _tag(block, u"CombineParameterName") or u""
    parts = []
    for m in re.finditer(u'<ParameterModel(?:\\s+xml:space_x003D_preserve="([^"]*)")?\\s*>(.*?)</ParameterModel>',
                         block, re.S):
        body = m.group(2)
        # A ParameterModel can hold its own <ParameterModels> list; only the outer name is wanted.
        body = re.sub(u"<ParameterModels>.*?</ParameterModels>", u"", body, flags=re.S)
        name = _tag(body, u"ParameterName")
        if not name:
            continue
        project = _bool(_tag(body, u"IsProjectParameter"), False)
        parts.append({
            "param": name,
            "prefix": _tag(body, u"Prefix") or u"",
            "suffix": _tag(body, u"Suffix") or u"",
            "sep": _unescape(m.group(1) or u""),
            "source": u"project" if project else u"sheet",
        })
    return parts, combined


def joined(parts):
    """The rule's parameter names joined as ProSheets shows them in CombineParameterName: each part's separator
    after it, the last one left out. Used to prove the separators are read the right way round."""
    out = []
    for i, p in enumerate(parts):
        out.append(p["param"])
        if i < len(parts) - 1:
            out.append(p["sep"])
    return u"".join(out)


def _profile_blocks(text):
    return re.findall(u"<Profile>(.*?)</Profile>", text, re.S)


def read_file(path, mounts, home, file_label=None):
    """Read one ProSheets XML file. Returns a list of (profile, notes): one per <Profile> in the file.
    notes lists, in plain words, anything that could not be brought across or was changed."""
    with io.open(path, "r", encoding="utf-8-sig") as f:
        text = f.read()
    label = file_label or path
    out = []
    for body in _profile_blocks(text):
        out.append(_read_profile(body, label, mounts, home))
    return out


def _read_profile(body, label, mounts, home):
    notes = []
    inner_name = _tag(body, u"Name") or u""
    info = _block(body, u"TemplateInfo")
    top = _without_blocks(info)

    profile = profiles.new(label)
    profile["note"] = u"Made from the ProSheets profile {} ({}).".format(label, inner_name) if inner_name else \
        u"Made from the ProSheets profile {}.".format(label)

    sheet_parts, sheet_combined = read_rule(_block(info, u"SelectSheetParameters"))
    view_parts, _ = read_rule(_block(info, u"SelectViewParameters"))
    if sheet_parts:
        if joined(sheet_parts) != sheet_combined:
            notes.append(u"The sheet naming rule reads as \"{}\" but the profile shows \"{}\". Check the rule before "
                         u"use.".format(joined(sheet_parts), sheet_combined))
        profile["rules"].insert(0, {"name": u"{} sheets".format(label), "parts": sheet_parts})
        profile["pdf"]["rule"] = profile["dwg"]["rule"] = u"{} sheets".format(label)
    else:
        notes.append(u"No sheet naming rule was found. The PD ISO 19650 rule is used.")
    if view_parts:
        profile["rules"].insert(1, {"name": u"{} views".format(label), "parts": view_parts})
        profile["pdf"]["view_rule"] = profile["dwg"]["view_rule"] = u"{} views".format(label)

    pdf = profile["pdf"]
    pdf["enabled"] = _bool(_tag(top, u"IsPDFChecked"), True)
    pdf["vector"] = _bool(_tag(top, u"IsVectorProcessing"), True)
    # Raster quality is not taken from ProSheets: PD profiles use High, with Presentation set per sheet where a sheet
    # needs it (Jarek, 14/10/2026). Every PD ProSheets profile has Presentation, so the change is noted.
    rq = _tag(top, u"RasterQuality")
    if rq in profiles.RASTER_QUALITIES and rq != pdf["raster_quality"]:
        notes.append(u"ProSheets used raster quality {}. PD profiles use {}; set {} for a sheet in the sheet list "
                     u"where that sheet needs it.".format(rq, pdf["raster_quality"], rq))
    elif rq and rq not in profiles.RASTER_QUALITIES:
        notes.append(u"Raster quality \"{}\" is not one Revit offers. {} is used.".format(rq, pdf["raster_quality"]))
    colour = (_tag(top, u"Color") or u"").replace(u" ", u"").lower()
    pdf["colour"] = {u"color": u"Color", u"grayscale": u"GrayScale", u"blackline": u"BlackLine"}.get(colour, u"Color")
    pdf["view_links_blue"] = _bool(_tag(top, u"ViewLink"), True)
    pdf["hide_ref_planes"] = _bool(_tag(top, u"HidePlanes"), True)
    pdf["hide_scope_boxes"] = _bool(_tag(top, u"HideScopeBox"), True)
    pdf["hide_unref_tags"] = _bool(_tag(top, u"HideUnreferencedTags"), True)
    pdf["hide_crop"] = _bool(_tag(top, u"HideCropBoundaries"), True)
    pdf["replace_halftone"] = _bool(_tag(top, u"ReplaceHalftone"), False)
    pdf["mask_coincident"] = _bool(_tag(top, u"MaskCoincidentLines"), False)
    if _bool(_tag(top, u"IsFitToPage"), False):
        pdf["zoom"] = u"fit"
    else:
        try:
            pdf["zoom"] = int(float(_tag(top, u"Zoom") or u"100"))
        except ValueError:
            pdf["zoom"] = 100
    pdf["centre"] = _bool(_tag(top, u"IsCenter"), True)
    margin = (_tag(top, u"SelectedMarginType") or u"").lower()
    pdf["margin"] = u"printer" if u"printer" in margin else (u"user" if u"user" in margin else u"none")
    pdf["offset_x_mm"] = _mm(_tag(top, u"OffsetX"))
    pdf["offset_y_mm"] = _mm(_tag(top, u"OffsetY"))
    if _tag(top, u"IsSeparateFile") is not None and not _bool(_tag(top, u"IsSeparateFile"), True):
        notes.append(u"The profile combines sheets into one PDF. PD Sheets v1 writes one PDF per sheet; combining "
                     u"is planned for v2.")

    dwg = profile["dwg"]
    dwg["enabled"] = _bool(_tag(top, u"IsDWGChecked"), False)
    setup = _tag(top, u"DWGSettingName") or u""
    if setup and setup.lower().startswith(u"diroots"):
        notes.append(u"The DWG setting \"{}\" belongs to ProSheets, not to the model. Choose one of the model's DWG "
                     u"export setups.".format(setup))
        setup = u""
    dwg["setup"] = setup

    others = [t for t in (u"IsDGNChecked", u"IsDWFChecked", u"IsNWCChecked", u"IsIFCChecked", u"IsIMGChecked",
                          u"IsXmlChecked") if _bool(_tag(top, t), False)]
    if others:
        notes.append(u"Formats not in PD Sheets v1 were ticked and are left out: {}.".format(
            u", ".join(t[2:-7].upper() for t in others)))

    folder = _tag(top, u"CreateExportFolderPath") or u""
    if folder:
        stored = folders.to_stored(folder, mounts, home)
        stored, changed = _other_users_home(stored, mounts, home)
        profile["folder"] = stored
        if changed:
            notes.append(u"The export folder {} is under another user's folder. It is now kept as the same folder "
                         u"for whoever uses the profile: {}.".format(folder, folders.describe(stored)))
    return profile, notes


def _other_users_home(stored, mounts, home):
    """A folder under C:\\Users\\<someone else>\\ is taken as the same folder under this user's own, and then
    stored as a SharePoint library where this user syncs one there. Returns (stored, changed)."""
    if "path" not in stored:
        return stored, False
    m = re.match(u"^[A-Za-z]:\\\\Users\\\\[^\\\\]+\\\\?(.*)$", stored["path"])
    if not m:
        return stored, False
    below = m.group(1)
    return folders.to_stored(os.path.join(home, below) if below else home, mounts, home), True
