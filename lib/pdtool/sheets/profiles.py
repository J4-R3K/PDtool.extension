# -*- coding: utf-8 -*-
"""PD Sheets profiles: one JSON file per profile.

A profile holds the naming rules, the output folder (in the form folders.to_stored gives, never with a user's name in
it), the settings of each format, the file size limit, and any paper, orientation or raster quality set for one
sheet. The DGN, DWF, IFC, NWC, image and XML settings start from formats.DEFAULTS. It never stores its own location:
each PC finds the profiles folder for itself (folders.profiles_folder).
"""
import copy
import io
import json
import os
import re

from pdtool.sheets import formats

SCHEMA = 1

# Revit's own values (RasterQualityType, ColorDepthType), kept as text so the file reads without Revit.
RASTER_QUALITIES = (u"Low", u"Medium", u"High", u"Presentation")
COLOURS = (u"Color", u"GrayScale", u"BlackLine")
ORIENTATIONS = (u"Auto", u"Portrait", u"Landscape")

PD_ISO_RULE_NAME = u"PD ISO 19650"


def _p(param, source, sep=u"-"):
    return {"param": param, "prefix": u"", "suffix": u"", "sep": sep, "source": source}


# Built-in rule (v1 build plan, "Naming rules"): the PD project parameters, then the sheet number, joined by "-".
PD_ISO_RULE = {
    "name": PD_ISO_RULE_NAME,
    "parts": [
        _p(u"PD_PRJ_Code_Project1", u"project"),
        _p(u"PD_PRJ_Code_Originator1", u"project"),
        _p(u"PD_SHT_FunctionalBreakdown", u"sheet"),
        _p(u"PD_SHT_SpatialBreakdown", u"sheet"),
        _p(u"PD_SHT_Form", u"sheet"),
        _p(u"PD_PRJ_Code_Discipline1", u"project"),
        _p(u"Sheet Number", u"sheet"),
    ],
}

SHEET_NUMBER_RULE = {"name": u"Sheet number", "parts": [_p(u"Sheet Number", u"sheet")]}
VIEW_NAME_RULE = {"name": u"View name", "parts": [_p(u"View Name", u"sheet")]}

# New profiles start with the settings every PD ProSheets profile uses (v1 build plan, "Defaults"), except raster
# quality: High (300 dpi), with Presentation set per sheet where a sheet needs it (Jarek, 14/10/2026; one sheet came
# out at 3.33 MB at Presentation and 1.9 MB at High: C:\Dev\PD-Revit-Sheets-PLAN-2026-10-14.md, section 5).
DEFAULT_PDF = {
    "enabled": True,
    "rule": PD_ISO_RULE_NAME,
    "view_rule": VIEW_NAME_RULE["name"],
    "vector": True,
    "raster_quality": u"High",
    "colour": u"Color",
    "view_links_blue": True,
    "hide_ref_planes": True,
    "hide_scope_boxes": True,
    "hide_unref_tags": True,
    "hide_crop": True,
    "replace_halftone": False,
    "mask_coincident": False,
    "zoom": 100,
    "centre": True,
    "margin": u"none",
    "offset_x_mm": 0.0,
    "offset_y_mm": 0.0,
}

DEFAULT_DWG = {
    "enabled": False,
    "rule": PD_ISO_RULE_NAME,
    "view_rule": VIEW_NAME_RULE["name"],
    "setup": u"",
    # Revit's "Export views on sheets and links as external references": a DWG file of its own for each linked model
    # in each view and each view on a sheet. Off, so each sheet or view is one DWG (Jarek, 15/10/2026: "the default
    # option should be that the DWG export is combined single file", after one sheet gave 47 DWG files). It applies
    # with a setup from the model too (exporter.dwg_options).
    "separate": False,
    # Revit's "Text treatment" (formats.DWG_TEXT_TREATMENTS): each text note as one multiline text, whatever the setup
    # says (Jarek, 15/10/2026: "can we ensure that revit multiline text is exported as DWG multiline text also? At the
    # moment every single text is a single line"). Revit's own default, Exact, wrote 339 of the 340 texts on one sheet
    # as one line each.
    "text": u"Approximate",
}


def new(name):
    out = {
        "schema": SCHEMA,
        "name": name,
        "rules": [copy.deepcopy(PD_ISO_RULE), copy.deepcopy(SHEET_NUMBER_RULE), copy.deepcopy(VIEW_NAME_RULE)],
        "pdf": copy.deepcopy(DEFAULT_PDF),
        "dwg": copy.deepcopy(DEFAULT_DWG),
        "folder": {},
        "size_limit_mb": 3.0,  # Jarek, 14/10/2026: "if the drawing is more than 3MB people are having problems with printing"
        "sheet_settings": {},
        "note": u"",
    }
    # DGN, DWF, IFC, NWC, images and XML (formats.DEFAULTS), each off until ticked.
    for key in formats.DEFAULTS:
        out[key] = formats.default(key)
    return out


def complete(profile):
    """Fill anything a profile file leaves out with the defaults, so an older or hand-edited file still opens.
    The built-in PD ISO 19650 rule is always present."""
    base = new(profile.get("name") or u"Profile")
    out = copy.deepcopy(profile)
    for key, value in base.items():
        if key not in out:
            out[key] = value
        elif isinstance(value, dict) and key in formats.KEYS and isinstance(out[key], dict):
            for k, v in value.items():
                out[key].setdefault(k, v)
    names = [r.get("name") for r in out["rules"]]
    for builtin in (PD_ISO_RULE, VIEW_NAME_RULE):
        if builtin["name"] not in names:
            out["rules"].append(copy.deepcopy(builtin))
    return out


def rule(profile, name):
    for r in profile.get("rules") or []:
        if r.get("name") == name:
            return r
    return None


def file_name_for(name):
    """The profile's file name: its name with the characters Windows refuses replaced."""
    safe = re.sub(u'[<>:"/\\\\|?*\x00-\x1f]', u"-", name).strip(u" .") or u"Profile"
    return safe + u".json"


def save(profile, folder):
    if not os.path.isdir(folder):
        os.makedirs(folder)
    path = os.path.join(folder, file_name_for(profile["name"]))
    text = json.dumps(profile, indent=2, sort_keys=True, ensure_ascii=False)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(u"{}".format(text))
    return path


def load(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return complete(json.loads(f.read()))


def list_profiles(folder):
    """[(name, path)] for every profile in the folder, sorted by name. A file that cannot be read is listed with
    name None, so the window can say which file is damaged rather than hide it."""
    out = []
    if not os.path.isdir(folder):
        return out
    for fn in sorted(os.listdir(folder), key=lambda s: s.lower()):
        if not fn.lower().endswith(u".json"):
            continue
        path = os.path.join(folder, fn)
        try:
            out.append((load(path)["name"], path))
        except Exception:
            out.append((None, path))
    return out


def delete(path):
    if os.path.isfile(path):
        os.remove(path)


def rename(profile, new_name, folder):
    """Save under the new name and remove the old file. Returns the new path."""
    old_path = os.path.join(folder, file_name_for(profile["name"]))
    profile["name"] = new_name
    path = save(profile, folder)
    if os.path.normcase(old_path) != os.path.normcase(path):
        delete(old_path)
    return path


def sheet_setting(profile, unique_id, key):
    """A setting made for one sheet ("paper", "orientation" or "raster_quality"), or None for the profile's own."""
    return ((profile.get("sheet_settings") or {}).get(unique_id) or {}).get(key)


def set_sheet_setting(profile, unique_id, key, value):
    """value None removes the sheet's own setting, so the profile's applies again."""
    settings = profile.setdefault("sheet_settings", {})
    one = settings.setdefault(unique_id, {})
    if value is None:
        one.pop(key, None)
        if not one:
            settings.pop(unique_id, None)
    else:
        one[key] = value
