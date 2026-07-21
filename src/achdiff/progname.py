"""Resolve the command name to show in `--help` output.

An alias shim runs `python -m achdiff.tools.plotter`, so argparse would derive
its program name from the module file and print `usage: plotter.py` no matter
what the user actually typed. The shim therefore exports ACHDIFF_PROG with its
own name, and the tools use it when present.
"""

import os
import sys
from pathlib import Path

ENV_PROG = 'ACHDIFF_PROG'


def prog_name(fallback):
	"""The name to hand argparse as `prog`.

	Order: the alias shim's ACHDIFF_PROG; else argv[0]'s stem when it looks like
	a console entry point (pip writes pp.exe, not a .py file); else `fallback`.
	"""
	env = os.environ.get(ENV_PROG)
	if env:
		return env

	argv0 = sys.argv[0] if sys.argv else ''
	if argv0:
		stem = Path(argv0).stem
		# `python -m pkg.mod` leaves the module's own filename here; that is the
		# case this function exists to avoid.
		if stem and not argv0.endswith('.py'):
			return stem

	return fallback
