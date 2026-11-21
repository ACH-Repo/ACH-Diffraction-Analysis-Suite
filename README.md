# ACH Diffraction Analysis Suite

PXRD and TOPAS analysis tools for the lab: Pawley fit setup, cell-parameter
prefitting, publication plotting, quick pattern comparison, lattice-parameter
tables, and conversion to plain `.xy`. Six commands, one install.

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
| `conv` | convert | Patterns, and CIFs simulated, to tab-separated `.xy` for Origin or Excel |
| `achdiff` | — | Profiles, plot styles, default flags, aliases, and the misc scripts |

The hand-written `.cmd` shims are no longer needed — pip puts real executables on
`PATH`. Delete the old shims to avoid them shadowing the installed commands.

**Changed in 0.2.0:** prefit moved from `ppf` to `pf`, tables from `pf` to `pt`,
and quickplot from `pxp` to `pq`. Note that `pf` now runs prefit, not tables.
If you prefer different names, see [Custom command names](#custom-command-names).

## Updating

```bash
pip install --upgrade ach-diffraction-suite
```

PyPI is updated less often than GitHub. For the latest version straight from
GitHub — plain pip, no git needed:

```bash
pip install --upgrade https://github.com/ACH-Repo/ACH-Diffraction-Analysis-Suite/archive/refs/heads/main.zip
```

One command updates all six tools. Your configuration is **not** touched: it
lives in the user config directory, outside the installed package, so an upgrade
structurally cannot overwrite it.

## Custom command names

The six commands above are pip *entry points*: pip writes real executables into
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
`quickplot`, `convert`.

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

If you have no CIF library and don't need one, register the ID on its own:

```bash
achdiff profile set -u CN
```

A profile decides which CIF library applies, which style sheet applies, and
whether the tools recognise your filenames at all. Only the last two need a
profile to exist, so an empty one is a perfectly good profile.

### One shared library for everyone

`--global` writes `[defaults]` instead of one person's profile, so a machine can
be set up once and used without anyone passing `-u`:

```bash
achdiff profile set --global cif_loc="D:\Workfolder\Shared\CIF_LOC"
achdiff profile unset --global cif_loc     # back to the built-in
```

Profiles still win over it, so someone with their own library keeps it and
everyone else falls back to the shared one.


```
$ pp -s -c
[*] Profile: CN  (from sample-name prefix)
```

### How a tool decides who you are

First match wins:

1. `-u CN` on the command line
2. `ACH_USER=CN` in the environment
3. the sample-name prefix of files in the working directory — `CN-sample1.xy`
   or `CN_sample1.xy`, either separator — **only if that prefix is a registered
   profile** (`achdiff profile set -u CN ...`; writing a style sheet does not
   register one)
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
cif_loc   = 'D:\Workfolder\<you>\CIF_LOC'
topas_exe = 'C:\TOPAS7\tc.exe'
qall      = true        # pp shows R_wp, R_exp and chi by default

[profiles.AB]
cif_loc = 'D:\Workfolder\<colleague>\CIF_LOC'
```

An explicit flag always wins for a single run: the setting decides the default,
the flag decides the invocation. A profile can also hold default *flags* per tool
— see [Flags every run starts with](#flags-every-run-starts-with).

Set `ACH_CONFIG_DIR` to relocate the whole config (useful for a portable install
or for testing against a throwaway config).

## Your own plot style

Every group has house rules for a figure — what the y axis is called, whether
the legend says "Reflections" or "Bragg reflections", whether the R-factor sits
in the plot or in the caption. `pp` and `pq` read those from a style sheet of
your own, picked by the same `-u` that picks your CIF library — and so does the
[`heatmap`](#heatmap--a-pattern-series-as-a-heat-map) misc script, with sheets
of its own (`achdiff style init heatmap`).

Each plotter has its own sheets. A Pawley fit and a stack of patterns are
different figures, and a column-width `pp` sheet has no business shrinking every
`pq` stack too — so every `achdiff style` command names the plotter it is for:

```bash
achdiff style init pp -u CN     # write a commented file listing every setting
achdiff style edit pp -u CN     # open it
pp -s                           # every pp plot from now on is in your style
achdiff style init pq -u CN     # the same, separately, for pq
```

Sent one by a colleague instead of writing your own? Install it in one step —
it is checked before it is copied, so a typo in it is caught now rather than the
next time you plot:

```bash
achdiff style install pp CN.toml -u CN
achdiff style list                    # confirm it landed
```

`init` writes `%APPDATA%\ach-diffraction\styles\pp\CN.toml` with every setting at
the value currently in effect, each one commented out and explained. Uncomment
what you want to own; anything left commented keeps following the built-in, so
a later release can improve a default you never asked about. Delete the `#` as
well as changing the value: a changed value still behind its `#` does nothing,
and the plotters point it out when they run — as they do a misspelt key
(`cmap: did you mean colormap?`) and text without its quotes.

```toml
[axes]
y_label   = 'Intensity / arb. units'
ticks_top = true

[legend]
observed_label   = 'observed'
calculated_label = 'calculated'
difference_label = 'difference'
bragg_label      = 'Bragg reflections'
legend_frame     = false

[annotations]
show_quality = false          # R_wp goes in the caption instead
```

Style sheets live outside the package, so `pip install --upgrade` never touches
them, and nothing personal has to be committed anywhere to make a person's plots
come out right on their own machine.

Settings that mean the same thing are spelled the same in both plotters —
`figsize`, `axis_label_size`, `x_tick_step`, `band_color` — but each sheet only
sets its own plotter's value. A `pq` setting written into a `pp` sheet is
reported as belonging to `pq`, not applied.

**Changed in 0.14.0:** sheets used to sit directly in `styles\`, and were all
for `pp`. The first run after upgrading moves them into `styles\pp\` and says so.

### Layering

```
--style FILE  >  ACH_STYLE_PP  >  styles/pp/<ID>.toml  >  styles/pp/default.toml  >  built-in
```

and the same for `pq` with `ACH_STYLE_PQ` and `styles/pq/`, and for `heatmap`
with `ACH_STYLE_HEATMAP` and `styles/heatmap/`. The older `ACH_STYLE` still
works, and still means `pp`.

`styles/pp/default.toml` sets a whole machine's `pp` look for everyone without
one of their own. `--style` layers a one-off on top without editing yours:

```bash
pp -s --style narrow-column          # same look, journal column width
pp --gif --gif-delay 250             # animate a whole sequential run
```

A bare name is looked up in that plotter's styles directory, so one-off styles
can live beside the personal ones. A path is used as given.

Both plotters print which style sheets they used, next to the profile line.

### Naming the Bragg rows

`bragg_label` gives every tick row one fixed name. Left empty, each row names
itself after its own space group and substance, which is the built-in behaviour.

A fixed name collapses to a single legend entry while the rows are drawn alike.
The moment two rows differ in colour it stops collapsing them and appends each
phase instead — `Bragg reflections (ZIF-4)`, `Bragg reflections (ZIF-zni)` —
because two colours in a plot need two entries in the key.

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

### Replacing a set as your fits improve

Re-register the phase. No flag, no need to remove it first — the new cell simply
replaces the old one, and the command shows what it changed:

```
$ achdiff trusted add ZIF-4 --from CN-better_pawley_01.out
[+] ZIF-4 updated for CN:
      a   = 15.484356`_0.000738   (was 15.475318`_0.000986)
      b   = 15.511304`_0.000704   (was 15.513932`_0.000957)
      c   = 18.103277`_0.000892   (unchanged)
    replaces the set from CN-first_pawley_01.out on 2026-07-22
```

A cell is replaced as a whole set, never merged parameter by parameter — mixing
`a` from one refinement with `c` from another describes a cell that was never
observed. If the new set has fewer parameters than the old one, the dropped ones
are listed so the loss is visible rather than silent.

`achdiff trusted import` is the exception: it *does* refuse to overwrite without
`--force`, because it can replace many phases at once from a file you did not
write. A single `add` from a `.out` you just chose is a different risk.

Sharing is possible, but only as a deliberate act:

```bash
achdiff trusted export -u CN -o cn.toml     # hand the file to a colleague
achdiff trusted import cn.toml -u AB        # refuses to clobber without --force
```

## The tools

### `rp` — Pawley input wizard, and refinement runner

```bash
rp                     # interactive wizard: build a new .inp
rp myfit.inp           # run TOPAS on an existing .inp and exit
```

Walks through data file, phases, instrument, background, naming, and comments,
then writes a TOPAS `.inp` and optionally launches the refinement.

Given a filename it skips the wizard entirely and just runs the refinement —
for `.inp` files you have edited by hand, so you never type the full path to
`tc.exe`. The engine runs with its working directory set to the `.inp`'s own
folder, so relative `Out_X_Yobs(...)` paths land beside it rather than wherever
you happened to be standing. TOPAS's exit code is reported and passed through.

The engine location is a setting, not a hardcoded path:

```bash
achdiff profile set -u CN topas_exe="C:\TOPAS7\tc.exe"
set TOPAS_EXE=C:\TOPAS6	c.exe        # this shell only
rp myfit.inp --topas "C:\TOPAS7\tc.exe"
```

It defaults to `C:\TOPAS7\tc.exe`, which is what the original script assumed.

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

### What `pp` and `pq` share

The two plotters grew up separately and had drifted — the same flag meant
different things, or was spelled differently. What they have in common now works
the same way in both, from one implementation in `core/overlays.py` and
`document.py`:

| Flag | What it does |
|---|---|
| `-m a,b,N ...` | Multiply the intensity in 2θ ∈ [a, b] by N. Several ranges after one `-m`; `,b,N` and `a,,N` run to the edge of the data; a fourth field colours the markers. The range is marked with dashed lines and an `x N` label. |
| `-b x[,w[,c]] ...` | Shade a vertical strip behind everything at 2θ = x — for a small feature in the difference curve, or a weak peak, that should jump out when you look at the plot again. Width `w` in degrees, or `2%` of the plot width; 1 % and light grey by default (`band_width`, `band_color` in your style sheet). |
| `-t [TEXT]` | A title. `-t` alone uses the fit name (`pp`) or the trace names (`pq`). |
| `--size W H`, `--dpi N` | Figure size and raster resolution, over the style sheet. |
| `-s`, `-x FMT`, `-v` | Save silently, in this format; talk more while doing it. |
| `-r "(name,N,colour)"` | Reflections simulated from a CIF, as dotted lines. |
| `--style FILE`, `-u ID` | Style sheet and profile. |
| `-d` | Record the command — see below. |

`pq` scales each trace from its own baseline, so a multiplied trace grows from
its own place in the stack. Its old `-m "((20,40,10,blue))"` form still works.

`-b` and `-m` both mark a range, but only `-b` shades: if both did, "this was
scaled" and "look here" would read the same.

```bash
pp -s -m 20,40,10 45,,5             # two ranges, the second to the end of the data
pp -s -b 23.4 31.2                  # two 1 % grey strips
pp -s -b 23.4,0.3 31.2,2%,lightblue # set width and colour per strip
```

#### Keeping the command: `-d`

Every tool — `pp`, `pq`, `pf`, `pt`, `rp`, `conv` — takes `-d`. It writes the
command you just ran to `run<N>.bat` in the current directory, or `run<N>_s.bat`
when it saves its plot silently (`-s`, or `pp --gif`). Double-click it to draw
the plot again; there is no need to keep the image.

```bash
pp -s -c --qall -m 20,40,10 -d      # plot, and write run1_s.bat
pq -i a.xy b.xy -b 12.2 -d          # interactive, so run2.bat
```

- One counter covers both kinds, one past the highest number already there, so
  a number is never reused and never names two files.
- `-d` itself is left out of the file, or running it would write another.
- Arguments are quoted and escaped for `cmd` — brackets, `%`, umlauts and 2θ in
  a title all come back exactly as typed.
- The file changes to its own directory first, so it redraws the same plot
  wherever it is started from, and pauses if the command fails so the reason
  stays on screen.

What goes in the file is what *ran*, not only what you typed: your
[default flags](#flags-every-run-starts-with) written out in full, then
`--no-defaults` so they are not added a second time, then `-u ID` when the
profile came from `set ACH_USER` or a filename rather than the command line. A
double-clicked file opens a fresh window without your `ACH_USER`, and without the
pin it would draw with nobody's settings. So an old `run3.bat` redraws the same
plot after you change your defaults or your session.

```
pp -c --qall -s -m 45,,5 --no-defaults -u CN
```

What it still reads at run time is the *content* of that profile — its style
sheet and CIF library. Change your style sheet and an old run file redraws in the
new look.

#### Flags every run starts with

Put flags you always want in your profile, per tool:

```bash
achdiff flags set -u CN pp -d -c --qall   # every pp run documents itself, with cell boxes
achdiff flags set -u CN pq -d
achdiff flags set --global pq -d          # for everyone without their own
achdiff flags show -u CN
achdiff flags clear -u CN pp
```

- They go in front of what you type, so a flag you type wins: `pp -x png` over
  a default `-x svg`, a typed `-m` instead of a default one. The tool prints
  which defaults it used and which you replaced.
- `--no-defaults` runs without them, for the one run where a default is wrong.
  There is no way to switch off a single default flag — `-c` has no `--no-c` —
  so it is all of them or none.
- They are checked with the tool's own parser when you set them, so a typo is
  refused then, not on every run afterwards. `-u` can't be a default (it picks
  the profile the defaults come from), and must come before the tool name.
- Nor can `conv -f`: overwriting files has to be typed on the run that means
  it. One already in a config — edited in by hand, or saved by 0.15.0 — is
  ignored along with the rest of that tool's defaults, and the run says so.
- A profile's own list replaces `--global`'s rather than adding to it;
  `achdiff flags set -u CN pq` with nothing after it opts CN out entirely.
- `qall = true` from before still works, and counts as a default `--qall`.

### `pp` — Pawley plotter

```bash
pp                                  # interactive windows
pp -s -c                            # save SVGs with unit-cell boxes
pp -s -c -x png --qall              # PNGs, all three quality factors
pp -s -m 20,40,10                   # multiply intensity in 2θ ∈ [20°, 40°] by 10
pp -s -b 23.4                       # shade a strip at 23.4° to find a feature again
pp -s -r "(ZIF-8,10,magenta)"       # overlay reflections simulated from a CIF
pp -s --style narrow-column.toml    # one-off look on top of your own style
```

Auto-discovers TOPAS output groups in the current directory. `-r` overlays
reflections from phases that are *not* in the fit — the Bragg tick rows come
from TOPAS's own `2Th_Ip` files, so this is the complementary check for whether
an unexplained feature belongs to a suspected impurity.

#### Animating a sequential run

A variable-temperature or time-resolved experiment leaves a directory of fits
that only mean anything next to each other. `--gif` turns the directory into two
animations and a trend plot for a talk:

```bash
pp --gif                    # <dir>-fits.gif, -cell.gif, -steps.gif, -trend.svg
pp --gif --gif-delay 400    # slower
pp --gif --gif-absolute     # cell bars as values, not as changes
```

`<dir>-fits.gif` is every fit in numerical order (`scan_2` before `scan_10`),
**on one common intensity scale** — a peak that halves and an axis that halves
with it look identical, so nothing is allowed to rescale between frames. The
Bragg rows and the difference band hold their height throughout too.

`<dir>-cell.gif` is the refined cell as bars that move with it: lengths on the
left axis, angles on the right, a dashed rule between them, the refined value
and its uncertainty printed above every bar and the esd drawn as an error bar.
Multi-phase fits get one file per phase.

By default the bars show the **change since the first fit**, not the value.
A cell edge moves in the third decimal while a and c can sit 3 Å apart, so an
axis wide enough to hold both is about a hundred times too coarse to show either
one move — the absolute view is a row of bars that never visibly change.
`--gif-absolute` gives that view if you want it; the printed numbers are the
same either way.

Frame resolution is the `gif_dpi` style setting (150 by default), kept apart from
`dpi` so print output stays print quality without making a GIF nobody can email.

#### The step chart

`<dir>-steps.gif` lays the run out along its own time axis, one fit at a time,
like a trade log with its running average:

- **bars** are the change in each cell parameter since the previous fit, in
  percent — vermillion where it shrank, green where it grew (a colour pair that
  stays distinct under colour-vision deficiencies), with propagated errors;
- **the black line** is the rolling mean of those bars (`--gif-rolling N`,
  default 5, `0` for none): flat means a steady rate, drifting means the rate is
  changing — softening or stiffening;
- **the blue line** on the right axis is the parameter relative to the first
  fit, dashed with open markers after a turning point.

One panel per cell parameter, stacked. Single fits that stand out show up as one
tall bar followed by one that undoes it, which a smooth trend curve hides.

The rolling mean is only drawn once a full window of steps exists, and never
across a turning point: averaging compression into decompression, or labelling
the mean of two steps "rolling mean of 5", would both misdescribe it. A step many
times larger than the rest — a reversible return often recovers the whole
compression at once — is drawn to the edge of the axis and labelled with its
real value, rather than flattening every other bar. Bars stand in measurement
order rather than at their x value, so a run that comes back down still reads
left to right in time; the tick labels carry the x values. As with the trend
plot, per-step bars are only comparable when the steps are evenly spaced.

#### The trend plot, and getting the order and the x axis right

`--gif` also writes `<dir>-trend.svg`: every cell parameter **relative to the
first fit** (a/a₀, V/V₀, …), as a static curve. That is the plot that shows
non-linear behaviour — curvature belongs to the whole run, and an animation
shows one frame at a time. Uncertainties are propagated through the ratio, and
the first point is exactly 1 with no error, since it is 1 by definition. Points
are joined in measurement order, so a compression-then-decompression run draws
its loop. Nothing is fitted.

Two things decide whether that curve means anything, and both are yours to get
right — neither is checked:

```bash
pp --gif --sort-key "_([0-9.]+)GPa"                        # the order
pp --gif --x-values "0,0.5,1:2:0.5,3,4.5,6,8,10" --x-label "p / GPa"   # the x axis
```

**Order.** Fits play in natural order unless `--sort-key` or `--order-name` says
otherwise, and natural order gets decimals wrong: it splits `0.5GPa` at the point
and puts it *before* `0GPa`. `--sort-key` (also spelt `--order-regex`) is a
regular expression whose capture groups are the sort key, compared as numbers
where they are numbers (a decimal comma is fine). `--order-name` says the same
with a wildcard template, for anyone who doesn't write regular expressions:

```bash
pp --gif --order-name "*_#GPa*"       # by the pressure in the name
pp --gif --order-name "#_*"           # by a leading run number
```

In a template `*` is any text, `?` one character and `#` a number; it covers the
whole fit name, as `dir *.out` does. A template that fits a name in two ways is
refused, naming both readings. Several groups or `#`s sort left to right. Fits
either doesn't match are kept, named, and put last; `--x-map-template` pre-fills
x values from the first number either reads.

**x values.** Without `--x-values` the x axis is the fit number, which assumes
evenly spaced steps. That's usually true, but when it isn't the curve can bend
the **wrong way** — measure at 0.5 GPa steps early and 2 GPa steps late, and a
compression that softens looks like one that accelerates. Give a list, a range
`start:stop:step` (stop included), or both. There must be exactly one value per
fit, in the order the fits are drawn; if not, `pp` refuses before rendering
anything and lists the fits in the order it would have used.

#### Runs that come back down: `--x-map`

A reversibility run goes up to pressure and returns over the same values. No
sort order recovers that — sorted by pressure, the outbound and return fits
interleave — and a value list is easy to miscount across forty fits. So write
the order and the values to a file instead:

```bash
pp --x-map-template run.txt --sort-key "_([0-9.]+)GPa"    # every fit, x pre-filled
# ...edit run.txt: put the lines in measurement order, check the values...
pp --gif --x-map run.txt --x-label "p / GPa"
```

The file is the timeline. One fit per line, x value last:

```text
# compression
CN-cubic_up_0GPa_pawley_01      0
CN-cubic_up_10GPa_pawley_01     10
# back down
CN-cubic_down_5GPa_pawley_01    5
CN-cubic_down_0GPa_pawley_01    0
```

Fits play in the order listed and only listed fits play, so delete or `#` a line
to leave a bad fit out. The same x may appear any number of times. Names may
contain spaces; `#` starts a comment; a spreadsheet export with `;` and a decimal
comma reads fine. Anything wrong — a name that isn't a fit here, a fit listed
twice, a value that isn't a number — is refused with its line number before
anything is drawn. `--x-map` replaces `--sort-key` and `--x-values` and can't be
combined with them.

In the trend plot the legs are drawn differently: **filled and solid while x
increases, open and dashed while it decreases.** A reversible change puts the
return points exactly on top of the outbound ones, so without that distinction
the return leg would disappear in exactly the case you are trying to show.

#### Animated SVG

```bash
pp --gif --gif-format svg        # or gif,svg for both
```

One self-contained SVG, animated with SMIL — no scripts, plays in any browser,
stays sharp at any size and isn't limited to 256 colours.

**It will not animate in PowerPoint**, which does not play SVG animation. The
file is built so that anything drawing it without running the animation shows
the first frame rather than every frame stacked — but for slides, use GIF.

Fit animations are large as SVG: every observed point is its own element, so
expect a few hundred KB per frame (a 10-fit run with ~6,000 points per pattern
is about 6 MB). The file is already stripped of styling that duplicates what it
points to, which is exact; coordinate rounding would shave off a little more
but moves antialiased edges, so it isn't done.

### `pq` — quickplot

```bash
pq -i a.xy b.xy --stack             # stacked comparison
pq -i *.brml -s -x png              # save without a window
pq -i a.xy b.xy -m 30,,4 -b 12.2    # scale the high-angle end, mark a peak
pq -i a.xy b.xy c.cif --labels "as made" _ --colors k _ tab:red
```

Reads `.xy`, `.raw`, `.brml`, `.dat`, PDF-card XML exports. `--labels` and
`--colors` go in input order, with `_` keeping a trace's default; `--order`
restacks the traces afterwards and they stay attached to their files.

**Changed in 0.14.0:** the `OVERRIDES` block — copy `quickplot.py` into a
project folder and edit it — is gone. It stopped working when the suite became a
package, and `-d` keeps a per-folder recipe without copying any code. Everything
it could set is a flag; the look is a `pq` style sheet.

Bruker `.raw` files are decoded natively — no TOPAS conversion step, so plotting
works on a machine without a TOPAS licence. Two generations are covered:

- **RAW1.01**, verified against PowDLL's RIET7 export: identical 2θ grid,
  identical intensities.
- **RAW4.00** (DIFFRAC.SUITE, and what `BrmlToV4Converter` writes from a
  `.brml`), verified against 37 lab files that have an independent copy of the
  same scan beside them — four `.brml` originals and 33 `.xy`/`.dat` exports.
  Every intensity matches exactly, and 2θ agrees within each reference's own
  rounding.

For RAW4 the 2θ axis is read from the scan's own `2Theta` axis record. A scan
that doesn't step in 2θ is refused rather than drawn on the wrong axis. Every
RAW4 file checked so far was a single-range "Locked Coupled" scan from one
converter; other scan types are read with a warning that they haven't been
checked against a reference.

RAW2/RAW3 and the old DIFFRAC-AT formats are not covered and still need PowDLL
or TOPAS; they raise a message saying so rather than plotting nonsense.

### `conv` — patterns to `.xy`

For plotting in Origin, Excel or anything else that wants plain columns:

```bash
conv                          # every .brml, .raw, .dat and .cif in this folder
conv -i *.raw                 # just these; the wildcard works in cmd too
conv -i a.brml b.dat -o xy    # into a subfolder
conv -i ZIF-4 -g 3,60,0.01    # a CIF from your library, on a finer grid
```

Each file becomes `<name>.xy`: 2θ, a tab, the intensity, one point per line, no
header. The tab is what makes Excel and Origin split a pasted block into two
columns; TOPAS and `pq` read it like any other whitespace. For a measured file
the numbers are the ones `pq` plots — both read through the same code — with at
most six decimals, so `3.0205` rather than `3.0205000000000002`.

A **CIF** is simulated the way `pq` simulates one: Cu Kα1, each reflection a
Lorentzian of 0.1° FWHM, scaled to a maximum of 1. The grid is 5–50° 2θ in steps
of 0.02° unless `-g START,STOP,STEP` says otherwise, and an empty slot keeps its
default as in `-m`: `-g ,60,` runs to 60°. A CIF that is not in the folder is
looked for in your CIF library, as with `pq -i`. When a file has no displacement
parameters, the run says the high-angle intensities are overestimated — nothing
in the `.xy` would.

- An existing `.xy` is left alone, and the run says so; `-f` overwrites it. It
  may be an export from another program, and the only copy. `-f` has to be
  typed each time: it cannot be one of your default flags.
- When two files share a name (`a.brml`, `a.raw`), the `.brml` is converted,
  then the `.raw`, then the `.dat` — whose header rounds 2θ to three decimals —
  and a CIF last: a measurement always wins over a simulation of the same name.
- `.xy`, `.txt` and `.csv` are converted only when named with `-i`: a fit folder
  is full of `.txt` that are not patterns. PDF cards are not read.
- The `.xy` files land beside the originals, so a bare `pq` in the same folder
  draws each pattern twice. `-o xy` keeps them apart.

### `pt` — lattice-parameter tables

Interactive selection of `.out` files, producing an HTML table of refined cell
parameters with crystallographic rounding.

A multi-phase refinement gets one column per phase. The filename stays the
heading and the phase is a suffix: `OJ-9_cryst.out (ZIF-62)`. The suffix comes
from `phase_name`, else from the wizard's `Selected phases:` header (matched by
space group, not by position), else from the space group itself. Since one fit
can contain the same space group — or the same name — more than once, anything
that repeats gets a running index from zero: `(SG 61 #0)`, `(SG 61 #1)`.
Single-phase files are headed with the filename alone, as before. Fit-quality
factors describe the whole refinement, so they repeat across a file's columns.

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

## Misc scripts

Some analyses are too specific to be a tool — one comparison for one paper, one
figure for one talk — but come back a year later as *"we did this before, do we
still have it?"*. They are kept here:

```bash
achdiff misc                          # what there is, and what each was for
achdiff misc show cell_drift          # what one does, in full
achdiff misc run cell_drift           # run it; with no arguments it asks
achdiff misc copy cell_drift          # a copy in this folder, to edit by hand
```

Two ship with the package: [`cell_drift`](#cell_drift--mixture-fits-against-pure-phase-fits)
compares mixture fits with pure-phase fits, and [`heatmap`](#heatmap--a-pattern-series-as-a-heat-map)
draws a pressure or temperature series as a heat map.

Run with no arguments, a script explains itself and asks for what it needs —
suggesting answers from the files in the folder — then prints the command that
would have skipped the questions. `-d` records that command like any tool's.

```
Which are the single-phase (pure) fits? [2]
Which are the mixture fits? [1]
Save the figure and a CSV instead of opening a window? (y/N) y

[*] Next time, skip the questions:
      achdiff misc run cell_drift --pure sample-B-cryst.out --mix sample-A-cryst.out -s
```

**`achdiff misc copy`** puts the script in the working folder. Edit it freely and
run it with `python cell_drift.py`; it keeps working there, and on any machine
with the suite installed, because a misc script imports from the suite only
through `achdiff.misc.kit` — a short list of names the suite promises to keep —
and only absolutely.

**A lab folder.** Scripts ship with the package, and a lab can keep its own
beside them without waiting for a release:

```bash
achdiff profile set --global misc_dir="D:\Workfolder\Shared\misc"
```

Any `.py` file there with a docstring and a `main()` is listed and runnable; one
with a packaged script's name replaces it. The first line of the docstring is
what `achdiff misc` lists, and an optional `ABOUT = {'for': ..., 'author': ...,
'written': ...}` says what it was written for — which is what someone searching
for "the thing we did for that paper" will recognise. `cell_drift.py` is the
worked example of the shape.

### `cell_drift` — mixture fits against pure-phase fits

A multi-phase Pawley fit of a mixture refines every cell at once, and each can
settle somewhere other than where the same phase refines on its own. This puts
each phase of a mixture fit next to a single-phase fit of the pure substance —
both from measured patterns, not simulated from a CIF:

```bash
achdiff misc run cell_drift --pure ZIF-4_pure.out ZIF-zni_pure.out --mix mix_50-50.out mix_25-75.out
```

```
  ZIF-4 (61)  vs  sample-B-cryst.out   [matched by name]
                      pure         mixture           delta   delta %  delta/esd
    a            15.517(2)     15.4753(10)       -0.041(2)    -0.267      -18.6 *
    b          15.4964(18)     15.5139(10)        0.018(2)    +0.113       +8.5 *
    c            18.036(2)     18.0750(13)        0.039(3)    +0.217      +14.2 *
    V           4336.8(10)       4339.5(5)         2.7(11)    +0.063       +2.5
```

- Phases are matched by the names `rp` writes into every `.out`. Where one side
  has no name, a space group only one pure fit has will do; two *differently*
  named phases are never matched on space group alone. `NAME=file.out` names a
  pure fit yourself.
- `delta/esd` uses the two esds combined, and is starred from 3 up. TOPAS esds
  tend to be too small, so read a star as "worth a look", not as proof.
- Several mixtures give one bar each per parameter in the figure; `-s` saves the
  figure and the table as CSV.

### `heatmap` — a pattern series as a heat map

Patterns measured along a series — pressure steps in a gas cell, a temperature
ramp — drawn as one image: 2θ across, the series value up, intensity as colour.
It is the figure of Mg₂(dobdc) from 1 to 4000 bar in Fig. 2 of
*J. Am. Chem. Soc.* 2025, **147**, 46075, and draws that look by default. A peak
that stays put is a vertical line, a peak that shifts bends, and a phase
transition ends lines and starts others.

```bash
achdiff misc run heatmap                                    # in a folder of patterns: asks
achdiff misc run heatmap -i *.xy --range 1.5 12 -s          # 2theta data
achdiff misc run heatmap -i *.xy --x-data q -s              # Q data, in 1/angstrom
```

- **The x axis** is what the files hold: 2θ in degrees, unless `--x-data q`
  (Å⁻¹) or `--x-data q-nm` (nm⁻¹) says otherwise — or the files' own header does,
  as pyFAI and DIOPTAS write one (`q_A^-1`, `Wavelength: …`). When nothing says,
  the run prints that it took the files as 2θ. `--x-axis` shows another quantity,
  converting between 2θ and Q with `--wavelength` in Å (or the header's), and the
  converted patterns are put back on an even grid; `--x-label` labels anything
  else. `--range` is in the units of the axis.
- **Nothing is written inside the plot** unless `--label "Mg$_2$(dobdc)"` asks
  for it, in the top right corner as in the paper.
- **Your own look** — ticks, fonts, sizes, the default colours — goes in a
  heatmap style sheet, as for [`pp` and `pq`](#your-own-plot-style):

  ```bash
  achdiff style init heatmap -u CN      # every setting, commented out, explained
  achdiff style edit heatmap -u CN
  ```

  ```toml
  [axes]
  tick_direction  = 'in'      # in, out or inout
  tick_label_size = 6         # points
  axis_label_size = 7
  ticks_top       = true      # mirror the ticks onto the top and right edges
  ticks_right     = true

  [figure]
  font    = 'Helvetica'
  figsize = [3.3, 1.3]
  ```

  The keys `pp` and `pq` have (`tick_direction`, `tick_label_size`,
  `axis_label_size`, `ticks_top`, `x_tick_step`, `figsize`, `dpi`, …) are spelled
  the same; the heat map adds `ticks_right`, `tick_width`, `frame_width`,
  `minor_ticks`, `font`, `label_size`, and in `[colours]` its default
  `colormap`, `intensity_scale` and `colorbar` and the colours of a missing step.
  `--style FILE` layers a one-off sheet on top; `--size`, `--dpi`, `-x`,
  `--cmap`, `--scale` and `--colorbar` still win for one plot. The axis label
  *texts* follow the data and change with `--x-label` and `--y-label`.

- **Stacked, not interpolated.** A series measured in regular steps (1, 100,
  200 … bar) gets one band per step: each pattern covers half a step either side
  of its value, so forty patterns fill a 4000 bar axis without a single
  invented row. The axis runs half a step past the first and last patterns, so
  they get whole bands too. Off any regular grid, each pattern reaches half way
  to its neighbours. `--smooth` blends between neighbouring steps instead; that
  hides the steps, but also turns a jump between two patterns into what looks
  like a gradual change.
- **Missing steps** — no pattern at 3400 bar, say — are found from the step the
  series was measured in (the commonest spacing of the values; `--step 100` to
  say it yourself) and **hatched** grey. `--fill` fills them instead, by linear
  interpolation between the measured steps either side, weighted by distance.
- **The SI notes.** `-s` writes `NAME_SI.txt` beside the figure: a paragraph for
  the supporting information, then the numbers — which pressures were measured
  and which filled or hatched, how far each pattern is stretched (one step of
  the axis; so many image rows; so many pixels in the saved figure), the colour
  scale, the 2θ range, and every file in measurement order with the band it is
  drawn in. A map of forty patterns that looks continuous is stretched, and this
  says by how much.
- **Values and order come from the file names**, by wildcard or by regex:

  | | wildcard template | regular expression |
  |---|---|---|
  | the value | `--y-name "*_#bar_*"` | `--y-regex "_(\d+)bar_"` |
  | the measurement order | `--order-name "#_*"` | `--order-regex "^(\d+)_"` |

  In a template `*` is any text, `?` one character and `#` the number (1700, 2.5,
  0,5); it covers the whole name, as `dir *.xy` does, in any case. A template
  that fits a name in two ways is refused, naming both readings — `*_#_*` finds
  27 and 001 in `00_GH077a_27_750_11112026_1bar_001_00000.xy` — so a wildcard
  never quietly takes the wrong number. Several `#`s in `--order-name` are
  compared left to right, as are the groups of `--order-regex`, which is `pp`'s
  `--sort-key` (and takes that name too).

  Without either, the value is the number before a unit (`_1bar_`, `2.5GPa`,
  `300K`), which also labels the axis (*p* / bar) — sample codes and dates are
  passed over, and so is a unit whose number never changes (a constant `25C` in a
  pressure series) — and the order is the order the names sort in, which a
  leading `00_`, `01_` … makes the measurement order. `--y-values
  1,100:4000:100` gives the values yourself, in measurement order. Two patterns
  at one value are refused: a run that comes back down needs one map per leg.

  > Before 0.18.0 `heatmap --sort-key` gave the value. It now gives the order,
  > as it does in `pp`; the value regex is `--y-regex`.
- **Colours**: `--cmap` takes any matplotlib colormap (`viridis`, `Blues_r`),
  part of one (`PuBu:0.28:1`), or colours to blend (`white,#08306b`). The default
  is the paper's, measured off the published figure: ColorBrewer PuBu without its
  palest 28 %. Intensity goes on a square-root scale, which puts the background
  of our gas-cell patterns where the paper's sits; `--scale linear` makes colour
  proportional to intensity, `--scale log` brings up the weakest peaks.
  `--normalize` scales each pattern to its own maximum first.
- **Figure**: a journal column wide (`--size 3.5 1.2`), Arial, outward ticks; the
  first value always gets a tick (the paper's "1" bar). `-s` saves it at
  `--dpi 300`; in an SVG or PDF the map is embedded as an image and the text stays
  vector. `--colorbar` adds a colour bar, which the paper does without.
- Columns that are zero in every pattern — a masked detector edge — are left off
  the ends; `--range LO HI` picks the window yourself. Patterns on different
  x grids are interpolated onto the range they all share.
- Labels are matplotlib mathtext. In PowerShell put a label containing `$` in
  single quotes (`--label 'Mg$_2$(dobdc)'`), or `$` starts a variable; cmd takes
  the double quotes above.

## Requirements

Python ≥ 3.10. Dependencies install automatically: numpy, matplotlib, spglib,
scipy, beautifulsoup4, platformdirs.

**Changed in 0.8.0:** pymatgen is no longer a dependency. Its CIF parser refuses
files this lab produces — a site occupancy above its tolerance discards the whole
data block, and several refinement programs write that column as atoms-per-site,
so a good file raised *"Invalid CIF file with no structures!"* and the phase
silently vanished from the plot. The crystallography now comes from a vendored
copy of [ACH-MoloM](https://github.com/ACH-Repo/ACH-MoloM)'s core, which computes
what the file says. Reflection positions and relative intensities are unchanged;
`pq`'s simulated CIF patterns are pixel-identical across the switch.

`rp` now writes the space group **the CIF declares**, where it used to re-derive
it from the atomic coordinates. A header that disagrees with its own atoms is a
fault in the file, and silently correcting it put a group into your `.inp` that
the depositor never claimed. Pass `--derive-symmetry` to get the old behaviour
for a file some conversion tool expanded to P1.

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
├── styles.py            # per-person, per-plotter style sheets
├── cmdline.py           # every tool's parsing: default flags, then -d
├── misc/                # one-off analyses: kit.py is all they import
├── document.py          # -d: the command, kept as run<N>.bat
├── core/
│   ├── rounding.py      # crystallographic rounding (one copy)
│   ├── cif.py           # CIF resolution, reflection + pattern simulation
│   ├── readers.py       # measured patterns: pq, pf and conv read here
│   ├── xaxis.py         # 2θ or Q, and converting between them
│   ├── topas.py         # .out parsing: cells, phase names (one copy)
│   ├── overlays.py      # -m and -b, shared by pp and pq
│   ├── animate.py       # GIFs of a sequential run
│   └── _molom/          # vendored MoloM crystallography (do not edit)
└── tools/               # one module per command
```

`core/_molom/` is a byte-for-byte copy of five modules from ACH-MoloM, re-synced
with `python tools/sync_molom.py`. It is vendored rather than depended on
because installing `molom` would pull PySide6, PyOpenGL, rdkit and openbabel
into a command-line suite. `core/cif.py` is the adapter and the only place that
knows both sides.

`core/` exists because these helpers had drifted apart across the old
repositories — two `cryst_round` implementations disagreed on refinement-limit
annotations, and the reflection parser had a fix in one copy but not the other.
`pp` and `pq` each grew their own multiply the same way. Shared code lives in
exactly one place now.

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
