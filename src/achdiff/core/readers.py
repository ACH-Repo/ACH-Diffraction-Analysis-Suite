"""Readers for measured powder patterns, one copy for every tool.

pq and pf each carried their own copy of these, word for word apart from the
error messages. conv writes out what they read, and an .xy that differed from
the plot of the same file would be worse than none -- so all three read here.

Simulated patterns (a CIF, a PDF card) are not measured data and stay in pq,
which is the only tool that draws them.

Every reader returns (two_theta, intensity) as float arrays, or raises
ValueError with a message fit to print.
"""

import re
import zipfile
from pathlib import Path

import numpy as np

from . import bruker


def read_xy(path):
	"""Whitespace-separated columns; the first two are 2theta and intensity, the
	rest (an esd column, say) are ignored. Lines starting with '#' are skipped.

	Ragged or single-column rows raise a ValueError naming the problem, rather
	than letting numpy fail on the shape."""
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
	arr = np.array([r[:2] for r in rows], dtype=float)
	return arr[:, 0], arr[:, 1]


def read_raw(path, verbose=False):
	"""Bruker .raw (RAW1.01 or RAW4.00), read natively -- see ``core.bruker``.
	No TOPAS conversion step, so this works on a machine without TOPAS."""
	return bruker.read_raw(path, verbose=verbose)


def read_brml(path):
	"""A 2theta/intensity scan from a Bruker .brml archive.

	Each <Datum> row is `timePerStep,1,2theta,theta,intensity`; columns 2 and 4
	are the ones wanted."""
	with zipfile.ZipFile(path, 'r') as z:
		# The first RawDataN.xml; most .brml files have RawData0.xml.
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


def read_riet7(path):
	"""Riet7 .dat: a header with '<start> <step> <stop> MeasureDateTime ...',
	then a block of integer intensities.

	The header rounds start and step to 3 decimals, so 2theta read from here is
	only as good as that rounding; the intensities are exact."""
	with open(path, encoding='utf-8', errors='replace') as inf:
		filestring = inf.read()

	header_re = re.compile(r'(\d+[.,]\d+)\s+(\d+[.,]\d+)\s+(\d+[.,]\d+)\s+[Mm]easureDateTime')
	m = header_re.search(filestring)
	if m is None:
		raise ValueError(f'Could not find Riet7 header (start/step/stop  MeasureDateTime) in {path}')

	start, step, stop = (float(g.replace(',', '.')) for g in m.groups())

	# Intensities follow the header line. Skip past the newline that ends the
	# MeasureDateTime line -- otherwise the date and time digits (e.g.
	# "21/05/2024 03:45") are read as the first intensities, a spurious spike
	# at the start of the pattern.
	nl = filestring.find('\n', m.end())
	tail = filestring[nl + 1:] if nl != -1 else filestring[m.end():]
	intensities = np.array(re.findall(r'-?\d+', tail), dtype=float)

	# The count the header promises; anything beyond it is trimmed.
	n_expected = int(round((stop - start) / step)) + 1
	if intensities.size < n_expected:
		raise ValueError(f'{path}: expected {n_expected} intensities, found {intensities.size}')
	intensities = intensities[:n_expected]

	x = start + np.arange(n_expected) * step
	return x, intensities


def read_dat(path, verbose=False):
	""".dat is either Riet7 or plain columns: Riet7 first, then read_xy."""
	try:
		return read_riet7(path)
	except Exception as e:
		if verbose:
			print(f'  .dat: Riet7 parse failed ({e}); falling back to read_xy.')
		return read_xy(path)


# Extension (lower case, no dot) -> reader. The ones taking `verbose` are
# called with it by `read`.
READERS = {
	'xy':   read_xy,
	'txt':  read_xy,
	'csv':  read_xy,
	'dat':  read_dat,
	'raw':  read_raw,
	'brml': read_brml,
}
_VERBOSE = {read_raw, read_dat}


def read(path, verbose=False):
	"""(two_theta, intensity) for any measured-pattern file, checked for shape.

	Raises ValueError for an extension there is no reader for, and for a file
	that reads as empty or with columns of different lengths."""
	ext = Path(path).suffix.lower().lstrip('.')
	reader = READERS.get(ext)
	if reader is None:
		raise ValueError(f'No reader for .{ext}: {path}')
	x, y = reader(path, verbose=verbose) if reader in _VERBOSE else reader(path)
	x = np.asarray(x, dtype=float)
	y = np.asarray(y, dtype=float)
	if x.ndim != 1 or x.size == 0 or y.shape != x.shape:
		raise ValueError(f'{path}: empty or mismatched data.')
	return x, y
