"""Parsing of TOPAS `.out` files: raw cell parameters, per phase.

This returns the *raw* tokens as TOPAS wrote them, e.g. ``15.484356`_0.000738``
-- mean and uncertainty in backtick-sigma form, unrounded. That form is what
trusted starting parameters need (they seed the next refinement), so harvesting
a converged fit is a straight extraction with no transcription step.

The plotter rounds these for display via ``core.rounding``; presentation is the
caller's job, not this module's.

Parameter keys use TOPAS's own short names (``a``, ``b``, ``c``, ``al``, ``be``,
``ga``) so a harvested set can be written straight into a wizard macro call.
"""

import os
import re
from pathlib import Path

# Crystal-system macros recognised on a single line, e.g. Cubic(@ 17.09`_0.01)
_MACRO_PAT = re.compile(
	r'\b(Cubic|Tetragonal|Hexagonal|Trigonal|Rhombohedral|Orthorhombic|Monoclinic|Triclinic)'
	r'\s*\(([^)]+)\)'
)

# Which parameters each macro's positional arguments correspond to, and which
# further parameters the symmetry implies. Mirrors the wizard's CRYSTAL_MACROS.
_MACRO_SHAPE = {
	'Cubic':        ['a'],
	'Tetragonal':   ['a', 'c'],
	'Hexagonal':    ['a', 'c'],
	'Trigonal':     ['a', 'c'],
	'Rhombohedral': ['a', 'al'],
	'Orthorhombic': ['a', 'b', 'c'],
	'Monoclinic':   ['a', 'b', 'c', 'be'],
	'Triclinic':    ['a', 'b', 'c', 'al', 'be', 'ga'],
}

# Loose per-line declarations: `a @ 15.4`, `b lpa 15.5`, `be 110.5`, ...
# The word boundary keeps `a` from matching `al` or `axial`; the optional
# keyword run skips `@` / `lpa` between the key and the value.
_LOOSE_KEYS = ('a', 'b', 'c', 'al', 'be', 'ga')


def strip_comments(text):
	"""Blank out TOPAS comment lines (first non-space char is `'`), preserving
	line count so per-line matches keep their positions."""
	return '\n'.join(
		'' if re.match(r"\s*'", line) else line
		for line in text.split('\n')
	)


def parse_phases(path):
	"""Raw cell parameters per phase, in the order the .out declares them.

	Returns a list of dicts::

	    [{'system': 'Orthorhombic',
	      'space_group': '61',
	      'params': {'a': "15.475318`_0.000986", ...}}, ...]

	`system` and `space_group` may be None when the .out does not say. Returns []
	if the file is missing or unreadable -- a caller harvesting parameters should
	report that itself rather than have this raise mid-parse.
	"""
	if not os.path.exists(path):
		return []
	try:
		raw = Path(path).read_text(encoding='utf-8', errors='replace')
	except OSError:
		return []

	content = strip_comments(raw)

	# Each phase starts at `hkl_Is`; the preamble before the first is dropped.
	blocks = re.split(r'\bhkl_Is\b', content)
	phase_blocks = blocks[1:] if len(blocks) > 1 else [content]

	phases = []
	for block in phase_blocks:
		if not block.strip():
			continue

		sg_m = (re.search(r'space_group\s+"([^"]+)"', block)
		        or re.search(r'space_group\s+(\S+)', block))
		sg = sg_m.group(1).strip() if sg_m else None

		params = {}
		system = None

		macro = _MACRO_PAT.search(block)
		if macro:
			system = macro.group(1)
			tokens = [p.replace('@', '').strip()
			          for p in macro.group(2).split(',') if p.strip()]
			labels = _MACRO_SHAPE.get(system, [])
			# Only zip what the macro actually declared; a Monoclinic line with a
			# missing beta should yield a, b, c rather than a mislabelled fourth.
			for label, token in zip(labels, tokens):
				params[label] = token
		else:
			for key in _LOOSE_KEYS:
				m = re.search(rf'^\s*{key}\b\s+(?:[a-zA-Z@]+\s+)*(\S+)',
				              block, re.MULTILINE)
				if m:
					params[key] = m.group(1).strip()

		if params:
			phases.append({'system': system, 'space_group': sg, 'params': params})

	return phases


def clean_value(token):
	"""Reduce a harvested token to the ``mean`_esd`` form TOPAS accepts as input.

	Refinement output can carry diagnostic suffixes -- ``_SVD_ERR``,
	``_LIMIT_MAX_<v>``, ``_LIMIT_MIN_<v>`` -- appended after the uncertainty.
	They describe how the fit behaved; feeding them back in as a starting value
	is not something TOPAS expects, so they are dropped here rather than being
	written into a trusted set.
	"""
	if token is None:
		return None
	m = re.match(r'^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)'   # mean
	             r'(?:`?_([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?))?',  # optional esd
	             str(token))
	if not m:
		return str(token).strip()
	mean, esd = m.group(1), m.group(2)
	return f'{mean}`_{esd}' if esd else mean


def free_params(system, params):
	"""Drop parameters the crystal system fixes or derives, keeping only those a
	refinement actually varies.

	A Tetragonal cell stores only a and c; carrying b=a into a trusted set would
	be redundant at best, and wrong if someone later edits a without b.
	"""
	if not system:
		return dict(params)
	keep = _MACRO_SHAPE.get(system)
	if not keep:
		return dict(params)
	return {k: v for k, v in params.items() if k in keep}
