"""Animations and a trend plot from a sequential series of fits.

A sequential Pawley experiment leaves a directory full of fits -- one per
temperature, per pressure, per time step -- that are only interesting next to
each other. This turns that directory into material for a talk:

    <name>-fits.gif    every fit as a frame, in order
    <name>-cell.gif    the cell parameters as bars, changing frame by frame
    <name>-trend.svg   every parameter relative to the first fit, as a curve

All three come from one `pp --gif`, because they answer the same question and
nobody wants to run three commands to get the parts of one slide. The
animations can also be written as animated SVG.

The trend plot is the one that shows non-linear behaviour. Curvature is a
property of the whole run, and an animation shows one frame at a time -- a
cubic cell is a single bar bobbing up and down, from which nobody can see a
bend. Its x axis is the fit number, which quietly assumes the steps were evenly
spaced; for a quantitative axis the caller supplies the real values, and is
responsible for their being right.

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
#: The trend plot also carries the volume. It stays out of the bar chart, whose
#: two axes are Angstrom and degrees and have no room for cubic Angstrom -- but
#: a trend plot is dimensionless, and for a cubic cell under pressure V/V0 is
#: the quantity an equation of state is written in.
TREND_KEYS = CELL_KEYS + ('V',)

DEFAULT_DELAY_MS = 250
ANIMATION_FORMATS = ('gif', 'svg')

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


def _sortable(text):
	"""One captured piece of a filename as something `sorted` can compare.

	Numbers compare as numbers, so `2.5` lands between `2` and `10` -- which a
	natural sort gets wrong, because it splits `2.5` at the point into two
	integers. A single decimal comma is accepted too, since `1,5GPa` is how a
	German keyboard writes it. Anything else sorts naturally, after the numbers,
	and a group that took no part in the match sorts last of all.

	The leading tag keeps a float from ever being compared with a list.
	"""
	if text is None:
		return (2, [])
	candidate = text.strip()
	if candidate.count(',') == 1 and '.' not in candidate:
		candidate = candidate.replace(',', '.')
	try:
		return (0, float(candidate))
	except ValueError:
		return (1, natural_key(text))


def sort_by_pattern(names, pattern):
	"""Order `names` by what `pattern` captures from each: `(ordered, unmatched)`.

	The capture groups are the sort key, compared left to right, so
	`_(\\d+(?:\\.\\d+)?)GPa` sorts by pressure and `T(\\d+)_run(\\d+)` by
	temperature and then run. With no groups the whole match is the key.

	Names the pattern does not match are not dropped -- a fit silently missing
	from the timeline would be worse than one out of place -- so they are
	returned separately, in the order they came, for the caller to report and
	put at the end.

	Nothing here checks that the resulting order is RIGHT. The pattern is the
	user's statement of what order the run was measured in, and a pattern that
	captures the wrong digits sorts faithfully by the wrong digits.

	Raises ValueError for a pattern that is not a valid regular expression.
	"""
	try:
		regex = re.compile(pattern)
	except re.error as e:
		raise ValueError(f'not a valid regular expression: {pattern!r} ({e})') from e

	keyed, unmatched = [], []
	for name in names:
		match = regex.search(str(name))
		if match is None:
			unmatched.append(name)
			continue
		parts = match.groups() if regex.groups else (match.group(0),)
		keyed.append((tuple(_sortable(p) for p in parts), name))
	# `sorted` is stable, so names that capture the same key keep the order they
	# arrived in -- the natural order the caller has already put them in.
	ordered = [name for _key, name in sorted(keyed, key=lambda kv: kv[0])]
	return ordered, unmatched


def parse_x_values(spec):
	"""The x values for a series, from a list and/or ranges: `[float, ...]`.

	    0,0.5,1,2,4          a list
	    0:10:2               start:stop:step, stop INCLUDED -> 0,2,4,6,8,10
	    10:0:-2              stepping down, for a decompression run
	    0,0.5,1:5:1          both at once, joined in the order written

	The stop is included because that is what anyone means by "0 to 10 in steps
	of 2" -- a numpy-style exclusive stop would silently drop the last pressure
	of every run. Separators are commas or whitespace, so decimals take a point.

	Values are not checked for sense. They are attributed to the fits in the
	order the fits are drawn, and whether that attribution is correct is the
	user's to know. Only what cannot be a list of numbers is refused.
	"""
	if spec is None:
		return None
	tokens = [t for t in re.split(r'[,\s]+', str(spec).strip()) if t]
	if not tokens:
		raise ValueError('no values given')

	values = []
	for token in tokens:
		if ':' not in token:
			try:
				values.append(float(token))
			except ValueError:
				raise ValueError(f'{token!r} is not a number') from None
			continue

		parts = token.split(':')
		if len(parts) != 3:
			raise ValueError(f'{token!r}: a range is start:stop:step')
		try:
			start, stop, step = (float(p) for p in parts)
		except ValueError:
			raise ValueError(f'{token!r}: a range is start:stop:step, all numbers') from None
		if step == 0:
			raise ValueError(f'{token!r}: the step cannot be zero')
		if (stop - start) * step < 0:
			raise ValueError(f'{token!r}: a step of {step:g} never gets from '
			                 f'{start:g} to {stop:g}')
		# Counted rather than accumulated, so 0:1:0.1 has eleven values instead
		# of ten-and-a-rounding-error; the tolerance lets the stop itself in.
		count = int(np.floor((stop - start) / step + 1e-9)) + 1
		values.extend(round(start + i * step, 12) for i in range(count))
	return values


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


def figure_to_svg(fig):
	"""One rendered figure as SVG text, for `write_animated_svg`.

	Same rule as `figure_to_frame` about `bbox_inches`: every frame has to share
	one canvas, and cropping to the artists would give each its own.
	"""
	buffer = io.StringIO()
	fig.savefig(buffer, format='svg', facecolor='white', transparent=False)
	return buffer.getvalue()


_SVG_ROOT = re.compile(r'<svg\b[^>]*>', re.DOTALL)
_SVG_ATTR = re.compile(r'\b(width|height|viewBox)="([^"]*)"')
_SVG_ID = re.compile(r'\bid="([^"]+)"')


def _svg_body(svg_text, prefix):
	"""The drawing inside one frame's `<svg>`, with every id made unique to it.

	Every matplotlib SVG names its pieces the same way -- `figure_1`, `axes_1`,
	`line2d_3`, glyphs such as `DejaVuSans-31` -- and stacking frames into one
	document would give each of those ids several owners. A reference then
	resolves to whichever frame came first, so a later frame draws its curve
	clipped by an earlier frame's axes or its tick labels in borrowed glyphs.
	Prefixing every id, and every `url(#...)` and `href="#..."` that points at
	one, gives each frame its own namespace.

	Regular expressions rather than an XML parser because the input is always
	matplotlib's own, very regular, output -- and ElementTree would rename the
	namespaces on the way through, which some viewers then refuse.
	"""
	root = _SVG_ROOT.search(svg_text)
	if root is None:
		raise ValueError('not an SVG document')
	body = svg_text[root.end():svg_text.rfind('</svg>')]
	body = re.sub(r'<metadata>.*?</metadata>', '', body, flags=re.DOTALL)

	body = _SVG_ID.sub(lambda m: f'id="{prefix}{m.group(1)}"', body)
	body = re.sub(r'url\(#([^)]+)\)', lambda m: f'url(#{prefix}{m.group(1)})', body)
	body = re.sub(r'href="#([^"]+)"', lambda m: f'href="#{prefix}{m.group(1)}"', body)
	return _compact(body).strip()


_USE_STYLE = re.compile(r'(<use xlink:href="#([^"]+)"[^>]*?) style="([^"]*)"')
_DEF_STYLE = re.compile(r'<path id="([^"]+)"[^>]*? style="([^"]*)"')


def _compact(body):
	"""Shrink one frame without changing a pixel of it.

	A fit frame is mostly observed points: thousands of `<use>` elements, one per
	'x', which is most of the file. Each carries a `style` that is usually
	character-for-character the style already on the marker it points to -- and
	the marker's own style wins over anything a `<use>` passes down, so the copy
	does nothing. Only exact matches are dropped: a Bragg tick's `<use>` adds a
	fill its marker lacks, and that one stays. On a fit frame this takes off
	about a quarter, and renders identically -- checked pixel for pixel.

	Rounding the coordinates was tried as well and deliberately left out. It
	saves little more (another ~10%) and is NOT exact: a hundredth of a point is
	invisible to the eye, but it moves antialiased edges where markers pile up
	at a peak, and a size optimisation that quietly alters the picture is the
	wrong kind of default.
	"""
	def_styles = dict(_DEF_STYLE.findall(body))

	def drop_redundant(m):
		head, ref, style = m.group(1), m.group(2), m.group(3)
		return head if def_styles.get(ref) == style else m.group(0)

	return _USE_STYLE.sub(drop_redundant, body)


def write_animated_svg(frames, path, delay_ms=DEFAULT_DELAY_MS):
	"""Write SVG frames as ONE self-contained animated SVG. Returns the path.

	Each frame becomes a group that is switched on for its slice of the cycle by
	SMIL `<animate>`, looping forever. Nothing is scripted, so it plays in any
	browser with the file opened directly.

	The groups are hidden by `display="none"` except the first, so a viewer that
	draws SVG but does not run its animation -- which includes PowerPoint -- shows
	the first frame as a clean still instead of every frame piled on top of each
	other.

	Vector all the way through: it stays sharp at any size, which is the point of
	choosing it over a GIF, and it is not limited to 256 colours.
	"""
	if not frames:
		raise ValueError('no frames to write')

	root = _SVG_ROOT.search(frames[0])
	if root is None:
		raise ValueError('first frame is not an SVG document')
	attrs = dict(_SVG_ATTR.findall(root.group(0)))
	canvas = tuple(attrs.get(k) for k in ('width', 'height', 'viewBox'))
	for i, frame in enumerate(frames[1:], start=2):
		other = _SVG_ROOT.search(frame)
		other_attrs = dict(_SVG_ATTR.findall(other.group(0))) if other else {}
		if tuple(other_attrs.get(k) for k in ('width', 'height', 'viewBox')) != canvas:
			raise ValueError(f'frame {i} has a different canvas from frame 1; an '
			                 f'animation needs every frame the same size')

	n = len(frames)
	total_s = max(int(delay_ms), 20) * n / 1000.0

	out = ['<?xml version="1.0" encoding="utf-8" standalone="no"?>',
	       '<svg xmlns="http://www.w3.org/2000/svg" '
	       'xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1" '
	       + ' '.join(f'{k}="{v}"' for k, v in zip(('width', 'height', 'viewBox'), canvas)
	                  if v is not None) + '>']

	for i, frame in enumerate(frames):
		start = i / n
		end = (i + 1) / n
		# Discrete keyframes: off until this frame's slice begins, on through it,
		# off again after. The first frame starts on and the last stays on to the
		# end of the cycle, so there is never an instant with nothing drawn.
		if n == 1:
			values, times = 'inline', '0'
		elif i == 0:
			values, times = 'inline;none', f'0;{end:.6f}'
		elif i == n - 1:
			values, times = 'none;inline', f'0;{start:.6f}'
		else:
			values, times = 'none;inline;none', f'0;{start:.6f};{end:.6f}'

		out.append(f'<g id="frame{i + 1}" display="{"inline" if i == 0 else "none"}">')
		out.append(f'<animate attributeName="display" values="{values}" keyTimes="{times}" '
		           f'dur="{total_s:.3f}s" calcMode="discrete" repeatCount="indefinite"/>')
		out.append(_svg_body(frame, prefix=f'f{i + 1}-'))
		out.append('</g>')

	out.append('</svg>')
	with open(str(path), 'w', encoding='utf-8', newline='\n') as fh:
		fh.write('\n'.join(out) + '\n')
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
		#: The x value of each frame, parallel to `frames`. Stored per frame
		#: rather than by position in the run, because a fit whose .out carried
		#: no cell is absent here but still used up its x value -- aligning by
		#: index would shift every later point onto its neighbour's pressure.
		self.xs = []

	def add(self, label, raw_params, x=None):
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
			self.xs.append(x)

	def __len__(self):
		return len(self.frames)

	def keys(self, order=CELL_KEYS):
		"""The parameters present in every frame, in `order`.

		Intersection rather than union: a parameter that appears halfway through
		the series would otherwise make a bar pop into existence mid-animation,
		and a missing bar is a worse lie than a missing parameter.
		"""
		if not self.frames:
			return []
		common = set(self.frames[0][1])
		for _label, values in self.frames[1:]:
			common &= set(values)
		return [k for k in order if k in common]

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
                       label_size=9, value_size=8, capture=None):
	"""Every frame of the cell-parameter animation.

	`capture` turns each finished figure into a frame -- `figure_to_frame` for a
	GIF (the default), `figure_to_svg` for an animated SVG -- so the drawing is
	written once and does not care which file it ends up in.

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

	if capture is None:
		capture = lambda fig: figure_to_frame(fig, dpi=dpi)  # noqa: E731

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

		frames.append(capture(fig))
		plt.close(fig)

	return frames


# ------------------------------------------------------------ the trend plot

_TREND_SYMBOLS = {'a': 'a', 'b': 'b', 'c': 'c', r'\alpha': r'\alpha',
                  r'\beta': r'\beta', r'\gamma': r'\gamma', 'V': 'V'}


def ratio_series(series, keys=None):
	"""Every parameter relative to its first fit: `{key: (xs, ratios, errors)}`.

	A ratio rather than the raw value, because the question is how the cell
	CHANGES, and a ratio puts every parameter on one dimensionless scale that
	starts at 1: a 17 A edge, a 110 degree angle and a 5000 A^3 volume become
	directly comparable, and for a cubic cell V/V0 = (a/a0)^3 is visible as
	exactly that.

	Uncertainties are propagated through the division as independent:

	    sigma(r) = r * sqrt((sigma_p / p)^2 + (sigma_p0 / p0)^2)

	except for the first point, which is 1 by definition and carries no error
	at all -- running the formula on it would divide the value by itself and
	report an uncertainty on a number that was never measured.

	x is each frame's stored x value, or its position in the run counting from 1
	when none was given. That second case assumes evenly spaced steps.
	"""
	if keys is None:
		keys = series.keys(order=TREND_KEYS)
	if not keys or len(series) == 0:
		return {}

	xs = [x if x is not None else float(i + 1) for i, x in enumerate(series.xs)]
	first = series.frames[0][1]
	out = {}
	for key in keys:
		p0, s0, _display = first[key]
		if p0 == 0:
			continue   # nothing is relative to zero
		rel0 = (s0 or 0.0) / abs(p0)
		ratios, errors = [], []
		for i, (_label, values) in enumerate(series.frames):
			p, s, _display = values[key]
			r = p / p0
			ratios.append(r)
			if i == 0:
				errors.append(0.0)
			else:
				rel = (s or 0.0) / abs(p) if p else 0.0
				errors.append(abs(r) * float(np.hypot(rel, rel0)))
		out[key] = (list(xs), ratios, errors)
	return out


def render_trend(series, x_label=None, figsize=(6.0, 4.0), title=None,
                 label_size=11, tick_size=10, legend_size=9):
	"""A static plot of every parameter relative to the first fit. Returns a figure.

	Points are joined in the order they were measured, not re-sorted by x, so a
	compression-then-decompression run draws its loop instead of folding it
	flat -- hysteresis is exactly what that shape would be hiding.

	Nothing is fitted to the points. A line through them would be a claim about
	the physics (an equation of state, a thermal expansion model) that this has
	no business making on the user's behalf.
	"""
	import matplotlib.pyplot as plt

	ratios = ratio_series(series)
	if not ratios:
		return None

	fig, ax = plt.subplots(figsize=figsize, layout='constrained')
	ax.axhline(1.0, color='0.6', linestyle='--', linewidth=0.8, zorder=1)
	for key, (xs, rs, es) in ratios.items():
		sym = _TREND_SYMBOLS.get(key, key)
		ax.errorbar(xs, rs, yerr=es, marker='o', markersize=4, linewidth=1.0,
		            capsize=3, elinewidth=0.8, label=f'${sym}/{sym}_0$', zorder=2)

	ax.set_xlabel(x_label or 'fit number', fontsize=label_size)
	ax.set_ylabel('relative to first fit', fontsize=label_size)
	ax.tick_params(labelsize=tick_size, direction='in', top=True, right=True)
	# Offsets make a ratio axis unreadable: "1e-3 + 1" beside the tick labels
	# is harder work than just printing 0.998.
	ax.ticklabel_format(axis='y', useOffset=False)
	ax.legend(fontsize=legend_size, frameon=False)
	if title:
		ax.set_title(title, fontsize=label_size)
	return fig
