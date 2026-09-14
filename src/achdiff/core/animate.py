"""Animations and a trend plot from a sequential series of fits.

A sequential Pawley experiment leaves a directory full of fits -- one per
temperature, per pressure, per time step -- that are only interesting next to
each other. This turns that directory into material for a talk:

    <name>-fits.gif    every fit as a frame, in order
    <name>-cell.gif    the cell parameters as bars, changing frame by frame
    <name>-steps.gif   the change from fit to fit as bars along the run, with
                       its rolling mean and the running ratio to the first fit
    <name>-trend.svg   every parameter relative to the first fit, as a curve

All of them come from one `pp --gif`, because they answer the same question
and nobody wants to run four commands to get the parts of one slide. The
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


def read_x_map(path):
	"""A hand-edited run order: `[(fit_name, x), ...]`, in the order written.

	One fit per line, its x value last::

	    # compression
	    CN-cubic_0GPa_pawley_01      0
	    CN-cubic_5GPa_pawley_01      5
	    # decompression, back to check it is reversible
	    CN-cubic_5GPa-r_pawley_01    5

	The file is the timeline: fits play in the order listed, only listed fits
	play, and an x value may appear as often as it was measured. That is what a
	flag cannot express -- a run that goes up and comes back down visits the
	same pressures twice, so no sort order recovers it and no value list is safe
	to count by hand across forty fits.

	The x value is the last whitespace-separated token, so fit names may
	contain spaces. `#` starts a comment; blank lines are ignored.

	Raises ValueError naming the line for anything that is not a name and a
	number, or for a fit listed twice -- almost always an editing slip, and
	drawing one measurement twice would put a frame in the animation that was
	never taken.
	"""
	entries, seen = [], {}
	with open(str(path), encoding='utf-8-sig') as fh:
		for lineno, raw_line in enumerate(fh, start=1):
			line = raw_line.split('#', 1)[0].strip()
			if not line:
				continue
			parts = line.rsplit(None, 1)
			if len(parts) < 2:
				# No whitespace: a file saved from a spreadsheet, "name;0,5" from a
				# German Excel or "name,5" from an English one.
				for sep in (';', ',', '\t'):
					if sep in line:
						parts = line.rsplit(sep, 1)
						break
			if len(parts) < 2:
				raise ValueError(f'line {lineno}: "{line}" needs a fit name and an x value')
			name, value = parts[0].strip().rstrip(',;').strip(), parts[1].strip()
			number = _sortable(value)
			if number[0] != 0:
				raise ValueError(f'line {lineno}: "{value}" is not a number '
				                 f'(the x value goes last on the line)')
			x = number[1]
			if name in seen:
				raise ValueError(f'line {lineno}: {name} is already listed on line '
				                 f'{seen[name]}; each fit can appear once')
			seen[name] = lineno
			entries.append((name, x))
	if not entries:
		raise ValueError('no fits listed')
	return entries


def write_x_map_template(path, names, xs=None, source=''):
	"""Write a starting point for `read_x_map`: every fit, one per line.

	`xs` pre-fills the values where something could supply them -- typically the
	number the --sort-key pattern captured from each name -- and leaves the rest
	blank to be filled in. The header says where the pre-filled values came
	from, because a guessed value sitting in a file looks exactly like a checked
	one.
	"""
	xs = list(xs) if xs is not None else [None] * len(names)
	width = max((len(n) for n in names), default=0)
	lines = [
		'# Run order and x value for pp --gif --x-map.',
		'#',
		'# One fit per line, x value last. Fits play in the order listed, and only',
		'# listed fits play: move lines to reorder, delete or # a line to leave a fit',
		'# out. The same x may appear more than once -- a return leg revisits its',
		'# pressures, and that is exactly what this file is for.',
		'#',
		(f'# x values were pre-filled from {source}. Check every one.'
		 if source else '# Fill in the x value of every fit.'),
		'',
	]
	for name, x in zip(names, xs):
		value = '' if x is None else f'{x:g}'
		lines.append(f'{name:<{width}}\t{value}'.rstrip())
	with open(str(path), 'w', encoding='utf-8', newline='\n') as fh:
		fh.write('\n'.join(lines) + '\n')
	return path


def first_number(names, pattern):
	"""The first capture of `pattern` in each name, as a float, or None.

	Used to pre-fill a template from the same pattern the user already wrote for
	--sort-key, so forty pressures do not have to be typed out by hand.
	"""
	regex = re.compile(pattern)
	out = []
	for name in names:
		m = regex.search(str(name))
		captured = (m.group(1) if (m and regex.groups) else (m.group(0) if m else None))
		key = _sortable(captured)
		out.append(key[1] if key[0] == 0 else None)
	return out


def monotonic_legs(xs):
	"""Split a run into stretches where x only rises or only falls: `[(indices, rising)]`.

	A reversibility run goes up and comes back down over the same pressures, so
	its return points sit on top of the outbound ones -- which, if the change
	really is reversible, is the whole result. Drawn as one line with one marker
	style, the two legs are indistinguishable exactly when they agree. Splitting
	them lets the trend plot draw each direction differently.

	The turning point belongs to both legs, so the drawn line is continuous.
	Repeated equal x values extend the leg they are in rather than starting a
	new one. Purely a matter of the order and values given: nothing here knows
	what compression is.
	"""
	n = len(xs)
	if n < 2:
		return [(list(range(n)), True)]
	legs = []
	start, direction = 0, 0
	for i in range(1, n):
		step = xs[i] - xs[i - 1]
		sign = (step > 0) - (step < 0)
		if sign == 0:
			continue
		if direction == 0:
			direction = sign
		elif sign != direction:
			legs.append((list(range(start, i)), direction > 0))
			start, direction = i - 1, sign
	legs.append((list(range(start, n)), direction >= 0))
	return legs


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


def _shared_palette(frames, samples=12):
	"""An adaptive 256-colour palette covering colours from across `frames`.

	Frames are sampled evenly -- always including the first and last -- shrunk
	with nearest-neighbour so a solid bar keeps its exact colour rather than
	being blended into its background, and stacked into one sheet that the
	palette is derived from.
	"""
	from PIL import Image

	n = len(frames)
	picks = sorted({0, n - 1} | {round(i * (n - 1) / max(samples - 1, 1))
	                              for i in range(samples)})
	w, h = frames[0].size
	tw, th = max(w // 2, 1), max(h // 2, 1)
	sheet = Image.new('RGB', (tw, th * len(picks)), 'white')
	for row, i in enumerate(picks):
		sheet.paste(frames[i].convert('RGB').resize((tw, th), Image.NEAREST), (0, row * th))
	return sheet.convert('P', palette=Image.ADAPTIVE, colors=256)


def write_gif(frames, path, delay_ms=DEFAULT_DELAY_MS, loop=0):
	"""Write `frames` as an animated GIF. Returns the path.

	`loop=0` means forever, which is what a slide wants.

	Frames are quantised to ONE shared adaptive palette. Letting each frame pick
	its own 256 colours makes the background shimmer between frames, which on a
	projector reads as a fault in the data.

	That palette is taken from a sample spread across the whole animation, not
	from the first frame. An animation that builds up -- the step chart starts
	with no bars at all -- only shows some of its colours later, and a palette
	that never saw them maps every bar onto the nearest grey.
	"""
	from PIL import Image

	if not frames:
		raise ValueError('no frames to write')
	sizes = {frame.size for frame in frames}
	if len(sizes) > 1:
		raise ValueError(f'frames differ in size ({sorted(sizes)}); a GIF needs one size')

	palette = _shared_palette(frames)
	quantised = [f.convert('RGB').quantize(palette=palette, dither=Image.NONE)
	             for f in frames]
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

	from matplotlib.lines import Line2D

	fig, ax = plt.subplots(figsize=figsize, layout='constrained')
	ax.axhline(1.0, color='0.6', linestyle='--', linewidth=0.8, zorder=1)

	# Every parameter shares one x sequence, so the legs are worked out once.
	xs_all = next(iter(ratios.values()))[0]
	legs = monotonic_legs(xs_all)
	returns = any(not rising for _idx, rising in legs)

	for k, (key, (xs, rs, es)) in enumerate(ratios.items()):
		sym = _TREND_SYMBOLS.get(key, key)
		color = f'C{k}'
		for j, (idx, rising) in enumerate(legs):
			# Filled and solid on the way up, open and dashed on the way back.
			# A reversible change puts the return points exactly on top of the
			# outbound ones, and without this they would vanish into them in
			# precisely the case that matters.
			#
			# A later leg starts at the previous leg's last point so the line
			# joins up, but that turning point was measured once, on the earlier
			# leg -- so it gets no marker here, or it would be drawn in the
			# style of a direction it was never measured in.
			marks = list(range(1, len(idx))) if j > 0 else None
			ax.errorbar([xs[i] for i in idx], [rs[i] for i in idx],
			            yerr=[0.0 if (j > 0 and n == 0) else es[i] for n, i in enumerate(idx)],
			            markevery=marks, color=color, marker='o',
			            markersize=4 if rising else 5,
			            markerfacecolor=color if rising else 'white',
			            linestyle='-' if rising else '--', linewidth=1.0,
			            capsize=3, elinewidth=0.8, zorder=3 if not rising else 2,
			            label=f'${sym}/{sym}_0$' if j == 0 else None)

	ax.set_xlabel(x_label or 'fit number', fontsize=label_size)
	ax.set_ylabel('relative to first fit', fontsize=label_size)
	ax.tick_params(labelsize=tick_size, direction='in', top=True, right=True)
	# Offsets make a ratio axis unreadable: "1e-3 + 1" beside the tick labels
	# is harder work than just printing 0.998.
	ax.ticklabel_format(axis='y', useOffset=False)

	handles, labels = ax.get_legend_handles_labels()
	if returns:
		handles += [Line2D([], [], color='0.3', marker='o', markersize=4, linestyle='-'),
		            Line2D([], [], color='0.3', marker='o', markersize=5,
		                   markerfacecolor='white', linestyle='--')]
		labels += ['x increasing', 'x decreasing']
	ax.legend(handles, labels, fontsize=legend_size, frameon=False)
	if title:
		ax.set_title(title, fontsize=label_size)
	return fig


# ------------------------------------------------------------ the step chart

#: Okabe-Ito vermillion and bluish green: a decrease and an increase that stay
#: distinct under the common colour-vision deficiencies, which the obvious
#: red/green pair does not -- and on a projected slide nobody can ask.
STEP_DOWN_COLOR = '#D55E00'
STEP_UP_COLOR = '#009E73'
RUNNING_COLOR = '#0072B2'
DEFAULT_ROLLING = 5

# A step this many times the typical one is drawn to the edge of the axis and
# labelled with its value, rather than being allowed to set the scale.
_OFF_SCALE_FACTOR = 8.0


def step_series(series, keys=None, window=DEFAULT_ROLLING, have_x=True):
	"""Fit-to-fit change of every parameter, for the step chart.

	Returns ``{key: dict}`` with, per parameter:

	    ratios, ratio_errors   p_i / p_0, as in `ratio_series`
	    steps, step_errors     100 * (p_i / p_(i-1) - 1), one per fit after the first
	    rolling                trailing mean of `window` steps, NaN where undefined

	A step's uncertainty is propagated from the two fits it joins, taken as
	independent.

	The rolling mean runs within one leg of the run at a time and is only
	defined once a full window of steps exists in that leg. Averaging across a
	turning point would blend compression into decompression, and a mean of
	two steps labelled "rolling mean of 5" would misstate what it is.
	`window` of 0 or 1 turns it off.
	"""
	if keys is None:
		keys = series.keys()
	if not keys or len(series) < 2:
		return {}

	ratios = ratio_series(series, keys)
	xs = next(iter(ratios.values()))[0] if ratios else []
	legs = monotonic_legs(xs if have_x else list(range(len(series))))
	out = {}
	for key in keys:
		if key not in ratios:
			continue
		per_fit = [frame_values[key] for _label, frame_values in series.frames]
		steps, errs = [], []
		for i in range(1, len(per_fit)):
			p, s, _d = per_fit[i]
			q, t, _d = per_fit[i - 1]
			if q == 0 or p == 0:
				steps.append(float('nan'))
				errs.append(0.0)
				continue
			r = p / q
			steps.append(100.0 * (r - 1.0))
			errs.append(100.0 * abs(r) * float(np.hypot((s or 0.0) / abs(p),
			                                            (t or 0.0) / abs(q))))
		rolling = [float('nan')] * len(steps)
		if window and window > 1:
			for idx, _rising in legs:
				leg_steps = [i - 1 for i in idx[1:]]      # step i-1 ends at fit i
				for m in range(window - 1, len(leg_steps)):
					chunk = [steps[j] for j in leg_steps[m - window + 1:m + 1]]
					rolling[leg_steps[m]] = float(np.mean(chunk))
		_xs, rs, res = ratios[key]
		out[key] = {'ratios': rs, 'ratio_errors': res, 'steps': steps,
		            'step_errors': errs, 'rolling': rolling, 'legs': legs}
	return out


def step_limit(steps, errors):
	"""Half-height of a step panel's axis: `(limit, off_scale_indices)`.

	Set from the ordinary steps, not the largest. A reversible run's return
	often recovers the whole compression in one step -- forty times the size of
	any step before it -- and scaling to that would flatten every other bar into
	a line. Those few are drawn to the edge and labelled with their real value.
	"""
	finite = [(abs(s), e) for s, e in zip(steps, errors) if np.isfinite(s)]
	if not finite:
		return 1.0, set()
	sizes = np.array([s for s, _e in finite])
	typical = float(np.median(sizes))
	cap = typical * _OFF_SCALE_FACTOR if typical > 0 else float('inf')
	ordinary = [s + e for s, e in finite if s <= cap] or [s + e for s, e in finite]
	limit = (max(ordinary) * 1.25) or 1.0
	off = {i for i, s in enumerate(steps) if np.isfinite(s) and abs(s) > limit}
	return limit, off


def _index_ticks(n, xs, have_x, target=7):
	"""Tick positions and labels along the fit order.

	The bars sit at their place in the run rather than at their x value, so a
	run that comes back down still reads left to right in time. The labels carry
	the x value so the pressure is never lost.
	"""
	if n <= target:
		ticks = list(range(n))
	else:
		stride = max(1, int(round((n - 1) / (target - 1))))
		ticks = [t for t in range(0, n - 1, stride) if n - 1 - t >= stride * 0.6] + [n - 1]
	labels = [f'{xs[t]:g}' if have_x else f'{t + 1}' for t in ticks]
	return ticks, labels


def render_step_frames(series, figsize=(6.0, 4.0), dpi=150, title=None,
                       x_label=None, have_x=False, window=DEFAULT_ROLLING,
                       label_size=10, tick_size=9, legend_size=8, capture=None):
	"""Frames of the step chart: the run revealed one fit at a time.

	One panel per cell parameter, stacked on a shared axis of fit order. In
	each, a bar is the change since the previous fit -- vermillion where the
	parameter shrank, green where it grew -- with its propagated error; the
	black line is the rolling mean of those bars; and the blue line on the right
	axis is the running ratio to the first fit, dashed with open markers after
	a turning point, as in the trend plot.

	The picture is a trade log with its running average: single steps show which
	fits stand out, the rolling mean shows whether the rate is steady or
	drifting, and the running ratio shows where the whole run has got to. The
	bars stand at their place in the run, not at their x value, so it reads left
	to right in time even when the run comes back down.

	Every axis is fixed to the full run before the first frame, as elsewhere.

	The volume is left out: it follows from the edges, and a panel repeating
	another adds height without adding information.
	"""
	import matplotlib.pyplot as plt

	if capture is None:
		capture = lambda fig: figure_to_frame(fig, dpi=dpi)  # noqa: E731

	keys = series.keys()
	data = step_series(series, keys, window, have_x=have_x)
	keys = [k for k in keys if k in data]
	n = len(series)
	if not keys or n < 2:
		return []

	xs = next(iter(ratio_series(series, keys).values()))[0]
	legs = data[keys[0]]['legs']
	turns = [idx[0] for idx, _rising in legs[1:]]

	limits = {}
	for key in keys:
		d = data[key]
		limit, off = step_limit(d['steps'], d['step_errors'])
		lo = min(r - e for r, e in zip(d['ratios'], d['ratio_errors']))
		hi = max(r + e for r, e in zip(d['ratios'], d['ratio_errors']))
		pad = max(hi - lo, 1e-6) * 0.08
		limits[key] = (limit, off, (lo - pad, hi + pad))

	ticks, tick_labels = _index_ticks(n, xs, have_x)
	height = figsize[1] if len(keys) == 1 else figsize[1] * 0.62 * len(keys)

	# The legend is built from stand-ins, identical on every frame. Collected
	# from what is drawn, it would grow as lines appear, and a legend that
	# changes size reflows the layout and makes the axes jump between frames.
	# It sits above the panels, where it can never cover a bar.
	from matplotlib.lines import Line2D
	from matplotlib.patches import Patch
	legend_handles = [Patch(color=STEP_DOWN_COLOR, label='decrease'),
	                  Patch(color=STEP_UP_COLOR, label='increase')]
	if window and window > 1:
		legend_handles.append(Line2D([], [], color='black', lw=1.3,
		                             label=f'rolling mean of {window} steps'))
	legend_handles.append(Line2D([], [], color=RUNNING_COLOR, lw=1.3, marker='o',
	                             markersize=2.8, label='relative to first fit'))
	if turns:
		legend_handles.append(Line2D([], [], color=RUNNING_COLOR, lw=1.3, linestyle='--',
		                             marker='o', markersize=2.8, markerfacecolor='white',
		                             label='after the turn'))

	frames = []
	for k in range(n):
		fig, axes = plt.subplots(len(keys), 1, figsize=(figsize[0], height), dpi=dpi,
		                         sharex=True, layout='constrained', squeeze=False)
		axes = list(axes[:, 0])
		for ax, key in zip(axes, keys):
			d = data[key]
			limit, off_scale, (r_lo, r_hi) = limits[key]
			sym = _TREND_SYMBOLS.get(key, key)
			right = ax.twinx()

			for j in range(min(k, n - 1)):
				v, e = d['steps'][j], d['step_errors'][j]
				if not np.isfinite(v):
					continue
				pos = j + 1                                  # the step ends at fit j+1
				color = STEP_DOWN_COLOR if v < 0 else STEP_UP_COLOR
				shown = float(np.clip(v, -limit, limit))
				ax.bar(pos, shown, width=0.75, color=color, zorder=2)
				if j in off_scale:
					# Beside the bar rather than centred on it, on whichever side has
					# room: a return step is usually the last bar, and a centred label
					# there runs into the axis on the right.
					right_half = pos > (n - 1) / 2
					ax.annotate(f'{v:+.3g} %\n(off scale)', (pos, shown),
					            xytext=(-6 if right_half else 6, -2 if v > 0 else 2),
					            textcoords='offset points',
					            ha='right' if right_half else 'left',
					            va='top' if v > 0 else 'bottom',
					            fontsize=legend_size, color='black', zorder=6)
				elif e:
					ax.errorbar(pos, v, yerr=e, fmt='none', ecolor='0.2',
					            elinewidth=0.6, capsize=1.5, zorder=3)

			# Rolling mean, one line per leg and never joined across a turn.
			for idx, _rising in legs:
				seg = [i for i in idx[1:] if i <= k and np.isfinite(d['rolling'][i - 1])]
				if seg:
					ax.plot(seg, [d['rolling'][i - 1] for i in seg], color='black', lw=1.3,
					        zorder=4)

			# Running ratio. A later leg starts at the previous one's last point so
			# the line joins, but that point keeps the marker of the leg it was
			# measured on.
			for j, (idx, rising) in enumerate(legs):
				seg = [i for i in idx if i <= k]
				if not seg:
					continue
				right.plot(seg, [d['ratios'][i] for i in seg], color=RUNNING_COLOR, lw=1.3,
				           linestyle='-' if rising else '--', zorder=5)
				marked = seg[1:] if j > 0 else seg
				right.plot(marked, [d['ratios'][i] for i in marked], linestyle='none',
				           marker='o', markersize=2.8, color=RUNNING_COLOR,
				           markerfacecolor=RUNNING_COLOR if rising else 'white', zorder=5)

			for t in turns:
				ax.axvline(t + 0.5, color='0.55', linestyle=':', linewidth=0.9, zorder=1)
			ax.axhline(0.0, color='0.5', linewidth=0.8, zorder=1)
			ax.set_xlim(-0.8, n - 0.2)
			ax.set_ylim(-limit, limit)
			right.set_ylim(r_lo, r_hi)
			right.ticklabel_format(axis='y', useOffset=False)
			ax.set_ylabel(f'$\\Delta {sym}$ since previous fit / %', fontsize=label_size)
			right.set_ylabel(f'${sym}/{sym}_0$', fontsize=label_size, color=RUNNING_COLOR)
			ax.tick_params(labelsize=tick_size, direction='in')
			right.tick_params(axis='y', labelsize=tick_size, labelcolor=RUNNING_COLOR,
			                  direction='in')

		axes[-1].set_xticks(ticks)
		axes[-1].set_xticklabels(tick_labels)
		axes[-1].set_xlabel(f'{x_label if have_x else "fit number"}   '
		                    f'(bars in measurement order)', fontsize=label_size)
		heading = (f'fit {k + 1} of {n}, x = {xs[k]:g}' if have_x else f'fit {k + 1} of {n}')
		# On the top panel rather than the figure: a figure title and an outside
		# legend both claim the top edge and draw over each other, while an axes
		# title is part of the panel and the legend is laid out above it.
		axes[0].set_title(heading if title is None else f'{title}: {heading}',
		                  fontsize=label_size)
		fig.legend(handles=legend_handles, loc='outside upper center',
		           ncol=min(len(legend_handles), 3), fontsize=legend_size, frameon=False)
		frames.append(capture(fig))
		plt.close(fig)
	return frames
