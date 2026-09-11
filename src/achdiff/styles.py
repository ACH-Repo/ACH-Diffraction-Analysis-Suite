"""Per-person plot styling, layered on top of the plotter's built-in look.

A style is a small TOML file of presentation values -- label wording, colours,
font sizes, tick furniture. It lives beside config.toml, one file per person:

    <config dir>/styles/default.toml     applies to everyone
    <config dir>/styles/CN.toml          applies when -u resolves to CN

Layering matches the rest of the suite, so there is one precedence rule to learn:

    --style FILE  >  ACH_STYLE  >  styles/<ID>.toml  >  styles/default.toml  >  built-in

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
never rename an internal. SCHEMA below is the translation layer, and it is the
only thing a style file is promised.

Unknown keys and bad values are reported and skipped, never fatal: a style sheet
is decoration, and a typo in one must not stop a figure being drawn.
"""

import os
from collections import namedtuple
from pathlib import Path

from . import config

ENV_STYLE = 'ACH_STYLE'
STYLES_DIRNAME = 'styles'
DEFAULT_STYLE_STEM = 'default'

# name   -- the key a person writes in their style file
# target -- the plotter settings key it drives
# kind   -- how the value is validated and coerced
# doc    -- the comment `achdiff style init` writes above it
Key = namedtuple('Key', 'name target kind doc')

SCHEMA = [
	('figure', 'Canvas and output.', [
		Key('figsize', 'figsize', 'size2',
		    'Width and height in inches.'),
		Key('dpi', 'dpi', 'int',
		    'Resolution of raster output. Ignored by svg and pdf.'),
		Key('transparent', 'transparent', 'bool',
		    'Save with a transparent background instead of white.'),
		Key('extension', 'extension', 'str',
		    'Default output format for -s. The -x flag still overrides this.'),
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
	         'numbers: intensities from a Pawley fit are on an arbitrary scale.', [
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
		Key('ticks_top', 'ticks_top', 'bool',
		    'Mirror the x ticks onto the top edge of the frame.'),
		Key('tick_direction', 'tick_direction', 'choice:in,out,inout',
		    'Whether ticks point into the axes, out of them, or both.'),
		Key('tick_length_major', 'tick_length_major', 'float',
		    'Length in points of the numbered ticks.'),
		Key('tick_length_minor', 'tick_length_minor', 'float',
		    'Length in points of the unnumbered ticks between them.'),
	]),
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
]

BY_NAME = {key.name: key for group in SCHEMA for key in group[2]}


def styles_dir():
	"""Directory holding the style sheets, beside config.toml so that both move
	together when ACH_CONFIG_DIR redirects them."""
	return config.config_dir() / STYLES_DIRNAME


def style_path(user=None):
	"""The style file for `user`, or the shared one when no profile is active."""
	stem = user if user else DEFAULT_STYLE_STEM
	return styles_dir() / f'{stem}.toml'


def available():
	"""Every style sheet on this machine, as sorted (stem, path) pairs."""
	directory = styles_dir()
	if not directory.is_dir():
		return []
	return sorted((p.stem, p) for p in directory.glob('*.toml'))


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


def _apply_one(target, path, seen_unknown):
	"""Layer one file onto `target`. Returns the number of settings applied."""
	applied = 0
	for name, raw in _read(path).items():
		key = BY_NAME.get(name)
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


def resolve_named_style(name):
	"""Turn a --style or ACH_STYLE value into a path.

	A path that exists is used as given. Otherwise the name is looked up in the
	styles directory, with and without a `.toml` suffix -- the same courtesy `-r`
	extends to bare CIF names against the CIF library, and for the same reason:
	the one-off styles people keep (a journal's column width, a poster) live
	beside the personal ones, and having to type the full path to a file the
	suite itself wrote is friction with nothing behind it.

	A name that matches nothing comes back unchanged, so the caller reports the
	spelling the user actually typed.
	"""
	given = Path(name)
	if given.is_file():
		return given
	for candidate in (styles_dir() / name, styles_dir() / f'{name}.toml'):
		if candidate.is_file():
			return candidate
	return given


def layer_paths(user=None, explicit=None):
	"""The style files to apply, in the order they should be layered.

	Discovered files that do not exist are simply absent. A file named outright
	-- by --style or ACH_STYLE -- is included even when missing, so the caller
	can tell a typo from a deliberate choice rather than silently drawing the
	wrong figure.
	"""
	paths = []
	shared = styles_dir() / f'{DEFAULT_STYLE_STEM}.toml'
	if shared.is_file():
		paths.append(shared)
	if user:
		personal = style_path(user)
		if personal.is_file() and personal != shared:
			paths.append(personal)
	env = os.environ.get(ENV_STYLE)
	if env:
		paths.append(resolve_named_style(env))
	if explicit:
		paths.append(resolve_named_style(explicit))
	return paths


def apply(target, user=None, explicit=None):
	"""Layer every applicable style file onto `target`, lowest precedence first.

	Returns a one-line description of what was applied, or None if nothing was.
	Raises FileNotFoundError for a file named outright that does not exist.
	"""
	paths = layer_paths(user, explicit)
	unknown = {}
	used = []
	for path in paths:
		if not path.is_file():
			raise FileNotFoundError(
				f'Style file not found: {path}\n'
				f'    Looked here and in {styles_dir()}\n'
				f'    `achdiff style list` shows the styles on this machine.')
		if _apply_one(target, path, unknown):
			used.append(path)

	for path, names in unknown.items():
		print(f'[!] {path.name}: ignoring unknown setting(s) {", ".join(sorted(names))}.')
		print(f'    `achdiff style init` writes a file listing every setting there is.')

	if not used:
		return None
	return ' + '.join(_describe(p) for p in used)


def _describe(path):
	"""How a style file is named when the plotter announces it.

	Files in the styles directory are named by filename alone -- that directory is
	printed by `achdiff style list` and the full path adds nothing but width. A
	file from anywhere else keeps its path, because where it came from is the
	interesting part.
	"""
	try:
		return path.relative_to(styles_dir()).as_posix()
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


def template(user=None, effective=None):
	"""A fully commented style file showing every setting at its current value.

	Every line is commented out, so a freshly written template changes nothing
	until something in it is uncommented. That is the point: it is a catalogue of
	what can be changed, not a second place for the defaults to live.
	"""
	if effective is None:
		# Imported here because this is the one entry point that needs the real
		# values, and importing the plotter costs a matplotlib import.
		from .tools import plotter
		effective = plotter.settings

	who = f'profile {user}' if user else 'everyone without a style of their own'
	out = [
		f'# ACH Diffraction Analysis Suite -- plot style for {who}.',
		'#',
		'# Every setting is listed below at the value currently in effect, and every',
		'# line is commented out. Uncomment one and edit it to take that setting over;',
		'# anything left commented keeps following the built-in default, including',
		'# after an upgrade changes what that default is.',
		'#',
		'# Precedence:  --style FILE > ACH_STYLE > this file > default.toml > built-in',
		'#',
		'# Group headers are only here to make the file readable. Keys work the same',
		'# outside them.',
		'',
	]

	for name, blurb, keys in SCHEMA:
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


def write_template(user=None, force=False):
	"""Create the style file for `user`. Returns (path, created)."""
	path = style_path(user)
	if path.exists() and not force:
		return path, False
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(template(user), encoding='utf-8')
	return path, True
