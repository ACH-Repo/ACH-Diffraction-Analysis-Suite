# ACH Diffraction Analysis Suite

PXRD and TOPAS analysis tools for the lab: Pawley fit setup, cell-parameter
prefitting, publication plotting, quick pattern comparison, and lattice-parameter
tables. Five commands, one install.

```bash
pip install ach-diffraction-suite
```

| Command | Tool | What it does |
|---|---|---|
| `rp` | wizard | Interactive wizard generating TOPAS Pawley `.inp` files from CIFs |
| `pf` | prefit | GUI cell-parameter tuning before a fit (sliders per crystal system) |
| `pp` | plotter | Publication plots of a finished Pawley fit |
| `pq` | quickplot | Quick stacked comparison of raw patterns |
| `pt` | tables | HTML lattice-parameter tables from a batch of `.out` files |
| `achdiff` | — | Manage profiles, config and your own command aliases |

The hand-written `.cmd` shims are no longer needed — pip puts real executables on
`PATH`. Delete the old shims to avoid them shadowing the installed commands.

**Changed in 0.2.0:** prefit moved from `ppf` to `pf`, tables from `pf` to `pt`,
and quickplot from `pxp` to `pq`. Note that `pf` now runs prefit, not tables.
If you prefer different names, see [Custom command names](#custom-command-names).

## Updating

```bash
pip install --upgrade ach-diffraction-suite
```

One command updates all five tools. Your configuration is **not** touched: it
lives in the user config directory, outside the installed package, so an upgrade
structurally cannot overwrite it.

## Custom command names

The five commands above are pip *entry points*: pip writes real executables into
the environment's Scripts directory when the package is installed. Nothing in a
config file can rename them afterwards, because your shell needs an actual file
on `PATH` to find.

A shorthand you choose therefore has to be an additional file, which `achdiff`
creates for you:

```bash
achdiff alias set plot plotter      # now `plot` runs the plotter
achdiff alias set tbl tables
achdiff alias list                  # built-ins plus your own
achdiff alias remove plot
```

Tool names for the second argument: `plotter`, `wizard`, `prefit`, `tables`,
`quickplot`.

Aliases are recorded in your config, so they survive upgrades. A reinstall can
clear the Scripts directory though — `achdiff alias sync` recreates them all.
`achdiff alias list` marks any that have gone missing.

Everyone on a shared machine writes to the same Scripts directory, so aliases
are shared too. Pick names that won't confuse a colleague, and note that
`achdiff` refuses to overwrite a built-in command or any file it did not create.

## Your CIF library, and per-person settings

Everyone shares one Windows login on the TOPAS PCs, so the tools identify people
by **ID**, using the same 2–3 letter prefix already used on sample names
(`CN-sample1.xy`).

### First run: register yourself

```bash
achdiff profile set -u CN cif_loc="D:\Workfolder\<you>\CIF_LOC"
```

That writes a profile for `CN`. Add other settings the same way, either at once
or later — they merge rather than replace:

```bash
achdiff profile set -u CN qall=true      # pp shows all three quality factors
achdiff profile unset -u CN qall         # back to the default
achdiff profile list                     # who is registered, and with what
```

Unknown setting names are rejected rather than stored, so a typo can't sit in
your config being silently ignored. From then on, working in a directory of your own
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

`CIF_LOC` still works as an environment variable, as it always has for prefit —
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

## Trusted starting parameters

A Pawley refinement converges much better when it starts from a cell close to
the truth. Once a fit has converged, register its cell so the wizard seeds the
next one with it:

```bash
achdiff trusted add ZIF-4 --from CN-sample_pawley_01.out -u CN
achdiff trusted list -u CN
```

The values are read straight out of the `.out`, uncertainties and all, so
nothing is retyped. For a multi-phase fit the command lists the phases and asks
which one with `--phase-index`. `achdiff trusted set` takes values by hand when
the `.out` is long gone.

From then on `rp` applies them automatically and says where each came from:

```
[*] Trusted parameters for ZIF-4 (a, b, c from CN-sample_pawley_01.out)
```

**Trusted parameters are per person and are never shared implicitly.** Yours are
a refined result for *your* sample on *your* instrument; inheriting a
colleague's would silently seed a refinement with a cell that was never measured
on your material. Two people can register the same phase name with different
values and neither affects the other. Nothing ships with the package, so a new
user starts with an empty set rather than someone else's numbers.

Sharing is possible, but only as a deliberate act:

```bash
achdiff trusted export -u CN -o cn.toml     # hand the file to a colleague
achdiff trusted import cn.toml -u AB        # refuses to clobber without --force
```

## The tools

### `rp` — Pawley input wizard

Walks through data file, phases, instrument, background, naming, and comments,
then writes a TOPAS `.inp` and optionally launches the refinement.

Background options, in menu order: a zeroed polynomial (6 coefficients, the safe
starting point for any holder), the pre-refined `silicon` and `plastic` holder
presets, and a zeroed polynomial with a coefficient count you type in.

`.brml` inputs auto-detect anode, monochromator, goniometer radius and Soller
angles, deriving a `Full_Axial_Model` line.

### `pf` — prefit

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

### `pq` — quickplot

```bash
pq -i a.xy b.xy --stack             # stacked comparison
pq -i *.brml -s -x png              # save without a window
```

Reads `.xy`, `.raw`, `.brml`, `.dat`, PDF-card XML exports. Same `-r` reflection
overlay as `pp`.

### `pt` — lattice-parameter tables

Interactive selection of `.out` files, producing an HTML table of refined cell
parameters with crystallographic rounding.

The table template and space-group lookup come from `resource.htm`, a real file
shipped with the package rather than a blob compiled into the source. To use
your own:

```bash
pt --resource "D:\path	o\your
esource.htm"
set ACH_RESOURCE_HTM=D:\path	o\your
esource.htm    # or set it once
```

Parsing 900 KB of HTML takes about 1.4 s, so the derived data is cached after
the first run (~19 ms thereafter). The cache key is a hash of the file's
contents, so editing `resource.htm` invalidates it automatically — there is no
regeneration step to forget. `ACH_CACHE_DIR` relocates the cache.

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

Publishing a new version: see [RELEASING.md](RELEASING.md).

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

## Credit

Written by Christian Nelle in the group of Prof. Sebastian Henke, Fakultät für
Chemie und Chemische Biologie, Technische Universität Dortmund.

Released under the MIT licence — see [LICENSE](LICENSE).

## History

Consolidates five previously separate repositories: `ACH-Pawley-Plotter`,
`ACH-Run-Pawley-Wizard`, `ACH-PXRD-Quickplot`, `ACH-Pawley-Prefit`, and
`ACH-TOPAS-Lattice-Parameter-Tables`. Those remain available as an archive but
receive no further updates. Variable-temperature IR tooling stays separate —
it shares none of this code.
