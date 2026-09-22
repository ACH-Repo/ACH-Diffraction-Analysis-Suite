"""Per-person plot styling, layered on top of each plotter's built-in look.

A style is a small TOML file of presentation values -- label wording, colours,
font sizes, tick furniture. It lives beside config.toml, one file per person and
per plotter:

    <config dir>/styles/pp/default.toml   pp, for everyone
    <config dir>/styles/pp/CN.toml        pp, when -u resolves to CN
    <config dir>/styles/pq/CN.toml        pq, when -u resolves to CN

Layering matches the rest of the suite, so there is one precedence rule to learn:

    --style FILE  >  ACH_STYLE_PP  >  styles/pp/<ID>.toml  >  styles/pp/default.toml  >  built-in

(and the same with PQ / pq for quickplot).

Why each plotter has its own sheets
-----------------------------------
A Pawley fit and a stack of patterns are different figures. Settings with the
same name -- figsize, axis_label_size -- would still want different values, and
one file driving both would mean a column-width pp sheet shrinking every pq
stack as well. So a sheet belongs to one plotter, and a setting from the other
one's list is reported as belonging there rather than silently applied.

Sheets written before the split all belonged to pp. The first time the styles
directory is used they are moved into styles/pp/, and that is announced.

Why a separate file rather than a [profiles.<ID>.style] table in config.toml
----------------------------------------------------------------------------
config.toml is machine-managed: `achdiff trusted add` and friends rewrite it in
full, and comments do not survive that. A style sheet is the opposite -- read
rarely, hand-edited often, and only useful with its comments intact. Keeping the
two apart means `achdiff style init` can emit a thoroughly annotated file that no
later save will strip.

Why public key names differ from the plotter's own
--------------------------------------------------
The plotter names its settings after the TOPAS output files they came from
(`X_Yobs_color`, `2Th_Ip_colors`). Those are the wrong words for a person editing
a figure, and freezing them into user files would also mean the plotter could
never rename an internal. SCHEMAS below is the translation layer, and it is the
only thing a style file is promised.

Unknown keys and bad values are reported and skipped, never fatal: a style sheet
is decoration, and a typo in one must not stop a figure being drawn.
"""

import os
import shutil
from collections import namedtuple
from pathlib import Path

from . import config

# The plotters that take a style sheet, and the module holding each one's
# live `settings` -- which is what `achdiff style init` reads the defaults from.
TOOLS = {
	'pp': 'achdiff.tools.plotter',
	'pq': 'achdiff.tools.quickplot',
}

# ACH_STYLE predates the split and meant pp's sheet; it still does.
ENV_STYLE = 'ACH_STYLE'
STYLES_DIRNAME = 'styles'
DEFAULT_STYLE_STEM = 'default'


def env_style_var(tool):
	return f'ACH_STYLE_{tool.upper()}'

# name   -- the key a person writes in their style file
# target -- the plotter settings key it drives
# kind   -- how the value is validated and coerced
# doc    -- the comment `achdiff style init` writes above it
Key = namedtuple('Key', 'name target kind doc')

# Settings both plotters have. Both tools use the same internal names for them,
# so one definition serves each tool's schema.
_OUTPUT_KEYS = [
	Key('figsize', 'figsize', 'size2',
	    'Width and height in inches. --size overrides it for one plot.'),
	Key('dpi', 'dpi', 'int',
	    'Resolution of raster output. Ignored by svg and pdf. --dpi overrides it.'),
	Key('transparent', 'transparent', 'bool',
	    'Save with a transparent background instead of white.'),
	Key('extension', 'extension', 'str',
	    'Default output format for -s. The -x flag still overrides this.'),
]

_AXES_KEYS = [
	Key('x_label', 'x_label_text', 'str',
	    'Mathtext. Anything between $...$ is set in maths italic, anything '
	    'outside stays upright -- which is how 2theta stays italic while the '
	    'degree sign does not.'),
	Key('y_label', 'y_label_text', 'str',
	    'Mathtext, same rules as x_label.'),
	Key('axis_label_size', 'size_axis_labels', 'float',
	    'Point size of both axis labels.'),
	Key('tick_label_size', 'size_tick_labels', 'float',
	    'Point size of the numbers along the x axis.'),
	Key('x_tick_step', 'x_tick_step', 'float',
	    'Degrees between numbered x ticks. 0 leaves the spacing to matplotlib.'),
	Key('ticks_top', 'ticks_top', 'bool',
	    'Mirror the x ticks onto the top edge of the frame.'),
	Key('tick_direction', 'tick_direction', 'choice:in,out,inout',
	    'Whether ticks point into the axes, out of them, or both.'),
	Key('tick_length_major', 'tick_length_major', 'float',
	    'Length in points of the numbered ticks.'),
	Key('tick_length_minor', 'tick_length_minor', 'float',
	    'Length in points of the unnumbered ticks between them.'),
	Key('title_size', 'title_font_size', 'float',
	    'Point size of the title drawn by -t.'),
]

_OVERLAY_GROUP = ('overlays', 'Marks added from the command line.', [
	Key('band_color', 'band_color', 'color',
	    'Colour of a -b strip given without one of its own.'),
	Key('band_width', 'band_width', 'float',
	    'Width of a -b strip given without one of its own, as a percentage of '
	    'the plot width.'),
	Key('multiply_label_size', 'multiply_label_size', 'float',
	    "Point size of the 'x N' label over a range scaled with -m."),
])

_PP_SCHEMA = [
	('figure', 'Canvas and output.', _OUTPUT_KEYS + [
		Key('gif_dpi', 'gif_dpi', 'int',
		    'Frame resolution for --gif. Kept apart from dpi, which is print '
		    'resolution: a 6-inch figure at 300 dpi is 1800 px per frame, and a '
		    'few dozen of those make a GIF too large to send anywhere.'),
	]),
	('traces', 'The curves themselves. Colours take any matplotlib spelling: '
	           "'k', 'red', '#e8000b'.", [
		Key('observed_color', 'X_Yobs_color', 'color',
		    'Measured pattern.'),
		Key('observed_markersize', 'X_Yobs_markersize', 'float',
		    "Size of the 'x' symbols, in points."),
		Key('observed_markeredgewidth', 'X_Yobs_markeredgewidth', 'float',
		    "Stroke weight of the 'x' symbols. Lower is finer."),
		Key('calculated_color', 'Out_X_Ycalc_color', 'color',
		    'Fitted pattern.'),
		Key('calculated_linewidth', 'Out_X_Ycalc_linewidth', 'float',
		    'Stroke weight of the fitted curve.'),
		Key('difference_color', 'X_Difference_color', 'color',
		    'Difference curve below the data.'),
		Key('difference_linewidth', 'X_Difference_linewidth', 'float',
		    'Stroke weight of the difference curve.'),
		Key('bragg_colors', '2Th_Ip_colors', 'colorlist',
		    'One colour per phase, used in phase order and cycled if a fit has '
		    'more phases than entries. A single-phase fit only ever uses the first.'),
		Key('bragg_markersize', '2Th_Ip_markersize', 'float',
		    'Height of the Bragg tick marks, in points.'),
		Key('bragg_markeredgewidth', '2Th_Ip_markeredgewidth', 'float',
		    'Stroke weight of the Bragg tick marks.'),
	]),
	('axes', 'Axis labels and tick furniture. The y axis carries no ticks or '
	         'numbers: intensities from a Pawley fit are on an arbitrary scale.',
	 _AXES_KEYS),
	('legend', 'Wording and placement of the key.', [
		Key('legend', 'show_legend', 'bool',
		    'Draw the legend at all.'),
		Key('observed_label', 'X_Yobs_label', 'str',
		    'Legend text for the measured pattern.'),
		Key('calculated_label', 'Out_X_Ycalc_label', 'str',
		    'Legend text for the fitted pattern.'),
		Key('difference_label', 'X_Difference_label', 'str',
		    'Legend text for the difference curve.'),
		Key('bragg_label', 'bragg_label', 'str',
		    "One fixed name for the Bragg tick rows, e.g. 'Bragg reflections'. "
		    'Left empty, each row is named after its own space group and substance '
		    'instead, in the shape sg_format asks for. A fixed name collapses to a '
		    'single legend entry only while every row is drawn in the same colour; '
		    'as soon as the colours differ each row keeps its phase in brackets, '
		    'because two colours in the plot need two entries in the key.'),
		Key('sg_format', 'use_sg_format',
		    'choice:HERMANN-MAUGUIN+SUBSTANCE,HERMANN-MAUGUIN,SUBSTANCE,NUMBER',
		    'How a Bragg row names itself when bragg_label is empty.'),
		Key('legend_loc', 'legend_loc', 'str',
		    "Corner or edge to place it against: 'upper right', 'upper left', "
		    "'lower right', 'best', and the rest of the matplotlib vocabulary."),
		Key('legend_frame', 'legend_frame', 'bool',
		    'Draw the box around the legend.'),
		Key('legend_columns', 'legend_columns', 'int',
		    'Lay the entries out in this many columns.'),
		Key('legend_fontsize', 'legend_fontsize', 'float',
		    'Point size of the legend text.'),
		Key('legend_dedupe', 'legend_dedupe', 'bool',
		    'Collapse entries that are identical in both wording and appearance. '
		    'Two rows that differ in colour are never collapsed, whatever this says.'),
	]),
	('annotations', 'Text drawn inside the axes.', [
		Key('show_quality', 'show_info', 'bool',
		    'Print the fit quality (R_wp, or all three factors under --qall) in '
		    'the bottom right corner. Turn it off for figures that report the '
		    'numbers in the caption instead.'),
		Key('quality_fontsize', 'quality_fontsize', 'float',
		    'Point size of that annotation.'),
	]),
	_OVERLAY_GROUP,
]

_PQ_SCHEMA = [
	('figure', 'Canvas and output.', _OUTPUT_KEYS),
	('traces', 'The stacked patterns. Colours take any matplotlib spelling: '
	           "'k', 'red', '#e8000b'.", [
		Key('trace_colors', 'trace_colors', 'colorlist',
		    'Colour of each trace, top of the stack first, cycled when there are '
		    'more traces than colours. --colors overrides it for one plot.'),
		Key('line_width', 'line_width', 'float',
		    'Stroke weight of every trace.'),
		Key('trace_label_size', 'trace_label_size', 'float',
		    'Point size of the name written under each trace.'),
	]),
	('axes', 'Axis labels and tick furniture. The y axis carries no ticks or '
	         'numbers: each trace is normalised, so the scale means nothing.',
	 _AXES_KEYS),
	_OVERLAY_GROUP,
]

SCHEMAS = {'pp': _PP_SCHEMA, 'pq': _PQ_SCHEMA}
BY_NAME = {tool: {key.name: key for group in schema for key in group[2]}
           for tool, schema in SCHEMAS.items()}


def _check_tool(tool):
	if tool not in TOOLS:
		raise ValueError(f'no style sheets for {tool!r}; choose from {", ".join(TOOLS)}')


# ---------------------------------------------------------------- locations

_migrated = False


def _migrate_flat_layout(root):
	"""Move sheets from the pre-split flat styles/ into styles/pp/, once.

	Every sheet there was written for pp, since pp was the only plotter that read
	them. Moved rather than copied, so there is never a second copy to edit by
	mistake; a name already taken in styles/pp/ is left where it is and reported."""
	global _migrated
	if _migrated:
		return
	_migrated = True
	if not root.is_dir():
		return
	flat = sorted(p for p in root.glob('*.toml') if p.is_file())
	if not flat:
		return
	target = root / 'pp'
	moved, clashed = [], []
	for path in flat:
		dest = target / path.name
		if dest.exists():
			clashed.append(path.name)
			continue
		try:
			target.mkdir(parents=True, exist_ok=True)
			shutil.move(str(path), str(dest))
			moved.append(path.name)
		except OSError as e:
			print(f'[!] Could not move style sheet {path} into {target}: {e}')
	if moved:
		print(f'[*] Style sheets are now kept per plotter. Moved yours, which were all '
		      f'for pp, into {target}: {", ".join(moved)}')
	if clashed:
		print(f'[!] Left in {root}, because {target} already has a file of that name: '
		      f'{", ".join(clashed)}. Merge them by hand; only the one in pp/ is read.')


def styles_root():
	"""Directory holding every plotter's style sheets, beside config.toml so that
	both move together when ACH_CONFIG_DIR redirects them."""
	root = config.config_dir() / STYLES_DIRNAME
	_migrate_flat_layout(root)
	return root


def styles_dir(tool):
	"""Directory holding `tool`'s style sheets."""
	_check_tool(tool)
	return styles_root() / tool


def style_path(tool, user=None):
	"""`tool`'s style file for `user`, or the shared one when no profile is active."""
	stem = user if user else DEFAULT_STYLE_STEM
	return styles_dir(tool) / f'{stem}.toml'


def available(tool=None):
	"""Every style sheet on this machine, as sorted (tool, stem, path) triples."""
	out = []
	for name in ([tool] if tool else TOOLS):
		directory = styles_dir(name)
		if directory.is_dir():
			out.extend((name, p.stem, p) for p in directory.glob('*.toml'))
	return sorted(out)


# ---------------------------------------------------------------- validation

def _is_color(value):
	# Imported here rather than at module scope: `achdiff style path` has no use
	# for matplotlib and should not pay a second of import time to answer.
	from matplotlib.colors import is_color_like
	return isinstance(value, str) and is_color_like(value)


def _coerce(key, value):
	"""Return the value in the type the plotter expects, or raise ValueError with
	a message written for the person editing the file."""
	kind = key.kind

	if kind == 'str':
		if not isinstance(value, str):
			raise ValueError('expected text in quotes')
		return value

	if kind == 'bool':
		if not isinstance(value, bool):
			raise ValueError('expected true or false')
		return value

	if kind == 'int':
		if isinstance(value, bool) or not isinstance(value, int):
			raise ValueError('expected a whole number')
		return value

	if kind == 'float':
		if isinstance(value, bool) or not isinstance(value, (int, float)):
			raise ValueError('expected a number')
		if value < 0:
			raise ValueError('expected a number of zero or more')
		return float(value)

	if kind == 'size2':
		if (not isinstance(value, (list, tuple)) or len(value) != 2
				or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
				           for v in value)):
			raise ValueError('expected two numbers, e.g. [6.0, 4.0]')
		if not all(v > 0 for v in value):
			raise ValueError('expected two positive numbers')
		return (float(value[0]), float(value[1]))

	if kind == 'color':
		if not _is_color(value):
			raise ValueError(f'{value!r} is not a colour matplotlib recognises')
		return value

	if kind == 'colorlist':
		if not isinstance(value, list) or not value:
			raise ValueError("expected a non-empty list, e.g. ['k', 'b']")
		bad = [v for v in value if not _is_color(v)]
		if bad:
			raise ValueError('not colours matplotlib recognises: '
			                 + ', '.join(repr(b) for b in bad))
		return list(value)

	if kind.startswith('choice:'):
		allowed = kind.split(':', 1)[1].split(',')
		if value not in allowed:
			raise ValueError('expected one of ' + ', '.join(allowed))
		return value

	raise ValueError(f'unsupported kind {kind!r}')   # unreachable; guards SCHEMA typos


def _read(path):
	"""Parse one style file into {name: value}. Problems are reported and the file
	is skipped, in keeping with config.load(): a broken style must not stop a plot."""
	if config.tomllib is None:
		print(f'[!] No TOML parser available, so {path} cannot be read and your '
		      f'style is being ignored.')
		print(f'    Fix with: pip install tomli')
		return {}
	try:
		with open(path, 'rb') as fh:
			data = config.tomllib.load(fh)
	except Exception as e:
		print(f'[!] Ignoring unreadable style {path}: {e}')
		return {}

	# Group headers are optional sugar: [axes] exists to make a long file
	# readable, not to namespace the keys, so a flat file works just as well.
	flat = {}
	for k, v in data.items():
		if isinstance(v, dict):
			flat.update(v)
		else:
			flat[k] = v
	return flat


def _other_tools_keys(tool, names):
	"""Of `names`, the ones that are another plotter's settings, as {name: tool}."""
	return {n: other for n in names for other in TOOLS
	        if other != tool and n in BY_NAME[other]}


def report_unknown(tool, label, names):
	belongs = _other_tools_keys(tool, names)
	strays = sorted(n for n in names if n not in belongs)
	if strays:
		print(f'[!] {label}: ignoring unknown setting(s) {", ".join(strays)}.')
		print(f'    `achdiff style init {tool}` writes a file listing every setting there is.')
	for other in sorted(set(belongs.values())):
		mine = sorted(n for n, t in belongs.items() if t == other)
		print(f'[!] {label}: ignoring {", ".join(mine)} -- only {other} has '
		      f'{"that setting" if len(mine) == 1 else "those settings"}, and {tool} '
		      f'does not read {other} style sheets.')


def validate(tool, path):
	"""Check a style file without applying it: `(good, unknown, invalid)`.

	`good` and `unknown` are key names, `invalid` is (name, reason) pairs. Used
	before installing a file someone was sent, so a typo is caught while it is
	still obvious what to do about it rather than the next time they plot.
	"""
	_check_tool(tool)
	good, unknown, invalid = [], [], []
	for name, raw in _read(path).items():
		key = BY_NAME[tool].get(name)
		if key is None:
			unknown.append(name)
			continue
		try:
			_coerce(key, raw)
		except ValueError as e:
			invalid.append((name, str(e)))
			continue
		good.append(name)
	return good, unknown, invalid


def _apply_one(tool, target, path, seen_unknown):
	"""Layer one file onto `target`. Returns the number of settings applied."""
	applied = 0
	for name, raw in _read(path).items():
		key = BY_NAME[tool].get(name)
		if key is None:
			seen_unknown.setdefault(path, []).append(name)
			continue
		try:
			target[key.target] = _coerce(key, raw)
		except ValueError as e:
			print(f'[!] {path.name}: ignoring {name} -- {e}.')
			continue
		applied += 1
	return applied


def resolve_named_style(tool, name):
	"""Turn a --style or ACH_STYLE_<TOOL> value into a path.

	A path that exists is used as given. Otherwise the name is looked up in the
	tool's styles directory, with and without a `.toml` suffix -- the same courtesy
	`-r` extends to bare CIF names against the CIF library, and for the same
	reason: the one-off styles people keep (a journal's column width, a poster)
	live beside the personal ones, and having to type the full path to a file the
	suite itself wrote is friction with nothing behind it.

	A name that matches nothing comes back unchanged, so the caller reports the
	spelling the user actually typed.
	"""
	given = Path(name)
	if given.is_file():
		return given
	directory = styles_dir(tool)
	for candidate in (directory / name, directory / f'{name}.toml'):
		if candidate.is_file():
			return candidate
	return given


def _env_style(tool):
	value = os.environ.get(env_style_var(tool))
	if value is None and tool == 'pp':
		value = os.environ.get(ENV_STYLE)
	return value


def layer_paths(tool, user=None, explicit=None):
	"""`tool`'s style files to apply, in the order they should be layered.

	Discovered files that do not exist are simply absent. A file named outright
	-- by --style or ACH_STYLE_<TOOL> -- is included even when missing, so the
	caller can tell a typo from a deliberate choice rather than silently drawing
	the wrong figure.
	"""
	paths = []
	shared = style_path(tool)
	if shared.is_file():
		paths.append(shared)
	if user:
		personal = style_path(tool, user)
		if personal.is_file() and personal != shared:
			paths.append(personal)
	env = _env_style(tool)
	if env:
		paths.append(resolve_named_style(tool, env))
	if explicit:
		paths.append(resolve_named_style(tool, explicit))
	return paths


def apply(tool, target, user=None, explicit=None):
	"""Layer every applicable style file for `tool` onto `target`, lowest
	precedence first.

	Returns a one-line description of what was applied, or None if nothing was.
	Raises FileNotFoundError for a file named outright that does not exist.
	"""
	paths = layer_paths(tool, user, explicit)
	unknown = {}
	used = []
	for path in paths:
		if not path.is_file():
			raise FileNotFoundError(
				f'Style file not found: {path}\n'
				f'    Looked here and in {styles_dir(tool)}\n'
				f'    `achdiff style list {tool}` shows the styles on this machine.')
		if _apply_one(tool, target, path, unknown):
			used.append(path)

	for path, names in unknown.items():
		report_unknown(tool, path.name, names)

	if not used:
		return None
	return ' + '.join(_describe(p) for p in used)


def _describe(path):
	"""How a style file is named when the plotter announces it.

	Files in the styles directory are named relative to it (`pp/CN.toml`) --
	that directory is printed by `achdiff style list` and the full path adds
	nothing but width. A file from anywhere else keeps its path, because where it
	came from is the interesting part.
	"""
	try:
		return path.relative_to(styles_root()).as_posix()
	except ValueError:
		return str(path)


# ------------------------------------------------------------------ template

def _fmt(value):
	"""A TOML literal for a value taken from the plotter's live settings."""
	if isinstance(value, bool):
		return 'true' if value else 'false'
	if isinstance(value, (int, float)):
		return str(value)
	if isinstance(value, (list, tuple)):
		return '[' + ', '.join(_fmt(v) for v in value) + ']'
	# Single-quoted TOML literal strings take no escapes at all, which is exactly
	# what the backslash-heavy mathtext in the axis labels wants. They also cannot
	# contain an apostrophe, so a value that has one falls back to a basic string
	# with its backslashes doubled.
	text = str(value)
	if "'" not in text:
		return "'" + text + "'"
	return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _wrap(text, width, prefix):
	import textwrap
	return '\n'.join(textwrap.wrap(text, width=width,
	                               initial_indent=prefix, subsequent_indent=prefix))


def live_settings(tool):
	"""`tool`'s built-in settings, read from the plotter itself.

	Imported only here because this is the one entry point that needs the real
	values, and importing a plotter costs a matplotlib import."""
	import importlib
	_check_tool(tool)
	return importlib.import_module(TOOLS[tool]).settings


def template(tool, user=None, effective=None):
	"""A fully commented style file showing every setting at its current value.

	Every line is commented out, so a freshly written template changes nothing
	until something in it is uncommented. That is the point: it is a catalogue of
	what can be changed, not a second place for the defaults to live.
	"""
	if effective is None:
		effective = live_settings(tool)

	who = f'profile {user}' if user else 'everyone without a style of their own'
	var = env_style_var(tool)
	out = [
		f'# ACH Diffraction Analysis Suite -- {tool} plot style for {who}.',
		'#',
		f'# Read by {tool} only. The other plotter has style sheets of its own.',
		'#',
		'# Every setting is listed below at the value currently in effect, and every',
		'# line is commented out. Uncomment one and edit it to take that setting over;',
		'# anything left commented keeps following the built-in default, including',
		'# after an upgrade changes what that default is.',
		'#',
		f'# Precedence:  --style FILE > {var} > this file > default.toml > built-in',
		'#',
		'# Group headers are only here to make the file readable. Keys work the same',
		'# outside them.',
		'',
	]

	for name, blurb, keys in SCHEMAS[tool]:
		out.append('')
		out.append('# ' + '-' * 68)
		out.append(_wrap(blurb, 72, '# '))
		out.append('# ' + '-' * 68)
		out.append(f'[{name}]')
		for key in keys:
			out.append('')
			out.append(_wrap(key.doc, 72, '# '))
			value = effective.get(key.target)
			out.append(f'# {key.name} = {_fmt(value)}')
		out.append('')

	return '\n'.join(out).rstrip() + '\n'


def write_template(tool, user=None, force=False):
	"""Create `tool`'s style file for `user`. Returns (path, created)."""
	path = style_path(tool, user)
	if path.exists() and not force:
		return path, False
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(template(tool, user), encoding='utf-8')
	return path, True
