# coding: utf-8
"""
Find & Replace inside Text Notes (like Word's Ctrl+H).
- Scope: entire model / current view / current selection.
- Match case + whole word options.
- Preview list with before/after; tick which notes to change.
- Edits FormattedText ranges, so bold/italic/underline around the
  replaced phrase is preserved (setting .Text would wipe it).
"""

import clr

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    TextNote,
)
from pyrevit import forms, revit, script

doc = revit.doc
output = script.get_output()

# 1) Scope + options
SCOPES = ["Entire model", "Current view", "Selection"]
picked = forms.CommandSwitchWindow.show(
    SCOPES,
    switches=["Match case", "Whole word"],
    message="Search scope:",
)
if isinstance(picked, tuple):
    scope, switches = picked
else:
    scope, switches = picked, {}
if not scope:
    script.exit()

match_case = bool(switches.get("Match case"))
whole_word = bool(switches.get("Whole word"))

find_text = forms.ask_for_string(prompt="Find phrase in text notes:",
                                 title="Replace in Text Notes")
if not find_text:
    script.exit()

replace_text = forms.ask_for_string(prompt="Replace with (empty = delete phrase):",
                                    title="Replace in Text Notes")
if replace_text is None:
    script.exit()

# 2) Collect text notes per scope
if scope == "Selection":
    notes = [el for el in revit.get_selection() if isinstance(el, TextNote)]
elif scope == "Current view":
    notes = list(
        FilteredElementCollector(doc, doc.ActiveView.Id)
        .OfClass(TextNote)
        .WhereElementIsNotElementType()
    )
else:
    notes = list(
        FilteredElementCollector(doc)
        .OfClass(TextNote)
        .WhereElementIsNotElementType()
    )

if not notes:
    forms.alert("No text notes found in scope: {}".format(scope))
    script.exit()


def replace_in_formatted(ftext, find, repl, case, word):
    """Replace every occurrence inside a FormattedText; returns count."""
    count = 0
    start = 0
    while True:
        plain = ftext.GetPlainText()
        if start >= len(plain):
            break
        rng = ftext.Find(find, start, case, word)
        if rng is None or rng.Start < 0 or rng.Length <= 0:
            break
        ftext.SetPlainText(rng, repl)
        count += 1
        start = rng.Start + len(repl)  # skip past replacement (repl may contain find)
    return count


def view_name(tn):
    v = doc.GetElement(tn.OwnerViewId)
    try:
        return v.Name if v else "?"
    except Exception:
        return "?"


def shorten(txt, n=55):
    txt = txt.replace("\r", " ").replace("\n", " ")
    return txt if len(txt) <= n else txt[: n - 1] + u"…"


# 3) Build preview: edit a detached FormattedText copy per note
class Candidate(object):
    def __init__(self, tn, ftext, hits, before):
        self.tn = tn
        self.ftext = ftext
        self.hits = hits
        self.before = before
        self.after = ftext.GetPlainText()
        self.name = u"[{}]  {}  →  {}   ({} hit{})".format(
            view_name(tn),
            shorten(self.before),
            shorten(self.after),
            hits,
            "s" if hits > 1 else "",
        )


candidates = []
for tn in notes:
    try:
        ftext = tn.GetFormattedText()
    except Exception:
        continue
    before = ftext.GetPlainText()
    hits = replace_in_formatted(ftext, find_text, replace_text, match_case, whole_word)
    if hits:
        candidates.append(Candidate(tn, ftext, hits, before))

if not candidates:
    forms.alert(u"No text notes contain “{}” in scope: {}".format(find_text, scope))
    script.exit()

chosen = forms.SelectFromList.show(
    candidates,
    title=u"Replace “{}” → “{}” - pick notes to change".format(
        find_text, replace_text
    ),
    multiselect=True,
    button_name="Replace",
)
if not chosen:
    script.exit()

# 4) Apply
changed = []
skipped = []
with revit.Transaction("Replace in Text Notes"):
    for c in chosen:
        try:
            c.tn.SetFormattedText(c.ftext)
            changed.append(c)
        except Exception as err:
            skipped.append((c, str(err)))

# 5) Report
total = sum(c.hits for c in changed)
output.print_md(
    u"### Replaced “{}” → “{}”: {} occurrence(s) in {} note(s)".format(
        find_text, replace_text, total, len(changed)
    )
)
for c in changed:
    output.print_md(
        u"* {} [{}] `{}` → `{}`".format(
            output.linkify(c.tn.Id), view_name(c.tn), shorten(c.before), shorten(c.after)
        )
    )

if skipped:
    output.print_md("\n### Skipped (could not edit - grouped or locked?):")
    for c, msg in skipped:
        output.print_md(u"* {} [{}] {}".format(output.linkify(c.tn.Id), view_name(c.tn), msg))
