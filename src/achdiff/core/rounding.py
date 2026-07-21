"""Crystallographic rounding of TOPAS `value`_uncertainty` tokens.

This is the single implementation. It previously existed twice -- in the plotter
and in the lattice-parameter tables -- with different signatures *and* different
results, which is the kind of drift that made bundling worth doing:

    input                              plotter      tables
    15.484`_0.002`_LIMIT_MAX_16        15.484(2)    None  (parameter dropped)

The plotter's behaviour is canonical: a value that hit a refinement limit is
still the best estimate available, so the annotation is stripped and the number
kept. If that turns out to be wrong crystallographically, this is now the one
place to change it.

The tables version also formatted quality factors (chi/rwp/rexp) to two decimals
when they carried no uncertainty. That is a presentation choice belonging to the
caller, not to rounding, so it lives in the tables tool as `format_quality`.
"""

import re
from decimal import Decimal, getcontext, InvalidOperation, ROUND_HALF_UP

# TOPAS appends diagnostics after the numeric uncertainty (`_LIMIT_MAX_<v>`,
# `_LIMIT_MIN_<v>`, `_SVD_ERR`, ...). Both sides are always plain numbers, so
# only the leading numeric prefix of each is kept.
_NUM = r'^\s*[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?'


def cryst_round(mean_err):
	"""Round a `mean`_esd` token to crystallographic form, e.g. `15.484(2)`.

	Returns the plain mean as a string when no uncertainty is present, and None
	only when the mean itself cannot be parsed.
	"""
	getcontext().prec = 32

	if mean_err is None:
		return None

	if '`_' in mean_err:
		mean, error = mean_err.split('`_', 1)
	elif '_' in mean_err:
		mean, error = mean_err.split('_', 1)
	else:
		return mean_err

	mn = re.match(_NUM, mean)
	en = re.match(_NUM, error)
	if mn:
		mean = mn.group(0)
	if en:
		error = en.group(0)

	# Salvage on partial garbage: if only the uncertainty is malformed, return
	# the mean alone. If even the mean can't parse, give up so the caller skips.
	try:
		mean = Decimal(mean)
		error = Decimal(error)
	except (InvalidOperation, ValueError):
		try:
			return str(Decimal(mean))
		except (InvalidOperation, ValueError):
			return None

	# "Rule of 19": the bracketed esd is an integer from 2 to 19 -- one
	# significant digit, or two when the leading digit is 1. An esd that would
	# round to 20 or more is shortened by one digit and the mean follows:
	# 15.4840(20) -> 15.484(2).
	error = abs(error)
	if error == 0:
		return format(mean, 'f')

	ndec = 1 - error.adjusted()
	while True:
		bracket = int(error.scaleb(ndec).to_integral_value(rounding=ROUND_HALF_UP))
		if bracket > 19:
			ndec -= 1
		elif bracket < 2:
			ndec += 1
		else:
			break

	mean_round = mean.quantize(Decimal(1).scaleb(-ndec), rounding=ROUND_HALF_UP)

	# Always fixed-point: lattice parameters and cell volumes must never appear
	# in scientific notation. When the esd's significant digit sits left of the
	# decimal point (ndec < 0), pad it back out so the bracket stays unambiguous:
	# 6.6E+3 +/- 7E+2 renders as 6600(700), not 6600(7).
	if ndec < 0:
		bracket *= 10 ** -ndec
	return '%s(%s)' % (format(mean_round, 'f'), bracket)


def split_value_bracket(rounded):
	"""Split `15.484(2)` into ('15.484', '(2)'); a bare value yields ('...', '').
	Used for column-aligning values in the plotter's unit-cell boxes."""
	if rounded is None:
		return None
	m = re.match(r"^([^(]+)(\(.*\))$", rounded)
	if m:
		return m.group(1), m.group(2)
	return rounded, ""
