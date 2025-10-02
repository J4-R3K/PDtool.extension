# PDtool.extension

Selected pyRevit tools for BIM (Building Information Modelling) workflows.  
**Note:** Third-party and internal-only code is excluded via `.gitignore` (e.g. `EF-Starter.tab`, `lib`, `hooks`, `bin`).

## What’s included
- Tools under `PD.tab` that are explicitly whitelisted in `.gitignore`.
- Each tool lives in:  
  `PD.tab/<Panel>.Panel/<Tool>.pushbutton/` with `script.py` and `bundle.yaml`.

## Install
1. Clone or download this repo.
2. Place the folder under your pyRevit extensions path (or add the path via `pyrevit extensions paths add "<path>"`).
3. Restart Revit; tools appear under the specified tab/panel.

## Development
- Edit `script.py` / `bundle.yaml`; commit as usual.
- To publish a new tool, add a whitelist line to `.gitignore`:
