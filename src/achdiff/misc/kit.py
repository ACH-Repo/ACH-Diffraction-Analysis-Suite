"""Everything a misc script may use from the suite, in one place.

A misc script gets copied out and edited by hand, sometimes years after it was
written, and it keeps working exactly as long as what it imports does. So it
imports from here and nowhere else in the suite, and always absolutely:

    from achdiff.misc import kit

A relative import (`from ..core import topas`) is what broke quickplot's old
copy-it-into-your-project recipe: the copy has no package around it. An absolute
one works from any folder on any machine with the suite installed.

The names here are a promise. They keep their meaning when the code behind them
moves; anything else in the package may change without notice. Everything that
belongs to one analysis stays in the script.

Reading TOPAS output
    phases(path)      the refined phases of an .out, with names and volumes
    value(token)      "15.47`_0.001" -> (15.47, 0.001)
    rounded(token)    "15.4753`_0.0010" -> "15.4753(10)"

Reading measured patterns
    pattern(path)     (two_theta, intensity), from any file pq and conv read
    PATTERN_TYPES     the suffixes pattern() reads: '.xy', '.dat', '.raw', ...

The x quantity: 2theta or Q
    X_QUANTITIES      '2theta', 'q', 'q-nm' -> name, symbol, unit, axis label
    convert_x(x, source, target, wavelength=None)
                      2theta <-> Q (1/angstrom or 1/nm); wavelength in angstrom
    x_from_header(path)
                      (quantity, wavelength) from a pyFAI / DIOPTAS header

Series
    values(spec)      "1,100:900:100" -> [1.0, 100.0, ..., 900.0], as pp --x-values
    natural_key(text) a sort key that puts scan_2 before scan_10
    template_numbers(names, template)
                      the numbers at the #s of a wildcard template: *_#bar_*
    sort_by_pattern(names, regex)
                      names ordered by a regex's capture groups, as pp --sort-key

Asking (so a script run with no arguments explains itself)
    interactive()     whether anyone is there to answer
    ask(), ask_yes(), choose()

Running
    add_common_arguments(parser)   -s, -x and -d, as every tool spells them
    main(parser, fill, run, ...)   the shape of every script's main()
    SUITE_VERSION                  the installed suite's version, e.g. '0.18.0'

Style sheets (for a script registered as a plotter in achdiff/styles.py)
    add_style_arguments(parser)    -u and --style, as pp and pq spell them
    apply_style(tool, settings, user, explicit)
                                   the person's sheets layered onto settings
"""

import os
import re
import sys
from pathlib import Path

from achdiff import __version__ as _version
from achdiff import document
from achdiff import identity as _identity
from achdiff import styles as _styles
from achdiff.core import readers as _readers
from achdiff.core import topas as _topas
from achdiff.core import xaxis as _xaxis
from achdiff.core.animate import natural_key as _natural_key
from achdiff.core.animate import parse_value_error as _parse_value_error
from achdiff.core.animate import parse_x_values as _parse_x_values
from achdiff.core.animate import sort_by_pattern as _sort_by_pattern
from achdiff.core.animate import template_numbers as _template_numbers
from achdiff.core.rounding import cryst_round as _cryst_round


# ---------------------------------------------------------------- TOPAS output

def phases(path):
	"""Each refined phase of a TOPAS .out, in the order it declares them.

	A list of dicts:
	    name         from rp's "Selected phases:" line; None in a hand-written fit
	    space_group  as TOPAS wrote it, e.g. '61'
	    system       the cell macro, e.g. 'Orthorhombic'
	    params       {'a': "15.475318`_0.000986", ...} -- only what was refined
	    volume       the cell_volume token, or None
	"""
	found = _topas.parse_phases(path)
	names = _topas.phase_names(path)
	# Names are only trusted when they line up one to one with the phases.
	aligned = len(names) == len(found)
	return [dict(ph, name=(names[i][0] or None) if aligned else None)
	        for i, ph in enumerate(found)]


def value(token):
	"""A TOPAS `value`_esd` token as (value, esd) floats; esd None if absent.
	None when the value itself will not parse."""
	return _parse_value_error(token)


def rounded(token):
	"""The token as a crystallographer writes it: 15.4753(10)."""
	text = _cryst_round(str(token))
	return text if text is not None else str(token)


#: The suite's version, for a script that writes down how its output was made.
SUITE_VERSION = _version


# ------------------------------------------------------------ measured patterns

#: The suffixes pattern() reads, lower case with the dot.
PATTERN_TYPES = tuple(f'.{ext}' for ext in _readers.READERS)


def pattern(path):
	"""A measured pattern as (two_theta, intensity) float arrays, read exactly as
	pq plots it and conv writes it out. Raises ValueError, with a message fit to
	print, for a file it cannot read."""
	return _readers.read(path)


#: '2theta', 'q' (1/angstrom), 'q-nm' (1/nm) -> Quantity(key, name, plain_unit,
#: symbol, unit, label): name and plain_unit ASCII for a console, symbol and
#: unit for a person, label mathtext for an axis.
X_QUANTITIES = _xaxis.QUANTITIES


def convert_x(x, source, target, wavelength=None):
	"""x from one quantity to another ('2theta', 'q', 'q-nm'). Between 2theta and
	Q it needs the wavelength in angstrom; raises ValueError without one, or for a
	Q that wavelength cannot reach."""
	return _xaxis.convert(x, source, target, wavelength)


def x_from_header(path):
	"""(quantity or None, wavelength in angstrom or None), from the comment lines
	pyFAI and DIOPTAS write at the top of a pattern ("q_A^-1", "Wavelength: ...")."""
	return _xaxis.from_header(path)


# ---------------------------------------------------------------------- series

def values(spec):
	"""A list of numbers from a list and/or ranges, the syntax of pp --x-values:
	"1,100:900:100" -> [1.0, 100.0, 200.0, ..., 900.0]. A range is
	start:stop:step with the stop included. Raises ValueError for what is not one."""
	return _parse_x_values(spec)


def natural_key(text):
	"""Sort key that puts scan_2 before scan_10."""
	return _natural_key(text)


def template_numbers(names, template):
	"""The numbers a wildcard template finds in each name: [(float, ...) or None].

	In the template * is any text, ? any one character and # a number; it covers
	the whole name, in any case: *_#bar_* reads 1700 from ..._1700bar_001.xy. None
	for a name it does not fit. Raises ValueError for a template without a #, and
	for one that fits a name in more than one way (*_#_*), naming the file."""
	return _template_numbers(names, template)


def sort_by_pattern(names, regex):
	"""(ordered, unmatched): names ordered by what `regex` captures, groups compared
	left to right, as numbers where they are numbers -- pp --sort-key exactly.
	Raises ValueError for a regex that will not compile."""
	return _sort_by_pattern(names, regex)


# ---------------------------------------------------------------------- asking

def interactive():
	"""Whether there is someone at a console to answer questions."""
	try:
		return sys.stdin.isatty()
	except (AttributeError, ValueError):
		return False


def ask(prompt, default=''):
	"""One line of input; Enter takes `default`. Ctrl+Z / Ctrl+C stop the script."""
	hint = f' [{default}]' if default else ''
	try:
		reply = input(f'{prompt}{hint} ').strip()
	except (EOFError, KeyboardInterrupt):
		print()
		raise SystemExit(1)
	return reply or default


def ask_yes(prompt, default=False):
	while True:
		reply = ask(f'{prompt} ({"Y/n" if default else "y/N"})').lower()
		if not reply:
			return default
		if reply in ('y', 'yes', 'j', 'ja'):
			return True
		if reply in ('n', 'no', 'nein'):
			return False


def _selection(text, n):
	"""'1,3-4' -> [0, 2, 3]; 'all' -> everything; None when it will not parse."""
	text = text.strip().lower()
	if text in ('all', '*'):
		return list(range(n))
	if text in ('none', '-'):
		return []
	picked = []
	for part in re.split(r'[,\s]+', text):
		if not part:
			continue
		m = re.fullmatch(r'(\d+)(?:-(\d+))?', part)
		if not m:
			return None
		lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
		if not (1 <= lo <= hi <= n):
			return None
		picked.extend(i - 1 for i in range(lo, hi + 1) if i - 1 not in picked)
	return picked


def choose(labels, prompt, default=(), show=True, at_least=1):
	"""Numbered choice from `labels`. Returns the chosen indices.

	Takes numbers and ranges ("1,3-4"), "all" or "none"; Enter takes `default`."""
	if show:
		for i, label in enumerate(labels, start=1):
			print(f'  {i:>3}  {label}')
	default = list(default)
	shown = ','.join(str(i + 1) for i in default)
	while True:
		reply = ask(prompt, shown)
		picked = _selection(reply, len(labels)) if reply else []
		if picked is None:
			print(f'    Numbers from 1 to {len(labels)}, e.g. 1,3 or 2-4, or "all".')
			continue
		if len(picked) < at_least:
			print(f'    Pick at least {at_least}.')
			continue
		return picked


# --------------------------------------------------------------------- running

def add_common_arguments(parser, extension='svg'):
	"""-s, -x and -d, meaning what they mean in every tool of the suite.

	`extension` is -x's default. A script with a style sheet passes None, so the
	sheet's format holds unless -x is typed, as in pp and pq."""
	parser.add_argument('-s', '--silent', action='store_true',
	                    help='Save the output instead of opening a window.')
	parser.add_argument('-x', '--extension', default=extension,
	                    help='Image format used with -s (default: '
	                         + (extension or "the style sheet's, else svg") + ').')
	document.add_document_argument(parser)


def add_style_arguments(parser):
	"""-u and --style, as pp and pq spell them, for a script with style sheets."""
	parser.add_argument('-u', '--user', default=None, metavar='ID',
	                    help='Person ID whose style sheet to use (e.g. CN). Defaults to '
	                         'ACH_USER, else the registered profile the files here match.')
	parser.add_argument('--style', default=None, metavar='FILE',
	                    help='A style sheet to layer on top of yours for this plot: a path, '
	                         'or a bare name from the styles directory.')


def apply_style(tool, settings, user=None, explicit=None):
	"""Layer the person's style sheets for `tool` onto `settings`, in place, and
	say which were used -- exactly as pp and pq do:

	    --style FILE > ACH_STYLE_<TOOL> > styles/<tool>/<ID>.toml > styles/<tool>/default.toml

	`tool` must be registered in achdiff/styles.py, which holds the keys a sheet
	may set. Returns the description of what was applied, or None. Raises
	FileNotFoundError for a --style file that is not there."""
	resolved, source = _identity.resolve(user)
	if user or resolved:
		print(_identity.describe(resolved, source))
	applied = _styles.apply(tool, settings, user=resolved, explicit=explicit)
	if applied:
		print(f'[*] Style: {applied}')
	return applied


def _shown(arg):
	"""An argument as it would be typed at the prompt."""
	if arg and not set(arg) & set(' \t"&|<>^()'):
		return arg
	return document._msvcrt_quote(arg)


def _own_command(script_file):
	"""How to run this script again when it was run as a copied file."""
	path = Path(script_file).resolve()
	try:
		shown = str(path.relative_to(Path.cwd()))
	except ValueError:
		shown = str(path)
	return ['python', shown]


def main(parser, fill, run, argv=None, command=None, script_file=None):
	"""The shape every misc script's main() takes.

	Parses `argv`. Then `fill(args, parser)` may ask for whatever is missing; its
	answers come back as command-line tokens and are parsed exactly like typed
	ones, and the command that would have skipped the questions is printed --
	which is how a wizard teaches its own command line. -d records that command,
	and `args.typed_command` carries it as one line. Finally `run(args)`, whose
	return value is the exit code.

	`command` is how the script was started (`achdiff misc run NAME`); a copy
	run on its own passes its `__file__` as `script_file` instead.
	"""
	argv = list(sys.argv[1:] if argv is None else argv)
	command = list(command) if command else _own_command(script_file or sys.argv[0])
	# --help and error messages then show the command as it has to be typed.
	parser.prog = ' '.join(_shown(c) for c in command)
	args = parser.parse_args(argv)

	extra = list(fill(args, parser) or []) if fill else []
	if extra:
		argv = argv + extra
		args = parser.parse_args(argv)
	typed = ' '.join(command + [_shown(a) for a in document.without_document_flag(parser, argv)])
	if extra:
		print()
		print('[*] Next time, skip the questions:')
		print('      ' + typed)
		print()
	# For a script that writes down how its output was made.
	args.typed_command = typed

	if getattr(args, 'document', False):
		document.write_run_file(parser, command[0], None, argv=argv, command=command,
		                        silent=bool(getattr(args, 'silent', False)))
	return run(args) or 0
