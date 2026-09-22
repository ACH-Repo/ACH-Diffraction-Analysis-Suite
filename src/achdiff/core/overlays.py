"""Marks both plotters share: -m scales a 2-theta range, -b highlights a position.

One implementation, called by pp and pq alike, so the two flags cannot drift
apart again. They did once: pq grew its own multiply, with its own syntax and a
shaded band, next to pp's dashed one.

Syntax (the same in both tools)
-------------------------------
  -m a,b,N[,colour] ...   multiply intensity in [a, b] by N. `,b,N` runs from
                          the start of the data, `a,,N` to its end.
  -b x[,width[,colour]]   a vertical strip centred on x, behind everything.
                          width is in degrees 2-theta, or `2%` for a share of
                          the plot width; left out, it is band_width (1 %).

Several go after one flag, separated by spaces: `-m 20,40,10 45,50,5`. The
bracketed form pq used to take, `"((20,40,10,blue),(45,50,5))"`, still parses,
so a command written down before this change still runs.

Why multiply marks its range with dashed lines, not shading
-----------------------------------------------------------
A -b strip is shaded. If a multiplied range were shaded too, "this was scaled"
and "look here" would read the same, and a strip inside a scaled range would
disappear into it.
"""

import re
from collections import namedtuple

import numpy as np
from matplotlib.colors import is_color_like
from matplotlib.transforms import blended_transform_factory

# lo/hi of None are open ends, resolved against the data range when drawn.
Multiply = namedtuple('Multiply', 'lo hi factor color')
# width is None (the style's default), ('deg', w) or ('pct', w).
Band = namedtuple('Band', 'x width color')


def add_arguments(parser, multiply_aliases=()):
	"""Attach -m and -b, worded the same in every plotter that has them.

	`multiply_aliases` keeps an old long name working where one existed -- pq's
	multiply was called --highlights."""
	parser.add_argument('-m', '--multiply', *multiply_aliases, nargs='+', metavar='a,b,N',
	                    help='Multiply the intensity in 2theta range [a, b] by N, e.g. '
	                         '-m 20,40,10 45,50,5. Leave a or b empty (,40,10 or 20,,10) '
	                         'to run to the edge of the data; add a fourth field for the '
	                         'colour of the dashed range markers.')
	parser.add_argument('-b', '--band', nargs='+', metavar='x[,w[,c]]',
	                    help='Shade a vertical strip behind the plot at 2theta x, to make '
	                         'a small feature easy to find again, e.g. -b 23.4 31.2. '
	                         'Width w is in degrees, or a share of the plot width with %% '
	                         '(default: the style sheet\'s band_width, 1%%); c is a colour '
	                         '(default: light grey). -b 23.4,0.3 31.2,2%%,lightblue sets both.')


def _groups(specs):
	"""Split -m / -b arguments into their comma-separated groups.

	`specs` is what argparse hands over for nargs='+' -- a list of strings -- or
	a single string. A string with brackets is read as the old tuple form."""
	if not specs:
		return []
	if isinstance(specs, str):
		specs = [specs]
	out = []
	for spec in specs:
		if '(' in spec:
			out.extend(re.findall(r'\(([^()]*)\)', spec))
		else:
			out.extend(spec.split())
	return out


def _color(text, flag, group):
	if not text:
		return None
	if is_color_like(text):
		return text
	print(f'[!] {flag} {group}: {text!r} is not a colour matplotlib knows; using the default.')
	return None


def parse_multiply(specs):
	"""-m arguments -> [Multiply]. Bad groups are reported and skipped."""
	out = []
	for group in _groups(specs):
		parts = [p.strip() for p in group.split(',')]
		if not 3 <= len(parts) <= 4:
			print(f'[!] -m {group}: expected a,b,N or a,b,N,colour; skipping it.')
			continue
		try:
			lo = float(parts[0]) if parts[0] else None
			hi = float(parts[1]) if parts[1] else None
			factor = float(parts[2])
		except ValueError:
			print(f'[!] -m {group}: a, b and N must be numbers (a or b may be empty); '
			      f'skipping it.')
			continue
		if lo is not None and hi is not None and lo > hi:
			lo, hi = hi, lo
		out.append(Multiply(lo, hi, factor,
		                    _color(parts[3] if len(parts) > 3 else '', '-m', group)))
	return out


def resolve(ranges, x_lo, x_hi):
	"""Fill the open ends of each range from the data range [x_lo, x_hi]."""
	return [m._replace(lo=x_lo if m.lo is None else m.lo,
	                   hi=x_hi if m.hi is None else m.hi) for m in ranges]


def scale(x, y, ranges, baseline=0.0):
	"""`y` with the signal above `baseline` multiplied inside each range.

	Ranges must already be resolved. pp passes 0; pq passes each trace's place in
	the stack, so a scaled trace grows from its own zero rather than from the
	bottom of the figure. Overlapping ranges multiply together."""
	x = np.asarray(x)
	y = np.array(y, dtype=float)
	for m in ranges:
		mask = (x >= m.lo) & (x <= m.hi)
		y[mask] = baseline + (y[mask] - baseline) * m.factor
	return y


def _label_anchor(lo, hi, x_lo, x_hi):
	"""Where the `x N` label goes: (x, horizontal alignment).

	Anchored to whichever edge of the range is nearer the middle of the plot and
	set inward from it, which keeps it inside the scaled range and clear of the
	legend in the upper right. Flipped when the text would run off the axes."""
	span = (x_hi - x_lo) or 1.0
	lo, hi = max(lo, x_lo), min(hi, x_hi)
	plot_mid = (x_lo + x_hi) / 2
	range_mid = (lo + hi) / 2
	dead_zone = span * 0.1

	if range_mid < plot_mid - dead_zone:
		x, ha = hi, 'right'
	elif range_mid > plot_mid + dead_zone:
		x, ha = lo, 'left'
	else:
		x, ha = range_mid, 'center'

	frac = (x - x_lo) / span
	if ha == 'left' and frac > 0.85:
		ha = 'right'
	elif ha == 'right' and frac < 0.15:
		ha = 'left'
	return x, ha


def draw_multiply_marks(ax, ranges, x_lo, x_hi, label_y=0.98, fontsize=10):
	"""Dashed lines at both edges of each range and an `x N` label at the top.

	Call after the data is plotted: the lines are appended to ax.lines, and pp
	finds its curves by position in that list. They carry no legend label."""
	trans = blended_transform_factory(ax.transData, ax.transAxes)
	for m in ranges:
		color = m.color or 'k'
		for edge in (m.lo, m.hi):
			ax.axvline(x=edge, color=color, linestyle='--', linewidth=0.8, alpha=0.5,
			           label='_nolegend_')
		x, ha = _label_anchor(m.lo, m.hi, x_lo, x_hi)
		ax.text(x, label_y, f'x {m.factor:g}', ha=ha, va='top', color=color,
		        fontsize=fontsize, transform=trans)


def parse_bands(specs):
	"""-b arguments -> [Band]. Bad groups are reported and skipped."""
	out = []
	for group in _groups(specs):
		parts = [p.strip() for p in group.split(',')]
		if not 1 <= len(parts) <= 3:
			print(f'[!] -b {group}: expected x, x,width or x,width,colour; skipping it.')
			continue
		try:
			x = float(parts[0])
		except ValueError:
			print(f'[!] -b {group}: {parts[0]!r} is not a number; skipping it.')
			continue

		width = None
		text = parts[1] if len(parts) > 1 else ''
		if text:
			unit = 'pct' if text.endswith('%') else 'deg'
			try:
				value = float(text.rstrip('%'))
			except ValueError:
				value = -1
			if value <= 0:
				print(f'[!] -b {group}: width {text!r} should be a positive number, '
				      f'in degrees or with a %; using the default.')
			else:
				width = (unit, value)

		out.append(Band(x, width, _color(parts[2] if len(parts) > 2 else '', '-b', group)))
	return out


def draw_bands(ax, bands, x_lo, x_hi, default_width_pct=1.0, default_color='gainsboro'):
	"""A vertical strip behind everything for each band.

	Width is measured against the data range [x_lo, x_hi], which both plotters
	use as the x limits, so 1 % is 1 % of the plot as drawn. Opaque rather than
	translucent: a strip is there to be seen, and alpha over a transparent
	background comes out as a different grey on every slide."""
	span = x_hi - x_lo
	for b in bands:
		unit, value = b.width or ('pct', default_width_pct)
		width = value if unit == 'deg' else span * value / 100.0
		ax.axvspan(b.x - width / 2, b.x + width / 2, color=b.color or default_color,
		           linewidth=0, zorder=-1, label='_nolegend_')
