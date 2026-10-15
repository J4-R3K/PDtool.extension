# -*- coding: utf-8 -*-
"""Worksharing checks before a change.

In a workshared model one element borrowed by another user makes Revit roll back the whole transaction. Check first:

    from pdtool.worksharing import keep_editable

    sheets = keep_editable(doc, sheets, title="Add revision to sheets")
    if sheets is None:
        script.exit()          # the user chose to stop

keep_editable asks once, only when something can't be changed now: go on with the rest, go on and list the others
(with links that select them), or stop. Pattern from guRoo_Py shareUtils_getEditable (Gavin Crump), with the
"changed in the central model" check added (an element updated in central since the last reload can't be edited
either).
"""
from Autodesk.Revit.DB import CheckoutStatus, ElementId, ModelUpdatesStatus, WorksharingUtils

GO_ON = "Go on with the elements that can be changed"
GO_ON_AND_LIST = "Go on, and list the elements left out"
STOP = "Stop, change nothing"


def _id_of(item):
    return item if isinstance(item, ElementId) else item.Id


def block_reason(doc, item):
    """None if the element can be changed now, else the reason in plain words."""
    if not doc.IsWorkshared:
        return None
    element_id = _id_of(item)
    try:
        if WorksharingUtils.GetCheckoutStatus(doc, element_id) == CheckoutStatus.OwnedByOtherUser:
            owner = ""
            try:
                owner = WorksharingUtils.GetWorksharingTooltipInfo(doc, element_id).Owner
            except Exception:
                pass
            return "Borrowed by {}".format(owner) if owner else "Borrowed by another user"

        updates = WorksharingUtils.GetModelUpdatesStatus(doc, element_id)
        if updates == ModelUpdatesStatus.UpdatedInCentral:
            return "Changed in the central model since your last reload: use Reload Latest first"
        if updates == ModelUpdatesStatus.DeletedInCentral:
            return "Deleted from the central model"
    except Exception as ex:
        return "Could not check: {}".format(ex)
    return None


def split_editable(doc, items):
    """(editable, blocked) where blocked is a list of (item, reason)."""
    editable, blocked = [], []
    for item in items:
        reason = block_reason(doc, item)
        if reason is None:
            editable.append(item)
        else:
            blocked.append((item, reason))
    return editable, blocked


def keep_editable(doc, items, title="PDtool"):
    """The items that can be changed now, after asking once if any can't. None if the user chose to stop."""
    items = list(items or [])
    editable, blocked = split_editable(doc, items)
    if not blocked:
        return editable

    from pyrevit import forms, script

    message = "{} of {} elements can't be changed now.".format(len(blocked), len(items))
    reasons = sorted(set(reason for _, reason in blocked))
    choice = forms.alert(message, title=title, sub_msg="\n".join(reasons[:6]),
                         options=[GO_ON, GO_ON_AND_LIST, STOP])
    if choice is None or choice == STOP:
        return None

    if choice == GO_ON_AND_LIST:
        output = script.get_output()
        output.print_md("**{}: elements left out**".format(title))
        rows = [[output.linkify(_id_of(item)), reason] for item, reason in blocked]
        output.print_table(rows, columns=["Element", "Reason"])
    return editable
