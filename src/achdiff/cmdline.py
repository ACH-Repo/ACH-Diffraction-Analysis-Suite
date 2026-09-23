"""A tool's command line: the profile's default flags in front, and -d behind.

Every tool parses through `parse_args` here, so default flags and the -d record
behave the same in all of them.

Default flags
-------------
`achdiff flags set pp -d -c` stores flags that every pp run starts with, per
profile (or for everyone, under [defaults]). Typed flags go after them, so a
typed value wins: `-x png` over a default `-x svg`, a typed `-m` over a default
one. A default on/off flag cannot be switched off for one run -- there is no
`--no-c` -- so `--no-defaults` drops all of them for that run instead. That is
the trade config.py's docstring once declined; one all-or-nothing switch is the
price of not inventing a counter-flag for every option.

A profile's older `qall = true` is folded in as a default `--qall`, so it
answers to --no-defaults and is written into a -d record like the rest.

What -d records
---------------
Not what was typed, but what ran: the default flags written out, then the typed
ones, then `--no-defaults`, and `-u ID` when the profile came from anywhere but
the command line. A run file is meant to redraw the same plot. Left to pick up
defaults again, a later change to them would change an old figure -- and a
default -d would make every replay write another file. Pinning the profile
matters for `set ACH_USER=CN`, which a double-clicked file does not inherit.

The style sheet and CIF library are still read from the profile when the file
runs; those are the profile's content, not the command.
"""

import contextlib
import importlib
import io
import sys

from . import config, document, identity

# The tools, and the module that builds each one's parser.
TOOL_MODULES = {
	'pp': 'achdiff.tools.plotter',
	'pq': 'achdiff.tools.quickplot',
	'pf': 'achdiff.tools.prefit',
	'pt': 'achdiff.tools.tables',
	'rp': 'achdiff.tools.wizard',
	'conv': 'achdiff.tools.convert',
}

# Profile settings that are a flag's default in all but name.
SETTING_FLAGS = {'pp': {'qall': '--qall'}}

NO_DEFAULTS = '--no-defaults'

# Flags that make no sense as a default: which profile to use cannot come from
# the profile, and --save-profile would rewrite it on every run. --force (conv
# -f) replaces files; stored, it would do so on every run of everyone the
# defaults reach, without anyone having asked. Overwriting is typed or not done.
_NOT_DEFAULTABLE = {'user', 'save_profile', 'no_defaults', 'force'}


def add_arguments(parser):
	"""-d and --no-defaults, the two flags every tool shares."""
	document.add_document_argument(parser)
	parser.add_argument(NO_DEFAULTS, action='store_true',
	                    help='Run without the default flags your profile sets for '
	                         'this tool (see `achdiff flags show`).')


def build_parser(tool):
	"""The argument parser of `tool`, built by its own module."""
	return importlib.import_module(TOOL_MODULES[tool])._build_parser()


def _try_parse(parser, argv):
	"""(namespace, None), or (None, argparse's complaint) -- without exiting."""
	err = io.StringIO()
	out = io.StringIO()
	try:
		with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
			return parser.parse_args(argv), None
	except SystemExit:
		lines = err.getvalue().strip().splitlines() or ['could not be read']
		# argparse ends with "prog: error: <what>"; the usage above it is noise here.
		return None, lines[-1].split('error: ', 1)[-1]


def _action_for(parser, token):
	"""The argparse action an option token names, or None for a value."""
	if token == '--' or document.looks_like_value(parser, token):
		return None
	actions = parser._option_string_actions
	name = token.split('=', 1)[0]
	if name in actions:
		return actions[name]
	if token.startswith('--'):
		hits = {actions[o] for o in actions if o.startswith('--') and o.startswith(name)}
		return hits.pop() if len(hits) == 1 else None
	return actions.get(token[:2])     # -xpng, or the first letter of a cluster


def merge(parser, defaults, typed):
	"""`defaults` + `typed`, less every default the typed flags replace.

	argparse keeps the last value of a repeated option anyway, so dropping the
	default changes nothing about the run -- but a record reading `-m 20,40,10
	... -m 45,,5` would look like both ranges applied. Returns (argv, dropped)."""
	groups = []
	for tok in defaults:
		action = _action_for(parser, tok)
		if action is not None or not groups:
			groups.append((action, [tok]))
		else:
			groups[-1][1].append(tok)
	typed_actions = {_action_for(parser, t) for t in typed} - {None}
	kept, dropped = [], []
	for action, tokens in groups:
		(dropped if action in typed_actions else kept).extend(tokens)
	return kept + list(typed), dropped


def default_flags(tool, user, cfg=None):
	"""`tool`'s default flags for `user`, as (flags, where they came from)."""
	flags, source = config.default_flags(tool, user, cfg=cfg)
	for key, flag in SETTING_FLAGS.get(tool, {}).items():
		if config.get(key, user=user, cfg=cfg) and flag not in flags:
			flags = flags + [flag]
			source = source or (f'profile {user}' if user else '[defaults]')
	return flags, source


def check_defaults(tool, flags):
	"""Why `flags` cannot be `tool`'s defaults, or None if they can.

	Parsed with the tool's own parser, so a typo is caught when it is stored
	rather than on every run afterwards."""
	return _defaults_problem(build_parser(tool), tool, flags)


def _defaults_problem(parser, tool, flags):
	"""check_defaults, with the parser already built."""
	parsed, problem = _try_parse(parser, list(flags))
	if parsed is None:
		return problem
	blank = vars(parser.parse_args([]))
	changed = {k for k, v in vars(parsed).items() if blank.get(k) != v}
	if 'user' in changed:
		return ('-u cannot be a default -- it picks the profile the defaults come '
		        'from. Put it before the tool name: achdiff flags set -u CN ' + tool + ' ...')
	if 'force' in changed:
		return ('-f cannot be a default -- it overwrites files, so it has to be typed '
		        'on the run that means to')
	bad = sorted(changed & _NOT_DEFAULTABLE)
	if bad:
		return 'not usable as a default: ' + ', '.join('--' + b.replace('_', '-') for b in bad)
	positionals = {a.dest for a in parser._actions if not a.option_strings}
	if changed & positionals:
		return 'a default can only be a flag, not a file name or other value on its own'
	return None


def parse_args(parser, tool, module, argv=None, silent=None):
	"""Parse this tool's command line, with the profile's default flags in front.

	Writes the -d record if asked for, and returns the namespace. `silent(args)`
	says whether the run saves its plot without a window, for the _s in the
	record's name.
	"""
	typed = list(sys.argv[1:] if argv is None else argv)
	# The typed flags on their own first: a typo or -h stops here, before any
	# default is applied or any file written.
	args = parser.parse_args(typed)
	user, _source = identity.resolve(getattr(args, 'user', None))

	ran = typed
	if not args.no_defaults:
		flags, source = default_flags(tool, user)
		if flags:
			combined, dropped = merge(parser, flags, typed)
			# Checked here as well as when stored: a config edited by hand, or
			# saved before a flag became undefaultable, must not slip one in.
			parsed, problem = None, _defaults_problem(parser, tool, flags)
			if problem is None:
				parsed, problem = _try_parse(parser, combined)
			if parsed is None:
				# Stored before an upgrade renamed something, most likely. The run
				# goes ahead on what was typed; the defaults are for convenience.
				where = f' -u {user}' if user and source != '[defaults]' else ''
				print(f'[!] Ignoring the default {tool} flags from {source} '
				      f'({" ".join(flags)}): {problem}.')
				print(f'    Change them with `achdiff flags set{where} {tool} ...`, '
				      f'or remove them with `achdiff flags clear{where} {tool}`.')
			else:
				args, ran = parsed, combined
				used = combined[:len(combined) - len(typed)]
				print(f'[*] Default flags from {source}: {" ".join(used) or "(all replaced)"}'
				      + (f'  (replaced by what you typed: {" ".join(dropped)})' if dropped else ''))

	if args.document:
		record = list(ran)
		if NO_DEFAULTS not in record:
			record.append(NO_DEFAULTS)
		if user and getattr(args, 'user', None) is None and '-u' in parser._option_string_actions:
			record += ['-u', user]
		document.write_run_file(parser, tool, module, argv=record,
		                        silent=bool(silent and silent(args)))
	return args
