"""CIF resolution, cell contents and powder simulation, shared by every tool.

The reflection-overlay helpers (`parse_reflections`, `resolve_reflection_cif`,
`simulate_reflections`, `collect_reflection_sets`) existed in both the plotter
and quickplot and had already started to diverge: the plotter's
`parse_reflections` restored the default on a non-positive N while quickplot's
kept the bad value, so `-r "(a,-3)"` there sliced off the three *weakest*
reflections instead of taking the three strongest. The corrected behaviour is
canonical here, which retires that divergence.

Only the drawing differs between the two tools and stays with them: quickplot
stacks set labels inside the top-right corner, while the plotter routes them
through its existing legend (its corner is already occupied by the legend and
the unit-cell boxes). Everything up to "which 2-theta positions, in what colour"
is common.

Settings arrive as arguments rather than being read from a tool's SETTINGS dict,
so this module stays independent of either caller's configuration shape.

Where the crystallography comes from
------------------------------------
`CifPhase` wraps the vendored MoloM core (``core/_molom/``), which replaced
pymatgen across the suite. The reason was not performance or dependency weight,
though both improved: pymatgen's CifParser *refuses* files this lab actually
produces. A site occupancy above its tolerance discards the whole data block,
and several refinement programs write that column as atoms-per-site rather than
a fraction -- so a perfectly good file would raise "Invalid CIF file with no
structures!" and the phase would silently vanish from the plot. MoloM computes
what the file says.

The arithmetic was cross-checked against pymatgen before the switch and agrees
to five decimal places on reflection position, with identical reflection counts;
the test suite keeps a reduced version of that check.

What MoloM adds beyond parity: the K-alpha doublet (an unmonochromated lab
pattern really is two lines, which is why peaks past ~40 degrees look split),
and a `note` on the pattern when the file carried no displacement parameters --
a B = 0 pattern has visibly wrong high-angle intensities, and saying so is
better than letting a plausible curve stand unqualified.
"""

import os
import re

import numpy as np

from ._molom import cif as _cif
from ._molom import pxrd as _pxrd
from ._molom import spacegroups as _spacegroups

DEFAULT_N_TOP = 10
DEFAULT_WAVELENGTH = 1.54060  # Cu K-alpha1
#: Lorentzian FWHM, degrees 2theta, a simulated pattern is drawn with.
DEFAULT_FWHM = 0.1

#: Parameter names in the order every tool spells a cell.
CELL_KEYS = ('a', 'b', 'c', 'alpha', 'beta', 'gamma')


class CifError(ValueError):
	"""A CIF that could not be turned into something to diffract from."""


def cell_volume(a, b, c, alpha=90.0, beta=90.0, gamma=90.0):
	"""Cell volume in cubic Angstrom, or NaN for a geometrically impossible cell.

	NaN rather than an exception because the callers are live readouts: prefit's
	sliders can pass through an impossible combination on the way to a sensible
	one, and a volume of NaN prints as `nan` while an exception would tear down
	the panel mid-drag.
	"""
	try:
		return float(_cif.Cell(a, b, c, alpha, beta, gamma).volume())
	except Exception:
		return float('nan')


class CifPhase(object):
	"""One crystal from a CIF: its cell, its whole cell contents, its name.

	`frac` is the FULL contents of the unit cell -- the asymmetric unit already
	expanded by the symmetry operators -- because that is what a structure
	factor sums over. Keeping the expansion here rather than at simulation time
	is what lets prefit swap the cell a hundred times a second: the contents do
	not change when the cell is stretched, only the geometry does.
	"""

	def __init__(self, cell, symbols, frac, occupancy, naming=None, path='',
	             notes=()):
		self.cell = cell
		self.symbols = list(symbols)
		self.frac = np.asarray(frac, dtype=float).reshape(-1, 3)
		self.occupancy = np.asarray(occupancy, dtype=float)
		self.naming = naming
		self.path = str(path)
		#: Anything the reader wants said out loud, already deduplicated.
		self.notes = list(notes)

	# ---------------------------------------------------------------- the cell

	def cell_parameters(self):
		"""The cell as a plain dict, in the spelling every tool here uses."""
		return {k: float(getattr(self.cell, k)) for k in CELL_KEYS}

	@property
	def volume(self):
		return float(self.cell.volume())

	def with_cell(self, **params):
		"""The same contents in a different cell.

		Only the lattice changes, never the fractional coordinates: that is the
		definition of straining a cell, and it is what prefit's sliders do. A
		degenerate cell raises rather than returning something unusable.
		"""
		values = self.cell_parameters()
		values.update({k: float(v) for k, v in params.items() if k in CELL_KEYS})
		cell = _cif.Cell(**values)
		cell.matrix()   # raises CifError on impossible angles, before anyone plots it
		return CifPhase(cell, self.symbols, self.frac, self.occupancy,
		                naming=self.naming, path=self.path, notes=self.notes)

	# ------------------------------------------------------------- the pattern

	def pattern(self, two_theta_range, wavelength=DEFAULT_WAVELENGTH):
		"""The simulated pattern over `two_theta_range`.

		Returns MoloM's Pattern: `.reflections` carry hkl, multiplicity, angle
		and intensity, and `.note` carries anything qualifying the numbers.
		"""
		x_lo, x_hi = float(two_theta_range[0]), float(two_theta_range[1])
		return _pxrd.compute(self.cell, self.symbols, self.frac,
		                     occupancy=self.occupancy,
		                     wavelength=float(wavelength),
		                     two_theta_range=(max(x_lo, 1e-3), x_hi))

	def peaks(self, two_theta_range, wavelength=DEFAULT_WAVELENGTH):
		"""`(positions, intensities, hkls)` as plain arrays, ascending in angle.

		The shape every plotting caller wants. `hkls` holds one representative
		index triple per merged reflection -- the rest of a multiplicity group
		sits at the same angle and would only repeat the label.
		"""
		pattern = self.pattern(two_theta_range, wavelength)
		reflections = sorted(pattern.reflections, key=lambda r: r.two_theta)
		positions = np.array([r.two_theta for r in reflections], dtype=float)
		intensities = np.array([r.intensity for r in reflections], dtype=float)
		return positions, intensities, [r.hkl for r in reflections]

	# -------------------------------------------------------- the space group

	@property
	def space_group_number(self):
		return int(getattr(self.naming, 'number', 0) or 0)

	@property
	def space_group_symbol(self):
		"""The short Hermann-Mauguin symbol, keeping the setting the file used.

		`P2_1/n`, not `P2_1/c`. Every one of P2_1/c's nine settings shares the
		standard symbol, so showing that instead would read as an outright error
		to anyone who knows their own compound.
		"""
		if self.naming is None:
			return ''
		return str(self.naming.setting_short or self.naming.short or
		           self.naming.given or '')

	@property
	def crystal_system(self):
		"""The system of the space group the FILE names.

		Trigonal groups are reported as `rhombohedral` when the cell is actually
		on rhombohedral axes. The distinction is invisible to the space-group
		number -- both settings of R-3c are number 167 -- but it decides which
		cell parameters are free, so a TOPAS macro that gets it wrong refines
		the wrong two numbers. The test is conservative: it needs a = b = c with
		three equal angles away from 90, which a hexagonal-axes file never has.

		Callers that cannot express that distinction want
		`detected_crystal_system` instead, which never returns it.
		"""
		name, _letter = _spacegroups.crystal_system(self.space_group_number)
		if name == 'trigonal' and self.cell.looks_rhombohedral():
			return 'rhombohedral'
		return name

	def detected_symmetry(self, symprec=0.01):
		"""`(number, symbol)` for the group the ATOMS have, not the one named.

		Worked out from the coordinates through spglib, which is the same route
		pymatgen's SpacegroupAnalyzer took before this replaced it -- deliberately
		so. Plenty of CIFs in this lab's library declare P1 and list a whole cell
		whose atoms plainly possess more symmetry than that, and every .inp the
		wizard has ever written used the derived answer. Reading the declared
		group instead would be defensible, but it would quietly change refinements
		that are already running.

		Falls back to what the file declared when spglib finds nothing, since an
		unresolvable structure is still better described by its own header than
		by silence.
		"""
		try:
			found = _spacegroups.from_structure(self.cell, self.symbols,
			                                    self.frac, symprec)
		except Exception:
			found = None
		number = int(getattr(found, 'number', 0) or 0) if found else 0
		symbol = str(getattr(found, 'symbol', '') or '') if found else ''
		if not number:
			return self.space_group_number, self.space_group_symbol
		return number, symbol or self.space_group_symbol

	def detected_crystal_system(self, symprec=0.01):
		"""The crystal system of `detected_symmetry`.

		Trigonal groups are reported as `rhombohedral` when the cell is on
		rhombohedral axes -- see `crystal_system`. Callers whose table has no
		such key must map it themselves; prefit does.

		Falls back to triclinic, the system with every parameter free, so a
		structure nothing could identify never has a parameter locked for it.
		"""
		number, _symbol = self.detected_symmetry(symprec)
		name, _letter = _spacegroups.crystal_system(number)
		if name == 'trigonal' and self.cell.looks_rhombohedral():
			return 'rhombohedral'
		return name or 'triclinic'


def _site_contents(data, symbols, frac, report):
	"""Per-atom occupancies for the expanded cell, splitting shared sites.

	Ported from MoloM's `pxrd.cell_contents`, which reads this off a live
	Structure's metadata; the same bookkeeping is needed starting from a parsed
	file instead.

	Two corrections happen here. An expanded atom inherits the occupancy of the
	site it came from, so a half-occupied site scatters as half an atom rather
	than a whole one. And a SHARED site -- several species on one position, as
	in a solid solution -- has had all but the first discarded by `expand`'s
	minimum-image merge; for a picture that costs a pie-slice sphere, but for a
	structure factor it is simply the wrong scatterer, so the site is put back
	together as one term per species at the one position.

	A third correction is this suite's own, and is why the occupancies are not
	simply passed through. Several refinement programs write that column as
	*atoms per site* rather than a fraction -- 4.0 on a four-fold site -- and
	taken literally that scatters four times too strongly, which reorders the
	very "N strongest reflections" the overlay is asking for. One position
	cannot hold more than one atom's worth of scatterer, so a site totalling
	more than 1 is rescaled to 1, across all of its species at once. That is the
	reading pymatgen applies before it gives up on the file, so the switch of
	backend changes no intensity that was previously computable.
	"""
	site_of = list(report.get('site_of') or ())
	site_occ = list(data.occupancy or ())
	composition = _cif.site_composition(data, tol=0.1)
	scale = _overfull_site_scale(site_occ, composition)

	out_symbols, out_frac, out_occ = [], [], []
	for i, symbol in enumerate(symbols):
		site = int(site_of[i]) if i < len(site_of) else -1
		factor = scale.get(site, 1.0)
		parts = composition.get(site)
		if parts:
			for element, share in parts:
				out_symbols.append(element)
				out_frac.append(frac[i])
				out_occ.append(float(share) * factor)
			continue
		out_symbols.append(symbol)
		out_frac.append(frac[i])
		raw = float(site_occ[site]) if 0 <= site < len(site_occ) else 1.0
		out_occ.append(raw * factor)

	return out_symbols, np.asarray(out_frac, dtype=float), \
		np.asarray(out_occ, dtype=float)


def _overfull_site_scale(site_occ, composition):
	"""`{site index: factor}` bringing any over-full site back to a total of 1.

	Keyed on the ASYMMETRIC-UNIT site, which is the only level where the total
	means anything: the expanded contents repeat each site once per symmetry
	operator, so totalling occupancies there would find 4 for an ordinary
	full site in a four-fold group and shrink every structure in sight.

	Sites that merely total less than 1 are left exactly as written.
	"""
	scale = {}
	sites = set(range(len(site_occ))) | set(composition)
	for site in sites:
		parts = composition.get(site)
		if parts:
			total = sum(float(share) for _element, share in parts)
		elif 0 <= site < len(site_occ):
			total = float(site_occ[site])
		else:
			continue
		if total > 1.0:
			scale[site] = 1.0 / total
	return scale


def load_phase(cif_path, announce=True):
	"""Read a CIF into a `CifPhase`.

	`errors='replace'` on the decode, because CIFs routinely carry a stray
	Latin-1 byte in a publication title and refusing to read a structure over a
	character in a comment would be absurd.
	"""
	path = str(cif_path)
	try:
		with open(path, 'r', encoding='utf-8', errors='replace') as fh:
			data = _cif.parse_cif(fh.read())
	except OSError as e:
		raise CifError(f'could not read {os.path.basename(path)}: {e}') from e
	except Exception as e:
		raise CifError(f'could not parse {os.path.basename(path)}: {e}') from e

	report = {}
	symbols, cart = _cif.expand(data, whole_molecules=False, boundary=False,
	                            report=report)
	if not symbols:
		raise CifError(f'{os.path.basename(path)} has no atoms to diffract from.')

	frac = data.cell.to_fractional(cart)
	symbols, frac, occupancy = _site_contents(data, symbols, frac, report)

	notes = []
	missing = _pxrd.missing_species(symbols)
	if missing:
		# Not fatal: the rest of the structure still diffracts, and a pattern
		# missing one weak scatterer beats no pattern at all. But the
		# intensities are wrong by however much that element contributed, so it
		# cannot pass silently.
		notes.append('no scattering data for ' + ', '.join(sorted(missing))
		             + '; those atoms contribute nothing to the intensities')

	naming = _spacegroups.identify(symbol=data.spacegroup or '',
	                               number=int(data.it_number or 0),
	                               rhombohedral=data.cell.looks_rhombohedral())

	phase = CifPhase(data.cell, symbols, frac, occupancy,
	                 naming=naming, path=path, notes=notes)
	if announce:
		for note in phase.notes:
			print(f'[!] {os.path.basename(path)}: {note}')
	return phase


def broaden(positions, intensities, x, fwhm=DEFAULT_FWHM):
	"""Reflections as a sum of Lorentzians of FWHM `fwhm`, on the grid `x`,
	scaled so the tallest point is 1. All zeros when there are none.

	Each term peaks at its own intensity, so the sum keeps the relative
	intensities. Shared by pq's CIF and PDF-card patterns and by conv."""
	x = np.asarray(x, dtype=float)
	half = fwhm / 2.0
	half_sq = half * half
	y = np.zeros_like(x)
	for pos, intensity in zip(positions, intensities):
		y += intensity * half_sq / ((x - pos) ** 2 + half_sq)
	top = y.max() if y.size else 0.0
	return y / top if top > 0 else y


def simulate(cif_path, x, wavelength=DEFAULT_WAVELENGTH, fwhm=DEFAULT_FWHM):
	"""A CIF's powder pattern on the 2theta grid `x`: every reflection between
	the grid's ends, broadened.

	Returns (y, number of reflections, note). The note is whatever qualifies
	the intensities -- no displacement parameters in the file, an element with
	no scattering factor -- or ''. Raises CifError for a file that will not
	read."""
	x = np.asarray(x, dtype=float)
	pattern = load_phase(cif_path, announce=False).pattern((x[0], x[-1]), wavelength)
	reflections = sorted(pattern.reflections, key=lambda r: r.two_theta)
	y = broaden([r.two_theta for r in reflections],
	            [r.intensity for r in reflections], x, fwhm)
	return y, len(reflections), pattern.note


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
	to `two_theta_range` and sorted ascending in 2-theta."""
	positions, intensities, _hkls = load_phase(cif_path).peaks(two_theta_range,
	                                                           wavelength)
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
