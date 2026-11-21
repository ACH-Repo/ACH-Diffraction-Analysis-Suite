r"""A pattern series as a heat map: 2theta or Q across, pressure up, intensity as colour.

Patterns measured along a series -- pressure steps in a gas cell, a temperature
ramp, a time series -- drawn as one image, the way Fig. 2 of J. Am. Chem. Soc.
2025, 147, 46075 shows Mg2(dobdc) from 1 to 4000 bar. A peak that stays put is a
vertical line, a peak that shifts bends, and a phase transition ends lines and
starts others.

Stacked, not interpolated. A series measured in regular steps (1, 100, 200 ...
bar) gets one band per step: each pattern covers half a step either side of its
value, and a step with no pattern is hatched -- or, with --fill, interpolated
linearly from its neighbours. Off any regular grid, each pattern reaches half way
to its neighbours. --smooth blends between neighbouring steps instead of drawing
bands. Saved with -s, the figure gets NAME_SI.txt beside it: what was measured,
what was stretched or filled and by how much, and a paragraph for the
supporting information.

Values and order come from the file names, whichever way suits:
  wildcards  * any text, ? one character, # the number. The template covers the
             whole name, in any case: --y-name "*_#bar_*" reads 1700 from
             17_GH077a_27_750_11112026_1700bar_001_00000.xy, and --order-name
             "#_*" takes the measurement order from the 17. A template that fits
             a name in two ways is refused, naming both readings.
  regex      --y-regex "_(\d+)bar_", the first group being the value, and
             --order-regex "^(\d+)_", groups compared left to right (pp calls it
             --sort-key).
Without either, the value is the number before a unit (1bar, 2.5GPa, 300K) and
the order is the order the names sort in. --y-values 1,100:4000:100 gives the
values yourself, in measurement order.

The x axis is what the files hold: 2theta in degrees unless --x-data says q
(1/angstrom) or q-nm (1/nm), or a pyFAI or DIOPTAS header says so. --x-axis
shows another, converting between 2theta and Q with --wavelength (angstrom),
which a header can also supply.

Colours: --cmap takes any matplotlib colormap (viridis, Blues_r), part of one
(PuBu:0.28:1 is PuBu from 28 % of the way along to the end), or colours to blend
(white,#08306b). The default is the paper's: PuBu without its palest 28 %, so the
weakest intensity is pale blue and the strongest navy. Intensity goes on a
square-root scale, which puts the background of our gas-cell patterns where the
paper's sits, with the weak peaks showing; --scale linear makes colour
proportional to intensity, and --scale log brings up the weakest peaks.

Labels are matplotlib mathtext: --label "Mg$_2$(dobdc)". In PowerShell put them
in single quotes instead, or $ starts a variable.

Run with no arguments in a folder of patterns to be asked for everything.
"""

ABOUT = {
	'for': 'pressure-series heat maps, after Fig. 2 of J. Am. Chem. Soc. 2025, 147, 46075',
	'author': 'Christian Nelle',
	'written': '2026-11-19',
}

import argparse
import os
import re
import sys
import textwrap
from collections import namedtuple
from datetime import datetime
from glob import glob
from pathlib import Path

import numpy as np

from achdiff.misc import kit

#: The paper's colours: ColorBrewer PuBu from 28 % of the way along. Measured off
#: the published figure, whose every pixel lies on PuBu between 0.28 and 1.
DEFAULT_CMAP = 'PuBu:0.28'
#: A journal column wide; the plot inside comes out about 4:1, as in the paper.
DEFAULT_SIZE = (3.5, 1.2)

# The look, as a heatmap style sheet can change it (`achdiff style init heatmap`;
# the keys are in achdiff/styles.py). Named as in pp and pq wherever the meaning
# is the same; the values are the heat map's own and reproduce the paper.
settings = {
	'figsize': DEFAULT_SIZE,
	'dpi': 300,
	'transparent': False,
	'extension': 'svg',
	# Arial where it is installed (every lab PC), as in the paper; mathtext in the
	# same face, so the italic p of "p / bar" matches the rest.
	'font': 'Arial',
	'size_axis_labels': 8,
	'size_tick_labels': 8,
	'x_tick_step': 0,              # 0: matplotlib chooses
	'ticks_top': False,
	'ticks_right': False,
	'tick_direction': 'out',
	'tick_length_major': 3.5,
	'tick_length_minor': 2.0,
	'tick_width': 0.8,
	'minor_ticks': True,
	'frame_width': 0.8,
	'colormap': DEFAULT_CMAP,
	'intensity_scale': 'sqrt',
	'colorbar': False,
	# Steps without a pattern: hatched in grey on lighter grey, whatever the
	# colormap. The fill is what shows when a band is too thin for the hatching --
	# a single missing step is a few pixels tall.
	'gap_color': '0.55',
	'gap_fill': '0.9',
	'label_size': 8,
}


def rc_params(look):
	"""The matplotlib settings a look (settings, with any style sheet applied)
	stands for."""
	fonts = [look['font']] + [f for f in ('Arial', 'Helvetica', 'Liberation Sans', 'DejaVu Sans')
	                          if f != look['font']]
	return {
		'font.family': 'sans-serif',
		'font.sans-serif': fonts,
		'mathtext.fontset': 'custom',
		'mathtext.rm': 'sans',
		'mathtext.it': 'sans:italic',
		'mathtext.bf': 'sans:bold',
		'font.size': look['size_tick_labels'],
		'axes.labelsize': look['size_axis_labels'],
		'xtick.labelsize': look['size_tick_labels'],
		'ytick.labelsize': look['size_tick_labels'],
		'axes.linewidth': look['frame_width'],
		'xtick.direction': look['tick_direction'],
		'ytick.direction': look['tick_direction'],
		'xtick.top': look['ticks_top'],
		'ytick.right': look['ticks_right'],
		'xtick.major.size': look['tick_length_major'],
		'ytick.major.size': look['tick_length_major'],
		'xtick.minor.size': look['tick_length_minor'],
		'ytick.minor.size': look['tick_length_minor'],
		'xtick.major.width': look['tick_width'],
		'ytick.major.width': look['tick_width'],
		'xtick.minor.width': 0.75 * look['tick_width'],
		'ytick.minor.width': 0.75 * look['tick_width'],
		'hatch.linewidth': 0.5,
		'hatch.color': look['gap_color'],
		'savefig.transparent': look['transparent'],
	}

PRESSURE_UNITS = ('bar', 'kbar', 'mbar', 'Pa', 'kPa', 'MPa', 'GPa')
TEMPERATURE_UNITS = ('K', '°C')
# A number with a unit straight after it, and not inside a longer number or word:
# "_1bar_" and "2.5GPa" but neither the 650 nor the date in GH072a_650_24062026.
_UNIT_NUMBER = re.compile(r'(?<![\d.,])(\d+(?:[.,]\d+)?)\s*'
                          r'(kbar|mbar|bar|GPa|MPa|kPa|Pa|K|°C|degC|C)(?![A-Za-z])')
# .txt and .csv are as often notes and tables as patterns.
_AMBIGUOUS_TYPES = ('.txt', '.csv')

#: The built-in look as matplotlib settings.
STYLE = rc_params(settings)

#: The patterns with what the names say about them. `paths` and `values` are in
#: measurement order; `order_numbers` are the numbers the order was read from,
#: when there is one per name, for spotting a measurement that is not there.
Series = namedtuple('Series', 'paths values label unit values_how order_how order_numbers')

#: One band of the map. `kind` is 'measured', 'filled' or 'missing'; `mix` says
#: which patterns (by position in rising value) make it, and with what weight.
Step = namedtuple('Step', 'centre kind mix')


def _values_arg(text):
	try:
		return kit.values(text)
	except ValueError as e:
		raise argparse.ArgumentTypeError(str(e)) from None


def _step_arg(text):
	try:
		step = float(text)
	except ValueError:
		raise argparse.ArgumentTypeError(f'{text!r} is not a number') from None
	if step <= 0:
		raise argparse.ArgumentTypeError('the step must be above zero')
	return step


def build_parser():
	parser = argparse.ArgumentParser(
		description=__doc__.strip().splitlines()[0],
		epilog='Run with no arguments to be asked for everything.')
	parser.add_argument('-i', '--input', nargs='+', metavar='FILE',
	                    help='Pattern files, or a folder; wildcards are fine (-i *.xy). '
	                         'Default: every pattern in this folder, of its most common type.')

	where = parser.add_argument_group(
		'values and order', 'Read from the file names with a wildcard template (* any text, '
		                    '? one character, # the number; covering the whole name) or a '
		                    'regular expression.')
	value = where.add_mutually_exclusive_group()
	value.add_argument('--y-name', default=None, metavar='TEMPLATE',
	                   help='Where the value is in the name, e.g. "*_#bar_*". Default: the '
	                        'number before a unit (1bar, 2.5GPa, 300K).')
	value.add_argument('--y-regex', default=None, metavar='REGEX',
	                   help=r'The value as the first group of a regex, e.g. "_(\d+)bar_".')
	value.add_argument('--y-values', type=_values_arg, default=None, metavar='SPEC',
	                   help='The values themselves, in measurement order: a list, '
	                        'start:stop:step with the stop included, or both, e.g. '
	                        '1,100:4000:100.')
	order = where.add_mutually_exclusive_group()
	order.add_argument('--order-name', default=None, metavar='TEMPLATE',
	                   help='Where the measurement number is in the name, e.g. "#_*"; several '
	                        '#s are compared left to right. Default: the order the names sort in.')
	order.add_argument('--order-regex', '--sort-key', dest='order_regex', default=None,
	                   metavar='REGEX',
	                   help='The measurement order from the groups of a regex, compared left '
	                        'to right, as pp --sort-key, e.g. ' + r'"^(\d+)_".')
	where.add_argument('--y-label', default=None, metavar='TEXT',
	                   help='Label of the series axis. Default: from the unit in the names, '
	                        'e.g. "$p$ / bar".')

	steps = parser.add_argument_group('steps')
	steps.add_argument('--step', type=_step_arg, default=None, metavar='N',
	                   help='The step the series was measured in, e.g. 100. Default: the '
	                        'commonest spacing of the values, when there is a clear one.')
	steps.add_argument('--fill', action='store_true',
	                   help='Fill steps that have no pattern by interpolating linearly between '
	                        'the measured patterns either side. Default: leave them hatched.')
	steps.add_argument('--smooth', action='store_true',
	                   help='Blend linearly between neighbouring steps instead of drawing each '
	                        'as a band.')

	xs = parser.add_argument_group('x axis')
	quantities = tuple(kit.X_QUANTITIES)
	xs.add_argument('--x-data', choices=quantities, default=None,
	                help='What the first column of the files is: 2theta in degrees, q in '
	                     '1/angstrom or q-nm in 1/nm. Default: what a pyFAI or DIOPTAS header '
	                     'says, else 2theta.')
	xs.add_argument('--x-axis', choices=quantities, default=None,
	                help='What the x axis shows, when not that: 2theta and Q convert into '
	                     'each other with --wavelength.')
	xs.add_argument('--wavelength', type=_step_arg, default=None, metavar='ANGSTROM',
	                help='The wavelength, for converting between 2theta and Q, e.g. 0.2073. '
	                     'Default: from a pyFAI or DIOPTAS header.')
	xs.add_argument('--x-label', default=None, metavar='TEXT',
	                help='Label of the x axis, over the one the quantity has.')
	xs.add_argument('--range', nargs=2, type=float, default=None, metavar=('LO', 'HI'),
	                help='The x range to show, in the units of the axis. Default: all of it, '
	                     'less any columns at the ends that are zero in every pattern.')

	look = parser.add_argument_group(
		'the figure', 'Ticks, fonts, sizes and the default colours come from your heatmap '
		              'style sheet: `achdiff style init heatmap` writes one listing every '
		              'setting. These flags override it for one plot.')
	look.add_argument('--cmap', default=None, metavar='SPEC',
	                  help='A matplotlib colormap, part of one (NAME:LOW:HIGH, 0 to 1), or '
	                       'colours to blend (white,#08306b). Default: the style sheet\'s, '
	                       f"else {DEFAULT_CMAP}, the paper's.")
	look.add_argument('--scale', choices=('linear', 'sqrt', 'log'), default=None,
	                  help="How intensity maps to colour. Default: the style sheet's, else sqrt, "
	                       "which puts a gas-cell pattern's background where the paper's sits. "
	                       'linear makes colour proportional to intensity; log brings up the '
	                       'weakest peaks.')
	look.add_argument('--limits', nargs=2, type=float, default=None, metavar=('LOW', 'HIGH'),
	                  help='The intensities at the two ends of the colour scale. Default: the '
	                       'lowest and highest shown.')
	look.add_argument('--normalize', action='store_true',
	                  help='Scale each pattern to its own maximum first, so a pattern counted '
	                       'for less time does not look paler.')
	look.add_argument('--label', default=None, metavar='TEXT',
	                  help='Text in the top right corner, e.g. "Mg$_2$(dobdc)".')
	look.add_argument('--colorbar', action='store_true',
	                  help='Add a colour bar (the paper has none).')
	look.add_argument('--size', nargs=2, type=float, default=None, metavar=('W', 'H'),
	                  help="Figure size in inches. Default: the style sheet's, else "
	                       f'{DEFAULT_SIZE[0]:g} {DEFAULT_SIZE[1]:g}.')
	look.add_argument('--dpi', type=int, default=None,
	                  help='Resolution of the saved image, and of the map inside an SVG or PDF. '
	                       "Default: the style sheet's, else 300.")
	look.add_argument('--name', default='heatmap',
	                  help='File name stem for -s output: NAME.svg and NAME_SI.txt (default: '
	                       '%(default)s).')
	kit.add_style_arguments(parser)
	kit.add_common_arguments(parser, extension=None)
	return parser


# ---------------------------------------------------------------- the patterns

def folder_patterns(folder='.'):
	"""The pattern files in `folder`, of its most common pattern type, so a .raw
	and the .xy converted from it are not both drawn: (names, suffix, others),
	`others` counting the files of the types left out. .txt and .csv count only
	when nothing else is there."""
	by_type = {}
	for entry in sorted(Path(folder).iterdir(), key=lambda p: kit.natural_key(p.name)):
		suffix = entry.suffix.lower()
		if entry.is_file() and suffix in kit.PATTERN_TYPES:
			by_type.setdefault(suffix, []).append(entry.name)
	if not by_type:
		return [], None, {}
	pool = {s: n for s, n in by_type.items() if s not in _AMBIGUOUS_TYPES} or by_type
	order = list(kit.PATTERN_TYPES)
	suffix = max(pool, key=lambda s: (len(pool[s]), -order.index(s)))
	others = {s: len(n) for s, n in by_type.items() if s != suffix}
	return by_type[suffix], suffix, others


def expand(entries):
	"""-i as files: wildcards expanded here, since cmd and PowerShell leave that to
	the program, and a folder taken as its patterns. (paths, entries that named
	nothing)."""
	paths, missing = [], []
	for entry in entries:
		if os.path.isdir(entry):
			hits = [os.path.join(entry, n) for n in folder_patterns(entry)[0]]
		elif set(entry) & set('*?['):
			hits = sorted((h for h in glob(entry) if os.path.isfile(h)),
			              key=lambda p: kit.natural_key(Path(p).name))
		else:
			hits = None
		if hits is not None:
			if hits:
				paths.extend(hits)
			else:
				missing.append(entry)
		elif os.path.isfile(entry):
			paths.append(entry)
		else:
			missing.append(entry)
	seen = set()
	return [p for p in paths if not (p in seen or seen.add(p))], missing


# ------------------------------------------------------ values and order, by name

def _number(text):
	"""'2.5' or '2,5' -> 2.5; None for anything else."""
	if text is None:
		return None
	text = text.strip()
	if text.count(',') == 1 and '.' not in text:
		text = text.replace(',', '.')
	try:
		return float(text)
	except ValueError:
		return None


def _unit(text):
	return '°C' if text in ('C', 'degC') else text


def _some(names, at_most=3):
	shown = ', '.join(names[:at_most])
	return shown + (f' and {len(names) - at_most} more' if len(names) > at_most else '')


def from_units(names):
	"""(values, unit) from the number before a unit in each name; a name without
	that unit gets None, and no name with a unit at all gives (None, None).

	Where the names carry more than one unit, the one whose number changes from
	file to file: a constant 25C in the names of a pressure series is passed over."""
	found = []
	for name in names:
		hits = {}
		for m in _UNIT_NUMBER.finditer(name):
			hits.setdefault(_unit(m.group(2)), _number(m.group(1)))
		found.append(hits)
	units = {u for hits in found for u in hits}
	if not units:
		return None, None
	preference = PRESSURE_UNITS + TEMPERATURE_UNITS

	def rank(unit):
		carried = [hits[unit] for hits in found if unit in hits]
		return len(set(carried)), len(carried), -preference.index(unit)

	unit = max(units, key=rank)
	return [hits.get(unit) for hits in found], unit


def from_template(names, template, flag='--y-name'):
	"""The number at the one # of a wildcard template, in each name. Raises
	ValueError, naming the names, for a template that misses or fits two ways."""
	if template.count('#') != 1:
		raise ValueError(f'{flag} {template!r} needs exactly one #, where the value is')
	found = kit.template_numbers(names, template)
	missed = [n for n, f in zip(names, found) if f is None]
	if missed:
		raise ValueError(f'{flag} {template!r} does not fit {_some(missed)}. A template covers '
		                 f'the whole name: * for any text, # for the number, e.g. *_#bar_*.')
	return [f[0] for f in found]


def from_regex(names, regex, flag='--y-regex'):
	"""The number `regex` captures from each name: its first group, or the whole
	match when it has none. Raises ValueError naming the names it misses."""
	try:
		compiled = re.compile(regex)
	except re.error as e:
		raise ValueError(f'{flag} {regex!r} is not a valid regular expression ({e})') from None
	values, missed = [], []
	for name in names:
		m = compiled.search(name)
		value = _number((m.group(1) if compiled.groups else m.group(0)) if m else None)
		if value is None:
			missed.append(name)
		values.append(value)
	if missed:
		raise ValueError(f'{flag} {regex!r} finds no number in {_some(missed)}')
	return values


class _Named:
	"""A path that sorts by its file name, for kit.sort_by_pattern."""

	def __init__(self, path):
		self.path = path

	def __str__(self):
		return Path(self.path).name


def measurement_order(paths, template=None, regex=None):
	"""(paths in measurement order, how that was decided, the order numbers or None).

	By the #s of a template, by a regex's groups, or else by how the names sort.
	The numbers come back when there is one per name, to spot a measurement that
	is not there. Raises ValueError naming the names a template or regex misses."""
	names = [Path(p).name for p in paths]
	if template:
		found = kit.template_numbers(names, template)
		missed = [n for n, f in zip(names, found) if f is None]
		if missed:
			raise ValueError(f'--order-name {template!r} does not fit {_some(missed)}. A '
			                 f'template covers the whole name: * for any text, # for the '
			                 f'number, e.g. #_*.')
		ranked = sorted(range(len(paths)), key=lambda i: found[i])
		numbers = [found[i][0] for i in ranked] if template.count('#') == 1 else None
		return [paths[i] for i in ranked], f'by the number at # in {template}', numbers
	if regex:
		ordered, unmatched = kit.sort_by_pattern([_Named(p) for p in paths], regex)
		if unmatched:
			raise ValueError(f'--order-regex {regex!r} does not match '
			                 f'{_some([str(u) for u in unmatched])}')
		ordered = [o.path for o in ordered]
		try:
			numbers = from_regex([Path(p).name for p in ordered], regex, '--order-regex')
		except ValueError:
			numbers = None
		return ordered, f'by the regular expression {regex}', numbers
	ranked = sorted(range(len(paths)), key=lambda i: (kit.natural_key(names[i]), i))
	ordered = [paths[i] for i in ranked]
	leading = [re.match(r'(\d+)(?=\D)', Path(p).name) for p in ordered]
	numbers = [float(m.group(1)) for m in leading] if all(leading) else None
	return ordered, 'the order the file names sort in', numbers


def sequence_gaps(numbers):
	"""Whole numbers missing from a run of them: [36, 37] from 0 ... 35, 38. Empty
	when the numbers are not a run (not whole, or more missing than present)."""
	if not numbers or any(not float(n).is_integer() for n in numbers):
		return []
	present = {int(n) for n in numbers}
	missing = sorted(set(range(min(present), max(present) + 1)) - present)
	return missing if len(missing) < len(present) else []


def axis_label(unit):
	if unit in PRESSURE_UNITS:
		return f'$p$ / {unit}'
	if unit in TEMPERATURE_UNITS:
		return f'$T$ / {unit}'
	return ''


def series(paths, y_values=None, y_name=None, y_regex=None, order_name=None,
           order_regex=None, y_label=None):
	"""The patterns, in measurement order, with their values and the axis label: a
	Series. Raises ValueError for anything that would draw a wrong map."""
	ordered, order_how, order_numbers = measurement_order(paths, order_name, order_regex)
	names = [Path(p).name for p in ordered]
	unit_values, unit = from_units(names)
	if y_values is not None:
		if len(y_values) != len(ordered):
			listing = '\n'.join(f'    {i:>4}  {n}' for i, n in enumerate(names, 1))
			raise ValueError(f'--y-values gives {len(y_values)} values for {len(ordered)} '
			                 f'patterns. They go to the patterns in this order:\n{listing}')
		values = [float(v) for v in y_values]
		values_how = 'given with --y-values, in measurement order'
	elif y_name is not None:
		values = from_template(names, y_name)
		values_how = f'read from the file names with the template {y_name}'
	elif y_regex is not None:
		values = from_regex(names, y_regex)
		values_how = f'read from the file names with the regular expression {y_regex}'
	elif unit_values is not None:
		bare = [n for n, v in zip(names, unit_values) if v is None]
		if bare:
			raise ValueError(f'the file names give values in {unit}, but not {_some(bare)}. '
			                 f'Leave those out with -i, or say where the value is with --y-name.')
		values = unit_values
		values_how = f'read from the file names: the number before "{unit}"'
	else:
		values = [float(i) for i in range(1, len(ordered) + 1)]
		values_how = 'numbered in measurement order (the file names give no values)'

	shared = {}
	for value, name in zip(values, names):
		shared.setdefault(value, []).append(name)
	twice = {v: n for v, n in shared.items() if len(n) > 1}
	if twice:
		v, clash = next(iter(twice.items()))
		raise ValueError(f'{len(clash)} patterns have the value {v:g}: {_some(clash)}. A run '
		                 f'that comes back down needs one map per leg (choose each with -i), '
		                 f'and a repeat needs leaving out.')

	if y_label is not None:
		label = y_label
	elif values_how.startswith('numbered'):
		label = 'pattern'
	elif unit_values is not None and all(
			u is not None and abs(u - v) <= 1e-9 * max(1.0, abs(v))
			for u, v in zip(unit_values, values)):
		label = axis_label(unit)      # the values are the very numbers the unit follows
	else:
		label = ''
	shown_unit = label.split('/')[-1].replace('$', '').strip() if '/' in label else ''
	return Series(ordered, values, label, shown_unit, values_how, order_how, order_numbers)


# ---------------------------------------------------------------------- steps

def nominal_step(values, step=None):
	"""(step, anchor) of the regular grid the values were measured on, or None.

	Without `step`: the commonest spacing between neighbouring values, if two
	thirds of the spacings are within 2 % of it -- so 1, 100, 200 ... is a series
	in steps of 100, its first pattern at ambient. Either way every value has to
	sit within a quarter step of the grid, one pattern to a step; the grid runs
	through zero where it can, through the first value where not. Raises
	ValueError when a `step` given does not fit the values."""
	v = np.asarray(sorted(values), dtype=float)
	if v.size < 2:
		return None
	gaps = np.diff(v)
	if step is None:
		spacings, counts = np.unique(np.round(gaps, 9), return_counts=True)
		size = float(spacings[counts.argmax()])
		if size <= 0 or np.sum(np.abs(gaps - size) <= 0.02 * size) < 2 / 3 * gaps.size:
			return None
	else:
		size = float(step)
	for anchor in (0.0, float(v[0])):
		k = (v - anchor) / size
		if (np.all(np.abs(k - np.round(k)) <= 0.25)
				and len(set(np.round(k).astype(int))) == v.size):
			return size, anchor
	if step is not None:
		raise ValueError(f'--step {step:g}: the values do not sit one to a step of {step:g} '
		                 f'(they are {_some([f"{x:g}" for x in v], 6)})')
	return None


def plan_steps(values, step=None, fill=False):
	"""The bands of the map, by rising value: ([Step], grid), grid being (step,
	anchor) or None. `values` must rise; a Step's mix points into them.

	On a regular grid every step of it is a band, measured or not: a step with no
	pattern is 'missing', or with `fill` 'filled' from the nearest measured steps
	either side, weighted by distance. Off any grid each pattern is a band of its
	own, reaching half way to its neighbours, and there is nothing to fill."""
	grid = nominal_step(values, step)
	if grid is None:
		return [Step(float(v), 'measured', ((i, 1.0),)) for i, v in enumerate(values)], None
	size, anchor = grid
	index = {int(round((v - anchor) / size)): i for i, v in enumerate(values)}
	measured = sorted(index)
	steps = []
	for k in range(measured[0], measured[-1] + 1):
		centre = round(anchor + k * size, 9)
		if k in index:
			steps.append(Step(centre, 'measured', ((index[k], 1.0),)))
		elif fill:
			below = max(m for m in measured if m < k)
			above = min(m for m in measured if m > k)
			w = (k - below) / (above - below)
			steps.append(Step(centre, 'filled', ((index[below], 1.0 - w), (index[above], w))))
		else:
			steps.append(Step(centre, 'missing', ()))
	return steps, grid


def bands(steps):
	"""(from, to) of each step's band: half way to the steps either side, and as
	far again beyond the first and last, so the patterns at the ends get whole
	bands rather than slivers under the frame. The axis runs from the first band's
	bottom to the last band's top."""
	c = [s.centre for s in steps]
	mids = [(a + b) / 2 for a, b in zip(c, c[1:])]
	return list(zip([c[0] - (c[1] - c[0]) / 2] + mids, mids + [c[-1] + (c[-1] - c[-2]) / 2]))


# --------------------------------------------------------------------- x grid

def x_setup(paths, x_data=None, x_axis=None, wavelength=None):
	"""What the x column is, what the axis shows, and the wavelength between them,
	each with how it was decided: a dict for run and the SI notes.

	The flags first; then what pyFAI or DIOPTAS headers say; else 2theta. Raises
	ValueError for headers that disagree with each other, and for a conversion
	between 2theta and Q with no wavelength from either."""
	found = [kit.x_from_header(p) for p in paths]
	keys = sorted({k for k, _w in found if k})
	waves = [w for _k, w in found if w]
	if len(keys) > 1:
		raise ValueError(f'the file headers disagree on what the x column is '
		                 f'({", ".join(keys)}); choose the files with -i')
	header = keys[0] if keys else None
	warning = None
	if x_data:
		data, data_how = x_data, 'given with --x-data'
		if header and header != x_data:
			warning = f'--x-data {x_data}, but the file headers say {header}'
	elif header:
		data, data_how = header, 'from the file headers'
	else:
		data, data_how = '2theta', 'taken as 2θ: no --x-data, and no header saying otherwise'
	axis = x_axis or data
	if wavelength:
		lam, lam_how = float(wavelength), 'given with --wavelength'
	elif waves:
		lam, lam_how = waves[0], 'from the file headers'
	else:
		lam, lam_how = None, ''
	if kit.X_QUANTITIES[data].name != kit.X_QUANTITIES[axis].name and lam is None:
		raise ValueError(f'showing {axis} from files in {data} needs the wavelength: '
		                 f'--wavelength, in angstrom')
	return {'data': data, 'axis': axis, 'wavelength': lam, 'data_how': data_how,
	        'wavelength_how': lam_how, 'warning': warning, 'regridded': False}


def _even(x):
	"""Whether x is evenly stepped and rising: every point within a tenth of a step
	of where an even grid puts it, so a column rounded in a text file still counts."""
	step = (x[-1] - x[0]) / (x.size - 1) if x.size > 1 else 0.0
	return bool(step > 0 and np.all(np.abs(x - np.linspace(x[0], x[-1], x.size)) <= 0.1 * step))


def common_grid(patterns):
	"""(xgrid, Z): every pattern on one evenly stepped x grid, Z with one row per
	pattern. Patterns from one detector share their grid and are used as they are;
	others are interpolated onto the range they all cover, at the finest step among
	them. Raises ValueError when they share no range."""
	xs = [np.asarray(x, dtype=float) for x, _y in patterns]
	first = xs[0]
	shared = all(x.shape == first.shape and np.allclose(x, first, rtol=0, atol=1e-6) for x in xs)
	if _even(first) and shared:
		return first.copy(), np.vstack([np.asarray(y, dtype=float) for _x, y in patterns])

	lo = max(x.min() for x in xs)
	hi = min(x.max() for x in xs)
	if hi <= lo:
		raise ValueError('the patterns have no x range in common')
	step = min(np.median(np.abs(np.diff(x))) for x in xs if x.size > 1)
	grid = lo + np.arange(int(np.floor((hi - lo) / step + 1e-9)) + 1) * step
	rows = []
	for x, (_x, y) in zip(xs, patterns):
		order = np.argsort(x)
		rows.append(np.interp(grid, x[order], np.asarray(y, dtype=float)[order]))
	return grid, np.vstack(rows)


def even_grid(x, Z):
	"""(grid, Z) on an evenly stepped grid over x's range, at its finest step. A
	conversion between 2theta and Q needs it: Q is not linear in 2theta, and the
	image is drawn on even columns. An x already even comes back as it is."""
	x = np.asarray(x, dtype=float)
	if x[0] > x[-1]:
		x, Z = x[::-1], Z[:, ::-1]
	if _even(x):
		return x, Z
	step = float(np.min(np.diff(x)))
	n = min(int(np.floor((x[-1] - x[0]) / step + 1e-9)) + 1, 4 * x.size)
	grid = np.linspace(x[0], x[-1], n)
	return grid, np.vstack([np.interp(grid, x, row) for row in Z])


def crop(xgrid, Z, window=None):
	"""The columns to show: `window` (lo, hi) if given; otherwise all but the
	columns at either end that are zero in every pattern -- a masked detector edge
	holds no data and would only stretch the axis. Raises ValueError for a window
	that leaves fewer than two points."""
	keep = np.ones(xgrid.size, dtype=bool)
	if window is not None:
		lo, hi = sorted(window)
		keep &= (xgrid >= lo) & (xgrid <= hi)
	else:
		live = np.flatnonzero(np.any(Z != 0, axis=0))
		if live.size:
			keep[:live[0]] = False
			keep[live[-1] + 1:] = False
	if keep.sum() < 2:
		raise ValueError(f'the x range {window[0]:g} to {window[1]:g} holds no data '
		                 f'(the patterns cover {xgrid[0]:g} to {xgrid[-1]:g})'
		                 if window is not None else 'every pattern is zero throughout')
	return xgrid[keep], Z[:, keep]


# ------------------------------------------------------------------- the image

def rows_needed(centres, low, high):
	"""Enough rows that the narrowest band gets a dozen, within 200 to 4000."""
	gap = float(np.diff(centres).min()) if len(centres) > 1 else float(high - low)
	return int(np.clip(np.ceil(12 * (high - low) / gap), 200, 4000))


def step_patterns(Z, steps):
	"""One row per step: its measured pattern, the blend that fills it, or NaN."""
	S = np.full((len(steps), Z.shape[1]), np.nan, dtype=np.float32)
	for k, step in enumerate(steps):
		if step.mix:
			S[k] = sum(w * Z[i] for i, w in step.mix)
	return S


def image(Z, steps, low, high, smooth=False, n_rows=None):
	"""The map as an (n_rows, columns) array covering low to high, bottom row
	first; NaN where a step has no pattern.

	Each row is the step nearest to it, so a band is the same row repeated -- the
	stretching that turns a few dozen patterns into a map. Smooth, a row is the
	straight-line blend of the steps either side of it, except next to a step
	with no pattern, which keeps its band."""
	centres = np.array([s.centre for s in steps], dtype=float)
	S = step_patterns(np.asarray(Z, dtype=np.float32), steps)
	edges = np.linspace(low, high, (n_rows or rows_needed(centres, low, high)) + 1)
	rows = (edges[:-1] + edges[1:]) / 2
	img = S[np.searchsorted((centres[:-1] + centres[1:]) / 2, rows, side='right')]
	if smooth and len(steps) > 1:
		upper = np.clip(np.searchsorted(centres, rows, side='right'), 1, len(centres) - 1)
		lower = upper - 1
		w = np.clip((rows - centres[lower]) / (centres[upper] - centres[lower]), 0, 1)
		w = w.astype(np.float32)[:, None]
		blend = S[lower] * (1 - w) + S[upper] * w
		img = np.where(np.isfinite(blend), blend, img)
	return img


def colormap(spec):
	"""A matplotlib colormap from --cmap: a name ('PuBu', 'viridis_r'), part of one
	('PuBu:0.28' or 'PuBu:0.28:0.9', fractions of the way along), or colours to
	blend ('white,#08306b', 'white,tab:blue,navy'). Raises ValueError."""
	import matplotlib
	from matplotlib.colors import LinearSegmentedColormap, ListedColormap, is_color_like

	spec = spec.strip()
	if ',' in spec:
		colours = [c.strip() for c in spec.split(',') if c.strip()]
		bad = [c for c in colours if not is_color_like(c)]
		if bad:
			raise ValueError(f'not a colour: {", ".join(bad)}')
		if len(colours) < 2:
			raise ValueError('blending needs at least two colours')
		return LinearSegmentedColormap.from_list(spec, colours)

	name, _, cut = spec.partition(':')
	known = {n.lower(): n for n in matplotlib.colormaps}
	if name.lower() not in known:
		import difflib
		close = difflib.get_close_matches(name.lower(), list(known), n=3)
		hint = f' Did you mean {", ".join(known[c] for c in close)}?' if close else ''
		raise ValueError(f'matplotlib has no colormap called {name!r}.{hint}')
	base = matplotlib.colormaps[known[name.lower()]]
	if not cut:
		return base
	parts = cut.split(':')
	try:
		low = float(parts[0]) if parts[0] else 0.0
		high = float(parts[1]) if len(parts) > 1 and parts[1] else 1.0
	except ValueError:
		raise ValueError(f'{spec!r}: the part is NAME:LOW:HIGH, two numbers from 0 to 1') from None
	if len(parts) > 2 or not 0 <= low < high <= 1:
		raise ValueError(f'{spec!r}: the part is NAME:LOW:HIGH with 0 <= LOW < HIGH <= 1')
	return ListedColormap(base(np.linspace(low, high, 256)), name=spec)


def colour_limits(Z, scale, given=None):
	"""(low, high) for the colour scale. Raises ValueError for limits the scale
	cannot use."""
	if given is not None:
		low, high = given
		if not low < high:
			raise ValueError(f'--limits {low:g} {high:g}: the first must be the lower')
		if scale == 'log' and low <= 0:
			raise ValueError('--limits: a log scale starts above zero')
		return float(low), float(high)
	finite = Z[np.isfinite(Z)]
	if scale == 'log':
		finite = finite[finite > 0]
		if not finite.size:
			raise ValueError('nothing above zero to put on a log scale')
	if not finite.size or finite.min() == finite.max():
		raise ValueError('every intensity shown is the same, so there is nothing to colour')
	return float(finite.min()), float(finite.max())


def series_ticks(low, high, bottom=None, top=None, nbins=3):
	"""(major ticks, minor ticks) for the series axis.

	Majors are round numbers across the measured values, low to high, but the
	first value always gets a tick and a label, as the paper's "1" bar does, and
	so does the last when no round number is near it. Minors fall half way
	between round numbers, across the whole axis (bottom to top), and none sits
	on top of a major -- no minor at 0 beside the major at 1."""
	from matplotlib.ticker import MaxNLocator
	raw = MaxNLocator(nbins=nbins, steps=[1, 2, 2.5, 5, 10]).tick_values(low, high)
	half = float(raw[1] - raw[0]) / 2
	span = high - low
	near = 1e-9 * span
	ticks = [t for t in raw if low - near <= t <= high + near]
	if not ticks or ticks[0] - low > near:
		ticks = [low] + [t for t in ticks if t - low > 0.2 * span]
	if high - ticks[-1] > 0.2 * span:
		ticks.append(high)
	bottom = low if bottom is None else bottom
	top = high if top is None else top
	minors = [float(m) for m in np.arange(np.ceil(bottom / half) * half, top + near, half)
	          if all(abs(m - t) > 0.2 * half for t in ticks)]
	return [float(t) for t in ticks], minors


def figure(xgrid, Z, steps, low, high, x_label, y_label, cmap, norm, args, dpi=100, look=None):
	"""The heat map, drawn the way the paper's Fig. 2 is: (figure, image shape).
	Nothing is written inside the plot unless --label asks for it. `look` is the
	settings with any style sheet applied; draw it inside rc_context(rc_params(look))."""
	import matplotlib.pyplot as plt
	from matplotlib.ticker import (AutoMinorLocator, FixedLocator, FuncFormatter,
	                               MultipleLocator, NullLocator)

	look = settings if look is None else look
	# run() has settled these from the style; a direct call may not have.
	size = tuple(args.size or look['figsize'])
	scale = args.scale or look['intensity_scale']

	step = (xgrid[-1] - xgrid[0]) / (xgrid.size - 1)
	window = [xgrid[0], xgrid[-1]]
	if args.range:
		# No further than the data: past it there is nothing to draw but white.
		window = [max(min(args.range), window[0]), min(max(args.range), window[1])]

	edges = bands(steps)
	bottom, top = edges[0][0], edges[-1][1]
	img = image(Z, steps, bottom, top, smooth=args.smooth)
	if scale == 'log':
		# Zeros would be masked, and masked is how a missing step shows through.
		img = np.where(np.isnan(img), np.nan, np.maximum(img, norm.vmin))
	fig, ax = plt.subplots(figsize=size, dpi=dpi, layout='constrained')
	for (lo, hi), s in zip(edges, steps):
		if s.kind == 'missing':
			ax.axhspan(lo, hi, facecolor=look['gap_fill'], edgecolor=look['gap_color'],
			           hatch='////', linewidth=0, zorder=0.5)
	shown = ax.imshow(img, cmap=cmap, norm=norm, zorder=1,
	                  extent=(xgrid[0] - step / 2, xgrid[-1] + step / 2, bottom, top),
	                  origin='lower', aspect='auto', interpolation='antialiased')
	ax.set_xlim(*window)
	ax.set_ylim(bottom, top)

	ticks, minors = series_ticks(low, high, bottom, top, nbins=3 if size[1] <= 2 else 6)
	ax.yaxis.set_major_locator(FixedLocator(ticks))
	ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _pos: f'{v:g}'))
	if look['x_tick_step'] > 0:
		ax.xaxis.set_major_locator(MultipleLocator(look['x_tick_step']))
	if look['minor_ticks']:
		ax.yaxis.set_minor_locator(FixedLocator(minors))
		ax.xaxis.set_minor_locator(AutoMinorLocator())
	else:
		ax.yaxis.set_minor_locator(NullLocator())
		ax.xaxis.set_minor_locator(NullLocator())
	ax.set_xlabel(x_label)
	ax.set_ylabel(y_label)
	if args.label:
		ax.text(0.985, 0.93, args.label, transform=ax.transAxes, ha='right', va='top', zorder=3,
		        fontsize=look['label_size'])
	if args.colorbar:
		bar = fig.colorbar(shown, ax=ax, pad=0.02, aspect=12)
		bar.set_label('normalised intensity' if args.normalize else 'intensity')
		bar.ax.tick_params(direction=look['tick_direction'])
	return fig, img.shape


# ------------------------------------------------------------------- SI notes

def _join(items):
	items = list(items)
	return items[0] if len(items) == 1 else f'{", ".join(items[:-1])} and {items[-1]}'


def _quantity(unit):
	if unit in PRESSURE_UNITS:
		return 'pressure'
	if unit in TEMPERATURE_UNITS:
		return 'temperature'
	return 'value'


def si_paragraph(n, ser, steps, grid, low, high, args, xinfo):
	"""The processing, as a paragraph for the supporting information. `xinfo` says
	what the x axis is and how it got there (see run)."""
	u = f' {ser.unit}' if ser.unit else ''
	quantity = _quantity(ser.unit)
	gaps = [s for s in steps if s.kind != 'measured']
	if grid:
		size = grid[0]
		text = (f'The heat map was constructed from {n} powder diffraction patterns recorded '
		        f'between {low:g} and {high:g}{u} in nominal steps of {size:g}{u}.')
		if gaps:
			text += (f' No pattern was recorded at {_join(f"{s.centre:g}" for s in gaps)}{u}; '
			         + ('these steps were filled by linear interpolation between the nearest '
			            'measured patterns on either side.' if args.fill
			            else 'these steps are shown hatched.'))
		text += (f' Each pattern is displayed as a horizontal band covering ±{size / 2:g}{u} '
		         f'around its nominal {quantity}, so that each pattern represents one '
		         f'{size:g}{u} step of the {quantity} axis.')
	else:
		text = (f'The heat map was constructed from {n} powder diffraction patterns recorded at '
		        f'{quantity}s between {low:g} and {high:g}{u}. Each pattern is displayed as a '
		        f'horizontal band reaching halfway to the neighbouring {quantity}s.')
	if args.smooth:
		text += ' Colours were blended linearly between neighbouring steps.'
	elif not (grid and gaps and args.fill):
		text += ' No interpolation was applied between patterns.'
	scale = {'linear': 'a linear', 'sqrt': 'a square-root', 'log': 'a logarithmic'}[args.scale]
	text += (f' Intensities are shown on {scale} colour scale'
	         + (' after scaling each pattern to its own maximum' if args.normalize else '') + '.')
	data, axis = kit.X_QUANTITIES[xinfo['data']], kit.X_QUANTITIES[xinfo['axis']]
	if data.key != axis.key and data.name == axis.name:
		text += f' Q was converted from {data.unit} to {axis.unit}.'
	elif data.key != axis.key:
		text += (f' The patterns were converted from {data.symbol} to {axis.symbol} with '
		         f'λ = {xinfo["wavelength"]:g} Å'
		         + (f' and interpolated linearly onto an even {axis.symbol} grid.'
		            if xinfo['regridded'] else '.'))
	elif xinfo['regridded']:
		text += f' The patterns were interpolated linearly onto a common {axis.symbol} grid.'
	else:
		text += f' No smoothing or interpolation was applied along {axis.symbol}.'
	return text


def _with_unit(text, quantity):
	"""'11.99' -> '11.99°' or '11.99 Å⁻¹': a degree sign sits on the number."""
	return f'{text}{quantity.unit}' if quantity.unit == '°' else f'{text} {quantity.unit}'


def si_notes(facts):
	"""NAME_SI.txt: how the map was made, in words for the supporting information
	and in numbers for whoever checks it."""
	ser, steps, grid = facts['series'], facts['steps'], facts['grid']
	low, high, args = facts['low'], facts['high'], facts['args']
	xgrid, n, xinfo = facts['xgrid'], len(ser.paths), facts['xinfo']
	data, axis = kit.X_QUANTITIES[xinfo['data']], kit.X_QUANTITIES[xinfo['axis']]
	u = f' {ser.unit}' if ser.unit else ''
	edges = bands(steps)
	bottom, top = edges[0][0], edges[-1][1]
	span = top - bottom
	rows, columns = facts['image_shape']
	px_w, px_h = facts['plot_px']
	gaps = [s for s in steps if s.kind != 'measured']
	wrap = textwrap.TextWrapper(width=92)
	field = textwrap.TextWrapper(width=92, initial_indent='', subsequent_indent=' ' * 15)

	def line(label, text):
		return field.fill(f'{label:<15}{text}')

	out = [line('Heat map', facts['figure']),
	       line('Made', f'{facts["when"]:%Y-%m-%d %H:%M} by achdiff misc run heatmap '
	                    f'(ach-diffraction-suite {kit.SUITE_VERSION})'),
	       line('Command', getattr(args, 'typed_command', '') or '(not recorded)'),
	       '', 'For the supporting information', '-' * 30,
	       wrap.fill(si_paragraph(n, ser, steps, grid, low, high, args, xinfo)),
	       '', 'How the map was made', '-' * 20]

	suffixes = sorted({Path(p).suffix.lower() for p in ser.paths})
	shared = ('interpolated onto one even grid' if xinfo['regridded'] else 'all on one grid')
	upto = _with_unit('%.4g' % xgrid[-1], axis)
	every = _with_unit('%.5g' % facts['x_step'], axis)
	out.append(line('Patterns', f'{n} files ({", ".join(suffixes)}); {axis.symbol} '
	                            f'{xgrid[0]:.4g} to {upto} in steps of {every}, '
	                            f'{xgrid.size} points shown, {shared}'
	                            + (' (columns zero in every pattern left out at the ends)'
	                               if facts['trimmed'] else '')))
	if data.key == axis.key:
		text = f'{axis.symbol} in {axis.unit}, as in the files ({xinfo["data_how"]})'
	else:
		text = (f'{axis.symbol} in {axis.unit}, converted from {data.symbol} in {data.unit} in '
		        f'the files ({xinfo["data_how"]})')
		if data.name != axis.name:
			text += f' with λ = {xinfo["wavelength"]:g} Å ({xinfo["wavelength_how"]})'
	out.append(line('X axis', text))
	out.append(line('Values', ser.values_how))
	order = ser.order_how
	missing_numbers = sequence_gaps(ser.order_numbers)
	if ser.order_numbers and missing_numbers:
		order += (f'; the order numbers run {min(ser.order_numbers):g} to '
		          f'{max(ser.order_numbers):g} without {_join(str(m) for m in missing_numbers)}')
	out.append(line('Order', order))
	out.append(line('Axis', f'patterns from {low:g} to {high:g}{u}; the axis runs {bottom:g} to '
	                        f'{top:g}{u}, half a step beyond the first and last, so that they '
	                        f'get whole bands too'))
	if grid:
		size = grid[0]
		how = 'given with --step' if args.step else 'the commonest spacing of the values'
		text = (f'{size:g}{u} ({how}): {len(steps)} steps, {n} measured')
		if gaps:
			text += (f', {len(gaps)} without a pattern ({_join(f"{s.centre:g}" for s in gaps)}{u}), '
			         + ('filled by linear interpolation between the measured steps either side'
			            if args.fill else 'shown hatched'))
		out.append(line('Steps', text))
		out.append(line('Bands', f'each step is drawn ±{size / 2:g}{u} around its value: each of '
		                         f'the {n} patterns stands for {size:g}{u} of the axis'))
	else:
		out.append(line('Steps', 'no regular step (--step N sets one); each pattern reaches '
		                         'half way to its neighbours, so the bands differ in height'))
	per_step = rows * (grid[0] if grid else span / max(n - 1, 1)) / span
	out.append(line('Stretching', f'the map is {rows} rows by {columns} columns, about '
	                              f'{per_step:.0f} identical rows per step'
	                              + (', blended between neighbouring steps' if args.smooth else '')
	                              + f'. In the saved figure the plot is {px_w} x {px_h} px at '
	                                f'{args.dpi} dpi: about {px_h * per_step / rows:.1f} px per '
	                                f'step, and {columns / max(px_w, 1):.1f} points of '
	                                f'{axis.symbol} per pixel, averaged for display only'))
	out.append(line('Colours', f'{args.cmap}, {args.scale} scale, {facts["colour"][0]:.4g} to '
	                           f'{facts["colour"][1]:.4g}'
	                           + (' (given with --limits)' if args.limits else
	                              ' (the lowest and highest intensity shown)')
	                           + ('; each pattern scaled to its own maximum first'
	                              if args.normalize else '')))
	out.append(line('Figure', f'{args.size[0]:g} x {args.size[1]:g} in, {args.dpi} dpi'))

	# The patterns in measurement order, the steps without one where they fall.
	step_of = {}
	for k, s in enumerate(steps):
		if s.kind == 'measured':
			step_of[s.mix[0][0]] = k
	by_value = sorted(range(n), key=lambda i: ser.values[i])
	rank_of = {i: r for r, i in enumerate(by_value)}
	rows_out = []
	for position, (path, value) in enumerate(zip(ser.paths, ser.values), 1):
		lo, hi = edges[step_of[rank_of[position - 1]]]
		rows_out.append((value, f'{position:>4}', Path(path).name, value, lo, hi, 'measured'))
	values_by_rank = [ser.values[i] for i in by_value]
	for k, s in enumerate(steps):
		if s.kind == 'measured':
			continue
		lo, hi = edges[k]
		if s.kind == 'filled':
			(a, wa), (b, wb) = s.mix
			drawn = (f'interpolated: {wa:.2f} x {values_by_rank[a]:g} + '
			         f'{wb:.2f} x {values_by_rank[b]:g}')
		else:
			drawn = 'hatched, no pattern'
		rows_out.append((s.centre, '   -', '(no pattern)', s.centre, lo, hi, drawn))
	rising = all(a < b for a, b in zip(ser.values, ser.values[1:]))
	falling = all(a > b for a, b in zip(ser.values, ser.values[1:]))
	measured_rows = [r for r in rows_out if r[6] == 'measured']
	gap_rows = [r for r in rows_out if r[6] != 'measured']
	if rising or falling:
		rows_out = sorted(rows_out, key=lambda r: r[0], reverse=falling)
	else:
		rows_out = measured_rows + gap_rows
	width = max(len(r[2]) for r in rows_out)
	head = ser.unit or 'value'
	out += ['', 'Patterns in measurement order', '-' * 29,
	        f'   #  {"file":<{width}}  {head:>9}  {"band from":>10}  {"to":>9}  drawn as']
	for _key, pos, name, value, lo, hi, drawn in rows_out:
		out.append(f'{pos}  {name:<{width}}  {value:>9g}  {lo:>10g}  {hi:>9g}  {drawn}')
	return '\n'.join(out) + '\n'


# ------------------------------------------------------------------ the wizard

def _summary(values, unit=''):
	shown = [f'{v:g}' for v in values]
	text = ', '.join(shown) if len(shown) <= 6 else f'{", ".join(shown[:3])} ... {shown[-1]}'
	return f'{text}{" " + unit if unit else ""} ({len(shown)} values)'


def _ask_template(prompt, check):
	"""A template (or re:REGEX) from the console, tried by `check` until it works.
	Returns (flag kind, text) -- ('name', '*_#bar_*') or ('regex', '...') -- or None."""
	while True:
		reply = kit.ask(prompt)
		if not reply:
			return None
		kind, text = ('regex', reply[3:]) if reply.lower().startswith('re:') else ('name', reply)
		try:
			check(kind, text)
			return kind, text
		except ValueError as e:
			print(f'    {e}')


def fill(args, parser):
	"""Run with no arguments in a console: ask for the patterns and the rest.
	Returns the answers as command-line tokens."""
	print('\n\n'.join(__doc__.strip().split('\n\n')[:2]))
	print()
	print('Enter takes the suggestion in [brackets].')
	print()
	names, suffix, others = folder_patterns()
	if not names:
		parser.error(f'no pattern files in {os.getcwd()}. Run it in the folder with your '
		             f'patterns, or pass -i.')
	values, unit = from_units(names)
	width = max(len(n) for n in names)
	labels = [n if not values else f'{n:<{width}}  ' + (f'{v:g} {unit}' if v is not None else '?')
	          for n, v in zip(names, values or [None] * len(names))]
	print(f'{suffix} patterns in this folder, in the order their names sort'
	      + (f' (also here: {", ".join(f"{k} x{n}" for k, n in others.items())})' if others else '')
	      + ':')
	picked = kit.choose(labels, 'Which go into the map?', default=range(len(names)),
	                    at_least=2)
	chosen = [names[i] for i in picked]
	extra = ['-i'] + ([f'*{suffix}'] if len(picked) == len(names) else chosen)
	opts = {}

	header, _wave = kit.x_from_header(chosen[0])
	if header:
		q = kit.X_QUANTITIES[header]
		print(f'The file header says the x column is {q.name} in {q.plain_unit}.')
	else:
		while True:
			reply = kit.ask('Is the x column 2theta (degrees), q (1/A) or q-nm (1/nm)?',
			                '2theta').lower()
			if reply in kit.X_QUANTITIES:
				break
			print(f'    One of: {", ".join(kit.X_QUANTITIES)}.')
		if reply != '2theta':
			extra += ['--x-data', reply]

	if not kit.ask_yes('Is that the order they were measured in?', default=True):
		def check_order(kind, text):
			key = {'template': text} if kind == 'name' else {'regex': text}
			ordered, _how, _n = measurement_order(chosen, **key)
			print('    In that order: ' + ', '.join(ordered[:3]) + (' ...' if len(ordered) > 3 else ''))
		answer = _ask_template('Where is the measurement number in the name? * for any text, # '
		                       'for the number, e.g. #_* (or re: and a regex):', check_order)
		if answer:
			flag = '--order-name' if answer[0] == 'name' else '--order-regex'
			extra += [flag, answer[1]]
			opts['order_name' if answer[0] == 'name' else 'order_regex'] = answer[1]

	try:
		found = series(chosen, **opts)
		detected = not found.values_how.startswith('numbered')
	except ValueError:
		found, detected = None, False
	if detected:
		print(f'Values from the file names: {_summary(sorted(found.values), found.unit)}')
	if not (detected and kit.ask_yes('Right?', default=True)):
		def check_values(kind, text):
			attempt = series(chosen, **opts, **{'y_name' if kind == 'name' else 'y_regex': text})
			print(f'    Reads {_summary(sorted(attempt.values), attempt.unit)}')
		answer = _ask_template('Where is the value in the name? * for any text, # for the number, '
		                       'e.g. *_#bar_* (or re: and a regex; Enter to number the patterns):',
		                       check_values)
		if answer:
			flag = '--y-name' if answer[0] == 'name' else '--y-regex'
			extra += [flag, answer[1]]
			opts['y_name' if answer[0] == 'name' else 'y_regex'] = answer[1]
			try:
				found = series(chosen, **opts)
			except ValueError:
				found = None
			if found is not None and not found.label:
				label = kit.ask('Label for that axis:', '$p$ / bar')
				extra += ['--y-label', label]
				opts['y_label'] = label

	if found is not None and not found.values_how.startswith('numbered'):
		try:
			steps, grid = plan_steps(sorted(found.values))
		except ValueError:
			steps, grid = [], None
		gaps = [f'{s.centre:g}' for s in steps if s.kind == 'missing']
		if grid and gaps:
			u = f' {found.unit}' if found.unit else ''
			print(f'Steps of {grid[0]:g}{u}, but no pattern at {_join(gaps)}{u}.')
			if kit.ask_yes('Fill those steps by interpolating between their neighbours? (No: '
			               'leave them hatched)'):
				extra.append('--fill')

	while True:
		window = kit.ask('x range to show, low and high, e.g. 2 12 (Enter for all of it):')
		parts = window.replace(',', ' ').split()
		if not parts:
			break
		if len(parts) == 2 and all(_number(p) is not None for p in parts):
			extra += ['--range'] + parts
			break
		print('    Two numbers, the low and the high end, e.g. 2 12.')
	label = kit.ask('Label in the top right corner, e.g. Mg$_2$(dobdc) (Enter for none):')
	if label:
		extra += ['--label', label]
	if not args.silent and kit.ask_yes('Save the figure (and the SI notes) instead of opening '
	                                   'a window?'):
		extra.append('-s')
	return extra


# --------------------------------------------------------------------- running

def run(args):
	# The look: built in, then the person's style sheets, then this command's flags.
	look = dict(settings)
	try:
		kit.apply_style('heatmap', look, user=args.user, explicit=args.style)
	except FileNotFoundError as e:
		print(f'[!] {e}')
		return 2
	args.size = tuple(args.size or look['figsize'])
	args.dpi = args.dpi or look['dpi']
	args.extension = args.extension or look['extension']
	args.cmap = args.cmap or look['colormap']
	args.scale = args.scale or look['intensity_scale']
	args.colorbar = args.colorbar or look['colorbar']

	try:
		cmap = colormap(args.cmap)
	except ValueError as e:
		print(f'[!] --cmap {args.cmap}: {e}')
		return 1

	if args.input:
		paths, missing = expand(args.input)
		for entry in missing:
			print(f'[!] -i {entry}: no such file.')
		if missing:
			return 1
	else:
		paths, suffix, others = folder_patterns()
		if paths:
			print(f'[*] Every {suffix} pattern in this folder ({len(paths)})'
			      + (f'; also here: {", ".join(f"{k} x{n}" for k, n in others.items())} '
			         f'(choose with -i)' if others else '') + '.')
	if len(paths) < 2:
		print(f'[!] A heat map needs at least two patterns; {"one was" if paths else "none were"} '
		      f'found{"" if args.input else " in " + os.getcwd()}.')
		return 1

	try:
		ser = series(paths, args.y_values, args.y_name, args.y_regex, args.order_name,
		             args.order_regex, args.y_label)
		by_value = sorted(range(len(ser.paths)), key=lambda i: ser.values[i])
		values = [ser.values[i] for i in by_value]
		steps, grid = plan_steps(values, args.step, args.fill)
	except ValueError as e:
		print(f'[!] {e}')
		return 1

	patterns = []
	for i in by_value:
		try:
			patterns.append(kit.pattern(ser.paths[i]))
		except Exception as e:  # a reader's own error, whatever it is, names the file
			print(f'[!] Cannot read {ser.paths[i]}: {e}')
			print('    Leave it out with -i, or the map would have a gap where it belongs.')
			return 1

	try:
		xinfo = x_setup(ser.paths, args.x_data, args.x_axis, args.wavelength)
		xgrid, Z = common_grid(patterns)
		regridded = any(np.asarray(x).shape != xgrid.shape
		                or not np.allclose(x, xgrid, rtol=0, atol=1e-6) for x, _y in patterns)
		if xinfo['axis'] != xinfo['data']:
			shown = kit.convert_x(xgrid, xinfo['data'], xinfo['axis'], xinfo['wavelength'])
			regridded = regridded or not _even(shown[::-1] if shown[0] > shown[-1] else shown)
			xgrid, Z = even_grid(shown, Z)
		xinfo['regridded'] = regridded
		full = (xgrid[0], xgrid[-1])
		xgrid, Z = crop(xgrid, Z, args.range)
		if args.normalize:
			peak = Z.max(axis=1, keepdims=True)
			Z = Z / np.where(peak > 0, peak, 1.0)
		low_c, high_c = colour_limits(Z, args.scale, args.limits)
	except ValueError as e:
		print(f'[!] {e}')
		return 1

	from matplotlib import colors
	# Outside --limits: the end colours. Masked, i.e. a step with no pattern: see-through,
	# so the hatching behind shows.
	cmap = cmap.with_extremes(bad=(0, 0, 0, 0), under=cmap(0.0), over=cmap(1.0))
	if args.scale == 'log':
		norm = colors.LogNorm(vmin=low_c, vmax=high_c)
	elif args.scale == 'sqrt':
		norm = colors.PowerNorm(0.5, vmin=low_c, vmax=high_c)
	else:
		norm = colors.Normalize(vmin=low_c, vmax=high_c)

	low, high = values[0], values[-1]
	u = f' {ser.unit}' if ser.unit else ''
	trimmed = not args.range and (xgrid[0], xgrid[-1]) != full
	gaps = [f'{s.centre:g}' for s in steps if s.kind != 'measured']
	data, axis = kit.X_QUANTITIES[xinfo['data']], kit.X_QUANTITIES[xinfo['axis']]
	print(f'[*] {len(values)} patterns from {low:g} to {high:g}{u}'
	      + (f' in steps of {grid[0]:g}{u}' if grid else ', no regular step') + '; '
	      f'{axis.name} {xgrid[0]:.4g} to {xgrid[-1]:.4g} {axis.plain_unit}'
	      + (' (columns zero in every pattern left out)' if trimmed else '') + '.')
	if xinfo['warning']:
		print(f'[!] {xinfo["warning"]}; going by --x-data.')
	if data.key != axis.key:
		print(f'[*] x: {data.name} in {data.plain_unit} in the files, shown as {axis.name} in '
		      f'{axis.plain_unit}' + (f' (wavelength {xinfo["wavelength"]:g} A, '
		                              f'{xinfo["wavelength_how"]})' if data.name != axis.name
		                              else '') + '.')
	elif not args.x_data:
		print(f'[*] x: {data.name} in {data.plain_unit}, '
		      + ('from the file headers.' if xinfo['data_how'].startswith('from')
		         else 'taken as that: --x-data q if the files hold Q.'))
	if gaps:
		print(f'[*] No pattern at {_join(gaps)}{u}: '
		      + ('interpolated from the steps either side.' if args.fill
		         else 'hatched. --fill interpolates them.'))
	elif args.fill and not grid:
		print('[*] --fill: with no regular step there is no missing step to fill '
		      '(--step N sets one).')
	print(f'    {"Blended between neighbouring steps" if args.smooth else "Each pattern is a band one step tall" if grid else "Each pattern reaches half way to its neighbours"}. '
	      f'Colours {args.cmap}, {args.scale}, {low_c:.4g} to {high_c:.4g}.')
	if ser.label == 'pattern' and args.y_label is None:
		print('[*] The file names give no values, so the patterns are numbered in measurement '
		      'order. --y-name or --y-values gives them.')
	elif not ser.label:
		print('[*] The series axis has no label: give it one with --y-label "$p$ / MPa".')

	import matplotlib.pyplot as plt
	with plt.rc_context(rc_params(look)):
		# On screen, drawn large enough to read; the saved file is --size at --dpi.
		fig, shape = figure(xgrid, Z, steps, low, high, args.x_label or axis.label, ser.label,
		                    cmap, norm, args,
		                    dpi=100 if args.silent else max(100, 900 / args.size[0]), look=look)
		if not args.silent:
			plt.show()
			print('    (-s saves the figure, and NAME_SI.txt with how it was made.)')
			return 0
		path = f'{args.name}.{args.extension.lstrip(".")}'
		fig.savefig(path, dpi=args.dpi)
		box = fig.axes[0].get_window_extent()
		scale = args.dpi / fig.dpi
		plt.close(fig)
	print(f'[+] {path}')

	notes = f'{args.name}_SI.txt'
	Path(notes).write_text(si_notes({
		'series': ser, 'steps': steps, 'grid': grid, 'low': low, 'high': high, 'args': args,
		'xgrid': xgrid, 'x_step': (xgrid[-1] - xgrid[0]) / (xgrid.size - 1),
		'xinfo': xinfo, 'trimmed': trimmed, 'image_shape': shape,
		'plot_px': (int(round(box.width * scale)), int(round(box.height * scale))),
		'colour': (low_c, high_c), 'figure': path, 'when': datetime.now(),
	}), encoding='utf-8')
	print(f'[+] {notes}  (how the map was made, for the supporting information)')
	return 0


def main(argv=None, command=None):
	argv = list(sys.argv[1:] if argv is None else argv)
	# Asked for everything only when given nothing: any argument means "run it".
	ask = fill if not argv and kit.interactive() else None
	return kit.main(build_parser(), ask, run, argv=argv, command=command,
	                script_file=__file__)


if __name__ == '__main__':
	sys.exit(main())
