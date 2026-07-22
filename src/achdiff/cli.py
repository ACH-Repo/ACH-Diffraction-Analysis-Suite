"""The `achdiff` umbrella command: profiles, config inspection, and user aliases.

Why aliases need a command at all
---------------------------------
The five short commands (pp, rp, pf, pt, pq) are pip *entry points*: pip writes a
real executable into the environment's Scripts directory at install time. Nothing
in a config file can rename them afterwards, because the shell needs an actual
file on PATH to find.

So a user-chosen shorthand has to be a *new* file. `achdiff alias set` writes one
-- a .cmd on Windows, a shell script elsewhere -- next to the entry points, and
records it in config.toml. The record is what makes `achdiff alias sync` able to
recreate them, since a reinstall can clear the Scripts directory while the config
(living outside site-packages) survives.
"""

import argparse
import os
import shutil
import stat
import sys
import sysconfig
from pathlib import Path

from . import config

# Tool name -> module implementing it. The keys are what a user names when
# creating an alias; the built-in entry-point names are deliberately not used
# here, so renaming an entry point later doesn't invalidate saved aliases.
TOOLS = {
	'plotter':   'achdiff.tools.plotter',
	'wizard':    'achdiff.tools.wizard',
	'prefit':    'achdiff.tools.prefit',
	'tables':    'achdiff.tools.tables',
	'quickplot': 'achdiff.tools.quickplot',
}

# Default entry points, shown by `achdiff alias list` for context.
BUILTIN_COMMANDS = {
	'pp': 'plotter',
	'rp': 'wizard',
	'pf': 'prefit',
	'pt': 'tables',
	'pq': 'quickplot',
}

RESERVED = set(BUILTIN_COMMANDS) | {'achdiff'}


def scripts_dir():
	"""Directory holding the console entry points -- where a new alias must land
	to be found on PATH.

	Resolution order matters: `sysconfig.get_path('scripts')` returns the *system*
	Scripts directory, which for a `pip install --user` is both the wrong place
	and usually unwritable (C:\\Program Files\\...). Locating an entry point that
	pip actually installed is the only reliable way to find where this install
	put its commands.
	"""
	# 1. Where an existing entry point actually lives.
	for probe in ('achdiff', *BUILTIN_COMMANDS):
		found = shutil.which(probe)
		if found:
			return Path(found).parent

	# 2. The user scheme, which is where `pip install --user` writes.
	try:
		user_path = sysconfig.get_path('scripts', f'{os.name}_user')
		if user_path and Path(user_path).is_dir():
			return Path(user_path)
	except (KeyError, ValueError):
		pass

	# 3. The system scheme, correct for venvs and system-wide installs.
	path = sysconfig.get_path('scripts')
	if path and Path(path).is_dir():
		return Path(path)
	return Path(sys.executable).parent


def _alias_file(name):
	suffix = '.cmd' if os.name == 'nt' else ''
	return scripts_dir() / f'{name}{suffix}'


def _write_shim(name, tool):
	"""Create the executable shim for `name` -> `tool`. Returns the path."""
	module = TOOLS[tool]
	target = _alias_file(name)
	if os.name == 'nt':
		# %* forwards all arguments. The interpreter is spelled out so the alias
		# keeps working if a different python later comes first on PATH.
		# ACHDIFF_PROG makes --help say `usage: <alias>` instead of the module
		# filename, which is what `python -m` would otherwise produce.
		body = (f'@echo off\r\n'
		        f'set ACHDIFF_PROG={name}\r\n'
		        f'"{sys.executable}" -m {module} %*\r\n')
		target.write_text(body, encoding='utf-8')
	else:
		body = (f'#!/bin/sh\n'
		        f'ACHDIFF_PROG={name} exec "{sys.executable}" -m {module} "$@"\n')
		target.write_text(body, encoding='utf-8')
		target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
	return target


def _save_aliases(aliases):
	"""Persist the [aliases] table, leaving profiles and defaults untouched."""
	cfg = config.load()
	cfg['aliases'] = aliases
	config.write(cfg)


def cmd_alias_set(args):
	name, tool = args.name, args.tool
	if tool not in TOOLS:
		print(f'[!] Unknown tool {tool!r}. Choose from: {", ".join(sorted(TOOLS))}')
		return 1
	if name in RESERVED:
		print(f'[!] {name!r} is a built-in command; pick a different alias name.')
		return 1
	if not name.replace('_', '').replace('-', '').isalnum():
		print(f'[!] {name!r} is not a usable command name (letters, digits, - and _ only).')
		return 1

	existing = _alias_file(name)
	aliases = config.load().get('aliases', {})
	if existing.exists() and name not in aliases:
		print(f'[!] {existing} already exists and was not created by achdiff. '
		      f'Refusing to overwrite it.')
		return 1

	try:
		path = _write_shim(name, tool)
	except OSError as e:
		print(f'[!] Could not write {_alias_file(name)}: {e}')
		print('    (If the environment is not writable, install with --user or use a venv.)')
		return 1

	aliases[name] = tool
	_save_aliases(aliases)
	print(f'[+] {name} -> {tool}   ({path})')
	if not _on_path(path.parent):
		print(f'[!] {path.parent} is not on PATH, so `{name}` will not be found. '
		      f'Add it, or use the built-in commands.')
	return 0


def cmd_alias_remove(args):
	aliases = config.load().get('aliases', {})
	if args.name not in aliases:
		print(f'[!] No alias named {args.name!r}. `achdiff alias list` shows the current set.')
		return 1
	path = _alias_file(args.name)
	try:
		if path.exists():
			path.unlink()
	except OSError as e:
		print(f'[!] Could not remove {path}: {e}')
		return 1
	del aliases[args.name]
	_save_aliases(aliases)
	print(f'[+] Removed alias {args.name}')
	return 0


def cmd_alias_list(args):
	aliases = config.load().get('aliases', {})
	print('Built-in commands (fixed at install time):')
	for name, tool in sorted(BUILTIN_COMMANDS.items()):
		print(f'  {name:10} -> {tool}')
	print()
	if not aliases:
		print('No user aliases. Create one with:')
		print('  achdiff alias set <name> <tool>')
		return 0
	print('Your aliases:')
	for name, tool in sorted(aliases.items()):
		mark = '' if _alias_file(name).exists() else '   [missing -- run `achdiff alias sync`]'
		print(f'  {name:10} -> {tool}{mark}')
	return 0


def cmd_alias_sync(args):
	"""Recreate every recorded alias. Needed after a reinstall, which can clear
	the Scripts directory while the config survives."""
	aliases = config.load().get('aliases', {})
	if not aliases:
		print('No aliases recorded; nothing to sync.')
		return 0
	made = 0
	for name, tool in sorted(aliases.items()):
		if tool not in TOOLS:
			print(f'[!] Skipping {name}: unknown tool {tool!r}')
			continue
		try:
			_write_shim(name, tool)
			made += 1
		except OSError as e:
			print(f'[!] {name}: {e}')
	print(f'[+] Recreated {made} alias(es) in {scripts_dir()}')
	return 0


PARAM_KEYS = ('a', 'b', 'c', 'al', 'be', 'ga')


def _require_user(args):
	"""Trusted sets are per person, so a command touching one must know whose.
	Falls back to the usual inference, but never guesses silently."""
	from . import identity
	user, source = identity.resolve(getattr(args, 'user', None))
	if not user:
		print('[!] No profile selected, and trusted parameters are always per person.')
		print('    Pass -u ID, set ACH_USER, or run from a directory of your own samples.')
		return None
	if source != 'command line':
		print(identity.describe(user, source))
	return user


def cmd_trusted_list(args):
	user = _require_user(args)
	if not user:
		return 1
	table = config.trusted_params(user)
	if not table:
		print(f'No trusted parameters registered for {user}.')
		print('  achdiff trusted add <phase> --from <fit>.out')
		return 0
	print(f'Trusted starting parameters for {user}:')
	for phase in sorted(table):
		entry = table[phase]
		cells = {k: v for k, v in entry.items() if k in PARAM_KEYS}
		print(f'  {phase}')
		for k in PARAM_KEYS:
			if k in cells:
				print(f'      {k:3} = {cells[k]}')
		src, when = entry.get('source'), entry.get('registered')
		if src or when:
			print(f'      from {src or "?"}{"  on " + when if when else ""}')
	return 0


def cmd_trusted_add(args):
	"""Harvest a phase's refined cell out of a .out file."""
	from .core import topas

	user = _require_user(args)
	if not user:
		return 1

	phases = topas.parse_phases(args.source)
	if not phases:
		print(f'[!] No cell parameters found in {args.source}. '
		      f'Is it a TOPAS .out from a completed refinement?')
		return 1

	if len(phases) > 1 and args.phase_index is None:
		print(f'{args.source} contains {len(phases)} phases:')
		for i, ph in enumerate(phases, 1):
			free = topas.free_params(ph['system'], ph['params'])
			desc = ', '.join(f'{k}={topas.clean_value(v)}' for k, v in free.items())
			print(f'  [{i}] {ph["system"] or "?"}  sg={ph["space_group"] or "?"}  {desc}')
		print('Re-run with --phase-index N to say which one to register.')
		return 1

	idx = (args.phase_index or 1) - 1
	if not 0 <= idx < len(phases):
		print(f'[!] --phase-index {args.phase_index} is out of range (1..{len(phases)}).')
		return 1

	ph = phases[idx]
	free = topas.free_params(ph['system'], ph['params'])
	params = {k: topas.clean_value(v) for k, v in free.items()}
	if not params:
		print(f'[!] Phase {idx + 1} of {args.source} declares no cell parameters.')
		return 1

	import datetime
	meta = {'source': os.path.basename(args.source),
	        'registered': datetime.date.today().isoformat()}
	path = config.save_trusted(user, args.phase, params, meta)
	print(f'[+] {args.phase} registered for {user}:')
	for k, v in params.items():
		print(f'      {k:3} = {v}')
	print(f'    -> {path}')
	return 0


def cmd_trusted_set(args):
	"""Enter values by hand, for a fit whose .out is long gone."""
	user = _require_user(args)
	if not user:
		return 1
	params = {}
	for item in args.assignments:
		if '=' not in item:
			print(f'[!] Expected key=value, got {item!r}.')
			return 1
		k, v = item.split('=', 1)
		k = k.strip()
		if k not in PARAM_KEYS:
			print(f'[!] Unknown parameter {k!r}. Use one of: {", ".join(PARAM_KEYS)}')
			return 1
		params[k] = v.strip()
	if not params:
		print('[!] Give at least one parameter, e.g. a=15.484356`_0.000738')
		return 1
	import datetime
	path = config.save_trusted(user, args.phase, params,
	                           {'source': 'manual entry',
	                            'registered': datetime.date.today().isoformat()})
	print(f'[+] {args.phase} registered for {user} -> {path}')
	return 0


def cmd_trusted_remove(args):
	user = _require_user(args)
	if not user:
		return 1
	if config.remove_trusted(user, args.phase):
		print(f'[+] Removed {args.phase} from {user}.')
		return 0
	print(f'[!] {user} has no trusted entry for {args.phase!r}.')
	return 1


def cmd_trusted_export(args):
	"""Write a shareable TOML file. Handing a colleague your starting cells is a
	normal thing to want; it stays an explicit act rather than shared storage."""
	user = _require_user(args)
	if not user:
		return 1
	table = config.trusted_params(user)
	if not table:
		print(f'Nothing to export: {user} has no trusted parameters.')
		return 1
	lines = [f'# Trusted starting cell parameters exported from profile {user}.',
	         f'# Import with: achdiff trusted import <file> -u <your-id>', '']
	for phase in sorted(table):
		lines.append(f'[{config._fmt_toml_key(phase)}]')
		for k, v in sorted(table[phase].items()):
			lines.append(f'{k} = {config._fmt_toml_value(v)}')
		lines.append('')
	text = '\n'.join(lines)
	if args.output:
		Path(args.output).write_text(text, encoding='utf-8')
		print(f'[+] Exported {len(table)} phase(s) to {args.output}')
	else:
		print(text)
	return 0


def cmd_trusted_import(args):
	user = _require_user(args)
	if not user:
		return 1
	path = Path(args.file)
	if not path.is_file():
		print(f'[!] No such file: {path}')
		return 1
	if config.tomllib is None:
		print('[!] No TOML parser available (Python < 3.11 needs `pip install tomli`).')
		return 1
	try:
		with open(path, 'rb') as fh:
			data = config.tomllib.load(fh)
	except Exception as e:
		print(f'[!] Could not parse {path}: {e}')
		return 1

	incoming = {k: v for k, v in data.items() if isinstance(v, dict)}
	if not incoming:
		print(f'[!] {path} has no phase tables. Expected e.g. [ZIF-4] with a/b/c keys.')
		return 1

	existing = config.trusted_params(user)
	clashes = sorted(set(incoming) & set(existing))
	if clashes and not args.force:
		print(f'[!] Already registered for {user}: {", ".join(clashes)}')
		print('    Re-run with --force to overwrite, or remove them first.')
		return 1

	for phase, params in sorted(incoming.items()):
		config.save_trusted(user, phase, params)
	print(f'[+] Imported {len(incoming)} phase(s) into {user}: {", ".join(sorted(incoming))}')
	return 0


def _coerce(key, raw):
	"""Convert a KEY=VALUE string to the type the setting actually uses.

	Typed from the built-in default, so `qall=true` stores a boolean rather than
	the string "true" -- which would be truthy either way, but would also make
	`qall=false` switch the option *on*.
	"""
	default = config.BUILTIN_DEFAULTS.get(key)
	if isinstance(default, bool):
		low = raw.strip().lower()
		if low in ('true', 'yes', 'on', '1'):
			return True
		if low in ('false', 'no', 'off', '0'):
			return False
		raise ValueError(f'{key} is a true/false setting; got {raw!r}')
	if isinstance(default, int) and not isinstance(default, bool):
		return int(raw)
	return raw


def cmd_profile_set(args):
	user = _require_user(args)
	if not user:
		return 1

	known = sorted(config.BUILTIN_DEFAULTS)
	settings = {}
	for item in args.assignments:
		if '=' not in item:
			print(f'[!] Expected key=value, got {item!r}.')
			return 1
		key, raw = item.split('=', 1)
		key = key.strip()
		# Unknown keys are rejected rather than stored: a typo that silently sits
		# in the config, never read by anything, is worse than an error here.
		if key not in config.BUILTIN_DEFAULTS:
			print(f'[!] Unknown setting {key!r}. Known settings: {", ".join(known)}')
			return 1
		try:
			settings[key] = _coerce(key, raw)
		except ValueError as e:
			print(f'[!] {e}')
			return 1

	if not settings:
		print(f'[!] Give at least one setting, e.g. cif_loc="D:\\path\\to\\CIFs"')
		return 1

	path = config.save_profile(user, settings)
	print(f'[+] Profile {user} updated:')
	for k, v in sorted(settings.items()):
		print(f'      {k} = {v!r}')
	print(f'    -> {path}')

	if 'cif_loc' in settings and not os.path.isdir(str(settings['cif_loc'])):
		print(f'[!] Note: {settings["cif_loc"]} is not a directory that exists right now.')
	return 0


def cmd_profile_unset(args):
	user = _require_user(args)
	if not user:
		return 1
	cfg = config.load()
	prof = cfg.get('profiles', {}).get(user, {})
	missing = [k for k in args.keys if k not in prof]
	if missing:
		print(f'[!] {user} has no setting(s): {", ".join(missing)}')
		return 1
	for k in args.keys:
		del prof[k]
	config.write(cfg)
	print(f'[+] Removed {", ".join(args.keys)} from {user}; '
	      f'they fall back to defaults again.')
	return 0


def cmd_profile_list(args):
	cfg = config.load()
	ids = config.profile_ids(cfg)
	print(f'Config: {config.config_path()}')
	print()
	defaults = cfg.get('defaults', {})
	if defaults:
		print('[defaults]')
		for k, v in sorted(defaults.items()):
			print(f'  {k} = {v!r}')
		print()
	if not ids:
		print('No profiles registered. Register one with, e.g.:')
		print(r'  pp -u CN --cif-loc "D:\path\to\your\CIFs" --save-profile')
		return 0
	print('Registered profiles (these are the IDs that filename inference will match):')
	for pid in ids:
		print(f'  [{pid}]')
		for k, v in sorted(config.profiles(cfg)[pid].items()):
			print(f'      {k} = {v!r}')
	return 0


def cmd_config_path(args):
	path = config.config_path()
	print(path)
	if not path.exists():
		print('(does not exist yet; it is created when you first save a profile or alias)')
	return 0


def _on_path(directory):
	entries = os.environ.get('PATH', '').split(os.pathsep)
	directory = str(directory).rstrip('\\/').lower()
	return any(e.rstrip('\\/').lower() == directory for e in entries if e)


def _build_parser():
	p = argparse.ArgumentParser(
		prog='achdiff',
		description='Manage profiles, config and command aliases for the diffraction suite.')
	sub = p.add_subparsers(dest='group', required=True)

	alias = sub.add_parser('alias', help='Create your own short command names.')
	alias_sub = alias.add_subparsers(dest='action', required=True)

	a_set = alias_sub.add_parser('set', help='Create or update an alias.')
	a_set.add_argument('name', help='The command name you want to type.')
	a_set.add_argument('tool', help=f'Which tool it runs: {", ".join(sorted(TOOLS))}.')
	a_set.set_defaults(func=cmd_alias_set)

	a_rm = alias_sub.add_parser('remove', help='Delete an alias.')
	a_rm.add_argument('name')
	a_rm.set_defaults(func=cmd_alias_remove)

	a_ls = alias_sub.add_parser('list', help='Show built-in commands and your aliases.')
	a_ls.set_defaults(func=cmd_alias_list)

	a_sync = alias_sub.add_parser('sync', help='Recreate aliases after a reinstall.')
	a_sync.set_defaults(func=cmd_alias_sync)

	tr = sub.add_parser('trusted', help='Your trusted starting cell parameters.')
	tr_sub = tr.add_subparsers(dest='action', required=True)

	def _with_user(p):
		"""-u goes on each leaf, not the `trusted` parser: attached to the parent it
		would have to precede the subcommand (`trusted -u CN add ...`), which is not
		where anyone types it."""
		p.add_argument('-u', '--user', default=None, metavar='ID',
		               help='Whose set to act on. Defaults to ACH_USER, else the '
		                    'sample-name prefix of files here.')
		return p

	t_ls = _with_user(tr_sub.add_parser('list', help='Show your registered phases.'))
	t_ls.set_defaults(func=cmd_trusted_list)

	t_add = _with_user(tr_sub.add_parser('add', help='Harvest a refined cell from a .out file.'))
	t_add.add_argument('phase', help='Phase name, matching the CIF stem the wizard will look up.')
	t_add.add_argument('--from', dest='source', required=True, metavar='OUT',
	                   help='A TOPAS .out from a converged refinement.')
	t_add.add_argument('--phase-index', type=int, default=None, metavar='N',
	                   help='Which phase in a multi-phase .out (1-based).')
	t_add.set_defaults(func=cmd_trusted_add)

	t_set = _with_user(tr_sub.add_parser('set', help='Enter parameters by hand.'))
	t_set.add_argument('phase')
	t_set.add_argument('assignments', nargs='+', metavar='KEY=VALUE',
	                   help="e.g. a=15.484356`_0.000738 b=15.511304`_0.000704")
	t_set.set_defaults(func=cmd_trusted_set)

	t_rm = _with_user(tr_sub.add_parser('remove', help='Forget a phase.'))
	t_rm.add_argument('phase')
	t_rm.set_defaults(func=cmd_trusted_remove)

	t_ex = _with_user(tr_sub.add_parser('export', help='Write a shareable TOML file.'))
	t_ex.add_argument('-o', '--output', default=None, metavar='FILE',
	                  help='Write here instead of printing to the terminal.')
	t_ex.set_defaults(func=cmd_trusted_export)

	t_im = _with_user(tr_sub.add_parser('import', help='Load a set exported by a colleague.'))
	t_im.add_argument('file')
	t_im.add_argument('--force', action='store_true',
	                  help='Overwrite phases you already have registered.')
	t_im.set_defaults(func=cmd_trusted_import)

	prof = sub.add_parser('profile', help='Inspect and edit per-person profiles.')
	prof_sub = prof.add_subparsers(dest='action', required=True)

	p_ls = prof_sub.add_parser('list', help='Show registered profiles and defaults.')
	p_ls.set_defaults(func=cmd_profile_list)

	p_set = _with_user(prof_sub.add_parser(
		'set', help='Register or update settings for a person.'))
	p_set.add_argument('assignments', nargs='+', metavar='KEY=VALUE',
	                   help='e.g. cif_loc="D:\\Workfolder\\you\\CIF_LOC" qall=true')
	p_set.set_defaults(func=cmd_profile_set)

	p_unset = _with_user(prof_sub.add_parser(
		'unset', help='Drop settings so they fall back to defaults.'))
	p_unset.add_argument('keys', nargs='+', metavar='KEY')
	p_unset.set_defaults(func=cmd_profile_unset)

	conf = sub.add_parser('config', help='Locate the configuration file.')
	conf_sub = conf.add_subparsers(dest='action', required=True)
	c_path = conf_sub.add_parser('path', help='Print the config file path.')
	c_path.set_defaults(func=cmd_config_path)

	return p


def main():
	args = _build_parser().parse_args()
	return args.func(args)


if __name__ == '__main__':
	sys.exit(main() or 0)
