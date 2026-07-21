# ACH Diffraction Analysis Suite

PXRD and TOPAS analysis tools for the lab: Pawley fit setup, cell-parameter
prefitting, publication plotting, quick pattern comparison, and lattice-parameter
tables. Five commands, one install.

```bash
pip install git+https://github.com/ACH-Repo/ACH-Diffraction-Analysis-Suite.git
```

| Command | Tool | What it does |
|---|---|---|
| `rp` | wizard | Interactive wizard generating TOPAS Pawley `.inp` files from CIFs |
| `ppf` | prefit | GUI cell-parameter tuning before a fit (sliders per crystal system) |
| `pp` | plotter | Publication plots of a finished Pawley fit |
| `pxp` | quickplot | Quick stacked comparison of raw patterns |
| `pf` | tables | HTML lattice-parameter tables from a batch of `.out` files |

The command names are unchanged from the standalone scripts, so existing habits
and any documentation referring to `rp`, `pp`, `pxp`, `ppf` or `pf` still apply.
The hand-written `.cmd` shims are no longer needed — pip puts real executables on
`PATH`. Delete the old shims to avoid them shadowing the installed commands.

## Updating

```bash
pip install --upgrade git+https://github.com/ACH-Repo/ACH-Diffraction-Analysis-Suite.git
```

One command updates all five tools. Your configuration is **not** touched: it
lives in the user config directory, outside the installed package, so an upgrade
structurally cannot overwrite it.

## Your CIF library, and per-person settings

Everyone shares one Windows login on the TOPAS PCs, so the tools identify people
by **ID**, using the same 2–3 letter prefix already used on sample names
(`CN-sample1.xy`).

### First run: register yourself

```bash
pp -u CN --cif-loc "D:\Workfolder\<you>\CIF_LOC" --save-profile
```

That writes a profile for `CN`. From then on, working in a directory of your own
`CN-` prefixed samples, the tools pick it up automatically:

```
$ pp -s -c
[*] Profile: CN  (from sample-name prefix)
```

### How a tool decides who you are

First match wins:

1. `-u CN` on the command line
2. `ACH_USER=CN` in the environment
3. the sample-name prefix of files in the working directory — **only if that
   prefix is a registered profile**
4. otherwise no profile: `[defaults]` applies

Step 3 is deliberately restricted to registered IDs. The prefix pattern
`[A-Z]{2,3}-` also matches material names this lab works with daily — `ZIF-4`,
`ZIF-62`, `MOF-5`, `MIL-101` — and an unrestricted match would read those as
people. An unregistered prefix is never adopted; the tools fall back to defaults
rather than silently loading someone else's CIF library. The chosen profile and
where it came from are always printed.

### Setting precedence

```
CLI flag  >  environment variable  >  [profiles.<ID>]  >  [defaults]  >  built-in
```

`CIF_LOC` still works as an environment variable, as it always has for `ppf` —
and now the other four tools honour it too.

```bash
set CIF_LOC=D:\Workfolder\<you>\CIF_LOC     # this shell session only
```

### The config file

`%APPDATA%\ach-diffraction\config.toml`, safe to hand-edit:

```toml
[defaults]
cif_loc = 'D:\Workfolder\Shared\CIF_LOC'

[profiles.CN]
cif_loc = 'D:\Workfolder\<you>\CIF_LOC'
qall    = true          # pp shows R_wp, R_exp and chi by default

[profiles.AB]
cif_loc = 'D:\Workfolder\<colleague>\CIF_LOC'
```

Profiles store settings, not command-line flags, so an explicit flag always wins
for a single run. A profile with `qall = true` can still be read normally — the
setting decides the default, the flag decides the invocation.

Set `ACH_CONFIG_DIR` to relocate the whole config (useful for a portable install
or for testing against a throwaway config).

## The tools

### `rp` — Pawley input wizard

Walks through data file, phases, instrument, background, naming, and comments,
then writes a TOPAS `.inp` and optionally launches the refinement.

Background options, in menu order: a zeroed polynomial (6 coefficients, the safe
starting point for any holder), the pre-refined `silicon` and `plastic` holder
presets, and a zeroed polynomial with a coefficient count you type in.

`.brml` inputs auto-detect anode, monochromator, goniometer radius and Soller
angles, deriving a `Full_Axial_Model` line.

### `ppf` — prefit

Loads CIF phases plus an experimental pattern and gives you sliders — restricted
to the parameters the detected crystal system allows — to line simulated peaks up
with observed ones. Useful when the CIF was collected at a different temperature
than the powder data. Prints a ready-to-paste TOPAS macro call.

### `pp` — Pawley plotter

```bash
pp                                  # interactive windows
pp -s -c                            # save SVGs with unit-cell boxes
pp -s -c -x png --qall              # PNGs, all three quality factors
pp -s -m 20,40,10                   # multiply intensity in 2θ ∈ [20°, 40°] by 10
pp -s -r "(ZIF-8,10,magenta)"       # overlay reflections simulated from a CIF
```

Auto-discovers TOPAS output groups in the current directory. `-r` overlays
reflections from phases that are *not* in the fit — the Bragg tick rows come
from TOPAS's own `2Th_Ip` files, so this is the complementary check for whether
an unexplained feature belongs to a suspected impurity.

### `pxp` — quickplot

```bash
pxp -i a.xy b.xy --stack            # stacked comparison
pxp -i *.brml -s -x png             # save without a window
```

Reads `.xy`, `.raw`, `.brml`, `.dat`, PDF-card XML exports. Same `-r` reflection
overlay as `pp`.

### `pf` — lattice-parameter tables

Interactive selection of `.out` files, producing an HTML table of refined cell
parameters with crystallographic rounding.

## Requirements

Python ≥ 3.10. Dependencies install automatically: numpy, matplotlib, pymatgen,
scipy, beautifulsoup4, platformdirs.

## Development install

```bash
git clone https://github.com/ACH-Repo/ACH-Diffraction-Analysis-Suite.git
cd ACH-Diffraction-Analysis-Suite
pip install -e .
python tests/test_config_identity.py
```

## Layout

```
src/achdiff/
├── config.py            # layered settings, profile storage
├── identity.py          # who is running this
├── core/
│   ├── rounding.py      # crystallographic rounding (one copy)
│   └── cif.py           # CIF resolution + reflection simulation
└── tools/               # one module per command
```

`core/` exists because these helpers had drifted apart across the old
repositories — two `cryst_round` implementations disagreed on refinement-limit
annotations, and the reflection parser had a fix in one copy but not the other.
Shared code lives in exactly one place now.

## History

Consolidates five previously separate repositories: `ACH-Pawley-Plotter`,
`ACH-Run-Pawley-Wizard`, `ACH-PXRD-Quickplot`, `ACH-Pawley-Prefit`, and
`ACH-TOPAS-Lattice-Parameter-Tables`. Those remain available as an archive but
receive no further updates. Variable-temperature IR tooling stays separate —
it shares none of this code.
