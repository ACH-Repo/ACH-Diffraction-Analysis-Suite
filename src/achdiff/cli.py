"""The `achdiff` umbrella command: profiles, config inspection, and user aliases.

Why aliases need a command at all
---------------------------------
The short commands (pp, rp, pf, pt, pq, conv) are pip *entry points*: pip writes a
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

from . import cmdline, config, identity, styles

# Tool name -> module implementing it. The keys are what a user names when
# creating an alias; the built-in entry-point names are deliberately not used
# here, so renaming an entry point later doesn't invalidate saved aliases.
TOOLS = {
	'plotter':   'achdiff.tools.plotter',
	'wizard':    'achdiff.tools.wizard',
	'prefit':    'achdiff.tools.prefit',
	'tables':    'achdiff.tools.tables',
	'quickplot': 'achdiff.tools.quickplot',
	'convert':   'achdiff.tools.convert',
}

# Default entry points, shown by `achdiff alias list` for context.
BUILTIN_COMMANDS = {
	'pp': 'plotter',
	'rp': 'wizard',
	'pf': 'prefit',
	'pt': 'tables',
	'pq': 'quickplot',
	'conv': 'convert',
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


def _report_trusted_save(user, phase, params, previous):
	"""Print the saved cell, showing what each value replaced.

	Overwriting is the expected workflow -- you re-register a phase every time a
	better refinement lands -- so it needs no --force. But it does need to be
	visible: silently replacing numbers you will later seed refinements with is
	how a worse cell quietly becomes your starting point.
	"""
	verb = 'updated' if previous else 'registered'
	print(f'[+] {phase} {verb} for {user}:')
	old_cells = {k: v for k, v in (previous or {}).items() if k in PARAM_KEYS}
	for k in PARAM_KEYS:
		if k not in params:
			continue
		was = old_cells.get(k)
		if was is None:
			print(f'      {k:3} = {params[k]}')
		elif was == params[k]:
			print(f'      {k:3} = {params[k]}   (unchanged)')
		else:
			print(f'      {k:3} = {params[k]}   (was {was})')
	dropped = sorted(set(old_cells) - set(params))
	if dropped:
		print(f'    dropped: {", ".join(dropped)} '
		      f'(not present in the new refinement)')
	if previous and previous.get('source'):
		print(f'    replaces the set from {previous["source"]}'
		      f'{" on " + previous["registered"] if previous.get("registered") else ""}')


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
	previous = config.trusted_params(user).get(args.phase)
	meta = {'source': os.path.basename(args.source),
	        'registered': datetime.date.today().isoformat()}
	path = config.save_trusted(user, args.phase, params, meta)
	_report_trusted_save(user, args.phase, params, previous)
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
	previous = config.trusted_params(user).get(args.phase)
	path = config.save_trusted(user, args.phase, params,
	                           {'source': 'manual entry',
	                            'registered': datetime.date.today().isoformat()})
	_report_trusted_save(user, args.phase, params, previous)
	print(f'    -> {path}')
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
	# --global writes [defaults], which everyone falls back to, so it is the one
	# form that must not ask whose profile this is.
	if args.is_global:
		user = None
	else:
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
		# Registering the ID with nothing in it is a real thing to want. A profile
		# decides which CIF library AND which style sheet applies, and whether the
		# tools recognise this person's filenames at all -- someone who needs only
		# the last two should not have to invent a setting to get them. Not so for
		# --global, where an empty [defaults] would mean nothing at all.
		if args.is_global:
			print('[!] --global needs at least one setting, e.g. '
			      'cif_loc="D:\\path\\to\\CIFs"')
			return 1
		already = user in config.profile_ids()
		path = config.save_profile(user, {})
		if already:
			print(f'[+] Profile {user} was already registered; nothing changed.')
		else:
			print(f'[+] Registered profile {user} with no settings.')
			print('    Filename inference will recognise it now, and a style sheet')
			print('    filed under it applies without -u. Add settings any time:')
			print(f'      achdiff profile set -u {user} cif_loc="D:\\path\\to\\CIFs"')
		print(f'    -> {path}')
		return 0

	if user:
		path = config.save_profile(user, settings)
		print(f'[+] Profile {user} updated:')
	else:
		path = config.save_defaults(settings)
		print('[+] Global defaults updated (used by anyone without their own value):')
	for k, v in sorted(settings.items()):
		print(f'      {k} = {v!r}')
	print(f'    -> {path}')

	if 'cif_loc' in settings and not os.path.isdir(str(settings['cif_loc'])):
		print(f'[!] Note: {settings["cif_loc"]} is not a directory that exists right now.')
	return 0


def cmd_profile_unset(args):
	cfg = config.load()

	if args.is_global:
		user, table = None, cfg.get('defaults', {})
	else:
		user = _require_user(args)
		if not user:
			return 1
		table = cfg.get('profiles', {}).get(user, {})

	missing = [k for k in args.keys if k not in table]
	if missing:
		owner = 'The global defaults have' if user is None else f'{user} has'
		print(f'[!] {owner} no setting(s): {", ".join(missing)}')
		return 1
	for k in args.keys:
		del table[k]
	config.write(cfg)
	if user:
		print(f'[+] Removed {", ".join(args.keys)} from {user}; '
		      f'they fall back to defaults again.')
	else:
		print(f'[+] Removed {", ".join(args.keys)} from the global defaults; '
		      f'the built-in values apply again.')
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
		print(r'  achdiff profile set -u CN cif_loc="D:\path\to\your\CIFs"')
		print('Or set one library for everyone, so nobody needs -u:')
		print(r'  achdiff profile set --global cif_loc="D:\path\to\shared\CIFs"')
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


def _style_user(args):
	"""Whose style sheet a `style` subcommand acts on.

	Unlike trusted parameters, no profile is an answer rather than an error: the
	styles directory has a `default.toml` that applies to everyone, and setting a
	whole machine's look up once is a real use of it.
	"""
	user, _ = identity.resolve(args.user)
	return user


def cmd_style_path(args):
	user = _style_user(args)
	path = styles.style_path(args.tool, user)
	print(path)
	if not path.exists():
		who = f'profile {user}' if user else 'everyone (default.toml)'
		print(f'(no {args.tool} style for {who} yet; '
		      f'`achdiff style init {args.tool}` writes one)')
	return 0


def cmd_style_list(args):
	tools = [args.tool] if args.tool else list(styles.TOOLS)
	found = styles.available(args.tool)
	print(f'Styles: {styles.styles_root()}')
	roster = set(config.profile_ids())
	for tool in tools:
		print()
		print(f'{tool}  ({styles.styles_dir(tool)})')
		mine = [(stem, path) for t, stem, path in found if t == tool]
		if not mine:
			print('  none yet. Write a fully commented one with:')
			print(f'    achdiff style init {tool} -u CN     for one person')
			print(f'    achdiff style init {tool}           for everyone on this machine')
			continue
		for stem, path in mine:
			if stem == styles.DEFAULT_STYLE_STEM:
				note = 'applies to everyone, underneath any personal style'
			elif stem in roster:
				note = f'applies when -u resolves to {stem}'
			else:
				# Not an error -- a style may be written before its profile exists,
				# or be a one-off used with --style -- but it is the likeliest
				# reason a style "does nothing", so say it.
				note = (f'no profile {stem} is registered, so only --style {stem} '
				        f'reaches it')
			print(f'  {path.name:<16} {note}')
	return 0


def cmd_style_init(args):
	user = _style_user(args)
	path, created = styles.write_template(args.tool, user, force=args.force)
	if not created:
		print(f'[!] {path} already exists.')
		print('    Re-run with --force to replace it with a fresh template.')
		return 1
	who = f'profile {user}' if user else 'everyone without a style of their own'
	print(f'[+] Wrote a {args.tool} style sheet for {who}:')
	print(f'      {path}')
	print('    Every setting is listed at its current value and commented out, so')
	print('    nothing changes until you uncomment a line. Open it with:')
	print(f'      achdiff style edit {args.tool}' + (f' -u {user}' if user else ''))

	# A style is filed under a profile ID, but writing one does not create the
	# profile -- and without the profile, filename inference has no roster to
	# match against, so the style only ever applies when -u is typed out. That
	# reads exactly like the style being ignored, so say it here rather than
	# leaving it to be discovered.
	if user and user not in config.profile_ids():
		print()
		print(f'[!] No profile {user} is registered yet, so the tools will only use')
		print(f'    this style when you pass -u {user} explicitly. To have it picked')
		print(f'    up from your sample-name prefixes as well, register the ID:')
		print(f'      achdiff profile set -u {user}')
	return 0


def cmd_style_install(args):
	"""Put a style file someone sent you where the tools will find it."""
	source = Path(args.file)
	if not source.is_file():
		print(f'[!] No such file: {source}')
		return 1

	user = _style_user(args)
	target = styles.style_path(args.tool, user)

	if target.exists() and source.resolve() == target.resolve():
		print(f'[+] {target} is already this file.')
		return 0

	# Check before copying, not after: a file that would have been ignored at
	# plot time is much easier to think about while it is still the thing you
	# just typed the name of.
	good, unknown, invalid = styles.validate(args.tool, source)
	for name, reason in invalid:
		print(f'[!] {source.name}: {name} -- {reason}.')
	if unknown:
		styles.report_unknown(args.tool, source.name, unknown)
	if not good and (unknown or invalid):
		print('[!] Nothing in this file would be applied. Not installing it.')
		return 1

	if target.exists() and not args.force:
		print(f'[!] {target} already exists.')
		print('    Re-run with --force to replace it. Keep a copy first if you have')
		print('    edited it -- the replacement is not merged with what is there.')
		return 1

	target.parent.mkdir(parents=True, exist_ok=True)
	shutil.copyfile(str(source), str(target))

	who = f'profile {user}' if user else 'everyone without a style of their own'
	print(f'[+] Installed {source.name} as the {args.tool} style for {who}:')
	print(f'      {target}')
	print(f'    {len(good)} setting(s) will be applied.')

	if user and user not in config.profile_ids():
		print()
		print(f'[!] No profile {user} is registered yet, so this style is only used')
		print(f'    when you pass -u {user} explicitly. To have it picked up from')
		print(f'    your sample-name prefixes as well, register the ID:')
		print(f'      achdiff profile set -u {user}')
	return 0


def cmd_style_edit(args):
	user = _style_user(args)
	path, created = styles.write_template(args.tool, user, force=False)
	if created:
		print(f'[+] Created {path}')

	# EDITOR/VISUAL first: someone who has set one means it. Otherwise hand the
	# file to whatever the desktop opens .toml with, which on these machines is
	# Notepad and is exactly what a lab user expects a double-click to do.
	editor = os.environ.get('VISUAL') or os.environ.get('EDITOR')
	try:
		if editor:
			import shlex
			import subprocess
			# EDITOR routinely carries flags ("code -w"), so it is a command line
			# rather than a filename. posix=False on Windows keeps the backslashes
			# in C:\Program Files\... from being read as escapes; the quotes it
			# leaves behind around a spaced path are stripped after the split.
			parts = [p.strip('"') for p in shlex.split(editor, posix=(os.name != 'nt'))]
			return subprocess.call(parts + [str(path)])
		if hasattr(os, 'startfile'):
			os.startfile(str(path))       # Windows only
			return 0
		import subprocess
		return subprocess.call(['xdg-open' if sys.platform != 'darwin' else 'open',
		                        str(path)])
	except Exception as e:
		print(f'[!] Could not open an editor ({e}). The file is at:')
		print(f'      {path}')
		return 1


def _flags_scope(args):
	"""Whose default flags a `flags` subcommand acts on: (user, label).

	user is None for --global. Returns (False, None) when nobody was named, since
	writing to [defaults] by accident would change everyone's runs."""
	if getattr(args, 'is_global', False):
		return None, '[defaults], for everyone without their own'
	user, source = identity.resolve(args.user)
	if not user:
		print('[!] No profile selected. Pass -u ID for one person, or --global for '
		      'everyone on this machine.')
		return False, None
	if source != 'command line':
		print(identity.describe(user, source))
	return user, f'profile {user}'


def cmd_flags_show(args):
	user, source = identity.resolve(args.user)
	print(identity.describe(user, source))
	print()
	width = max(len(t) for t in cmdline.TOOL_MODULES)
	for tool in cmdline.TOOL_MODULES:
		flags, where = cmdline.default_flags(tool, user)
		if flags:
			print(f'  {tool:<{width}}  {" ".join(flags):<40} ({where})')
		else:
			print(f'  {tool:<{width}}  (none)')
	print()
	print('Set with e.g.  achdiff flags set -u CN pp -d -c')
	print('Skip for one run with --no-defaults.')
	return 0


def cmd_flags_set(args):
	# The flags first: `flags set pp -u CN -d` puts -u among them, and saying
	# where it belongs beats "no profile selected".
	problem = cmdline.check_defaults(args.tool, args.flags)
	if problem:
		print(f'[!] Not saved. {args.tool} {" ".join(args.flags)}: {problem}')
		return 1
	user, label = _flags_scope(args)
	if user is False:
		return 1
	config.save_default_flags(args.tool, args.flags, user=user)
	if args.flags:
		print(f'[+] Default {args.tool} flags for {label}: {" ".join(args.flags)}')
		print(f'    Every {args.tool} run now starts with these. Flags you type come after')
		print(f'    them and win; `{args.tool} --no-defaults` skips them for one run.')
	elif user:
		print(f'[+] {label} now has no default {args.tool} flags, even where [defaults] '
		      f'sets some.')
	else:
		print(f'[+] [defaults] now sets no {args.tool} flags.')
	return 0


def cmd_flags_clear(args):
	user, label = _flags_scope(args)
	if user is False:
		return 1
	config.save_default_flags(args.tool, None, user=user)
	print(f'[+] Removed the default {args.tool} flags of {label}.')
	if user:
		flags, where = cmdline.default_flags(args.tool, user)
		if flags:
			print(f'    {args.tool} now starts with {" ".join(flags)} from {where}.')
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
		'set', help='Register or update settings for a person, or for everyone.'))
	p_set.add_argument('assignments', nargs='*', metavar='KEY=VALUE',
	                   help='e.g. cif_loc="D:\\Workfolder\\you\\CIF_LOC" qall=true. '
	                        'With none, the ID is simply registered -- which is all '
	                        'that filename inference and a style sheet need.')
	p_set.add_argument('--global', dest='is_global', action='store_true',
	                   help='Write [defaults] instead of one person\'s profile: the '
	                        'value everyone gets without passing -u. A profile that '
	                        'sets the same key still wins for that person.')
	p_set.set_defaults(func=cmd_profile_set)

	p_unset = _with_user(prof_sub.add_parser(
		'unset', help='Drop settings so they fall back to defaults.'))
	p_unset.add_argument('keys', nargs='+', metavar='KEY')
	p_unset.add_argument('--global', dest='is_global', action='store_true',
	                     help='Drop from [defaults] rather than from a person.')
	p_unset.set_defaults(func=cmd_profile_unset)

	st = sub.add_parser('style', help='Your own plot style for pp and pq.',
	                    description='Style sheets are TOML files kept beside config.toml, '
	                                'one per person and per plotter, and are never touched '
	                                'by an upgrade. A pp sheet never affects pq, nor the '
	                                'other way round. Precedence, for pp: --style FILE > '
	                                'ACH_STYLE_PP > styles/pp/<ID>.toml > '
	                                'styles/pp/default.toml > built-in; likewise for pq.')
	st_sub = st.add_subparsers(dest='action', required=True)

	def _with_style_user(p):
		# TOOL comes first, so `style install pq FILE` reads in the order typed.
		p.add_argument('tool', choices=sorted(styles.TOOLS),
		               help='The plotter whose style sheet this is: pp or pq.')
		p.add_argument('-u', '--user', default=None, metavar='ID',
		               help='Whose style to act on. Without it, the shared '
		                    'default.toml that applies to everyone.')
		return p

	s_ls = st_sub.add_parser('list', help='Show the style sheets on this machine.')
	s_ls.add_argument('tool', nargs='?', choices=sorted(styles.TOOLS),
	                  help="Only this plotter's sheets: pp or pq. Default: both.")
	s_ls.set_defaults(func=cmd_style_list)

	s_path = _with_style_user(st_sub.add_parser('path', help='Print a style file path.'))
	s_path.set_defaults(func=cmd_style_path)

	s_init = _with_style_user(st_sub.add_parser(
		'init', help='Write a commented style sheet listing every setting.'))
	s_init.add_argument('--force', action='store_true',
	                    help='Replace an existing style sheet with a fresh template. '
	                         'This discards whatever you had changed in it.')
	s_init.set_defaults(func=cmd_style_init)

	s_inst = _with_style_user(st_sub.add_parser(
		'install', help='Install a style file someone sent you.'))
	s_inst.add_argument('file', metavar='FILE', help='The .toml file to install.')
	s_inst.add_argument('--force', action='store_true',
	                    help='Replace an existing style sheet. The replacement is not '
	                         'merged with it, so keep a copy if you have edited yours.')
	s_inst.set_defaults(func=cmd_style_install)

	s_edit = _with_style_user(st_sub.add_parser(
		'edit', help='Open a style sheet, creating it first if needed.'))
	s_edit.set_defaults(func=cmd_style_edit)

	fl = sub.add_parser('flags', help='Flags a tool starts every run with.',
	                    description='Default flags per tool, stored in your profile -- '
	                                'e.g. -d on every pp run. Flags you type come after '
	                                'them and win; --no-defaults skips them for one run. '
	                                'A -d record writes them out in full, so an old run '
	                                'file never changes when your defaults do.')
	fl_sub = fl.add_subparsers(dest='action', required=True)

	def _with_flags_scope(p):
		p.add_argument('-u', '--user', default=None, metavar='ID',
		               help='Whose defaults. Must come before TOOL.')
		p.add_argument('--global', dest='is_global', action='store_true',
		               help='The [defaults] everyone without their own falls back to.')
		p.add_argument('tool', choices=list(cmdline.TOOL_MODULES), metavar='TOOL',
		               help='pp, pq, pf, pt, rp or conv.')
		return p

	f_show = fl_sub.add_parser('show', help="Show each tool's default flags.")
	f_show.add_argument('-u', '--user', default=None, metavar='ID',
	                    help='Whose defaults to show.')
	f_show.set_defaults(func=cmd_flags_show)

	f_set = _with_flags_scope(fl_sub.add_parser(
		'set', help='Set the flags a tool starts with.',
		usage='achdiff flags set [-u ID | --global] TOOL [FLAG ...]'))
	# REMAINDER, so `-d` after the tool name is taken as one of the flags rather
	# than as an option of this command.
	f_set.add_argument('flags', nargs=argparse.REMAINDER, metavar='FLAG',
	                   help='The flags, exactly as you would type them after the tool. '
	                        'None at all stores an empty set, which opts a profile out '
	                        'of [defaults].')
	f_set.set_defaults(func=cmd_flags_set)

	f_clear = _with_flags_scope(fl_sub.add_parser(
		'clear', help="Remove a tool's default flags."))
	f_clear.set_defaults(func=cmd_flags_clear)

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
