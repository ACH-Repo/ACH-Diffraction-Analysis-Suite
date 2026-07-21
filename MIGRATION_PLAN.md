# ACH Diffraction Analysis Suite — migration plan

Draft for review. Nothing has been implemented; the folder is currently empty.

Consolidates five standalone scripts into one installable package with five
commands, a shared core, and per-person configuration. The five existing repos
stay as-is (archive), and code is copied in fresh rather than history-merged.

---

## 1. Why bundle at all

Not aesthetics — the copies have already diverged in ways that change results.

**`cryst_round` exists twice with different signatures and different behaviour:**

| input | plotter | lattice-tables |
|---|---|---|
| `15.4840`\_`0.0020` | `15.484(2)` | *(different signature)* |
| `15.484`\_`0.002`\_`LIMIT_MAX_16` | `15.484(2)` | `None` — value dropped |

`pawley_plotter.py` takes `(mean_err)`; `cell_param_tables.py` takes `(parm, mean_err)`
and returns `None` for TOPAS `LIMIT_MAX` annotations, silently dropping the parameter
from the table. Same name, same crystallographic job, two answers.

**The reflection trio is duplicated and already drifting.** `parse_reflections`,
`simulate_reflections` and `resolve_reflection_cif` now exist in both Quickplot and
Plotter. The Plotter copy has a negative-N fix that the Quickplot copy does not
(`-r "(a,-3)"` in Quickplot slices off the *weakest* reflections instead of taking
the top 3). This duplication is two days old and already inconsistent.

**CIF location is handled three different ways:**

| script | mechanism |
|---|---|
| `pawley_prefit.py` | `os.environ.get('CIF_LOC', default)` + `--cif-loc` flag |
| `run_pawley_wizard.py` | hardcoded `SETTINGS['cif_dir_path']` |
| `pawley_plotter.py` | hardcoded `settings['cif_dir_path']` |

Prefit already solved it. The others didn't get the fix. That is the whole argument
in one table.

---

## 2. Target layout

```
ACH-Diffraction-Analysis-Suite/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/achdiff/
│   ├── __init__.py
│   ├── config.py            # layered config, profile storage
│   ├── identity.py          # who is running this
│   ├── core/
│   │   ├── rounding.py      # cryst_round — ONE copy
│   │   ├── spacegroups.py   # sgs_HM (230), _hm_aliases, resolve_sg
│   │   ├── topas.py         # .out parsing, comment stripping, quality factors
│   │   ├── cif.py           # CIF resolution + pymatgen reflection simulation
│   │   └── xy.py            # two-column data loading
│   └── tools/
│       ├── plotter.py       # was pawley_plotter.py
│       ├── wizard.py        # was run_pawley_wizard.py
│       ├── quickplot.py     # was pxrd_quickplot.py
│       ├── prefit.py        # was pawley_prefit.py
│       └── tables.py        # was cell_param_tables.py
├── examples/                # merged from the five repos
└── tests/
```

`src/` layout (not a flat package) so tests run against the installed package, not
the working copy — that catches "works on my machine, missing from the wheel" errors.

---

## 3. Commands — existing names preserved

Console entry points replace the hand-written `.cmd` shims currently documented in
every README. Same commands your users already type; the shims stop being your
problem because pip generates real executables on `PATH`.

```toml
[project.scripts]
pp  = "achdiff.tools.plotter:main"     # was pp.cmd
rp  = "achdiff.tools.wizard:main"      # was rp.cmd
pxp = "achdiff.tools.quickplot:main"   # was pxp.cmd
ppf = "achdiff.tools.prefit:main"      # was ppf.cmd
pf  = "achdiff.tools.tables:main"      # was pf.cmd
```

`specac` (VT-IR wizard) is deliberately excluded — IR spectroscopy is neither PXRD
nor TOPAS. See §8.

---

## 4. Identity: who is running this

Everyone shares one Windows login, so `%APPDATA%` separates nobody. Identity must be
explicit. People already carry IDs as sample-name prefixes (`CN-`, `AB-`), pattern
roughly `[A-Z]{2,3}`.

### The collision problem

A naive `^[A-Z]{2,3}-` match is unsafe on this lab's own data. Tested against
realistic filenames:

```
CN-sample1_pawley_01_X_Yobs.txt   ->  CN    correct
CN-ZIF-62-quenched_...            ->  CN    correct
ZIF-4_pawley_01_X_Yobs.txt        ->  ZIF   FALSE POSITIVE
ZIF-zni_pawley_01.out             ->  ZIF   FALSE POSITIVE
MOF-5_ambient.xy                  ->  MOF   FALSE POSITIVE
MIL-101_run.xy                    ->  MIL   FALSE POSITIVE
```

6 false positives in 16 names, and every one is a material class — ZIF-4, ZIF-62 and
ZIF-zni are in the wizard's own `trusted_params`. Naive inference would misread your
real data constantly.

### The fix: infer only known IDs

Inference matches the prefix against the **registered profile roster**, never against
an open-ended pattern. `ZIF` is only ever a person if someone deliberately registered
`ZIF` as their ID.

Resolution order, first hit wins:

```
1.  -u CN                     explicit flag        (verified free on all five scripts)
2.  ACH_USER=CN               environment variable
3.  filename prefix           ONLY if it matches a registered profile
4.  [defaults]                no profile
```

Registration is explicit and one-off:

```
pp -u CN --save-profile       registers CN, stores current settings
achdiff profile list          show the roster
```

An unregistered prefix is never silently adopted. Worst case the tool uses
`[defaults]` and prints one line saying so — never picks the wrong person's CIF folder.

---

## 5. Configuration

### Location

`%APPDATA%\ach-diffraction\config.toml` via `platformdirs`.

Outside `site-packages`, so `pip install --upgrade` cannot touch it — that is the
"updates never overwrite my config" requirement, solved structurally rather than by
convention. Shared Windows login means one file holds the whole roster, which is what
you want: profiles are keyed by person ID inside it.

### Shape

```toml
[defaults]
cif_loc = 'D:\Workfolder\Shared\CIF_LOC'

[profiles.CN]
cif_loc = 'D:\Workfolder\Nelle\CIF_LOC'
qall    = true                       # pp shows all three quality factors

[profiles.AB]
cif_loc = 'D:\Workfolder\Bauer\CIF_LOC'
```

### Precedence

```
CLI flag  >  env var  >  [profiles.<ID>]  >  [defaults]  >  built-in
```

### Settings, not injected flags

Profiles store **settings**, not command-line strings. `qall = true` sets the default
value the script reads; `--qall` on the CLI overrides it.

The alternative — injecting `--qall` into `sys.argv` — creates an immediate problem:
`store_true` flags have no negation, so a user with `--qall` in their profile could
never turn it off for one run without a `--no-qall` counter-flag for every such
option. Settings-not-flags avoids inventing that whole surface.

---

## 6. De-duplication — decisions needed

| # | duplicate | resolution |
|---|---|---|
| 1 | `cryst_round` ×2 | **Needs your call — see below.** Unify on one signature. |
| 2 | reflection trio ×2 | Take the Plotter copy (has the negative-N fix). Retires the open chip. |
| 3 | space-group tables | Plotter's complete 230-entry `sgs_HM` becomes canonical. |
| 4 | `.out` parsing | Plotter's is most developed; wizard/tables adopt it. |

**Open question on `cryst_round`:** the two copies disagree on TOPAS `LIMIT_MAX` /
`LIMIT_MIN` annotations. Plotter strips the annotation and keeps the rounded value;
lattice-tables returns `None`, dropping the parameter from the output table. These
are opposite intentions and I don't know which is correct crystallographically — a
parameter that hit a refinement limit is arguably *suspect* (tables' view) or
*still the best estimate* (plotter's view). Unifying will change one tool's output,
so this needs a decision before I touch it.

The tables copy also has a second behaviour the plotter lacks: `parm in ['chi','rwp','rexp']`
formats quality factors to 2 decimals. That's a caller concern, not a rounding
concern — it moves out of `cryst_round` into the tables tool.

---

## 7. Distribution

**Recommended:** install straight from GitHub, no PyPI account, works today.

```bat
pip install git+https://github.com/ACH-Repo/ACH-Diffraction-Analysis-Suite.git
pip install --upgrade git+https://github.com/ACH-Repo/ACH-Diffraction-Analysis-Suite.git
```

One command updates all five tools on a remote TOPAS PC, versus five copy operations
today. `pipx` is worth considering instead of `pip` — it isolates the tools in their
own venv so a pymatgen upgrade can't break an unrelated Python project on that PC.

PyPI can be added later without changing anything structural; it buys a shorter
command and not needing git on the target machine, at the cost of a permanent public
name and release ceremony. Not needed for a handful of lab PCs.

### Dependencies

| package | needed by |
|---|---|
| numpy, matplotlib | plotter, quickplot, prefit |
| pymatgen | plotter, quickplot, prefit, wizard |
| scipy | prefit only |
| beautifulsoup4 | tables only |
| tkinter | prefit only (stdlib on Windows) |

Proposal: one install with everything. Optional extras (`pip install .[tables]`) add
friction for a five-tool lab suite where the heavy dependency (pymatgen) is needed by
four of five anyway.

---

## 8. Scope boundary

`ACH-VT-IR-Plotter` and `ACH-VT-IR-Wizard` are **excluded**. Variable-temperature IR
is neither diffraction nor TOPAS, shares none of the core (no space groups, no CIFs,
no `.out` files), and would only dilute the package. Flagging because the suite name
says "Diffraction" but you said "all things PXRD/TOPAS" — those two agree, and the
IR pair falls outside both.

---

## 9. Phases

Each phase is independently shippable and verifiable. Stop after any of them.

**Phase 0 — scaffold.** `git init`, `pyproject.toml`, package skeleton. Scripts copied
in *verbatim* except: add `main()` + `__main__` guard to `pawley_plotter.py` and
`cell_param_tables.py` (both currently execute at import — importing
`cell_param_tables` launches its interactive file prompt, which blocks entry points).
*Verify:* all five commands run and produce byte-identical output to the old repos.

**Phase 1 — config + identity.** `config.py`, `identity.py`, `CIF_LOC` as the first
managed setting, wired into all five. Env var honoured everywhere (matching prefit).
*Verify:* config survives a simulated upgrade; unknown prefix never adopts an ID.

**Phase 2 — de-duplicate core.** Move the shared code into `core/`, resolve the
`cryst_round` divergence per §6. *Verify:* golden-output comparison on the examples
from all five repos, before vs after.

**Phase 3 — docs + distribution.** Merged README, install/update instructions,
per-tool docs. Archive notices on the five old repos.

---

## 10. Risks

- **Phase 2 changes output.** Unifying `cryst_round` will change one tool's numbers by
  design. Needs the §6 decision and golden-file comparison.
- **`cell_param_tables.py` is interactive at import.** Its file-selection prompt runs
  on module load; converting to a `main()` is a real edit, not a mechanical wrap.
- **Five READMEs to reconcile.** Substantial content, some overlapping, some stale
  (all reference `.cmd` shims that entry points replace).
- **Old repos become stale installs.** Anyone who cloned them keeps working from
  diverging copies until archived with a pointer (Phase 3).
