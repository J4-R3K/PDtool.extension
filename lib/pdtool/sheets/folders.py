# -*- coding: utf-8 -*-
"""Folders stored without the user's name in them.

Why (Jarek, 14/10/2026): a shared ProSheets profile "always inherits my file path with \\JarekWityk\\ and that fails
the print". Each of PD's 11 shared ProSheets profiles stores its own location and its export folder under
C:\\Users\\<name>\\. PD Sheets stores a folder in one of three forms:

    {"library": "https://projectdesignio.sharepoint.com/sites/PD/01_Projects", "below": "<project folder>\\04-DES"}
        a folder inside a SharePoint library that OneDrive syncs. On each PC the library is found from that user's
        own OneDrive settings (HKCU\\Software\\SyncEngines\\Providers\\OneDrive\\<id>: MountPoint and UrlNamespace),
        so it works wherever the user has synced it.
    {"home": "Documents\\Exports"}
        a folder inside the user's own profile folder (C:\\Users\\<name>), found on each PC under that user's own.
    {"path": "P:\\Issue"}
        anything else, as typed.

A personal OneDrive is treated as part of the user's own folders, not as a library: its address names the user.

A profile comes from the shared folder or from a ProSheets import, so what it stores is checked before it is used
(security review of commit 352edb9, 15/10/2026): "below" and "home" must stay inside the library or the user's folder
(_stays_inside), and a "path" on another computer (is_network) is not looked at until the user confirms it in the
window, because Windows contacts that computer as soon as the folder is looked at. None of PD's profiles stored a
network folder on 15/10/2026 (the 2 PD Sheets profiles and the 11 ProSheets profiles all name folders under
C:\\Users).
"""
import os

PD_TEMPLATES_LIBRARY = u"https://projectdesignio.sharepoint.com/sites/PD/00_Templates"
PROFILES_BELOW = u"AppSettings\\PD Sheets"


def is_network(path):
    """True when the path starts with two backslashes (or slashes): a folder on another computer, \\\\host\\share, and
    the \\\\?\\ and \\\\.\\ forms, which can name one too."""
    return (path or u"").replace(u"/", u"\\").startswith(u"\\\\")


def _stays_inside(below):
    """True when below, joined to a folder, names that folder or one inside it: no drive, no starting slash, and no
    part made only of dots and spaces. ".." is the folder above; other runs such as ".. " are refused as well, because
    Windows removes the dots and spaces at the end of a path ("File path formats on Windows systems", Microsoft
    Learn), and PD's folders never have such a name."""
    try:
        text = (below or u"").replace(u"/", u"\\")
    except AttributeError:  # not text: a damaged or hand-edited profile
        return False
    if u":" in text or text.startswith(u"\\"):
        return False
    return not any(part and not part.strip(u". ") for part in text.split(u"\\"))


def _norm(path):
    return os.path.normcase(os.path.normpath(path)) if path else u""


def _inside(path, root):
    """The part of path below root, or None when path is not inside root."""
    p, r = _norm(path), _norm(root)
    if not r:
        return None
    if p == r:
        return u""
    if p.startswith(r.rstrip(u"\\/") + os.sep):
        return os.path.normpath(path)[len(os.path.normpath(root).rstrip(u"\\/")) + 1:]
    return None


def read_mounts():
    """The SharePoint libraries OneDrive syncs on this PC, for this user: list of (local folder, library address).
    Personal OneDrive folders are left out. Returns [] when nothing can be read."""
    out = []
    try:
        try:
            import _winreg as winreg  # IronPython 2.7
        except ImportError:
            import winreg  # CPython 3
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, u"Software\\SyncEngines\\Providers\\OneDrive")
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:  # no more keys (WindowsError is an OSError)
                break
            i += 1
            try:
                k = winreg.OpenKey(root, sub)
                mount = winreg.QueryValueEx(k, u"MountPoint")[0]
                url = winreg.QueryValueEx(k, u"UrlNamespace")[0]
                try:
                    kind = winreg.QueryValueEx(k, u"LibraryType")[0]
                except Exception:
                    kind = u""
            except Exception:
                continue
            if mount and url and (kind or u"").lower() not in (u"personal", u"mysite"):
                out.append((mount, url.rstrip(u"/")))
    except Exception:
        return []
    return out


def to_stored(path, mounts, home):
    """The form a folder is saved in (see the module notes). The longest matching library wins."""
    if not path:
        return {}
    best = None
    for mount, url in mounts:
        below = _inside(path, mount)
        if below is not None and (best is None or len(mount) > len(best[0])):
            best = (mount, url, below)
    if best:
        return {"library": best[1].rstrip(u"/"), "below": best[2]}
    below = _inside(path, home)
    if below is not None:
        return {"home": below}
    return {"path": os.path.normpath(path)}


def to_local(stored, mounts, home):
    """(folder on this PC, problem). problem is None when the folder could be worked out; the folder may still not
    exist, which the caller checks."""
    if not stored:
        return None, u"No output folder is set. Choose one."
    if "library" in stored:
        want = stored["library"].rstrip(u"/").lower()
        name = stored["library"].rstrip(u"/").split(u"/")[-1]
        below = stored.get("below") or u""
        if not _stays_inside(below):
            return None, (u"The output folder in the profile, {}, is outside the SharePoint library {}, so PD Sheets "
                          u"does not use it. Choose another folder.").format(below, name)
        for mount, url in mounts:
            if url.rstrip(u"/").lower() == want:
                return os.path.join(mount, below), None
        return None, (u"The SharePoint library {} is not synced on this PC. Sync it from SharePoint, or choose "
                      u"another folder.").format(name)
    if "home" in stored:
        if not _stays_inside(stored["home"]):
            return None, (u"The output folder in the profile, {}, is outside your own user folder, so PD Sheets does not "
                          u"use it. Choose another folder.").format(stored["home"])
        return os.path.join(home, stored["home"]), None
    if "path" in stored:
        return stored["path"], None
    return None, u"The output folder could not be read from the profile. Choose one."


def describe(stored):
    """How the stored folder reads to a person: library name plus the folder below it."""
    if "library" in stored:
        name = stored["library"].rstrip(u"/").split(u"/")[-1]
        return u"SharePoint library {}: {}".format(name, stored.get("below") or u"(top of the library)")
    if "home" in stored:
        return u"Your own folder: {}".format(stored["home"])
    return stored.get("path") or u""


def profiles_folder(mounts, home, local_fallback):
    """Where the profiles are kept on this PC: (folder, shared). The shared folder is AppSettings\\PD Sheets in the
    PD - 00_Templates library, found from this user's OneDrive settings, or in the usual place under the user's
    folder. Otherwise the local fallback, and shared is False so the window can say so."""
    folder, problem = to_local({"library": PD_TEMPLATES_LIBRARY, "below": PROFILES_BELOW}, mounts, home)
    if problem is None and os.path.isdir(os.path.dirname(folder)):
        return folder, True
    usual = os.path.join(home, u"PD(io)", u"PD - 00_Templates", PROFILES_BELOW)
    if os.path.isdir(os.path.dirname(usual)):
        return usual, True
    return local_fallback, False
