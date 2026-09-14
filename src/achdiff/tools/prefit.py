"""Interactive cell-parameter tuning for Pawley fit setup.

Loads one or more CIF phases plus an experimental PXRD pattern, and lets you
slide the cell parameters of each phase until the simulated peaks line up with
the observed ones. Useful as a pre-fit step when the CIF was collected at a
different temperature than the powder data (e.g. 77 K vs RT) -- Pawley
refinements often fail to converge without sane starting cell parameters.

Sliders are restricted to the parameters that the detected crystal system
actually allows, so you can't accidentally break the symmetry. A master
"uniform scale" slider mutates a, b, c together for a quick first pass at
isotropic thermal contraction. Clicking a simulated stick labels it with the
Miller indices and 2theta. A "Print TOPAS" button writes a ready-to-paste
macro call to stdout.

Inputs:
  --exp PATH       experimental data: .xy, .txt, .csv, .dat, .raw, .brml
  --cif PATH ...   one or more CIF files (multi-phase supported)
  --wavelength W   X-ray wavelength in Angstrom (default Cu Ka1, 1.54060)

If --exp or --cif is omitted, a file dialog opens for the missing ones.
"""

import os
import re
import sys
import argparse
import zipfile
from glob import glob
from pathlib import Path

import numpy as np

import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.collections import LineCollection

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
	from scipy.signal import find_peaks
except ImportError:
	find_peaks = None

from .. import config, identity
from ..core import bruker
from ..core import cif as cifcore
from ..progname import prog_name


# Hardcoded fallback. Overridden by the CIF_LOC environment variable or the
# --cif-loc CLI flag if either is set.
CIF_LOC_DEFAULT = r'D:\Workfolder\<you>\CIF_LOC'
CIF_LOC = os.environ.get('CIF_LOC', CIF_LOC_DEFAULT)


# Filled by main() once CLI flags are parsed; vprint() reads this.
VERBOSE = False


def vprint(*a, **kw):
	if VERBOSE:
		print(*a, **kw)


# ==========================================
# CONFIG
# ==========================================

SETTINGS = {
	'wavelength': 1.5406,         # Cu Kα default; overridable via CLI
	'broadening': 0.10,           # Lorentzian FWHM (°2θ) for the simulated overlay curve
	'top_n_metric': 10,           # number of strongest sim peaks used in the alignment metric
	'slider_range_frac': 0.10,    # ±10% around initial edge values for the per-axis sliders
	'angle_slider_window': 10.0,  # ±10° around initial angle for monoclinic/triclinic sliders
	'uniform_scale_min': 0.90,
	'uniform_scale_max': 1.10,
	'phase_colors': ['tab:blue', 'tab:orange', 'tab:green', 'tab:red', 'tab:purple', 'tab:brown'],
	'exp_color': 'black',
	'exp_peak_prominence': 0.02,  # fraction of max intensity — for peak detection on the experimental data
	'fig_size': (9.5, 5.5),
}


# Free parameters per crystal system. Symmetry-equivalent ones (b=a in
# tetragonal, all 90° angles in orthorhombic, etc.) are filled in by
# `expand_params` and never get a slider.
SYSTEM_PARAMS = {
	'cubic':        ['a'],
	'tetragonal':   ['a', 'c'],
	'hexagonal':    ['a', 'c'],
	'trigonal':     ['a', 'c'],
	'orthorhombic': ['a', 'b', 'c'],
	'monoclinic':   ['a', 'b', 'c', 'beta'],
	'triclinic':    ['a', 'b', 'c', 'alpha', 'beta', 'gamma'],
}


# System override dropdown: each system can be relaxed to any lower-symmetry
# choice (or the same one). Lets the user opt out of the lock if needed.
_ORDER = ['cubic', 'tetragonal', 'hexagonal', 'trigonal',
          'orthorhombic', 'monoclinic', 'triclinic']
SYSTEM_OVERRIDES = {sys: _ORDER[_ORDER.index(sys):] for sys in _ORDER}


# TOPAS macro signatures, matching the conventions used in run_pawley.py.
TOPAS_MACROS = {
	'cubic':        'Cubic({a})',
	'tetragonal':   'Tetragonal({a}, {c})',
	'hexagonal':    'Hexagonal({a}, {c})',
	'trigonal':     'Trigonal({a}, {c})',
	'orthorhombic': 'Orthorhombic({a}, {b}, {c})',
	'monoclinic':   'Monoclinic({a}, {b}, {c}, {beta})',
	'triclinic':    'Triclinic({a}, {b}, {c}, {alpha}, {beta}, {gamma})',
}

ANGLE_PARAMS = ('alpha', 'beta', 'gamma')


# ==========================================
# READERS  (duplicated from PXRD_Plotter so importing isn't required)
# ==========================================

def read_xy(path):
	with open(path) as inf:
		rows = [line.split() for line in inf.read().strip().split('\n')
		        if line.strip() and not line.startswith('#')]
	if not rows:
		raise ValueError(f'{path}: no data rows.')
	ncols = {len(r) for r in rows}
	if len(ncols) > 1:
		raise ValueError(f'{path}: inconsistent column counts {sorted(ncols)}.')
	if next(iter(ncols)) < 2:
		raise ValueError(f'{path}: need at least 2 columns.')
	arr = np.array([r[:2] for r in rows], dtype=float)
	return arr[:, 0], arr[:, 1]


def read_brml(path):
	with zipfile.ZipFile(path, 'r') as z:
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
	return data[:, 2], data[:, 4]


def read_Riet7(path):
	with open(path, encoding='utf-8', errors='replace') as inf:
		fs = inf.read()
	header_re = re.compile(r'(\d+[.,]\d+)\s+(\d+[.,]\d+)\s+(\d+[.,]\d+)\s+[Mm]easureDateTime')
	m = header_re.search(fs)
	if m is None:
		raise ValueError(f'Could not find Riet7 header in {path}')
	start, step, stop = (float(g.replace(',', '.')) for g in m.groups())
	nl = fs.find('\n', m.end())
	tail = fs[nl + 1:] if nl != -1 else fs[m.end():]
	intensities = np.array(re.findall(r'-?\d+', tail), dtype=float)
	n_expected = int(round((stop - start) / step)) + 1
	if intensities.size < n_expected:
		raise ValueError(f'{path}: expected {n_expected} intensities, found {intensities.size}')
	intensities = intensities[:n_expected]
	x = start + np.arange(n_expected) * step
	return x, intensities


def read_dat(path):
	try:
		return read_Riet7(path)
	except Exception:
		return read_xy(path)


def read_raw(path):
	"""Bruker .raw (RAW1.01 or RAW4.00) read natively -- see ``core.bruker``. No TOPAS
	conversion step, so prefitting works on a machine without TOPAS."""
	return bruker.read_raw(path)


READERS = {
	'xy': read_xy, 'txt': read_xy, 'csv': read_xy,
	'dat': read_dat, 'raw': read_raw, 'brml': read_brml,
}


def read_experimental(path):
	ext = Path(path).suffix.lower().lstrip('.')
	if ext not in READERS:
		raise ValueError(f'No reader for .{ext}: {path}')
	x, y = READERS[ext](path)
	x = np.asarray(x, dtype=float)
	y = np.asarray(y, dtype=float)
	if x.size == 0 or y.size != x.size:
		raise ValueError(f'{path}: empty or mismatched data.')
	return x, y


# ==========================================
# CELL EXPANSION + TOPAS FORMATTING
# ==========================================

def expand_params(system, p, scale=1.0):
	"""Free slider values + system → full (a, b, c, α, β, γ) dict."""
	s = float(scale)
	if system == 'cubic':
		a = p['a'] * s
		return dict(a=a, b=a, c=a, alpha=90.0, beta=90.0, gamma=90.0)
	if system == 'tetragonal':
		a, c = p['a'] * s, p['c'] * s
		return dict(a=a, b=a, c=c, alpha=90.0, beta=90.0, gamma=90.0)
	if system in ('hexagonal', 'trigonal'):
		a, c = p['a'] * s, p['c'] * s
		return dict(a=a, b=a, c=c, alpha=90.0, beta=90.0, gamma=120.0)
	if system == 'orthorhombic':
		return dict(a=p['a']*s, b=p['b']*s, c=p['c']*s,
		            alpha=90.0, beta=90.0, gamma=90.0)
	if system == 'monoclinic':
		return dict(a=p['a']*s, b=p['b']*s, c=p['c']*s,
		            alpha=90.0, beta=p['beta'], gamma=90.0)
	if system == 'triclinic':
		return dict(a=p['a']*s, b=p['b']*s, c=p['c']*s,
		            alpha=p['alpha'], beta=p['beta'], gamma=p['gamma'])
	raise ValueError(f'Unknown system: {system}')


def format_topas(system, full_params):
	fmt = {k: f'{v:.5f}' for k, v in full_params.items()}
	return TOPAS_MACROS[system].format(**fmt)


def detect_system(phase):
	"""The crystal system to start a phase in, clamped to the ones with sliders.

	`symprec=0.1` is deliberately loose, and inherited: it recognises a
	structure whose file understates its symmetry, which is the case worth
	catching here. Anything outside SYSTEM_PARAMS becomes triclinic -- the
	system with every parameter free, so an unexpected answer never silently
	locks one."""
	system = phase.detected_crystal_system(symprec=0.1)
	# `rhombohedral` is a setting rather than a system and has no slider set of
	# its own; its free parameters are trigonal's, which is what it falls back to.
	if system == 'rhombohedral':
		system = 'trigonal'
	return system if system in SYSTEM_PARAMS else 'triclinic'


# ==========================================
# PEAK DETECTION (for the alignment metric)
# ==========================================

def detect_exp_peaks(x, y):
	"""Return the 2θ positions of local maxima above the prominence threshold."""
	y = np.asarray(y, dtype=float)
	if y.size < 3:
		return np.array([])
	ymax = y.max()
	if ymax <= 0:
		return np.array([])
	if find_peaks is not None:
		idx, _ = find_peaks(y, prominence=ymax * SETTINGS['exp_peak_prominence'])
		return x[idx]
	# Fallback: naive local-max sweep.
	mid = y[1:-1]
	thresh = ymax * SETTINGS['exp_peak_prominence']
	mask = (mid > y[:-2]) & (mid > y[2:]) & (mid > thresh)
	return x[1:-1][mask]


# ==========================================
# PHASE
# ==========================================

class Phase:
	"""One CIF + its current cell parameters + the most recent simulated pattern."""

	def __init__(self, cif_path, color, wavelength):
		self.path = str(cif_path)
		self.label = Path(cif_path).stem
		self.color = color
		self.wavelength = float(wavelength)

		phase = cifcore.load_phase(cif_path)
		self.phase = phase

		self.detected_system = detect_system(phase)
		self.system = self.detected_system

		self.original = phase.cell_parameters()
		self.params = {k: self.original[k] for k in SYSTEM_PARAMS[self.system]}
		self.uniform_scale = 1.0

		# Filled by simulate()
		self.peak_positions = np.array([])
		self.peak_intensities = np.array([])
		self.peak_hkls = []
		self.sim_x = np.array([])
		self.sim_y = np.array([])

	def full_params(self):
		return expand_params(self.system, self.params, self.uniform_scale)

	def volume(self):
		return cifcore.cell_volume(**self.full_params())

	def reset(self):
		self.system = self.detected_system
		self.params = {k: self.original[k] for k in SYSTEM_PARAMS[self.system]}
		self.uniform_scale = 1.0

	def change_system(self, new_system):
		"""Switch crystal system; preserve overlapping params, fill the rest from original."""
		self.system = new_system
		new_p = {}
		for k in SYSTEM_PARAMS[new_system]:
			new_p[k] = self.params.get(k, self.original[k])
		self.params = new_p

	def simulate(self, two_theta_range, broadening):
		"""Recompute peak positions, intensities, hkls, and broadened curve."""
		x_lo, x_hi = float(two_theta_range[0]), float(two_theta_range[1])

		try:
			# Only the cell is restated; the contents never move, which is what
			# straining a cell means and why this is cheap enough to run on every
			# drag of a slider.
			strained = self.phase.with_cell(**self.full_params())
			pos, ii, hkls = strained.peaks((max(x_lo, 1e-3), x_hi), self.wavelength)
		except Exception:
			# Pattern not computable (e.g. degenerate lattice) — clear arrays.
			self.peak_positions = np.array([])
			self.peak_intensities = np.array([])
			self.peak_hkls = []
			self.sim_x = np.array([])
			self.sim_y = np.array([])
			return

		if ii.size > 0 and ii.max() > 0:
			ii = ii / ii.max()

		self.peak_positions = pos
		self.peak_intensities = ii
		# One representative index triple per merged reflection: the rest of a
		# multiplicity group sits at the same angle and would only repeat itself
		# in the click annotation.
		self.peak_hkls = list(hkls)

		# Lorentzian-broadened overlay curve.
		step = max(broadening / 10.0, 0.001)
		x = np.arange(x_lo, x_hi + step, step)
		y = np.zeros_like(x)
		half = broadening / 2.0
		half_sq = half * half
		for p_pos, p_i in zip(pos, ii):
			y += p_i * half_sq / ((x - p_pos) ** 2 + half_sq)
		if y.max() > 0:
			y = y / y.max()
		self.sim_x = x
		self.sim_y = y

	def metric(self, exp_peaks_x, n_top):
		"""Mean |Δ2θ| between the N strongest sim peaks and the nearest experimental peak."""
		if self.peak_positions.size == 0 or len(exp_peaks_x) == 0:
			return float('nan')
		order = np.argsort(-self.peak_intensities)
		top = self.peak_positions[order][:n_top]
		exp = np.asarray(exp_peaks_x, dtype=float)
		diffs = np.array([np.min(np.abs(t - exp)) for t in top])
		return float(np.mean(diffs))

	def topas_macro(self):
		return format_topas(self.system, self.full_params())


# ==========================================
# APP
# ==========================================

class PrefitApp:

	def __init__(self, exp_path, cif_paths, wavelength):
		self.exp_path = exp_path
		self.exp_label = Path(exp_path).stem

		x, y = read_experimental(exp_path)
		# Sort by 2θ in case the reader returns out-of-order rows.
		order = np.argsort(x)
		x, y = x[order], y[order]
		self.exp_x = x
		self.exp_y = y / (np.nanmax(y) or 1.0)

		self.exp_peaks_x = detect_exp_peaks(self.exp_x, self.exp_y)

		# Build phases with a colour each.
		colors = SETTINGS['phase_colors']
		self.phases = [Phase(p, colors[i % len(colors)], wavelength)
		               for i, p in enumerate(cif_paths)]

		self.current_phase_idx = 0
		self.last_uniform_scale = 1.0  # for ratio-tracking on the master slider

		# True while widgets are being created so their initial `command` callbacks
		# (ttk.Scale fires one when `variable=` is bound) don't mutate parameters.
		self._building = True

		# Tk setup
		self.root = tk.Tk()
		self.root.title(f'Pawley prefit  —  {self.exp_label}')
		self.root.geometry('1400x720')

		# Matplotlib figure
		self.fig, self.ax = plt.subplots(figsize=SETTINGS['fig_size'])
		self.ax.plot(self.exp_x, self.exp_y, lw=0.7, color=SETTINGS['exp_color'],
		             label=self.exp_label, zorder=1)
		self.ax.set_xlabel(r'$2\theta$  /  °')
		self.ax.set_ylabel('Normalized intensity')
		self.ax.set_xlim(self.exp_x.min(), self.exp_x.max())
		self.ax.set_ylim(-0.05, 1.10)
		self.ax.tick_params(direction='in')
		self.fig.tight_layout()

		# Persistent annotation for click-to-hkl.
		self.annotation = self.ax.annotate(
			'', xy=(0, 0), xytext=(15, 15),
			textcoords='offset points',
			bbox=dict(boxstyle='round,pad=0.3', fc='lightyellow',
			          ec='gray', alpha=0.95),
			arrowprops=dict(arrowstyle='->', color='gray'),
			fontsize=9, visible=False, zorder=10,
		)

		# Display toggles
		self.show_sticks = tk.BooleanVar(value=True)
		self.show_curve = tk.BooleanVar(value=True)
		self.show_exp_peaks = tk.BooleanVar(value=False)
		self.exp_peak_markers = None

		# Per-phase artist storage: phase.label → {'sticks': LC, 'curve': Line}
		self.phase_artists = {}

		self._build_ui()
		self._refresh_panel()
		self._recompute_all()
		self._redraw()
		# All initial Tk callback storms have fired; real user input from now on.
		self._building = False

		self.fig.canvas.mpl_connect('pick_event', self._on_pick)
		self.fig.canvas.mpl_connect('button_press_event', self._on_canvas_click)

		self.root.protocol('WM_DELETE_WINDOW', self._on_quit)

	# ---- UI construction ----

	def _build_ui(self):
		self.root.grid_columnconfigure(0, weight=1)
		self.root.grid_rowconfigure(0, weight=1)

		# Canvas + toolbar
		left = ttk.Frame(self.root)
		left.grid(row=0, column=0, sticky='nsew')
		self.canvas = FigureCanvasTkAgg(self.fig, master=left)
		self.canvas.get_tk_widget().pack(side='top', fill='both', expand=True)
		toolbar = NavigationToolbar2Tk(self.canvas, left)
		toolbar.update()

		# Control panel
		panel = ttk.Frame(self.root, padding=10)
		panel.grid(row=0, column=1, sticky='ns')
		self.panel = panel

		row = 0
		ttk.Label(panel, text='Phase:').grid(row=row, column=0, sticky='w')
		self.phase_var = tk.StringVar(value=self.phases[0].label)
		self.phase_combo = ttk.Combobox(
			panel, textvariable=self.phase_var,
			values=[p.label for p in self.phases], state='readonly', width=24)
		self.phase_combo.grid(row=row, column=1, sticky='ew', pady=2)
		self.phase_combo.bind('<<ComboboxSelected>>', lambda e: self._on_phase_change())
		row += 1

		ttk.Label(panel, text='Crystal system:').grid(row=row, column=0, sticky='w')
		self.system_var = tk.StringVar()
		self.system_combo = ttk.Combobox(panel, textvariable=self.system_var,
		                                  state='readonly', width=24)
		self.system_combo.grid(row=row, column=1, sticky='ew', pady=2)
		self.system_combo.bind('<<ComboboxSelected>>', lambda e: self._on_system_change())
		row += 1

		ttk.Separator(panel, orient='horizontal').grid(row=row, column=0, columnspan=2,
		                                                sticky='ew', pady=6)
		row += 1

		# Uniform scale slider (master)
		ttk.Label(panel, text='Uniform scale (a, b, c):').grid(row=row, column=0,
		                                                       columnspan=2, sticky='w')
		row += 1
		self.scale_var = tk.DoubleVar(value=1.0)
		self.scale_label_var = tk.StringVar(value='1.0000')
		scale_row = ttk.Frame(panel)
		scale_row.grid(row=row, column=0, columnspan=2, sticky='ew')
		self.scale_slider = ttk.Scale(
			scale_row,
			from_=SETTINGS['uniform_scale_min'], to=SETTINGS['uniform_scale_max'],
			variable=self.scale_var, orient='horizontal',
			command=lambda v: self._on_scale_change())
		self.scale_slider.pack(side='left', fill='x', expand=True)
		ttk.Label(scale_row, textvariable=self.scale_label_var, width=8).pack(side='left')
		row += 1
		ttk.Button(panel, text='Apply scale & reset to 1.00',
		           command=self._apply_and_reset_scale).grid(row=row, column=0,
		                                                      columnspan=2, sticky='ew', pady=2)
		row += 1

		ttk.Separator(panel, orient='horizontal').grid(row=row, column=0, columnspan=2,
		                                                sticky='ew', pady=6)
		row += 1

		ttk.Label(panel, text='Free parameters:').grid(row=row, column=0,
		                                                columnspan=2, sticky='w')
		row += 1
		self.slider_frame = ttk.Frame(panel)
		self.slider_frame.grid(row=row, column=0, columnspan=2, sticky='ew')
		row += 1

		ttk.Separator(panel, orient='horizontal').grid(row=row, column=0, columnspan=2,
		                                                sticky='ew', pady=6)
		row += 1

		# Display toggles
		ttk.Checkbutton(panel, text='Sticks', variable=self.show_sticks,
		                 command=self._redraw).grid(row=row, column=0, sticky='w')
		ttk.Checkbutton(panel, text='Lorentzian overlay', variable=self.show_curve,
		                 command=self._redraw).grid(row=row, column=1, sticky='w')
		row += 1
		ttk.Checkbutton(panel, text='Mark detected exp. peaks',
		                 variable=self.show_exp_peaks,
		                 command=self._redraw).grid(row=row, column=0, columnspan=2, sticky='w')
		row += 1

		ttk.Separator(panel, orient='horizontal').grid(row=row, column=0, columnspan=2,
		                                                sticky='ew', pady=6)
		row += 1

		# Status display (volume + metric per phase)
		self.status_var = tk.StringVar(value='')
		status = ttk.Label(panel, textvariable=self.status_var, justify='left',
		                   font=('TkFixedFont', 9))
		status.grid(row=row, column=0, columnspan=2, sticky='w')
		row += 1

		# Buttons
		btn_frame = ttk.Frame(panel)
		btn_frame.grid(row=row, column=0, columnspan=2, sticky='ew', pady=8)
		ttk.Button(btn_frame, text='Reset phase',
		           command=self._on_reset).pack(side='left', padx=2)
		ttk.Button(btn_frame, text='Print TOPAS',
		           command=self._on_print_topas).pack(side='left', padx=2)
		ttk.Button(btn_frame, text='Quit',
		           command=self._on_quit).pack(side='right', padx=2)

		# Initial column weights so sliders/entries stretch.
		panel.grid_columnconfigure(1, weight=1)

	# ---- Sliders for the current phase ----

	def _refresh_panel(self):
		# Guard against the cascade of `command` callbacks fired by ttk widgets
		# as they're (re)built — those are not real user input.
		was_building = self._building
		self._building = True

		phase = self._current_phase()

		# System dropdown
		options = SYSTEM_OVERRIDES.get(phase.detected_system, ['triclinic'])
		self.system_combo['values'] = options
		self.system_var.set(phase.system)

		# Uniform scale display reset (per-phase tracking)
		self.last_uniform_scale = phase.uniform_scale
		self.scale_var.set(phase.uniform_scale)
		self.scale_label_var.set(f'{phase.uniform_scale:.4f}')

		# Rebuild sliders
		for w in self.slider_frame.winfo_children():
			w.destroy()
		self.sliders = {}

		for name in SYSTEM_PARAMS[phase.system]:
			v0 = phase.params[name]
			is_angle = name in ANGLE_PARAMS
			if is_angle:
				win = SETTINGS['angle_slider_window']
				vmin = max(30.0, v0 - win)
				vmax = min(150.0, v0 + win)
				fmt = '{:.3f}'
			else:
				frac = SETTINGS['slider_range_frac']
				vmin, vmax = v0 * (1 - frac), v0 * (1 + frac)
				fmt = '{:.4f}'

			row = ttk.Frame(self.slider_frame)
			row.pack(fill='x', pady=2)
			ttk.Label(row, text=name, width=6).pack(side='left')

			var = tk.DoubleVar(value=v0)
			scale = ttk.Scale(row, from_=vmin, to=vmax, variable=var,
			                  orient='horizontal',
			                  command=lambda val, n=name: self._on_param_change(n, float(val)))
			scale.pack(side='left', fill='x', expand=True, padx=4)

			entry_var = tk.StringVar(value=fmt.format(v0))
			entry = ttk.Entry(row, textvariable=entry_var, width=10)
			entry.pack(side='left')
			entry.bind('<Return>', lambda e, n=name, ev=entry_var:
			           self._on_entry_change(n, ev.get()))
			entry.bind('<FocusOut>', lambda e, n=name, ev=entry_var:
			           self._on_entry_change(n, ev.get()))

			self.sliders[name] = dict(scale=scale, var=var,
			                          entry_var=entry_var, fmt=fmt,
			                          vmin=vmin, vmax=vmax)

		# Restore building state — keep True if we were already in construction.
		self._building = was_building

	# ---- Callbacks ----

	def _current_phase(self):
		return self.phases[self.current_phase_idx]

	def _on_phase_change(self):
		if self._building:
			return
		label = self.phase_var.get()
		for i, p in enumerate(self.phases):
			if p.label == label:
				self.current_phase_idx = i
				break
		self._refresh_panel()

	def _on_system_change(self):
		if self._building:
			return
		new_sys = self.system_var.get()
		phase = self._current_phase()
		if new_sys != phase.system:
			phase.change_system(new_sys)
			self._refresh_panel()
			self._recompute_phase(phase)
			self._redraw()

	def _on_param_change(self, name, val):
		if self._building:
			return
		phase = self._current_phase()
		phase.params[name] = val
		fmt = self.sliders[name]['fmt']
		self.sliders[name]['entry_var'].set(fmt.format(val))
		self._recompute_phase(phase)
		self._redraw()

	def _on_entry_change(self, name, text):
		if self._building:
			return
		try:
			val = float(text)
		except ValueError:
			# Restore previous valid value in the entry.
			phase = self._current_phase()
			self.sliders[name]['entry_var'].set(
				self.sliders[name]['fmt'].format(phase.params[name]))
			return
		phase = self._current_phase()
		phase.params[name] = val
		# Slider clamps if outside range — that's fine.
		self.sliders[name]['var'].set(val)
		self._recompute_phase(phase)
		self._redraw()

	def _on_scale_change(self):
		"""Master scale moved: multiply current edge sliders by the relative change."""
		if self._building:
			return
		new = float(self.scale_var.get())
		if self.last_uniform_scale == 0:
			self.last_uniform_scale = 1.0
		ratio = new / self.last_uniform_scale
		self.last_uniform_scale = new
		self.scale_label_var.set(f'{new:.4f}')

		phase = self._current_phase()
		phase.uniform_scale = 1.0  # baked directly into params now
		for name in ('a', 'b', 'c'):
			if name in phase.params:
				phase.params[name] *= ratio
				if name in self.sliders:
					self.sliders[name]['var'].set(phase.params[name])
					self.sliders[name]['entry_var'].set(
						self.sliders[name]['fmt'].format(phase.params[name]))
		self._recompute_phase(phase)
		self._redraw()

	def _apply_and_reset_scale(self):
		"""Snap the master slider back to 1.00 after a drag; values stay applied."""
		self.last_uniform_scale = 1.0
		self.scale_var.set(1.0)
		self.scale_label_var.set('1.0000')

	def _on_reset(self):
		phase = self._current_phase()
		phase.reset()
		self.last_uniform_scale = 1.0
		self._refresh_panel()
		self._recompute_phase(phase)
		self._redraw()

	def _on_print_topas(self):
		phase = self._current_phase()
		full = phase.full_params()
		V = phase.volume()
		print()
		print('=' * 68)
		print(f'Phase:   {phase.label}')
		print(f'System:  {phase.system}'
		      + ('' if phase.system == phase.detected_system
		         else f'  (detected: {phase.detected_system})'))
		V0 = cifcore.cell_volume(**self.fill_original(phase))
		print(f'Volume:  {V:.4f} A^3  (delta {V - V0:+.3f} A^3)')
		print(f'a={full["a"]:.5f}  b={full["b"]:.5f}  c={full["c"]:.5f}')
		print(f'alpha={full["alpha"]:.4f}  beta={full["beta"]:.4f}  gamma={full["gamma"]:.4f}')
		print('TOPAS:')
		print('   ', phase.topas_macro())
		print('=' * 68)

	def fill_original(self, phase):
		"""Full (a, b, c, α, β, γ) of the original CIF lattice for diff display."""
		return phase.original

	def _on_quit(self):
		try:
			self.root.quit()
		finally:
			self.root.destroy()

	# ---- Plot click handling ----

	def _on_pick(self, event):
		for phase in self.phases:
			arts = self.phase_artists.get(phase.label, {})
			if event.artist is arts.get('sticks'):
				if not hasattr(event, 'ind') or len(event.ind) == 0:
					return
				ind = int(event.ind[0])
				if ind >= len(phase.peak_positions):
					return
				pos = float(phase.peak_positions[ind])
				inten = float(phase.peak_intensities[ind])
				h, k, l = phase.peak_hkls[ind]
				self.annotation.xy = (pos, inten)
				self.annotation.set_text(
					f'{phase.label}\n({h} {k} {l})\n2θ = {pos:.3f}°')
				self.annotation.get_bbox_patch().set_facecolor('lightyellow')
				self.annotation.set_visible(True)
				self.canvas.draw_idle()
				return

	def _on_canvas_click(self, event):
		"""Clicking outside any stick hides the annotation."""
		if event.inaxes is not self.ax:
			return
		# If a stick was hit, the pick handler will fire first and re-show it.
		# We just defer the hide a tiny bit by using draw_idle after the pick.
		# Simpler: hide here unconditionally; pick handler then re-shows.
		if event.button == 1 and self.annotation.get_visible():
			# Heuristic: only hide if the click is far from the current annotation point.
			ax_x = event.xdata
			if ax_x is None:
				return
			cur_x = self.annotation.xy[0]
			x_lo, x_hi = self.ax.get_xlim()
			if abs(ax_x - cur_x) > 0.5 * (x_hi - x_lo) / 50:
				# Will be re-shown by pick handler if a stick was actually hit.
				self.annotation.set_visible(False)
				self.canvas.draw_idle()

	# ---- Pattern simulation + redraw ----

	def _exp_range(self):
		return float(np.nanmin(self.exp_x)), float(np.nanmax(self.exp_x))

	def _recompute_all(self):
		rng = self._exp_range()
		for p in self.phases:
			p.simulate(rng, SETTINGS['broadening'])

	def _recompute_phase(self, phase):
		phase.simulate(self._exp_range(), SETTINGS['broadening'])

	def _redraw(self):
		# Drop previous per-phase artists.
		for label, arts in self.phase_artists.items():
			for a in arts.values():
				try:
					a.remove()
				except Exception:
					pass
		self.phase_artists = {}

		# Drop previous exp-peak markers.
		if self.exp_peak_markers is not None:
			try:
				self.exp_peak_markers.remove()
			except Exception:
				pass
			self.exp_peak_markers = None

		# Redraw each phase's artists.
		for p in self.phases:
			arts = {}
			if self.show_sticks.get() and p.peak_positions.size > 0:
				segs = [[(t, 0), (t, max(i, 0.005))]
				        for t, i in zip(p.peak_positions, p.peak_intensities)]
				lc = LineCollection(segs, colors=p.color, linewidths=1.4,
				                    alpha=0.85, picker=True, pickradius=5,
				                    zorder=4)
				self.ax.add_collection(lc)
				arts['sticks'] = lc
			if self.show_curve.get() and p.sim_x.size > 0:
				line, = self.ax.plot(p.sim_x, p.sim_y, lw=0.7, color=p.color,
				                     alpha=0.55, zorder=2)
				arts['curve'] = line
			self.phase_artists[p.label] = arts

		# Exp peak markers (small triangles along the baseline).
		if self.show_exp_peaks.get() and len(self.exp_peaks_x) > 0:
			self.exp_peak_markers = self.ax.scatter(
				self.exp_peaks_x, np.full_like(self.exp_peaks_x, -0.025),
				marker='^', s=30, color='gray', zorder=3)

		# Status panel: V, ΔV, metric per phase.
		lines = []
		for p in self.phases:
			full = p.full_params()
			V = p.volume()
			V0 = cifcore.cell_volume(**p.original)
			dV_pct = 100.0 * (V - V0) / V0 if V0 > 0 else 0.0
			m = p.metric(self.exp_peaks_x, SETTINGS['top_n_metric'])
			marker = '►' if p is self._current_phase() else ' '
			lines.append(
				f'{marker} {p.label}\n'
				f'   sys: {p.system}\n'
				f'   V  : {V:9.3f} Å³  (Δ {dV_pct:+5.2f}%)\n'
				f'   |Δ2θ|: {m:6.4f}°  (top {SETTINGS["top_n_metric"]})'
			)
		self.status_var.set('\n'.join(lines))

		# Hide stale annotation when redrawing.
		self.annotation.set_visible(False)

		self.canvas.draw_idle()

	def run(self):
		self.root.mainloop()


# ==========================================
# INPUT GATHERING
# ==========================================

def _ask_open(title, filetypes, initialdir=None):
	# Hidden root for the dialog only.
	dialog_root = tk.Tk()
	dialog_root.withdraw()
	kw = dict(title=title, filetypes=filetypes)
	if initialdir and os.path.isdir(initialdir):
		kw['initialdir'] = initialdir
	path = filedialog.askopenfilename(**kw)
	dialog_root.destroy()
	return path or None


def _ask_open_many(title, filetypes, initialdir=None):
	dialog_root = tk.Tk()
	dialog_root.withdraw()
	kw = dict(title=title, filetypes=filetypes)
	if initialdir and os.path.isdir(initialdir):
		kw['initialdir'] = initialdir
	paths = filedialog.askopenfilenames(**kw)
	dialog_root.destroy()
	return list(paths) if paths else []


def resolve_cif(arg):
	"""Resolve a CIF argument, trying (in order):
	  1. the path as given (relative to cwd or absolute);
	  2. <CIF_LOC>/<arg>   (or <arg>.cif if no extension);
	  3. <CIF_LOC>/<arg>.cif   when arg already ends in .cif this is a no-op.

	Returns the resolved path, or None. Also returns the list of paths
	attempted so the caller can report them on failure.
	"""
	tried = []

	# 1) literal path
	tried.append(os.path.abspath(arg))
	if os.path.exists(arg):
		vprint(f'  [v] CIF "{arg}" -> found as literal path: {tried[-1]}')
		return arg, tried

	# 2) inside CIF_LOC, with or without .cif suffix
	name = arg if arg.lower().endswith('.cif') else arg + '.cif'
	cand = os.path.join(CIF_LOC, name)
	tried.append(cand)
	if os.path.exists(cand):
		vprint(f'  [v] CIF "{arg}" -> found in CIF_LOC: {cand}')
		return cand, tried

	# 3) case-insensitive scan of CIF_LOC (Windows is case-insensitive but a
	# remote SMB share or differently-cased symlink can trip case-sensitive code)
	if os.path.isdir(CIF_LOC):
		target = name.lower()
		for entry in os.listdir(CIF_LOC):
			if entry.lower() == target:
				cand = os.path.join(CIF_LOC, entry)
				tried.append(cand)
				vprint(f'  [v] CIF "{arg}" -> found case-insensitively: {cand}')
				return cand, tried

	return None, tried


def report_cif_failure(arg, tried):
	"""Print a clear breakdown of what was attempted when a CIF can't be found."""
	print(f'[!] Could not resolve CIF "{arg}". Tried:')
	for t in tried:
		print(f'      - {t}    ({"exists" if os.path.exists(t) else "missing"})')
	loc_status = 'exists' if os.path.isdir(CIF_LOC) else 'MISSING'
	print(f'    CIF_LOC = {CIF_LOC!r}  ({loc_status})')
	if not os.path.isdir(CIF_LOC):
		print('    -> override with the CIF_LOC environment variable or --cif-loc PATH.')
	else:
		# Show a couple of similarly-named files to help spot typos.
		try:
			candidates = sorted(
				e for e in os.listdir(CIF_LOC)
				if e.lower().endswith('.cif') and arg.lower()[:3] in e.lower())[:8]
			if candidates:
				print('    Similar names in CIF_LOC:')
				for c in candidates:
					print(f'      - {c}')
		except OSError as e:
			print(f'    (could not list CIF_LOC: {e})')


# ==========================================
# MAIN
# ==========================================

def main():
	# Windows consoles default to cp1252; reconfigure to UTF-8 so the unicode
	# in --help text and the TOPAS printout doesn't crash.
	for stream in (sys.stdout, sys.stderr):
		try:
			stream.reconfigure(encoding='utf-8')  # Python 3.7+
		except Exception:
			pass

	ap = argparse.ArgumentParser(prog=prog_name('pf'), description=__doc__,
	                              formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument('-e', '--exp', help='Path to the experimental data file.')
	ap.add_argument('-c', '--cif', nargs='+',
	                 help='One or more CIF paths (or bare names resolvable in CIF_LOC).')
	ap.add_argument('--cif-loc', dest='cif_loc',
	                 help='Override the static CIF library location '
	                      '(also overridable via the CIF_LOC env var).')
	ap.add_argument('--wavelength', type=float, default=SETTINGS['wavelength'],
	                 help='X-ray wavelength in Å (default: Cu Kα = 1.5406).')
	ap.add_argument('-v', '--verbose', action='store_true',
	                 help='Print resolution diagnostics for inputs.')
	identity.add_user_argument(ap)
	args = ap.parse_args()

	global VERBOSE, CIF_LOC
	VERBOSE = bool(args.verbose)
	# --cif-loc still wins, but the fallback chain is now the shared one
	# (env var > saved profile > [defaults]) instead of env-var-or-hardcoded.
	user, source = identity.resolve(args.user)
	if args.user or user:
		print(identity.describe(user, source))
	CIF_LOC = config.get('cif_loc', cli_value=args.cif_loc, user=user)

	if args.save_profile:
		if not args.user:
			print('[!] --save-profile needs -u ID to say which profile to write.')
		else:
			path = config.save_profile(args.user, {'cif_loc': CIF_LOC})
			print(f'[+] Saved profile {args.user} to {path}')
	vprint(f'[v] cwd        = {os.getcwd()}')
	vprint(f'[v] CIF_LOC    = {CIF_LOC!r}  '
	       f'({"exists" if os.path.isdir(CIF_LOC) else "MISSING"})')

	# Resolve experimental data.
	# If --exp was given we either use it or bail — no fallback dialog, because
	# the user already told us what they wanted.
	exp_path = args.exp
	if exp_path is not None:
		if not os.path.exists(exp_path):
			print(f'[!] --exp path not found: {os.path.abspath(exp_path)}')
			print('    (no fallback dialog because --exp was specified explicitly.)')
			return 1
		vprint(f'[v] exp data   = {os.path.abspath(exp_path)}')
	else:
		exp_path = _ask_open(
			'Select experimental PXRD data',
			[('PXRD data', '*.xy *.txt *.csv *.dat *.raw *.brml'),
			 ('All files', '*.*')])
		if not exp_path or not os.path.exists(exp_path):
			print('[-] No experimental data selected. Exiting.')
			return 1

	# Resolve CIFs. Same rule: if --cif was given, the dialog must NOT open.
	# Either everything resolves or we error out clearly.
	cif_paths = []
	if args.cif is not None:
		failed_any = False
		for entry in args.cif:
			resolved, tried = resolve_cif(entry)
			if resolved is None:
				report_cif_failure(entry, tried)
				failed_any = True
			else:
				cif_paths.append(resolved)
		if failed_any or not cif_paths:
			print('[-] One or more --cif arguments could not be resolved. Exiting.')
			print('    (no fallback dialog because --cif was specified explicitly.)')
			return 1
	else:
		cif_paths = _ask_open_many(
			'Select one or more CIF files',
			[('CIF files', '*.cif'), ('All files', '*.*')],
			initialdir=CIF_LOC,
		)
		if not cif_paths:
			print('[-] No CIF files selected. Exiting.')
			return 1
	vprint('[v] CIFs used:')
	for p in cif_paths:
		vprint(f'      {p}')

	SETTINGS['wavelength'] = args.wavelength

	app = PrefitApp(exp_path, cif_paths, args.wavelength)
	app.run()
	return 0


if __name__ == '__main__':
	sys.exit(main())
