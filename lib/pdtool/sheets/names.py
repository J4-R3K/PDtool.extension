# -*- coding: utf-8 -*-
"""File names from a naming rule.

A rule is a list of parts. Each part names one parameter and has a prefix, a suffix and a separator; the separator is
written AFTER the part, and the last part's separator is not used. This is how PD's ProSheets profiles store it
(every one of the 11 shared profiles, read 14/10/2026: "Sheet Number_Sheet Name_Current Revision" has "_" after the
number and the name, and "-" after the revision, which is not used).
"""
import re

# Characters Windows does not allow in a file name, and control characters. Each one becomes "-": sheet number
# DB/00/SCRE gives DB-00-SCRE, as ProSheets names it.
_ILLEGAL = re.compile(u'[<>:"/\\\\|?*\x00-\x1f]')

# Windows refuses a path longer than this unless long paths are switched on.
MAX_PATH = 259

# What to use instead of a parameter Revit gives no value for (model.value_getter), where there is something.
# "Revisions on Sheet" is the Edit button in a sheet's Properties that lists the revisions shown on the sheet; the
# sheet's revision, as the title block shows it, is "Current Revision" (Jarek added "Revisions on Sheet" to a rule on
# 15/10/2026, and the sheet could not be exported).
INSTEAD = {u"Revisions on Sheet": u"For the sheet's revision, use Current Revision."}


def clean(text):
    """Replace the characters Windows refuses with "-", and drop spaces and dots at the end (Windows strips them,
    so two names differing only there would be the same file)."""
    return _ILLEGAL.sub(u"-", text or u"").rstrip(u" .")


def copy_name(name, existing, dwg=False, extension=u".pdf"):
    """The name for a new file when the file of this name is open in another program and cannot be replaced: "<name>
    (1)", or (2) and so on, the first one free in the folder, the way Windows names a second copy of a download (Jarek,
    14/10/2026: "it would be much better if the file was saved as (1) same as windows does it").

    existing: the names of the files in the folder. Capitals are ignored, as Windows ignores them. A DWG or DGN name
    (dwg True) is free only when no file in the folder starts with it followed by "." or "-", because the files Revit
    may write beside a DWG (a .pcp file, a DWG for each view when the views are not merged) are named after the DWG.
    Any other name is free when no file has that name with the extension given."""
    taken = set(f.lower() for f in existing)
    n = 1
    while True:
        candidate = u"{} ({})".format(name, n)
        low = candidate.lower()
        if dwg:
            busy = any(f.startswith(low + u".") or f.startswith(low + u"-") for f in taken)
        else:
            busy = low + (extension or u".pdf").lower() in taken
        if not busy:
            return candidate
        n += 1


def part(param, prefix=u"", suffix=u"", sep=u"-", source=u""):
    """One part of a rule. source is "sheet" or "project" (project information), or "" to look in both."""
    return {"param": param, "prefix": prefix, "suffix": suffix, "sep": sep, "source": source}


def build(parts, value_of):
    """Build a file name (without extension).

    value_of(part) returns the parameter's value as text, or None when the parameter does not exist.
    Returns (name, missing): missing lists the parameters that do not exist or are empty, in rule order.
    A name is built even when something is missing, so the window can show it; it must not be used."""
    pieces = []
    missing = []
    for i, p in enumerate(parts):
        value = value_of(p)
        if value is None or not u"{}".format(value).strip():
            missing.append(p["param"])
            value = u""
        piece = u"{}{}{}".format(p.get("prefix") or u"", value, p.get("suffix") or u"")
        pieces.append(piece)
        if i < len(parts) - 1:
            pieces.append(p.get("sep") or u"")
    return clean(u"".join(pieces)), missing


def describe(parts):
    """The rule as a reader sees it: "PD_PRJ_Code_Project1 - ... - Sheet Number"."""
    out = []
    for i, p in enumerate(parts):
        out.append(u"{}{}{}".format(p.get("prefix") or u"", p["param"], p.get("suffix") or u""))
        if i < len(parts) - 1:
            sep = p.get("sep") or u""
            out.append(u" {} ".format(sep) if sep else u" + ")
    return u"".join(out)


def _and(words):
    return words[0] if len(words) == 1 else u", ".join(words[:-1]) + u" and " + words[-1]


def missing_text(missing, no_text=()):
    """What to do about the parameters of a name that gave no value, in rule order: first those Revit gives no value
    for at all (no_text: the names model.value_getter found to be buttons in Properties), which must come out of
    the rule; then those that are empty or missing, which can be filled in the model."""
    buttons = [m for m in missing if m in no_text]
    others = [m for m in missing if m not in no_text]
    out = []
    if buttons:
        one = len(buttons) == 1
        out.append(u"{} cannot be part of a file name: Revit gives no value for {}. Remove {} from the rule at "
                   u"step 2.".format(_and(buttons), u"it" if one else u"them", u"it" if one else u"them"))
        out.extend(INSTEAD[b] for b in buttons if b in INSTEAD)
    if others:
        out.append(u"Empty or missing: {}. Fill it in the model or type the name.".format(u", ".join(others)))
    return u" ".join(out)


def problems(items, folder=u"", extension=u".pdf", no_text=()):
    """Check the names of the ticked items before anything is written.

    items: list of (key, name, missing). Returns {key: message}; an item with no message is fine. no_text: see
    missing_text. Windows treats names that differ only in capitals as the same file, so duplicates are found
    ignoring case."""
    out = {}
    seen = {}
    for key, name, missing in items:
        if missing:
            out[key] = missing_text(missing, no_text)
        elif not name:
            out[key] = u"The name is empty. Type a name."
        elif folder and len(u"{}\\{}{}".format(folder.rstrip(u"\\"), name, extension)) > MAX_PATH:
            out[key] = u"The full path is longer than Windows allows ({} characters). Shorten the name or the folder.".format(
                MAX_PATH)
        seen.setdefault((name or u"").lower(), []).append(key)
    for low, keys in seen.items():
        if low and len(keys) > 1:
            for key in keys:
                if key not in out:
                    others = [k for k in keys if k != key]
                    out[key] = u"Same file name as {}. Change one of the names.".format(u", ".join(
                        u"{}".format(o) for o in others))
    return out
