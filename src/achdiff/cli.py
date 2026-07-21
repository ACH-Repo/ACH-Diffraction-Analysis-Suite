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

	prof = sub.add_parser('profile', help='Inspect saved per-person profiles.')
	prof_sub = prof.add_subparsers(dest='action', required=True)
	p_ls = prof_sub.add_parser('list', help='Show registered profiles and defaults.')
	p_ls.set_defaults(func=cmd_profile_list)

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
