"""A pattern series as a heat map: 2theta across, pressure up, intensity as colour.

Patterns measured along a series -- pressure steps in a gas cell, a temperature
ramp, a time series -- drawn as one image, the way Fig. 2 of J. Am. Chem. Soc.
2025, 147, 46075 shows Mg2(dobdc) from 1 to 4000 bar. A peak that stays put is a
vertical line, a peak that shifts bends, and a phase transition ends lines and
starts others.

Stacked, not interpolated. Each pattern is a horizontal band centred on its own
value and reaching half way to its neighbours, so every row of the map is the
pattern measured nearest to it, and unevenly spaced steps keep their true
heights. The vertical stretch is only the shape of the axes: forty patterns in a
panel four times as wide as it is tall already look continuous. --smooth blends
linearly between neighbouring patterns instead. It hides the steps, but it also
turns a jump between two patterns into what looks like a gradual change.

Values come from the file names: the number before a unit (1bar, 2.5GPa, 300K),
which also labels the axis (p / bar). --sort-key REGEX takes another number, as
in pp, and --y-values 1,100:4000:100 gives them yourself, in file-name order.

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
from glob import glob
from pathlib import Path

import numpy as np

from achdiff.misc import kit

#: The paper's colours: ColorBrewer PuBu from 28 % of the way along. Measured off
#: the published figure, whose every pixel lies on PuBu between 0.28 and 1.
DEFAULT_CMAP = 'PuBu:0.28'
#: A journal column wide; the plot inside comes out about 4:1, as in the paper.
DEFAULT_SIZE = (3.5, 1.2)

PRESSURE_UNITS = ('bar', 'kbar', 'mbar', 'Pa', 'kPa', 'MPa', 'GPa')
TEMPERATURE_UNITS = ('K', '°C')
# A number with a unit straight after it, and not inside a longer number or word:
# "_1bar_" and "2.5GPa" but neither the 650 nor the date in GH072a_650_24062026.
_UNIT_NUMBER = re.compile(r'(?<![\d.,])(\d+(?:[.,]\d+)?)\s*'
                          r'(kbar|mbar|bar|GPa|MPa|kPa|Pa|K|°C|degC|C)(?![A-Za-z])')
# .txt and .csv are as often notes and tables as patterns.
_AMBIGUOUS_TYPES = ('.txt', '.csv')

# Arial where it is installed (every lab PC), as in the paper; mathtext in the
# same face, so the italic p of "p / bar" matches the rest.
STYLE = {
	'font.family': 'sans-serif',
	'font.sans-serif': ['Arial', 'Helvetica', 'Liberation Sans', 'DejaVu Sans'],
	'mathtext.fontset': 'custom',
	'mathtext.rm': 'sans',
	'mathtext.it': 'sans:italic',
	'mathtext.bf': 'sans:bold',
	'font.size': 8,
	'axes.linewidth': 0.8,
	'xtick.direction': 'out',
	'ytick.direction': 'out',
	'xtick.major.size': 3.5,
	'ytick.major.size': 3.5,
	'xtick.minor.size': 2.0,
	'ytick.minor.size': 2.0,
	'xtick.major.width': 0.8,
	'ytick.major.width': 0.8,
	'xtick.minor.width': 0.6,
	'ytick.minor.width': 0.6,
}


def _values_arg(text):
	try:
		return kit.values(text)
	except ValueError as e:
		raise argparse.ArgumentTypeError(str(e)) from None


def build_parser():
	parser = argparse.ArgumentParser(
		description=__doc__.strip().splitlines()[0],
		epilog='Run with no arguments to be asked for everything.')
	parser.add_argument('-i', '--input', nargs='+', metavar='FILE',
	                    help='Pattern files; wildcards are fine (-i *.xy). Default: every '
	                         'pattern in this folder, of its most common type.')
	parser.add_argument('--y-values', type=_values_arg, default=None, metavar='SPEC',
	                    help='The value of each pattern, in file-name order (by --sort-key '
	                         'if given): a list, start:stop:step with the stop included, or '
	                         'both, e.g. 1,100:4000:100. Default: read from the file names.')
	parser.add_argument('--sort-key', default=None, metavar='REGEX',
	                    help='Which number in the file names is the value: the first capture '
	                         'group, as in pp, e.g. "_([0-9.]+)GPa". Default: the number '
	                         'before a unit (1bar, 2.5GPa, 300K).')
	parser.add_argument('--y-label', default=None, metavar='TEXT',
	                    help='Label of the series axis. Default: from the unit in the file '
	                         'names, e.g. "$p$ / bar".')
	parser.add_argument('--range', nargs=2, type=float, default=None, metavar=('LO', 'HI'),
	                    help='The 2theta range to show. Default: all of it, less any columns '
	                         'at the ends that are zero in every pattern.')
	parser.add_argument('--cmap', default=DEFAULT_CMAP, metavar='SPEC',
	                    help='A matplotlib colormap, part of one (NAME:LOW:HIGH, 0 to 1), or '
	                         'colours to blend (white,#08306b) (default: %(default)s, the '
	                         "paper's).")
	parser.add_argument('--scale', choices=('linear', 'sqrt', 'log'), default='sqrt',
	                    help='How intensity maps to colour (default: %(default)s, which puts a '
	                         "gas-cell pattern's background where the paper's sits). linear "
	                         'makes colour proportional to intensity; log brings up the '
	                         'weakest peaks.')
	parser.add_argument('--limits', nargs=2, type=float, default=None, metavar=('LOW', 'HIGH'),
	                    help='The intensities at the two ends of the colour scale. Default: '
	                         'the lowest and highest shown.')
	parser.add_argument('--normalize', action='store_true',
	                    help='Scale each pattern to its own maximum first, so a pattern counted '
	                         'for less time does not look paler.')
	parser.add_argument('--smooth', action='store_true',
	                    help='Blend linearly between neighbouring patterns instead of '
	                         'drawing each as a band.')
	parser.add_argument('--label', default=None, metavar='TEXT',
	                    help='Text in the top right corner, e.g. "Mg$_2$(dobdc)".')
	parser.add_argument('--colorbar', action='store_true',
	                    help='Add a colour bar (the paper has none).')
	parser.add_argument('--size', nargs=2, type=float, default=DEFAULT_SIZE, metavar=('W', 'H'),
	                    help='Figure size in inches (default: %(default)s).')
	parser.add_argument('--dpi', type=int, default=300,
	                    help='Resolution of the saved image, and of the map inside an SVG '
	                         'or PDF (default: %(default)s).')
	parser.add_argument('--name', default='heatmap',
	                    help='File name stem for -s output (default: %(default)s).')
	kit.add_common_arguments(parser)
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


def from_key(names, key):
	"""The number `key` captures from each name: its first group, or the whole
	match when it has none. Raises ValueError naming the names it misses."""
	try:
		regex = re.compile(key)
	except re.error as e:
		raise ValueError(f'--sort-key {key!r} is not a valid regular expression ({e})') from None
	values, missed = [], []
	for name in names:
		m = regex.search(name)
		value = _number((m.group(1) if regex.groups else m.group(0)) if m else None)
		if value is None:
			missed.append(name)
		values.append(value)
	if missed:
		raise ValueError(f'--sort-key {key!r} finds no number in: {", ".join(missed)}')
	return values


def axis_label(unit):
	if unit in PRESSURE_UNITS:
		return f'$p$ / {unit}'
	if unit in TEMPERATURE_UNITS:
		return f'$T$ / {unit}'
	return ''


def series(paths, y_values=None, sort_key=None, y_label=None):
	"""The patterns in map order, [(value, path)] by rising value, and the label of
	the series axis. Raises ValueError for anything that would draw a wrong map."""
	names = [Path(p).name for p in paths]
	unit_values, unit = from_units(names)
	by_path = dict(zip(paths, unit_values or [None] * len(paths)))
	if y_values is not None:
		if sort_key:
			keys = from_key(names, sort_key)
			order = [p for _k, p in sorted(zip(keys, paths), key=lambda kp: kp[0])]
		else:
			order = sorted(paths, key=lambda p: kit.natural_key(Path(p).name))
		if len(y_values) != len(order):
			listing = '\n'.join(f'    {i:>4}  {Path(p).name}' for i, p in enumerate(order, 1))
			raise ValueError(f'--y-values gives {len(y_values)} values for {len(order)} '
			                 f'patterns. They are given in this order:\n{listing}')
		pairs = list(zip(y_values, order))
	elif sort_key:
		pairs = list(zip(from_key(names, sort_key), paths))
	elif unit_values is not None:
		bare = [n for n, v in zip(names, unit_values) if v is None]
		if bare:
			raise ValueError(f'the file names give values in {unit}, but not these: '
			                 f'{", ".join(bare)}. Leave them out with -i, or give every '
			                 f'value with --y-values.')
		pairs = list(zip(unit_values, paths))
	else:
		order = sorted(paths, key=lambda p: kit.natural_key(Path(p).name))
		pairs = [(float(i), p) for i, p in enumerate(order, 1)]
	pairs.sort(key=lambda vp: vp[0])
	if unit_values is None and y_values is None and not sort_key:
		label = 'pattern'
	elif all(by_path[p] is not None and abs(by_path[p] - v) <= 1e-9 * max(1.0, abs(v))
	         for v, p in pairs):
		label = axis_label(unit)      # the values are the very numbers the unit follows
	else:
		label = ''

	shared = {}
	for value, path in pairs:
		shared.setdefault(value, []).append(Path(path).name)
	twice = {v: n for v, n in shared.items() if len(n) > 1}
	if twice:
		v, clash = next(iter(twice.items()))
		raise ValueError(f'{len(clash)} patterns have the value {v:g}: {", ".join(clash)}. '
		                 f'A run that comes back down needs one map per leg (choose each '
		                 f'with -i), and a repeat needs leaving out.')
	return pairs, (y_label if y_label is not None else label)


def common_grid(patterns):
	"""(two_theta, Z): every pattern on one evenly stepped 2theta grid, Z with one
	row per pattern. Patterns from one detector share their grid and are used as
	they are; others are interpolated onto the range they all cover, at the finest
	step among them. Raises ValueError when they share no range."""
	xs = [np.asarray(x, dtype=float) for x, _y in patterns]
	first = xs[0]
	# Even enough when every point is within a tenth of a step of where an even
	# grid puts it: 2theta rounded in a text file still counts.
	step = (first[-1] - first[0]) / (first.size - 1) if first.size > 1 else 0.0
	even = step > 0 and np.all(np.abs(first - np.linspace(first[0], first[-1], first.size))
	                           <= 0.1 * step)
	shared = all(x.shape == first.shape and np.allclose(x, first, rtol=0, atol=1e-6) for x in xs)
	if even and shared:
		return first.copy(), np.vstack([np.asarray(y, dtype=float) for _x, y in patterns])

	lo = max(x.min() for x in xs)
	hi = min(x.max() for x in xs)
	if hi <= lo:
		raise ValueError('the patterns have no 2theta range in common')
	step = min(np.median(np.abs(np.diff(x))) for x in xs if x.size > 1)
	grid = lo + np.arange(int(np.floor((hi - lo) / step + 1e-9)) + 1) * step
	rows = []
	for x, (_x, y) in zip(xs, patterns):
		order = np.argsort(x)
		rows.append(np.interp(grid, x[order], np.asarray(y, dtype=float)[order]))
	return grid, np.vstack(rows)


def crop(two_theta, Z, window=None):
	"""The columns to show: `window` (lo, hi) if given; otherwise all but the
	columns at either end that are zero in every pattern -- a masked detector edge
	holds no data and would only stretch the axis. Raises ValueError for a window
	that leaves fewer than two points."""
	keep = np.ones(two_theta.size, dtype=bool)
	if window is not None:
		lo, hi = sorted(window)
		keep &= (two_theta >= lo) & (two_theta <= hi)
	else:
		live = np.flatnonzero(np.any(Z != 0, axis=0))
		if live.size:
			keep[:live[0]] = False
			keep[live[-1] + 1:] = False
	if keep.sum() < 2:
		raise ValueError(f'the 2theta range {window[0]:g} to {window[1]:g} holds no data '
		                 f'(the patterns cover {two_theta[0]:g} to {two_theta[-1]:g})'
		                 if window is not None else 'every pattern is zero throughout')
	return two_theta[keep], Z[:, keep]


# ------------------------------------------------------------------- the image

def rows_needed(values):
	"""Enough rows that the narrowest band gets a dozen, within 200 to 4000."""
	values = np.asarray(values, dtype=float)
	gap = np.diff(values).min()
	return int(np.clip(np.ceil(12 * (values[-1] - values[0]) / gap), 200, 4000))


def rows(values, n_rows, smooth=False):
	"""Where each row of the image comes from: (centres, lower, upper, weight).

	The `n_rows` rows cover values[0] to values[-1] evenly, and row k is
	(1 - weight[k]) * Z[lower[k]] + weight[k] * Z[upper[k]]. Stacked, every weight
	is 0 and lower is the pattern nearest the row's centre, so each band reaches
	half way to its neighbours and the first and last are half bands. Smooth, a row
	is the straight-line blend of the patterns either side of it."""
	values = np.asarray(values, dtype=float)
	edges = np.linspace(values[0], values[-1], n_rows + 1)
	centres = (edges[:-1] + edges[1:]) / 2
	if smooth:
		upper = np.clip(np.searchsorted(values, centres, side='right'), 1, values.size - 1)
		lower = upper - 1
		weight = (centres - values[lower]) / (values[upper] - values[lower])
	else:
		lower = np.searchsorted((values[:-1] + values[1:]) / 2, centres, side='right')
		upper = lower
		weight = np.zeros(n_rows)
	return centres, lower, upper, weight


def image(Z, values, smooth=False, n_rows=None):
	"""The map as an (n_rows, columns) array, bottom row first."""
	Z = np.asarray(Z, dtype=np.float32)
	_centres, lower, upper, weight = rows(values, n_rows or rows_needed(values), smooth)
	if not smooth:
		return Z[lower]
	weight = weight.astype(np.float32)[:, None]
	return Z[lower] * (1 - weight) + Z[upper] * weight


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


def series_ticks(low, high, nbins=3):
	"""(major ticks, minor step) for the series axis. Round numbers, but the first
	value always gets a tick and a label, as the paper's "1" bar does, and so does
	the last when no round number is near it."""
	from matplotlib.ticker import MaxNLocator
	raw = MaxNLocator(nbins=nbins, steps=[1, 2, 2.5, 5, 10]).tick_values(low, high)
	step = raw[1] - raw[0]
	span = high - low
	near = 1e-9 * span
	ticks = [t for t in raw if low - near <= t <= high + near]
	if not ticks or ticks[0] - low > near:
		ticks = [low] + [t for t in ticks if t - low > 0.2 * span]
	if high - ticks[-1] > 0.2 * span:
		ticks.append(high)
	return [float(t) for t in ticks], float(step) / 2


def figure(two_theta, values, Z, y_label, cmap, norm, args, dpi=100):
	"""The heat map, drawn the way the paper's Fig. 2 is."""
	import matplotlib.pyplot as plt
	from matplotlib.ticker import AutoMinorLocator, FixedLocator, FuncFormatter, MultipleLocator

	values = [float(v) for v in values]
	low, high = values[0], values[-1]
	step = (two_theta[-1] - two_theta[0]) / (two_theta.size - 1)
	window = [two_theta[0], two_theta[-1]]
	if args.range:
		# No further than the data: past it there is nothing to draw but white.
		window = [max(min(args.range), window[0]), min(max(args.range), window[1])]

	fig, ax = plt.subplots(figsize=tuple(args.size), dpi=dpi, layout='constrained')
	shown = ax.imshow(image(Z, values, smooth=args.smooth), cmap=cmap, norm=norm,
	                  extent=(two_theta[0] - step / 2, two_theta[-1] + step / 2, low, high),
	                  origin='lower', aspect='auto', interpolation='antialiased')
	ax.set_xlim(*window)
	ax.set_ylim(low, high)

	ticks, minor = series_ticks(low, high, nbins=3 if args.size[1] <= 2 else 6)
	ax.yaxis.set_major_locator(FixedLocator(ticks))
	ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _pos: f'{v:g}'))
	ax.yaxis.set_minor_locator(MultipleLocator(minor))
	ax.xaxis.set_minor_locator(AutoMinorLocator())
	ax.set_xlabel(r'$2\theta$ / °')
	ax.set_ylabel(y_label)
	if args.label:
		ax.text(0.985, 0.93, args.label, transform=ax.transAxes, ha='right', va='top')
	if args.colorbar:
		bar = fig.colorbar(shown, ax=ax, pad=0.02, aspect=12)
		bar.set_label('normalised intensity' if args.normalize else 'intensity')
		bar.ax.tick_params(direction='out')
	return fig


# ------------------------------------------------------------------ the wizard

def _summary(values, unit=''):
	shown = [f'{v:g}' for v in values]
	text = ', '.join(shown) if len(shown) <= 6 else f'{", ".join(shown[:3])} ... {shown[-1]}'
	return f'{text}{" " + unit if unit else ""} ({len(shown)} values)'


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
	print(f'{suffix} patterns in this folder'
	      + (f' (also here: {", ".join(f"{k} x{n}" for k, n in others.items())})' if others else '')
	      + ':')
	picked = kit.choose(labels, 'Which go into the map?', default=range(len(names)),
	                    at_least=2)
	extra = ['-i'] + ([f'*{suffix}'] if len(picked) == len(names) else [names[i] for i in picked])

	chosen = [values[i] for i in picked] if values else []
	if chosen and None not in chosen:
		print(f'Values from the file names: {_summary(sorted(chosen), unit)}')
		if not kit.ask_yes('Use these?', default=True):
			extra += ['--y-values', kit.ask('Values in file-name order, e.g. 1,100:4000:100:')]
	elif chosen:
		extra += ['--y-values', kit.ask(f'Not every file name gives a value in {unit}. Values '
		                                f'in file-name order, e.g. 1,100:4000:100:')]
	else:
		spec = kit.ask('The file names carry no value. Values in file-name order, e.g. '
		               '1,100:4000:100 (Enter to number the patterns 1, 2, 3...):')
		if spec:
			extra += ['--y-values', spec,
			          '--y-label', kit.ask('Label for that axis:', '$p$ / bar')]

	while True:
		window = kit.ask('2theta range to show, e.g. 2 12 (Enter for all of it):')
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
	if not args.silent and kit.ask_yes('Save the figure instead of opening a window?'):
		extra.append('-s')
	return extra


# --------------------------------------------------------------------- running

def run(args):
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
		pairs, y_label = series(paths, args.y_values, args.sort_key, args.y_label)
	except ValueError as e:
		print(f'[!] {e}')
		return 1
	values = [v for v, _p in pairs]

	patterns = []
	for _value, path in pairs:
		try:
			patterns.append(kit.pattern(path))
		except Exception as e:  # a reader's own error, whatever it is, names the file
			print(f'[!] Cannot read {path}: {e}')
			print('    Leave it out with -i, or the map would have a gap where it belongs.')
			return 1

	try:
		two_theta, Z = common_grid(patterns)
		full = (two_theta[0], two_theta[-1])
		two_theta, Z = crop(two_theta, Z, args.range)
		if args.normalize:
			peak = Z.max(axis=1, keepdims=True)
			Z = Z / np.where(peak > 0, peak, 1.0)
		low, high = colour_limits(Z, args.scale, args.limits)
	except ValueError as e:
		print(f'[!] {e}')
		return 1

	from matplotlib import colors
	# Zeros on a log scale, and anything outside --limits, take the end colours.
	cmap = cmap.with_extremes(bad=cmap(0.0), under=cmap(0.0), over=cmap(1.0))
	if args.scale == 'log':
		norm = colors.LogNorm(vmin=low, vmax=high)
	elif args.scale == 'sqrt':
		norm = colors.PowerNorm(0.5, vmin=low, vmax=high)
	else:
		norm = colors.Normalize(vmin=low, vmax=high)

	trimmed = '' if args.range or (two_theta[0], two_theta[-1]) == full else \
		' (columns that are zero in every pattern left out)'
	print(f'[*] {len(pairs)} patterns from {values[0]:g} to {values[-1]:g}'
	      f'{" " + y_label.split("/")[-1].strip() if "/" in y_label else ""}; '
	      f'2theta {two_theta[0]:.3f} to {two_theta[-1]:.3f}{trimmed}.')
	print(f'    {"Blended between neighbours" if args.smooth else "Stacked: each pattern is a band reaching half way to its neighbours"}. '
	      f'Colours {args.cmap}, {args.scale}, {low:g} to {high:g}.')
	if y_label == 'pattern' and args.y_label is None:
		print('[*] The file names give no values, so the patterns are numbered in name '
		      'order. --y-values gives them yourself.')
	elif not y_label:
		print('[*] The series axis has no label: give it one with --y-label "$p$ / MPa".')

	import matplotlib.pyplot as plt
	with plt.rc_context(STYLE):
		# On screen, drawn large enough to read; the saved file is --size at --dpi.
		fig = figure(two_theta, values, Z, y_label, cmap, norm, args,
		             dpi=100 if args.silent else max(100, 900 / args.size[0]))
		if args.silent:
			path = f'{args.name}.{args.extension.lstrip(".")}'
			fig.savefig(path, dpi=args.dpi)
			plt.close(fig)
			print(f'[+] {path}')
		else:
			plt.show()
	return 0


def main(argv=None, command=None):
	argv = list(sys.argv[1:] if argv is None else argv)
	# Asked for everything only when given nothing: any argument means "run it".
	ask = fill if not argv and kit.interactive() else None
	return kit.main(build_parser(), ask, run, argv=argv, command=command,
	                script_file=__file__)


if __name__ == '__main__':
	sys.exit(main())
