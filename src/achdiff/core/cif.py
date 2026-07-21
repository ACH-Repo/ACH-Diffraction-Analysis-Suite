"""CIF resolution and reflection simulation, shared by the plotter and quickplot.

These four functions existed in both tools and had already started to diverge:
the plotter's `parse_reflections` restored the default on a non-positive N while
quickplot's kept the bad value, so `-r "(a,-3)"` there sliced off the three
*weakest* reflections instead of taking the three strongest. The corrected
behaviour is canonical here, which retires that divergence.

Only the drawing differs between the two tools and stays with them: quickplot
stacks set labels inside the top-right corner, while the plotter routes them
through its existing legend (its corner is already occupied by the legend and
the unit-cell boxes). Everything up to "which 2-theta positions, in what colour"
is common.

Settings arrive as arguments rather than being read from a tool's SETTINGS dict,
so this module stays independent of either caller's configuration shape.
"""

import os
import re

import numpy as np

DEFAULT_N_TOP = 10
DEFAULT_WAVELENGTH = 1.54060  # Cu K-alpha1


def parse_reflections(spec, default_n_top=DEFAULT_N_TOP):
	"""Parse e.g. "(MyCIF,10,magenta),(Other.cif,5)" -> [(name, n_top, color_or_None), ...].

	A non-numeric *or* non-positive N falls back to `default_n_top`. The fallback
	is reassigned inside the except block: `int()` succeeds for "-3", so testing
	the value and raising afterwards would otherwise leave n_top bound to the bad
	number and report "using default -3".
	"""
	if not spec:
		return []
	out = []
	for inner in re.findall(r'\(([^()]*)\)', spec):
		parts = [p.strip() for p in inner.split(',')]
		# Drop trailing empties from "(name,N,)" but keep interior ones so
		# positional meaning survives.
		while parts and parts[-1] == '':
			parts.pop()
		if not parts:
			continue
		name = parts[0]
		if not name:
			print(f'[!] Skipping reflection spec "({inner})": missing CIF name.')
			continue
		n_top = default_n_top
		if len(parts) > 1 and parts[1]:
			try:
				n_top = int(parts[1])
				if n_top <= 0:
					raise ValueError
			except ValueError:
				n_top = default_n_top
				print(f'[!] Reflection spec "({inner})": N must be a positive integer; '
				      f'using default {n_top}.')
		color = parts[2] if len(parts) > 2 and parts[2] else None
		out.append((name, n_top, color))
	return out


def resolve_reflection_cif(name, cif_dir=None):
	"""Resolve a CIF name to an existing path.

	Tries the literal string, the literal + .cif, then the same two inside
	`cif_dir`. Returns the resolved path or None."""
	name_cif = name if name.lower().endswith('.cif') else name + '.cif'
	candidates = [name, name_cif]
	if cif_dir:
		candidates += [os.path.join(cif_dir, name), os.path.join(cif_dir, name_cif)]
	for c in candidates:
		if os.path.exists(c):
			return c
	return None


def simulate_reflections(cif_path, n_top, two_theta_range, wavelength=DEFAULT_WAVELENGTH):
	"""2-theta positions of the `n_top` strongest reflections from a CIF, limited
	to `two_theta_range` and sorted ascending in 2-theta.

	pymatgen is imported here rather than at module scope so the suite's other
	tools keep working without it installed."""
	try:
		from pymatgen.core import Structure
		from pymatgen.analysis.diffraction.xrd import XRDCalculator
	except ImportError as e:
		raise ImportError('Reflection markers need pymatgen installed.') from e

	x_lo, x_hi = float(two_theta_range[0]), float(two_theta_range[1])
	structure = Structure.from_file(cif_path)
	calc = XRDCalculator(wavelength=wavelength)
	pattern = calc.get_pattern(structure, two_theta_range=(max(x_lo, 1e-6), x_hi))
	positions = np.asarray(pattern.x, dtype=float)
	intensities = np.asarray(pattern.y, dtype=float)
	if positions.size == 0:
		return np.array([])
	order = np.argsort(-intensities)
	return np.sort(positions[order][:n_top])


def collect_reflection_sets(spec, two_theta_range, palette, cif_dir=None,
                            wavelength=DEFAULT_WAVELENGTH, default_n_top=DEFAULT_N_TOP,
                            verbose_print=None):
	"""Resolve, simulate and colour every set in `spec`.

	`spec` is either the CLI string ("(name,N,color),...") or an already-parsed
	list of (name, n_top, color) tuples -- quickplot's OVERRIDES supplies the
	latter directly, so accepting both keeps that path working without a
	separate entry point.

	Returns [(label, positions, color), ...]. Sets that cannot be resolved or
	simulated, or that have no reflections in range, are reported and skipped --
	a bad overlay must never take the whole plot down.
	"""
	from pathlib import Path

	specs = parse_reflections(spec, default_n_top) if isinstance(spec, str) else list(spec or [])

	ref_sets = []
	x_lo, x_hi = float(two_theta_range[0]), float(two_theta_range[1])
	for i, (name, n_top, color) in enumerate(specs):
		resolved = resolve_reflection_cif(name, cif_dir)
		if resolved is None:
			tried = os.path.join(cif_dir or '',
			                     name if name.lower().endswith('.cif') else name + '.cif')
			print(f'[!] Reflection CIF not found: {name}  (also tried {tried!r})')
			continue
		try:
			positions = simulate_reflections(resolved, n_top, (x_lo, x_hi), wavelength)
		except Exception as e:
			print(f'[!] Reflection simulation failed for {name}: {e}')
			continue
		if positions.size == 0:
			print(f'[!] {name}: no reflections in 2-theta range '
			      f'[{x_lo:.2f}, {x_hi:.2f}].')
			continue
		c = color or palette[i % len(palette)]
		ref_sets.append((Path(resolved).stem, positions, c))
		if verbose_print:
			verbose_print(f'    + reflections from {resolved}: '
			              f'{positions.size} lines, color={c}')
	return ref_sets
