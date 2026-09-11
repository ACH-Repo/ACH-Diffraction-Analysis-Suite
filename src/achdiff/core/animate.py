"""Animated GIFs from a sequential series of fits.

A sequential Pawley experiment leaves a directory full of fits -- one per
temperature, per pressure, per time step -- that are only interesting next to
each other. This turns that directory into two GIFs for a talk:

    <name>-fits.gif   every fit as a frame, in order
    <name>-cell.gif   the cell parameters as bars, changing frame by frame

Both are written by one `pp --gif`, because they answer the same question and
nobody wants to run two commands to get the two halves of one slide.

Why nothing rescales
--------------------
An animation that re-fits its own axes every frame is unreadable: a peak that
grows and an axis that shrinks look identical, and the eye cannot tell which it
is watching. Every limit here is therefore computed ONCE over the whole series
and held fixed, which is also why this module needs to see all the frames before
drawing any of them.

The bar chart's y axis does not start at zero, and that is deliberate rather
than an oversight. A cell edge moves in the third decimal place; a bar drawn
from zero to 15.48 A shows nothing at all. The axis spans the series' own range
so the change is visible, and the refined value is printed on every bar so the
absolute number is never left to be read off the axis.

Lengths and angles cannot share a scale -- Angstrom and degrees are not
comparable and a shared axis would make 90 degrees tower over 15 A -- so the
lengths take the left axis, the angles the right, and a dashed rule marks where
one stops and the other starts.
"""

import io
import re

import numpy as np

from .rounding import cryst_round

#: Cell parameters in the order they are drawn, lengths first. The keys match
#: the labels `plotter.get_unit_cell_raw` emits.
LENGTH_KEYS = ('a', 'b', 'c')
ANGLE_KEYS = (r'\alpha', r'\beta', r'\gamma')
CELL_KEYS = LENGTH_KEYS + ANGLE_KEYS

DEFAULT_DELAY_MS = 250

# Padding above and below the bars, as a fraction of the series' own span, so
# the value labels have somewhere to sit and the shortest bar is still a bar.
_HEADROOM = 0.35
_FOOTROOM = 0.20

# A series whose parameter never moves would otherwise get a zero-height axis.
_FLAT_PAD = 1e-4


def natural_key(text):
	"""Sort key that orders `scan_2` before `scan_10`.

	Sequential fits are numbered, and plain string order puts every `_10` in
	front of every `_2` -- which in an animation is not a cosmetic problem but a
	timeline played out of order.
	"""
	return [int(part) if part.isdigit() else part.lower()
	        for part in re.split(r'(\d+)', str(text))]


def parse_value_error(token):
	"""A TOPAS ``value`_esd`` token as ``(value, error)`` floats.

	`error` is None when the token carries none. Returns None when the value
	itself will not parse, so the caller can drop the parameter rather than plot
	a zero.

	Deliberately separate from `cryst_round`, which answers the neighbouring
	question: that returns `15.484(2)` for printing, and the bracket is exactly
	the information an error bar needs back as a number.
	"""
	if token is None:
		return None
	text = str(token)
	mean, _, err = text.partition('`_')
	if not mean:
		return None
	number = r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?'
	m = re.match(number, mean.strip())
	if not m:
		return None
	value = float(m.group(0))

	error = None
	if err:
		# TOPAS appends diagnostics after the esd (`_LIMIT_MAX_16`, `_SVD_ERR`),
		# so only the leading number is the uncertainty.
		me = re.match(number, err.strip())
		if me:
			try:
				error = abs(float(me.group(0)))
			except ValueError:
				error = None
	return value, error


def display_value(token):
	"""The number as a person writes it: `15.484(2)`, or the bare value."""
	rounded = cryst_round(str(token))
	return rounded if rounded is not None else str(token)


# ------------------------------------------------------------------- frames

def figure_to_frame(fig, dpi=None):
	"""One rendered figure as a PIL image, at a size that will not vary.

	Routed through a PNG in memory rather than the canvas buffer so the result
	does not depend on which backend the tool happens to be using, and composited
	onto white because a GIF's single transparent index makes a poor background
	for anti-aliased text.

	`bbox_inches='tight'` is pointedly NOT used: it crops to the artists, so a
	frame whose labels are one character wider comes out a different size, and
	GIF frames must all agree.
	"""
	from PIL import Image

	buffer = io.BytesIO()
	fig.savefig(buffer, format='png', dpi=dpi or fig.dpi, facecolor='white',
	            transparent=False)
	buffer.seek(0)
	image = Image.open(buffer).convert('RGBA')
	flat = Image.new('RGBA', image.size, (255, 255, 255, 255))
	flat.alpha_composite(image)
	return flat.convert('RGB')


def write_gif(frames, path, delay_ms=DEFAULT_DELAY_MS, loop=0):
	"""Write `frames` as an animated GIF. Returns the path.

	`loop=0` means forever, which is what a slide wants.

	Frames are quantised to a shared adaptive palette taken from the first one.
	Letting each frame pick its own 256 colours makes the background shimmer
	between frames, which on a projector reads as a fault in the data.
	"""
	from PIL import Image

	if not frames:
		raise ValueError('no frames to write')
	sizes = {frame.size for frame in frames}
	if len(sizes) > 1:
		raise ValueError(f'frames differ in size ({sorted(sizes)}); a GIF needs one size')

	palette = frames[0].convert('P', palette=Image.ADAPTIVE, colors=256)
	quantised = [palette] + [f.quantize(palette=palette, dither=Image.NONE)
	                         for f in frames[1:]]
	quantised[0].save(str(path), save_all=True, append_images=quantised[1:],
	                  duration=max(int(delay_ms), 20), loop=int(loop),
	                  optimize=True, disposal=2)
	return path


# -------------------------------------------------------------- cell series

class CellSeries(object):
	"""The cell parameters of one phase across a whole run of fits.

	Holds the frames in order and the limits every frame will share. Built by
	`add` during the caller's own pass over the fits, then frozen by `finish`.
	"""

	def __init__(self, name=''):
		self.name = str(name)
		self.frames = []        # [(label_for_frame, {key: (value, error, display)})]

	def add(self, label, raw_params):
		"""Record one fit. `raw_params` is {key: raw TOPAS token}."""
		values = {}
		for key, token in raw_params.items():
			parsed = parse_value_error(token)
			if parsed is None:
				continue
			value, error = parsed
			values[key] = (value, error, display_value(token))
		if values:
			self.frames.append((str(label), values))

	def __len__(self):
		return len(self.frames)

	def keys(self):
		"""The parameters present in every frame, in cell order.

		Intersection rather than union: a parameter that appears halfway through
		the series would otherwise make a bar pop into existence mid-animation,
		and a missing bar is a worse lie than a missing parameter.
		"""
		if not self.frames:
			return []
		common = set(self.frames[0][1])
		for _label, values in self.frames[1:]:
			common &= set(values)
		return [k for k in CELL_KEYS if k in common]

	def baselines(self, keys):
		"""Each parameter's value in the first frame.

		The reference for `relative` mode. Taken from the first frame rather than
		the mean because a sequential run has a starting point, and "how far has
		it moved since the run began" is the question being asked.
		"""
		if not self.frames:
			return {}
		first = self.frames[0][1]
		return {k: first[k][0] for k in keys if k in first}

	def span(self, keys, baselines=None):
		"""`(low, high)` covering every value and its error bar, over all frames.

		This is the number that makes the animation honest: computed once, used
		for every frame, never recomputed.

		With `baselines`, the span is of the CHANGE rather than the value. That
		matters more than it sounds: a cell edge moves in the third decimal while
		a and c can sit 3 A apart, so an axis wide enough to hold both is roughly
		a hundred times too coarse to show either one moving.
		"""
		lows, highs = [], []
		for _label, values in self.frames:
			for key in keys:
				if key not in values:
					continue
				value, error, _display = values[key]
				if baselines is not None:
					value = value - baselines.get(key, 0.0)
				error = error or 0.0
				lows.append(value - error)
				highs.append(value + error)
		if not lows:
			return None
		low, high = min(lows), max(highs)
		span = high - low
		if span <= 0:
			# Nothing moved. Open a little window around the value so the bars
			# have a height and the labels have somewhere to go.
			pad = max(abs(low) * _FLAT_PAD, _FLAT_PAD)
			low, high, span = low - pad, high + pad, 2 * pad
		if baselines is not None:
			# Relative mode puts bars on both sides of zero, so both ends need room
			# for a value label. Absolute mode only ever grows upward.
			return low - _HEADROOM * span, high + _HEADROOM * span
		return low - _FOOTROOM * span, high + _HEADROOM * span


def align_zero(*spans):
	"""Re-fit each `(low, high)` so zero sits at the same height on all of them.

	Two y axes that share a plot do not share a scale, and in relative mode each
	one's bars grow from its OWN zero. Left alone those zeros land at different
	heights, so a length bar and an angle bar of the same apparent height start
	from different places and the eye compares them wrongly -- and a single zero
	rule can only be drawn correctly for one of them.

	Each returned span still contains all of its own data; only the padding
	changes. Spans that are None are passed through.
	"""
	real = [s for s in spans if s is not None]
	if len(real) < 2:
		return list(spans)

	# Where zero already falls on each axis, as a fraction from the bottom.
	fractions = []
	for low, high in real:
		if high <= low:
			continue
		fractions.append(min(max((0.0 - low) / (high - low), 0.0), 1.0))
	if not fractions:
		return list(spans)
	# The most generous demand wins: any other axis can be stretched to meet it,
	# where shrinking one would cut off its data.
	f = min(max(max(fractions), 0.05), 0.95)

	out = []
	for span in spans:
		if span is None:
			out.append(None)
			continue
		low, high = span
		# range must be wide enough to keep both ends inside, with zero at f.
		needed = [0.0]
		if low < 0:
			needed.append(-low / f)
		if high > 0:
			needed.append(high / (1.0 - f))
		extent = max(needed) or (high - low) or 1.0
		out.append((-f * extent, (1.0 - f) * extent))
	return out


# --------------------------------------------------------- the cell bar chart

#: Lengths and angles are told apart by colour as well as by side, so a reader
#: who looks at a bar before looking at an axis still knows which scale it is on.
LENGTH_COLOR = '#1f77b4'
ANGLE_COLOR = '#d95f02'


def render_cell_frames(series, figsize=(7.0, 4.5), dpi=150, title=None,
                       relative=False,
                       length_color=LENGTH_COLOR, angle_color=ANGLE_COLOR,
                       label_size=9, value_size=8):
	"""Every frame of the cell-parameter animation, as PIL images.

	Lengths go on the left axis in Angstrom, angles on the right in degrees,
	with a dashed rule between them -- they are different quantities and putting
	them on one scale would flatten every length against a 90 degree angle.

	Both axes are fixed to `series.span` before the first frame is drawn, so a
	bar that grows is a parameter that grew.

	`relative` is usually what you want, and is why it exists. In absolute mode
	the bar is the parameter itself, which reads naturally but hides the thing
	being filmed: a and c can sit 3 A apart while each moves 0.05 A, so an axis
	wide enough for both is far too coarse to show either one move. In relative
	mode the bar is the change since the first fit, every parameter shares a
	scale that is the size of the changes themselves, and the error bars become
	visible instead of being a pixel wide.

	Either way the refined value with its uncertainty is printed above every bar,
	so the absolute number is never left to be read off an axis.
	"""
	import matplotlib.pyplot as plt

	keys = series.keys()
	if not keys or not len(series):
		return []

	lengths = [k for k in keys if k in LENGTH_KEYS]
	angles = [k for k in keys if k in ANGLE_KEYS]
	base = series.baselines(keys) if relative else None
	length_span = series.span(lengths, base) if lengths else None
	angle_span = series.span(angles, base) if angles else None
	if relative:
		# Only relative mode has a zero worth drawing, and therefore a zero that
		# has to mean the same height on both axes.
		length_span, angle_span = align_zero(length_span, angle_span)

	positions = {key: i for i, key in enumerate(lengths + angles)}
	n_total = len(positions)

	frames = []
	for frame_label, values in series.frames:
		fig, ax = plt.subplots(figsize=figsize, dpi=dpi, layout='constrained')
		ax2 = ax.twinx() if angles else None

		for group, axis, span, color in ((lengths, ax, length_span, length_color),
		                                 (angles, ax2, angle_span, angle_color)):
			if not group or axis is None or span is None:
				continue
			axis.set_ylim(*span)
			for key in group:
				if key not in values:
					continue
				value, error, display = values[key]
				if base is not None:
					value = value - base.get(key, 0.0)
				x = positions[key]
				axis.bar(x, value, width=0.62, color=color,
				         edgecolor='black', linewidth=0.6, zorder=2)
				if error:
					axis.errorbar(x, value, yerr=error, fmt='none', ecolor='black',
					              elinewidth=1.0, capsize=4, zorder=3)
				# Clear of the error bar, on the far side of the bar from zero.
				# A bar that went DOWN has its label underneath: placing every
				# label above the value would drop it inside a negative bar,
				# which in relative mode is half of them.
				gap = (span[1] - span[0]) * 0.04
				reach = (error or 0.0) + gap
				if value < 0:
					axis.text(x, value - reach, display, ha='center', va='top',
					          fontsize=value_size, zorder=4)
				else:
					axis.text(x, value + reach, display, ha='center', va='bottom',
					          fontsize=value_size, zorder=4)

		ax.set_xlim(-0.6, n_total - 0.4)
		ax.set_xticks(range(n_total))
		ax.set_xticklabels([f'${k}$' for k in lengths + angles], fontsize=label_size + 2)
		ax.set_ylabel((r'$\Delta$ length / $\mathrm{\AA}$' if relative
		               else r'length / $\mathrm{\AA}$'),
		              fontsize=label_size, color=length_color)
		ax.tick_params(axis='y', labelsize=label_size - 1, labelcolor=length_color)
		ax.tick_params(axis='x', length=0)
		if relative:
			ax.axhline(0.0, color='0.5', linewidth=0.8, zorder=1)
		if ax2 is not None:
			ax2.set_ylabel((r'$\Delta$ angle / $^\circ$' if relative
			                else r'angle / $^\circ$'),
			               fontsize=label_size, color=angle_color)
			ax2.tick_params(axis='y', labelsize=label_size - 1, labelcolor=angle_color)
			# The rule sits between the last length and the first angle, which is
			# also where the axis a bar belongs to changes.
			ax.axvline(len(lengths) - 0.5, color='0.35', linestyle='--',
			           linewidth=1.0, zorder=1)

		heading = frame_label if title is None else f'{title} — {frame_label}'
		ax.set_title(heading, fontsize=label_size + 1)

		frames.append(figure_to_frame(fig, dpi=dpi))
		plt.close(fig)

	return frames
