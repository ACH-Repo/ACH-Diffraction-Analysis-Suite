"""The x quantity of a powder pattern -- 2theta or Q -- and converting between them.

A laboratory diffractometer writes 2theta in degrees. A synchrotron pattern
integrated with pyFAI or DIOPTAS is as often in Q, in reciprocal angstrom or
nanometres, and patterns measured at different wavelengths only line up in Q.
A plot has to say which it shows, and the file usually does not:

    Q = 4 pi sin(theta) / lambda        lambda in angstrom, Q in 1/angstrom

Where a file does say -- the column header and "Wavelength:" line pyFAI and
DIOPTAS write -- `from_header` reads it.
"""

import re
from collections import namedtuple

import numpy as np

#: `name` and `plain_unit` are ASCII, for a console that cannot print a theta;
#: `symbol` and `unit` are for text a person reads; `label` is matplotlib
#: mathtext for an axis.
Quantity = namedtuple('Quantity', 'key name plain_unit symbol unit label')

QUANTITIES = {
	'2theta': Quantity('2theta', '2theta', 'deg', '2θ', '°', r'$2\theta$ / °'),
	'q': Quantity('q', 'Q', '1/A', 'Q', 'Å⁻¹', r'$Q$ / Å$^{-1}$'),
	'q-nm': Quantity('q-nm', 'Q', '1/nm', 'Q', 'nm⁻¹', r'$Q$ / nm$^{-1}$'),
}

# pyFAI's names for the units, which DIOPTAS writes too.
_HEADER_UNITS = {'2th_deg': '2theta', 'q_A^-1': 'q', 'q_nm^-1': 'q-nm'}
_HEADER_UNIT = re.compile(r'(?<![\w^-])(2th_deg|q_A\^-1|q_nm\^-1)(?![\w^-])')
_HEADER_WAVELENGTH = re.compile(r'[Ww]avelength\s*[:=]\s*([0-9.]+(?:[eE][+-]?\d+)?)\s*(m|nm|A|Å)?\b')


def _wavelength(wavelength, source, target):
	if wavelength is None:
		raise ValueError(f'{QUANTITIES[source].name} to {QUANTITIES[target].name} needs the '
		                 f'wavelength, in angstrom (--wavelength)')
	if wavelength <= 0:
		raise ValueError(f'a wavelength of {wavelength:g} angstrom cannot be right')
	return float(wavelength)


def convert(x, source, target, wavelength=None):
	"""`x`, in `source` units, in `target` units: '2theta' (degrees), 'q'
	(1/angstrom) or 'q-nm' (1/nm).

	Between 2theta and Q it needs the wavelength in angstrom. Raises ValueError
	without one, and for a Q beyond what that wavelength reaches (Q lambda / 4 pi
	above 1), which means the wavelength or the unit is wrong."""
	x = np.asarray(x, dtype=float)
	if source == target:
		return x.copy()
	if source == 'q':
		q = x
	elif source == 'q-nm':
		q = x / 10.0
	else:
		q = 4 * np.pi * np.sin(np.radians(x) / 2) / _wavelength(wavelength, source, target)
	if target == 'q':
		return q
	if target == 'q-nm':
		return q * 10.0
	lam = _wavelength(wavelength, source, target)
	s = q * lam / (4 * np.pi)
	if np.any(np.abs(s) > 1):
		raise ValueError(f'Q reaches {np.nanmax(q):.4g} 1/angstrom, which a wavelength of '
		                 f'{lam:g} angstrom cannot: Q lambda / 4 pi must stay below 1. Is the '
		                 f'wavelength or the unit of the files wrong?')
	return np.degrees(2 * np.arcsin(s))


def from_header(path, lines=200):
	"""(quantity key or None, wavelength in angstrom or None) from the comment
	lines at the top of a text pattern -- the column header ("q_A^-1", "2th_deg")
	and "Wavelength: 2.073e-11 m" that pyFAI and DIOPTAS write. (None, None) for
	a file without them, or one that cannot be read as text."""
	key = wavelength = None
	try:
		with open(path, encoding='utf-8', errors='replace') as fh:
			for _, line in zip(range(lines), fh):
				stripped = line.strip()
				if stripped and not stripped.startswith('#'):
					break
				unit = _HEADER_UNIT.search(stripped)
				if unit and key is None:
					key = _HEADER_UNITS[unit.group(1)]
				m = _HEADER_WAVELENGTH.search(stripped)
				if m and wavelength is None:
					value = float(m.group(1))
					scale = {'m': 1e10, 'nm': 10.0}.get(m.group(2) or '', 1.0)
					# A bare number this small is metres, as pyFAI writes it.
					wavelength = value * (1e10 if not m.group(2) and value < 1e-6 else scale)
	except (OSError, ValueError):
		return None, None
	return key, wavelength
