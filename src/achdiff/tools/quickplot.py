"""Plot PXRD data files of various formats stacked on a single axis.

Supports: .xy, .txt, .csv, .dat (Riet7), .raw (via TOPAS7), .brml (Bruker), .cif (simulated).
"""

import re
import os
import sys
import pathlib
import argparse
import zipfile
from glob import glob
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator, MultipleLocator
from matplotlib.transforms import blended_transform_factory


CIF_LOC = r'D:\Workfolder\<you>\CIF_LOC'
script_name = pathlib.Path(__file__).name

# Recognised extensions and the reader each one dispatches to. Order also
# defines preference if two files share a stem (xy beats raw etc.).
READER_EXTENSIONS = ('xy', 'txt', 'csv', 'dat', 'raw', 'brml', 'cif', 'xml')


SETTINGS = {
	'x_range': None,
	'y_offsetting': ['CENTER', 'TOPDOWN'][0],
	'normalize': ['GLOBAL', 'INDIVIDUAL'][1],
	'no_intensities': True,
	'yoff': 0.8,
	'title_font_size': 14,
	'tick_label_font_size': 10,
	'title_font_weight': 'bold',
	'transparent': True,
	'xlabel_font_size': 12,
	'xlabel_font_weight': None,
	'ylabel_font_size': 12,
	'ylabel_font_weight': None,
	'x_step_size': 5,
	'line_width': 0.6,
	'highlight_alpha': 0.18,
	'highlight_default_color': 'red',
	'cif_wavelength': 1.54060,  # Cu Kα1
	'label_font_size': 9,
	'margin_top': 0.05,          # y-axis whitespace tolerance above the data, as a fraction of data range.
	'margin_bottom': 0.05,       # y-axis whitespace tolerance below the data, as a fraction of data range.
	'label_x_frac': 0.98,        # x position of trace labels in axes coords (0 = left, 1 = right edge).
	'label_y_pad_frac': 0.01,    # vertical nudge above each trace's baseline, as a fraction of data range.
	'broadening': 0.1,           # Lorentzian FWHM (in 2theta degrees) applied to simulated CIF / PDF-card patterns.

	# PDF card (.xml) handling. A PDF card only covers the measured 2theta
	# interval, so the simulated pattern is flat outside it — that flat region is
	# drawn dashed. The solid region is the measured reflection span padded by a
	# few FWHM so the edge peaks aren't bisected by the solid/dashed boundary.
	'pdf_xml_solid_tol_fwhm': 3.0,      # solid-region padding beyond measured span, in multiples of FWHM
	'pdf_xml_outside_linestyle': (0, (4, 3)),  # dash style for the flat extrapolated region

	# Trace colors. The reflection marker palette is kept disjoint from this
	# list so dotted reflection lines never read as a data trace.
	'trace_color_cycle': ['tab:blue', 'tab:orange', 'tab:green', 'tab:red',
	                      'tab:purple', 'tab:brown', 'tab:pink',
	                      'tab:olive', 'tab:cyan'],

	# Default color cycle for reflection marker sets when --reflections is used
	# without an explicit color. Distinct saturated hues that are NOT in
	# `trace_color_cycle`, so reflection lines never read as a data trace.
	# (At a thin dotted line width, shades of gray are indistinguishable from
	# each other and from black — so we use clearly different colours instead.)
	'reflection_color_cycle': ['black', 'magenta', 'teal', 'goldenrod', 'darkviolet'],
	'reflection_n_top': 10,  # Default count of strongest reflections per set
	'reflection_linestyle': ':',
	'reflection_linewidth': 0.7,
	'reflection_alpha': 0.75,
	'reflection_label_font_size': 9,
	'reflection_label_marker': '┊ ',  # ┊ — visual hint at a dotted vertical
	'reflection_label_inset': 0.015,  # gap from the top/right axes edges (axes-fraction)
	'reflection_label_step': 0.045,   # vertical spacing between stacked set labels (axes-fraction)
}


DEFAULTS = {
	'silent': False,
	'input': None,
	'verbose': False,
	'extension': 'svg',
	'dpi': 300,
	'size': (7, 5),
	'highlights': None,
	'title': None,
	'stack': True,
	'limit_extension': False,
}


# ==========================================
# USER OVERRIDES  (for per-project customisation)
# ==========================================
# When this script is copied into a project directory to serve as a custom
# plot recipe, edit the values below instead of passing CLI flags. Anything
# set to a non-None value overrides BOTH the CLI argument and the default —
# so `python pxrd_quickplot.py` (no flags) reproduces your customisation.
#
# Leave entries as None / empty to fall back to the normal CLI behaviour.

OVERRIDES = {
	# ---- inputs ----
	# Explicit list of files (replaces -i and the cwd glob). Plot stack order
	# follows list order. Bare CIF names resolve against CIF_LOC too.
	'inputs': None,                  # e.g. ['sample_A.xy', 'sample_B.brml', 'phase.cif']

	# Per-trace colours, aligned with `inputs` above (or with whatever the
	# script discovers if `inputs` is None). Use None in a slot to keep the
	# default cycle colour for that trace.
	'trace_colors': None,            # e.g. ['tab:blue', '#cc0000', None]

	# Per-trace labels, aligned with `inputs`. None = use filename stem.
	'trace_labels': None,            # e.g. ['Sample A', 'Sample B', 'Reference']

	# Stacking order, top-to-bottom, as input indices. The value at display
	# position i is the input index drawn there. e.g. [0, 2, 1, 3] keeps input
	# 0 on top, then draws inputs 2, 1, 3 below it. None = natural input order.
	'order': None,                   # e.g. [0, 2, 1, 3]

	# ---- overlays ----
	# Highlight bands as a Python list of tuples (a, b, multiplier, colour).
	# Mirrors the --highlights syntax. colour may be None for the default red.
	'highlights': None,              # e.g. [(20, 30, 3, 'blue'), (35, 45, 5, None)]

	# Reflection markers, list of (cif_name, n_top, colour). colour may be None
	# to draw from the default reflection palette.
	'reflections': None,             # e.g. [('H2bdc', 10, 'magenta'), ('Other', 5, 'teal')]

	# ---- axes / output ----
	'x_range':   None,               # e.g. (5, 50)
	'title':     None,               # e.g. 'sample-A..D amorphous series'
	'figsize':   None,               # e.g. (10, 6) — overrides --size
	'extension': None,               # e.g. 'png' — overrides --extension
	'silent':    None,               # True / False — overrides --silent
}


info = '''This script automates the plotting of PXRD data files.'''

parser = argparse.ArgumentParser(description=info)
parser.add_argument('-i', '--input', nargs='+', default=DEFAULTS['input'],
                    help='One or more data files to plot. If omitted, all readable files in cwd are collected.')
parser.add_argument('-x', '--extension', default=DEFAULTS['extension'],
                    help='Output image extension (svg, png, pdf, ...).')
parser.add_argument('--dpi', type=int, default=DEFAULTS['dpi'],
                    help='Dots per inch for raster images.')
parser.add_argument('-t', '--title', nargs='?', const=True, type=str, default=DEFAULTS['title'],
                    help='Set a title, or pass -t alone for an auto-generated one.')
parser.add_argument('--size', nargs=2, type=float, default=DEFAULTS['size'],
                    help='Plot size: WIDTH HEIGHT (inches).')
parser.add_argument('-s', '--silent', action='store_true', default=DEFAULTS['silent'],
                    help='Save without opening an interactive plot window.')
parser.add_argument('-v', '--verbose', action='store_true', default=DEFAULTS['verbose'],
                    help='Print extra info while running.')
parser.add_argument('-m', '--highlights', default=DEFAULTS['highlights'], type=str,
                    help='Zoom regions: "((a,b,N,color),(a,b,N))". Scales y by N inside [a,b] and shades the band.')
parser.add_argument('--stack', action='store_true', default=DEFAULTS['stack'],
                    help='Stack multiple PXRDs (default on).')
parser.add_argument('-l', '--limit_extension', nargs='+', default=DEFAULTS['limit_extension'],
                    help='Restrict --stack to these extensions (without dot).')
parser.add_argument('-r', '--reflections', default=None, type=str,
                    help='Overlay reflection markers from CIFs as fine vertical dotted '
                         'lines. Format: "(name,N,color),(name,N,color),...". '
                         f'N (count of strongest reflections) defaults to {SETTINGS["reflection_n_top"]}; color defaults '
                         'to a distinct hue not used by the data traces. Bare CIF names '
                         'resolve against CIF_LOC. Useful for highlighting impurity phases.')
parser.add_argument('--labels', nargs='+', default=None,
                    help='Per-trace labels, in input order. Use _ (a single underscore) '
                         'in a slot to keep that trace\'s filename stem.')
parser.add_argument('--order', default=None, type=str,
                    help='Reorder the stack top-to-bottom by input index. The i-th value '
                         'is the input index drawn at position i. e.g. "0,2,1,3" keeps '
                         'input 0 on top, then draws inputs 2, 1, 3 below it.')
args = parser.parse_args()


def vprint(*a, **kw):
	if args.verbose:
		print(*a, **kw)


# ==========================================
# FILE READERS
# ==========================================

def read_xy(path):
	"""Generic whitespace-separated x,y reader. Lines starting with '#' are skipped.

	Tolerant: rejects ragged or single-column rows with a clear error message so
	the main loop can skip the file instead of crashing on a numpy shape error."""
	with open(path) as inf:
		rows = [line.split() for line in inf.read().strip().split('\n')
		        if line.strip() and not line.startswith('#')]
	if not rows:
		raise ValueError(f'{path}: no data rows.')
	ncols = {len(r) for r in rows}
	if len(ncols) > 1:
		raise ValueError(f'{path}: inconsistent column counts {sorted(ncols)}.')
	if next(iter(ncols)) < 2:
		raise ValueError(f'{path}: need at least 2 columns, got {next(iter(ncols))}.')
	# Only use the first two columns; extras (e.g. error columns) are ignored.
	arr = np.array([r[:2] for r in rows], dtype=float)
	return arr[:, 0], arr[:, 1]


def read_raw(path):
	"""Convert a Bruker .raw file to .xy via TOPAS7 tc.exe, then read it in."""
	TC_PATH = r"C:\TOPAS7\tc.exe"
	TOPAS_INP = 'temptemptemp.inp'
	TOPAS_FS = 'xdd "%s.raw"\n\tOut_X_Yobs("temptemptemp.xy")'

	name = Path(path).stem
	with open(TOPAS_INP, 'w', encoding='utf8') as outf:
		outf.write(TOPAS_FS % name)

	vprint('RUNNING CONVERSION:   %s.raw to temptemptemp.xy' % name)
	os.system('%s %s' % (TC_PATH, TOPAS_INP))

	stem = Path(TOPAS_INP).stem
	x, y = read_xy(stem + '.xy')

	for ext in ('.inp', '.out', '.xy'):
		try:
			os.remove(stem + ext)
		except OSError:
			pass

	return x, y


def read_brml(path):
	"""Extract a 2θ/intensity scan from a Bruker .brml archive.

	Each <Datum> row is `timePerStep,1,2theta,theta,intensity`. We only need
	columns 2 (2θ) and 4 (intensity)."""
	with zipfile.ZipFile(path, 'r') as z:
		# Find the first RawDataN.xml; most .brml files have RawData0.xml.
		raw_name = next((n for n in z.namelist()
		                 if re.match(r'Experiment0/RawData\d+\.xml$', n)), None)
		if raw_name is None:
			raise ValueError(f'No RawDataN.xml found inside {path}')
		with z.open(raw_name) as f:
			xml = f.read().decode('utf-8')

	rows = re.findall(r'<Datum>([^<]+)</Datum>', xml)
	if not rows:
		raise ValueError(f'No <Datum> rows found in {path}')

	data = np.array([r.split(',') for r in rows], dtype=float)
	# columns: timePerStep, _, 2theta, theta, intensity
	return data[:, 2], data[:, 4]


def read_cif(path, two_theta_range=None):
	"""Simulate a PXRD pattern from a CIF: pymatgen reflections convolved with
	Lorentzians of FWHM `args.broadening` (degrees 2θ).

	`two_theta_range`: optional (lo, hi) in degrees. The main loop passes the
	global x-range of all measured traces so the simulated pattern lines up
	with the experimental data. Reflections outside the range are dropped."""
	try:
		from pymatgen.core import Structure
		from pymatgen.analysis.diffraction.xrd import XRDCalculator
	except ImportError as e:
		raise ImportError('CIF plotting needs pymatgen installed.') from e

	if two_theta_range is None:
		two_theta_range = (0.0, 90.0)
	x_lo, x_hi = float(two_theta_range[0]), float(two_theta_range[1])

	structure = Structure.from_file(path)
	calc = XRDCalculator(wavelength=SETTINGS['cif_wavelength'])
	# pymatgen requires a non-zero lower bound; clamp to a tiny positive value.
	pattern = calc.get_pattern(structure, two_theta_range=(max(x_lo, 1e-6), x_hi))

	positions = np.asarray(pattern.x, dtype=float)
	intensities = np.asarray(pattern.y, dtype=float)

	fwhm = float(getattr(args, 'broadening', SETTINGS['broadening']))
	half = fwhm / 2.0
	half_sq = half * half

	# Build the evaluation grid on the exact range; step finely enough that
	# the Lorentzian core (~10 samples across the FWHM) renders smoothly.
	step = max(fwhm / 10.0, 0.001)
	x = np.arange(x_lo, x_hi + step, step)

	if positions.size == 0:
		return x, np.zeros_like(x)

	# Sum of Lorentzians. L_i(x) = I_i * (γ/2)² / ((x − x0_i)² + (γ/2)²)
	# Peak value of one term is I_i (at x = x0_i); summing keeps relative
	# intensities intact and we normalise to [0, 1] at the end.
	y = np.zeros_like(x)
	for pos, I in zip(positions, intensities):
		y += I * half_sq / ((x - pos) ** 2 + half_sq)

	ymax = y.max()
	if ymax > 0:
		y = y / ymax
	return x, y


def read_pdf_xml(path, two_theta_range=None):
	"""Simulate a PXRD pattern from an ICDD PDF card (.xml export).

	A PDF card lists reflection positions + relative intensities only (no atom
	coordinates), so it can't be converted to a CIF — but the stick pattern can
	still be broadened with Lorentzians of FWHM `args.broadening`. Because the
	card only covers the 2θ interval that was actually measured, the pattern is
	genuinely flat outside that interval; the caller draws that flat region with
	a dashed line.

	Returns (x, y, solid_range), where solid_range = (lo, hi) is the 2θ window
	to draw solid: the measured reflection span padded by a few FWHM so the edge
	peaks (and their visible tails) aren't bisected by the solid/dashed border."""
	import xml.etree.ElementTree as ET
	try:
		root = ET.parse(path).getroot()
	except ET.ParseError as e:
		raise ValueError(f'{path}: not parseable XML ({e}).') from e

	# Collect (2θ, intensity) from the stick series. The block element and the
	# intensity-value element are BOTH named "intensity"; navigate by hierarchy
	# (block → child) to disambiguate them.
	series_list = root.findall('.//stick_series')
	if not series_list:
		raise ValueError(f'{path}: no <stick_series> found - not a PDF card export?')

	positions, intensities = [], []
	for series in series_list:
		for block in series.findall('intensity'):
			theta_el = block.find('theta')
			if theta_el is None or not theta_el.text:
				continue
			try:
				tt = float(theta_el.text)
			except ValueError:
				continue
			# The intensity value may carry a letter suffix (e.g. "7m"); the
			# leading number is the relative intensity.
			ival = 1.0
			int_el = block.find('intensity')
			if int_el is not None and int_el.text:
				m = re.match(r'\s*([\d.]+)', int_el.text)
				if m:
					ival = float(m.group(1))
			positions.append(tt)
			intensities.append(ival)
		if positions:
			break  # use the first stick series that yielded reflections

	if not positions:
		raise ValueError(f'{path}: no <theta> reflections found in stick series.')

	positions = np.asarray(positions, dtype=float)
	intensities = np.asarray(intensities, dtype=float)
	meas_lo, meas_hi = float(positions.min()), float(positions.max())

	# Evaluation grid: align to the measured data range if given, else pad the
	# card's own span a little so it isn't cropped exactly at the edge peaks.
	if two_theta_range is None:
		two_theta_range = (max(0.0, meas_lo - 5.0), meas_hi + 5.0)
	x_lo, x_hi = float(two_theta_range[0]), float(two_theta_range[1])

	fwhm = float(getattr(args, 'broadening', SETTINGS['broadening']))
	half_sq = (fwhm / 2.0) ** 2
	step = max(fwhm / 10.0, 0.001)
	x = np.arange(x_lo, x_hi + step, step)

	# Sum of Lorentzians, normalised to [0, 1]. Naturally ~0 (flat) away from the
	# measured reflections, which is exactly the region we want dashed.
	y = np.zeros_like(x)
	for pos, I in zip(positions, intensities):
		y += I * half_sq / ((x - pos) ** 2 + half_sq)
	ymax = y.max()
	if ymax > 0:
		y = y / ymax

	tol = SETTINGS['pdf_xml_solid_tol_fwhm'] * fwhm
	solid_range = (meas_lo - tol, meas_hi + tol)
	return x, y, solid_range


def read_Riet7(path):
	"""Riet7 .dat: header has '<start> <step> <stop> MeasureDateTime ...',
	followed by an integer intensity block."""
	with open(path, encoding='utf-8', errors='replace') as inf:
		filestring = inf.read()

	header_re = re.compile(r'(\d+[.,]\d+)\s+(\d+[.,]\d+)\s+(\d+[.,]\d+)\s+[Mm]easureDateTime')
	m = header_re.search(filestring)
	if m is None:
		raise ValueError(f'Could not find Riet7 header (start/step/stop  MeasureDateTime) in {path}')

	start, step, stop = (float(g.replace(',', '.')) for g in m.groups())

	# Intensities live after the header line. Skip past the newline that
	# terminates the MeasureDateTime line — otherwise the trailing date/time
	# digits (e.g. "21/05/2024 03:45") get picked up as the first intensities
	# and produce a spurious spike at the start of the pattern.
	nl = filestring.find('\n', m.end())
	tail = filestring[nl + 1:] if nl != -1 else filestring[m.end():]
	intensities = np.array(re.findall(r'-?\d+', tail), dtype=float)

	# Expected count from the header. Trim or pad as needed.
	n_expected = int(round((stop - start) / step)) + 1
	if intensities.size < n_expected:
		raise ValueError(f'{path}: expected {n_expected} intensities, found {intensities.size}')
	intensities = intensities[:n_expected]

	x = start + np.arange(n_expected) * step
	return x, intensities


def read_dat(path):
	"""Dispatcher for .dat: try Riet7 first, fall back to generic x,y."""
	try:
		return read_Riet7(path)
	except Exception as e:
		vprint(f'  .dat: Riet7 parse failed ({e}); falling back to read_xy.')
		return read_xy(path)


READERS = {
	'xy':   read_xy,
	'txt':  read_xy,
	'csv':  read_xy,
	'raw':  read_raw,
	'brml': read_brml,
	'cif':  read_cif,
	'dat':  read_dat,
}


def read_any(path):
	ext = Path(path).suffix.lower().lstrip('.')
	if ext not in READERS:
		raise ValueError(f'No reader for extension .{ext}: {path}')
	return READERS[ext](path)


# ==========================================
# COLLECTING INPUTS
# ==========================================

def collect_input_paths():
	"""Build the ordered list of files to plot.

	-i with explicit paths: use them as given. Names matching a static CIF in
	CIF_LOC are pulled in too (cwd takes precedence over the static dir).

	Otherwise glob the cwd for all readable extensions, optionally restricted
	by --limit_extension.
	"""
	if args.input:
		out = []
		for entry in args.input:
			if os.path.exists(entry):
				out.append(entry)
				continue
			# Try resolving against the static CIF dir.
			cif_candidate = os.path.join(CIF_LOC, entry)
			if os.path.exists(cif_candidate):
				out.append(cif_candidate)
				continue
			print(f'[!] Skipping {entry}: not found in cwd or {CIF_LOC}.')
		return out

	# Auto-collect from cwd.
	exts = args.limit_extension or READER_EXTENSIONS
	if isinstance(exts, str):
		exts = [exts]
	files = []
	for ext in exts:
		files.extend(sorted(glob(f'*.{ext}')))
	# Deduplicate keeping order.
	seen = set()
	ordered = []
	for f in files:
		if f not in seen:
			seen.add(f)
			ordered.append(f)
	return ordered


# ==========================================
# NORMALISATION & OFFSETTING
# ==========================================

def normalize_traces(traces):
	"""traces: list of (label, x, y). Returns a new list with y normalised."""
	out = []
	if SETTINGS['normalize'] == 'GLOBAL':
		gmax = max(np.nanmax(y) for _, _, y in traces) or 1.0
		for label, x, y in traces:
			out.append((label, x, y / gmax))
	else:  # INDIVIDUAL
		for label, x, y in traces:
			ymax = np.nanmax(y) or 1.0
			out.append((label, x, y / ymax))
	return out


def offset_traces(traces):
	"""Stack traces with constant spacing. Returns (new_traces, baselines)."""
	yoff = SETTINGS['yoff']
	N = len(traces)
	baselines = []
	out = []
	if SETTINGS['y_offsetting'] == 'TOPDOWN':
		# i=0 sits at top (baseline 0), each next one yoff lower.
		for i, (label, x, y) in enumerate(traces):
			b = -i * yoff
			baselines.append(b)
			out.append((label, x, y + b))
	else:  # CENTER
		# Distribute so the stack is centred around zero.
		center_shift = (N - 1) * yoff / 2.0
		for i, (label, x, y) in enumerate(traces):
			b = center_shift - i * yoff
			baselines.append(b)
			out.append((label, x, y + b))
	return out, baselines


# ==========================================
# HIGHLIGHTS / MULTIPLICATIONS
# ==========================================

def parse_highlights(spec):
	"""Parse e.g. "((10,20,3,r),(5,7,10))" → [(a,b,N,color_or_None), ...]."""
	if not spec:
		return []
	out = []
	# Match inner tuples — content between ( and ) excluding nested parens.
	for inner in re.findall(r'\(([^()]*)\)', spec):
		parts = [p.strip() for p in inner.split(',')]
		if len(parts) < 3:
			print(f'[!] Skipping highlight "{inner}": need at least a,b,N.')
			continue
		try:
			a = float(parts[0])
			b = float(parts[1])
			n = float(parts[2])
		except ValueError:
			print(f'[!] Skipping highlight "{inner}": non-numeric a/b/N.')
			continue
		color = parts[3] if len(parts) > 3 and parts[3] else None
		out.append((a, b, n, color))
	return out


def apply_highlights(ax, traces, baselines, highlights):
	"""Scale y inside [a,b] by N around each trace's baseline, shade the band, label x N."""
	if not highlights:
		return traces

	xmin, xmax = ax.get_xlim() if ax.get_xlim() != (0.0, 1.0) else (None, None)

	new_traces = []
	for (label, x, y), baseline in zip(traces, baselines):
		y_new = y.copy()
		for a, b, n, _ in highlights:
			mask = (x >= a) & (x <= b)
			# Multiply the signal above the baseline by N.
			y_new[mask] = baseline + (y_new[mask] - baseline) * n
		new_traces.append((label, x, y_new))

	# Draw shading + labels once on the axes (not per-trace).
	for a, b, n, color in highlights:
		c = color or SETTINGS['highlight_default_color']
		ax.axvspan(a, b, color=c, alpha=SETTINGS['highlight_alpha'], zorder=0)
		trans = blended_transform_factory(ax.transData, ax.transAxes)
		ax.text((a + b) / 2.0, 1.0, f'x {n:g}', ha='center', va='top',
		        fontsize=SETTINGS['label_font_size'], transform=trans)

	return new_traces


# ==========================================
# STACK ORDERING (--order)
# ==========================================

def parse_order(spec):
	"""Parse "0,2,1,3" (commas and/or whitespace) into [0, 2, 1, 3].

	Returns the list of ints, or None on a parse error."""
	if not spec:
		return None
	try:
		return [int(tok) for tok in re.split(r'[,\s]+', spec.strip()) if tok]
	except ValueError:
		print(f'[!] --order: could not parse "{spec}" as integers; ignoring.')
		return None


def validate_order(order, n):
	"""Ensure `order` is a permutation of range(n).

	Returns the order list, or None if it isn't a valid permutation (in which
	case a warning is printed and the caller should fall back to natural order)."""
	if order is None:
		return None
	if sorted(order) != list(range(n)):
		print(f'[!] order {list(order)} is not a permutation of 0..{n - 1} '
		      f'({n} traces read); keeping natural order.')
		return None
	return list(order)


# ==========================================
# REFLECTION MARKERS (--reflections)
# ==========================================

def parse_reflections(spec):
	"""Parse e.g. "(MyCIF,10,magenta),(Other.cif,5)" → [(name, n_top, color_or_None), ...]."""
	if not spec:
		return []
	out = []
	for inner in re.findall(r'\(([^()]*)\)', spec):
		parts = [p.strip() for p in inner.split(',')]
		# Drop trailing empty parts from "(name,N,)" trailing commas, but keep
		# empties in the middle so positional meaning is preserved.
		while parts and parts[-1] == '':
			parts.pop()
		if not parts:
			continue
		name = parts[0]
		if not name:
			print(f'[!] Skipping reflection spec "({inner})": missing CIF name.')
			continue
		n_top = SETTINGS['reflection_n_top']
		if len(parts) > 1 and parts[1]:
			try:
				n_top = int(parts[1])
				if n_top <= 0:
					raise ValueError
			except ValueError:
				n_top = SETTINGS['reflection_n_top']
				print(f'[!] Reflection spec "({inner})": N must be a positive integer; '
				      f'using default {n_top}.')
		color = parts[2] if len(parts) > 2 and parts[2] else None
		out.append((name, n_top, color))
	return out


def resolve_reflection_cif(name):
	"""Resolve a CIF name to an existing path.

	Tries, in order: the literal string; the literal string + .cif; CIF_LOC/name;
	CIF_LOC/name.cif. Returns the resolved path or None."""
	name_cif = name if name.lower().endswith('.cif') else name + '.cif'
	candidates = [name, name_cif,
	              os.path.join(CIF_LOC, name),
	              os.path.join(CIF_LOC, name_cif)]
	for c in candidates:
		if os.path.exists(c):
			return c
	return None


def simulate_reflections(cif_path, n_top, two_theta_range):
	"""Return the 2θ positions of the n_top strongest reflections from a CIF,
	restricted to the given two_theta range. Sorted ascending in 2θ."""
	try:
		from pymatgen.core import Structure
		from pymatgen.analysis.diffraction.xrd import XRDCalculator
	except ImportError as e:
		raise ImportError('Reflection markers need pymatgen installed.') from e

	x_lo, x_hi = float(two_theta_range[0]), float(two_theta_range[1])
	structure = Structure.from_file(cif_path)
	calc = XRDCalculator(wavelength=SETTINGS['cif_wavelength'])
	pattern = calc.get_pattern(structure,
	                            two_theta_range=(max(x_lo, 1e-6), x_hi))
	positions = np.asarray(pattern.x, dtype=float)
	intensities = np.asarray(pattern.y, dtype=float)
	if positions.size == 0:
		return np.array([])
	# Top N strongest, then sort ascending by 2θ.
	order = np.argsort(-intensities)
	top = positions[order][:n_top]
	return np.sort(top)


def draw_reflection_lines(ax, ref_sets):
	"""Draw fine vertical dotted lines for each reflection set and add a
	stacked label legend just inside the axes top-right corner."""
	if not ref_sets:
		return
	for _, positions, color in ref_sets:
		for p in positions:
			ax.axvline(p,
			           color=color,
			           linestyle=SETTINGS['reflection_linestyle'],
			           linewidth=SETTINGS['reflection_linewidth'],
			           alpha=SETTINGS['reflection_alpha'],
			           zorder=1)
	# Stacked labels just INSIDE the top-right corner so they stay within the
	# plotting box. The first set sits at the top; subsequent sets stack
	# downward. The top-right interior of a stacked PXRD is the topmost trace's
	# high-angle tail, which is normally flat, so labels rarely collide with data.
	pad = SETTINGS['reflection_label_inset']
	step = SETTINGS['reflection_label_step']
	for i, (label, _pos, color) in enumerate(ref_sets):
		y = (1.0 - pad) - i * step
		ax.text(1.0 - pad, y,
		        SETTINGS['reflection_label_marker'] + label,
		        transform=ax.transAxes,
		        color=color,
		        ha='right', va='top',
		        fontsize=SETTINGS['reflection_label_font_size'])


# ==========================================
# STYLING
# ==========================================

def style(ax):
	ax.set_xlabel(r'$2\theta \quad / \quad ^\circ$',
	              fontsize=SETTINGS['xlabel_font_size'],
	              fontweight=SETTINGS['xlabel_font_weight'] or 'normal',
	              labelpad=6)
	ax.set_ylabel(r'$\mathrm{Intensity} \quad / \quad \mathrm{a.u.}$',
	              fontsize=SETTINGS['ylabel_font_size'],
	              fontweight=SETTINGS['ylabel_font_weight'] or 'normal',
	              labelpad=6)

	if SETTINGS['no_intensities']:
		ax.set_yticks([])

	ax.xaxis.set_major_locator(MultipleLocator(SETTINGS['x_step_size']))
	ax.xaxis.set_minor_locator(AutoMinorLocator())
	ax.tick_params(axis='both', which='both',
	               labelsize=SETTINGS['tick_label_font_size'], direction='in')


def derive_label(path):
	return Path(path).stem


# ==========================================
# MAIN
# ==========================================

def _apply_overrides_to_args():
	"""Mutate `args` in place so OVERRIDES win over CLI/defaults.

	Per-trace fields (colors, labels) and the structured overlay lists are not
	on the argparse namespace; main() reads them straight from OVERRIDES."""
	# args.input gets handled by collect_input_paths() reading OVERRIDES.
	if OVERRIDES.get('title') is not None:
		args.title = OVERRIDES['title']
	if OVERRIDES.get('figsize') is not None:
		args.size = OVERRIDES['figsize']
	if OVERRIDES.get('extension') is not None:
		args.extension = OVERRIDES['extension']
	if OVERRIDES.get('silent') is not None:
		args.silent = OVERRIDES['silent']


def main():
	_apply_overrides_to_args()

	# OVERRIDES['inputs'] (if set) replaces both -i and the cwd glob.
	if OVERRIDES.get('inputs'):
		paths = []
		for entry in OVERRIDES['inputs']:
			if os.path.exists(entry):
				paths.append(entry)
				continue
			cif_candidate = os.path.join(CIF_LOC, entry)
			if os.path.exists(cif_candidate):
				paths.append(cif_candidate)
				continue
			print(f'[!] Override input not found: {entry} '
			      f'(also tried {cif_candidate!r})')
	else:
		paths = collect_input_paths()
	if not paths:
		print('[-] No input files found. Pass -i, edit OVERRIDES["inputs"], '
		      'or place data files in the cwd.')
		return 1

	vprint(f'[+] Plotting {len(paths)} file(s):')
	for p in paths:
		vprint(f'    - {p}')

	# Multi-pass read: measured data first to fix the global x-range, then the
	# simulated patterns (CIF, PDF card) within that range so they line up with
	# the experimental data rather than spanning their own default extents.
	def _is_cif(p):
		return Path(p).suffix.lower() == '.cif'

	def _is_pdfxml(p):
		return Path(p).suffix.lower() == '.xml'

	def _validate(x, y):
		"""Raise if the (x, y) returned by a reader isn't usable for plotting."""
		x = np.asarray(x, dtype=float)
		y = np.asarray(y, dtype=float)
		if x.ndim != 1 or y.ndim != 1:
			raise ValueError(f'arrays are not 1-D (got shapes {x.shape}, {y.shape})')
		if x.size == 0 or y.size == 0:
			raise ValueError('empty data')
		if x.size != y.size:
			raise ValueError(f'x and y length mismatch ({x.size} vs {y.size})')
		if not np.any(np.isfinite(y)):
			raise ValueError('no finite y values')
		return x, y

	def _safe_read(path, reader=None, **kwargs):
		"""Call a reader and validate the result. Any failure (read error,
		bad shape, empty data, …) is caught and logged; returns None instead
		of propagating so the rest of the batch can still be plotted."""
		try:
			x, y = (reader or read_any)(path, **kwargs)
			return _validate(x, y)
		except Exception as e:
			print(f'[!] Skipping {path}: {e}')
			return None

	slots = [None] * len(paths)        # holds (label, x, y) or stays None on failure
	slots_solid = [None] * len(paths)  # parallel: (lo, hi) solid range for PDF cards, else None
	for i, p in enumerate(paths):
		if _is_cif(p) or _is_pdfxml(p):
			continue
		res = _safe_read(p)
		if res is None:
			continue
		x, y = res
		slots[i] = (derive_label(p), x, y)

	measured = [s for s in slots if s is not None]
	if measured:
		global_x_lo = min(np.nanmin(x) for _, x, _ in measured)
		global_x_hi = max(np.nanmax(x) for _, x, _ in measured)
	else:
		# Simulation-only input (CIF / PDF card): fall back to a typical lab range.
		global_x_lo, global_x_hi = 5.0, 90.0

	for i, p in enumerate(paths):
		if not _is_cif(p):
			continue
		res = _safe_read(p, reader=read_cif,
		                 two_theta_range=(global_x_lo, global_x_hi))
		if res is None:
			continue
		x, y = res
		slots[i] = (derive_label(p), x, y)

	# PDF cards: simulate within the global range and remember the solid window.
	# read_pdf_xml returns a 3-tuple, so it can't go through _safe_read directly.
	for i, p in enumerate(paths):
		if not _is_pdfxml(p):
			continue
		try:
			x, y, solid_range = read_pdf_xml(
				p, two_theta_range=(global_x_lo, global_x_hi))
			x, y = _validate(x, y)
		except Exception as e:
			print(f'[!] Skipping {p}: {e}')
			continue
		slots[i] = (derive_label(p), x, y)
		slots_solid[i] = solid_range
		vprint(f'    + PDF card {p}: solid 2-theta in '
		       f'[{solid_range[0]:.2f}, {solid_range[1]:.2f}], dashed outside.')

	traces = [s for s in slots if s is not None]
	trace_solid_ranges = [slots_solid[i] for i, s in enumerate(slots) if s is not None]
	if not traces:
		print('[-] Nothing read successfully.')
		return 1

	# The next three steps all operate in INPUT order (i.e. aligned with -i /
	# OVERRIDES['inputs']), so labels and colours stay attached to their source
	# file. Reordering is applied last and permutes everything together — so the
	# user supplies --labels / --colors / --order all in the same input order.

	# --- per-trace labels: OVERRIDES['trace_labels'] wins over --labels. ---
	# A slot value of None or '_' keeps that trace's filename-stem label.
	label_override = OVERRIDES.get('trace_labels') or args.labels
	if label_override:
		traces = [((label_override[i] if i < len(label_override)
		            and label_override[i] not in (None, '_') else lbl), x, y)
		          for i, (lbl, x, y) in enumerate(traces)]

	# --- per-trace colours: OVERRIDES['trace_colors'] wins over default cycle. ---
	# Computed here (input order) so a colour stays with its trace through a
	# reorder. The trace cycle is disjoint from the reflection palette so the
	# two never collide.
	color_cycle = SETTINGS['trace_color_cycle']
	color_override = OVERRIDES.get('trace_colors') or []
	trace_colors = [color_override[i] if i < len(color_override) and color_override[i]
	                else color_cycle[i % len(color_cycle)]
	                for i in range(len(traces))]

	# --- reorder the stack top-to-bottom: OVERRIDES['order'] wins over --order. ---
	# Indices refer to successfully-read traces in input order. The value at
	# position i is the input index drawn at display position i.
	order = OVERRIDES.get('order')
	if order is None and args.order:
		order = parse_order(args.order)
	order = validate_order(order, len(traces))
	if order is not None:
		traces = [traces[i] for i in order]
		trace_colors = [trace_colors[i] for i in order]
		trace_solid_ranges = [trace_solid_ranges[i] for i in order]
		vprint(f'[+] Stack order (top->bottom): {order}')

	traces = normalize_traces(traces)

	# Only stack if more than one trace and --stack is set; for a single trace
	# offsetting is a no-op anyway, so we always run it for uniformity.
	traces, baselines = offset_traces(traces) if (args.stack or len(traces) > 1) \
	                    else (traces, [0.0] * len(traces))

	fig, ax = plt.subplots(figsize=tuple(args.size), layout='constrained')

	# Determine x-range. Precedence: OVERRIDES > SETTINGS > derived from data.
	if OVERRIDES.get('x_range') is not None:
		ax.set_xlim(*OVERRIDES['x_range'])
	elif SETTINGS['x_range']:
		ax.set_xlim(*SETTINGS['x_range'])
	else:
		ax.set_xlim(global_x_lo, global_x_hi)

	# Highlights: prefer OVERRIDES (structured tuple list) over the CLI string.
	if OVERRIDES.get('highlights') is not None:
		highlights = list(OVERRIDES['highlights'])
	else:
		highlights = parse_highlights(args.highlights)
	traces = apply_highlights(ax, traces, baselines, highlights)

	# Plot each trace (colours computed above, aligned through the reorder).
	# A PDF-card trace carries a solid_range: its measured window is drawn solid
	# and the flat extrapolated region dashed. The full dashed line is laid down
	# first; the solid line then overpaints the measured window, so the two join
	# seamlessly with no gap at the boundary.
	dash_style = SETTINGS['pdf_xml_outside_linestyle']
	for (label, x, y), c, solid_range in zip(traces, trace_colors, trace_solid_ranges):
		if solid_range is None:
			ax.plot(x, y, lw=SETTINGS['line_width'], color=c, label=label)
		else:
			s_lo, s_hi = solid_range
			ax.plot(x, y, lw=SETTINGS['line_width'], color=c,
			        ls=dash_style, label='_nolegend_')
			y_solid = np.where((x >= s_lo) & (x <= s_hi), y, np.nan)
			ax.plot(x, y_solid, lw=SETTINGS['line_width'], color=c, label=label)

	# Derive y-limits from the actual plotted data, but also include the
	# stacking baselines. A trace with a non-zero amorphous background has a
	# data minimum well above its mathematical baseline, and the trace label
	# is anchored to that baseline — so excluding baselines from y_range
	# would leave the bottom label outside the axes.
	y_lo = float(ax.dataLim.y0)
	y_hi = float(ax.dataLim.y1)
	if baselines:
		y_lo = min(y_lo, min(baselines))
		y_hi = max(y_hi, max(baselines))
	y_range = y_hi - y_lo if y_hi > y_lo else 1.0
	ax.set_ylim(y_lo - SETTINGS['margin_bottom'] * y_range,
	            y_hi + SETTINGS['margin_top'] * y_range)

	# In-plot trace labels: sit just BELOW each baseline near the right edge,
	# in the empty strip between this trace's zero and the next trace down.
	# Works because PXRD intensities are non-negative.
	trans = blended_transform_factory(ax.transAxes, ax.transData)
	label_y_pad = SETTINGS['label_y_pad_frac'] * y_range
	trace_label_artists = []
	for (label, _x, _y), baseline, c in zip(traces, baselines, trace_colors):
		txt = ax.text(SETTINGS['label_x_frac'], baseline - label_y_pad, label,
		              ha='right', va='top',
		              fontsize=SETTINGS['label_font_size'],
		              color=c,
		              transform=trans)
		trace_label_artists.append(txt)

	# Post-render verification: text height in data units depends on dpi /
	# axes height / fontsize and can't be predicted analytically, so we draw
	# once, query the actual bottom of each label, and expand the lower y-limit
	# if anything still falls below it.
	fig.canvas.draw()
	inv = ax.transData.inverted()
	cur_ymin, cur_ymax = ax.get_ylim()
	min_label_bottom = float('inf')
	for txt in trace_label_artists:
		bbox = txt.get_window_extent()
		_, y_bottom_data = inv.transform((bbox.x0, bbox.y0))
		if y_bottom_data < min_label_bottom:
			min_label_bottom = y_bottom_data
	if trace_label_artists and min_label_bottom < cur_ymin:
		pad = (cur_ymax - cur_ymin) * 0.01
		ax.set_ylim(bottom=min_label_bottom - pad)

	# Reflection markers: simulate the top-N peaks per CIF and overlay them as
	# fine dotted vertical lines, colour-coded per set, with a label legend
	# anchored just above the axes top-right corner. OVERRIDES['reflections']
	# accepts the same tuples as the CLI parser already returns.
	if OVERRIDES.get('reflections') is not None:
		ref_specs = list(OVERRIDES['reflections'])
	else:
		ref_specs = parse_reflections(args.reflections)
	ref_sets = []  # list of (display_label, positions_array, color)
	default_ref_colors = SETTINGS['reflection_color_cycle']
	for i, (name, n_top, color) in enumerate(ref_specs):
		resolved = resolve_reflection_cif(name)
		if resolved is None:
			tried_loc = os.path.join(
				CIF_LOC, name if name.lower().endswith('.cif') else name + '.cif')
			print(f'[!] Reflection CIF not found: {name}  '
			      f'(also tried {tried_loc!r})')
			continue
		try:
			positions = simulate_reflections(
				resolved, n_top, (global_x_lo, global_x_hi))
		except Exception as e:
			print(f'[!] Reflection simulation failed for {name}: {e}')
			continue
		if positions.size == 0:
			print(f'[!] {name}: no reflections in 2-theta range '
			      f'[{global_x_lo:.2f}, {global_x_hi:.2f}].')
			continue
		c = color or default_ref_colors[i % len(default_ref_colors)]
		ref_sets.append((Path(resolved).stem, positions, c))
		vprint(f'    + reflections from {resolved}: '
		       f'{positions.size} lines, color={c}')

	draw_reflection_lines(ax, ref_sets)

	# Title.
	if args.title:
		title_text = args.title if isinstance(args.title, str) else \
		             ' / '.join(t[0] for t in traces)
		ax.set_title(title_text,
		             fontsize=SETTINGS['title_font_size'],
		             fontweight=SETTINGS['title_font_weight'])

	style(ax)

	# Output.
	if args.silent:
		# Build a sensible output name. Single file → its stem; many → "stack".
		stem = traces[0][0] if len(traces) == 1 else 'PXRD_stack'
		out_name = f'{stem}.{args.extension}'
		plt.savefig(out_name,
		            dpi=args.dpi,
		            bbox_inches='tight',
		            transparent=SETTINGS['transparent'])
		vprint(f'[+] Saved -> {out_name}')
		plt.close(fig)
	else:
		plt.show()

	return 0


if __name__ == '__main__':
	sys.exit(main())
