"""Layered configuration for the suite.

Settings resolve in this order, first hit wins:

    CLI flag  >  environment variable  >  [profiles.<ID>]  >  [defaults]  >  built-in

The config file lives in the per-machine user config directory (on Windows,
``%APPDATA%\\ach-diffraction\\config.toml``), which is *outside* site-packages.
That placement is what makes ``pip install --upgrade`` unable to touch it -- the
guarantee is structural rather than a promise to be careful.

Every person on a shared TOPAS login writes to the same file; they are separated
by profile, not by Windows account. That is deliberate: one file holds the whole
roster, so `achdiff profile list` can show who is registered.

Profiles store *settings*. They can also store default *flags* per tool --
``[profiles.<ID>.flags]`` with ``pp = ['-d', '-c']`` -- which was once declined
here: a flag set by default can never be switched back off for a single run
without a ``--no-X`` counter-flag for every option. Default flags exist anyway,
because people wanted ``-d`` on every run, and the objection is answered with a
single ``--no-defaults`` that drops all of them for one run. See cmdline.py.
"""

import os
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
	import tomllib
else:  # 3.10 has no tomllib; tomli is the same API and a declared dependency
	try:
		import tomli as tomllib
	except ImportError:
		tomllib = None

APP_NAME = 'ach-diffraction'
CONFIG_FILENAME = 'config.toml'

# Settings the suite manages, mapped to the environment variable that overrides
# them. CIF_LOC keeps its historic name: the prefit tool has always honoured it
# and people's existing shells already set it.
ENV_OVERRIDES = {
	'cif_loc': 'CIF_LOC',
	'topas_exe': 'TOPAS_EXE',
}

# Built-in fallbacks, used when nothing else supplies a value.
BUILTIN_DEFAULTS = {
	'cif_loc': r'D:\Workfolder\<you>\CIF_LOC',
	# The refinement engine. Hardcoded to TOPAS 7 in the original wizard, which
	# breaks on any machine with a different version or install location -- the
	# same problem cif_loc had, so it gets the same treatment.
	'topas_exe': r'C:\TOPAS7\tc.exe',
	'qall': False,
}


def config_dir():
	"""Directory holding config.toml. Honours ACH_CONFIG_DIR so tests (and anyone
	wanting a portable install) can redirect it without touching the real one."""
	override = os.environ.get('ACH_CONFIG_DIR')
	if override:
		return Path(override)
	try:
		from platformdirs import user_config_dir
		return Path(user_config_dir(APP_NAME, appauthor=False))
	except ImportError:
		# platformdirs is a declared dependency, but a missing optional import
		# should not take the tools down -- fall back to the same location it
		# would have chosen on Windows.
		base = os.environ.get('APPDATA') or os.path.expanduser('~')
		return Path(base) / APP_NAME


def config_path():
	return config_dir() / CONFIG_FILENAME


def load():
	"""Read config.toml into a dict. Returns {} when absent or unreadable -- a
	broken config must never stop a plot from being drawn, so problems are
	reported and stepped over rather than raised."""
	path = config_path()
	if not path.exists():
		return {}
	if tomllib is None:
		# Should be unreachable: tomli is a declared dependency below 3.11. If it
		# is somehow missing, say so in terms of the consequence -- the tools keep
		# working but every saved setting is invisible, which is far more confusing
		# than an error.
		print(f'[!] No TOML parser available, so {path} cannot be read: your '
		      f'profiles, aliases and trusted parameters are being ignored.')
		print(f'    Fix with: pip install tomli')
		return {}
	try:
		with open(path, 'rb') as fh:
			return tomllib.load(fh)
	except Exception as e:
		print(f'[!] Ignoring unreadable config {path}: {e}')
		return {}


def profiles(cfg=None):
	"""The registered profile table: {ID: {setting: value}}."""
	cfg = load() if cfg is None else cfg
	table = cfg.get('profiles', {})
	return table if isinstance(table, dict) else {}


def profile_ids(cfg=None):
	"""Registered person IDs. This is the roster that guards prefix inference --
	an ID is only ever inferred from a filename if it appears here."""
	return sorted(profiles(cfg).keys())


def get(key, cli_value=None, user=None, cfg=None):
	"""Resolve one setting through the full precedence chain.

	`cli_value` is whatever the command line supplied (None when the flag was
	absent). `user` is the resolved profile ID, or None for no profile.
	"""
	if cli_value is not None:
		return cli_value

	env_name = ENV_OVERRIDES.get(key)
	if env_name:
		env_value = os.environ.get(env_name)
		if env_value:
			return env_value

	cfg = load() if cfg is None else cfg

	if user:
		prof = profiles(cfg).get(user, {})
		if key in prof:
			return prof[key]

	defaults = cfg.get('defaults', {})
	if isinstance(defaults, dict) and key in defaults:
		return defaults[key]

	return BUILTIN_DEFAULTS.get(key)


def _fmt_toml_key(key):
	"""A TOML table key. Bare keys allow only [A-Za-z0-9_-], which covers phase
	names like ZIF-4 and H2pPDA; anything else gets quoted."""
	key = str(key)
	if key and all(c.isalnum() or c in '_-' for c in key):
		return key
	return '"' + key.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _fmt_toml_value(value):
	if isinstance(value, bool):
		return 'true' if value else 'false'
	if isinstance(value, (int, float)):
		return str(value)
	if isinstance(value, (list, tuple)):
		return '[' + ', '.join(_fmt_toml_value(v) for v in value) + ']'

	# Single-quoted TOML literal strings need no backslash escaping, which is
	# exactly what Windows paths want. They cannot hold an apostrophe at all
	# though -- there is no escape for one inside a literal string, and doubling
	# it (the old behaviour) just ends the string early and leaves the rest as a
	# syntax error. A path like D:\Bob's data is not far-fetched, so a value with
	# an apostrophe falls back to a basic string with its backslashes doubled.
	text = str(value)
	if "'" not in text:
		return "'" + text + "'"
	return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def default_flags(tool, user=None, cfg=None):
	"""`tool`'s default flags as (list, source), or ([], None).

	A profile's list replaces [defaults]' rather than adding to it, so a person
	can opt out of a machine-wide default -- `achdiff flags set -u CN pp` with
	nothing after it stores an empty list that does exactly that."""
	cfg = load() if cfg is None else cfg
	if user:
		table = profiles(cfg).get(user, {}).get('flags', {})
		if isinstance(table, dict) and isinstance(table.get(tool), list):
			return [str(f) for f in table[tool]], f'profile {user}'
	table = cfg.get('defaults', {}).get('flags', {})
	if isinstance(table, dict) and isinstance(table.get(tool), list):
		return [str(f) for f in table[tool]], '[defaults]'
	return [], None


def save_default_flags(tool, flags, user=None):
	"""Store `flags` as `tool`'s defaults for `user`, or in [defaults] for
	everyone when `user` is None. `flags=None` removes the entry instead, which
	for a profile means falling back to [defaults] again. Returns the path."""
	cfg = load()
	scope = (cfg.setdefault('profiles', {}).setdefault(user, {}) if user
	         else cfg.setdefault('defaults', {}))
	table = scope.setdefault('flags', {})
	if flags is None:
		table.pop(tool, None)
	else:
		table[tool] = list(flags)
	if not table:
		scope.pop('flags')
	return write(cfg)


def trusted_params(user, cfg=None):
	"""Trusted starting cell parameters for `user`: {phase_name: {param: value}}.

	Deliberately **not** layered over a shared default set. A trusted parameter is
	an empirical result from one person's sample on one instrument, so inheriting
	somebody else's would silently seed a refinement with a cell that was never
	measured on your material. Without a profile you get none, which is the
	correct answer rather than a gap to fill in.
	"""
	if not user:
		return {}
	cfg = load() if cfg is None else cfg
	table = profiles(cfg).get(user, {}).get('trusted', {})
	return table if isinstance(table, dict) else {}


def save_trusted(user, phase, params, meta=None):
	"""Record `params` for `phase` under `user`, replacing any previous entry.

	Replacing rather than merging is deliberate: a cell is refined as a set, and
	mixing `a` from one fit with `c` from another produces a cell that was never
	actually observed.
	"""
	cfg = load()
	prof = cfg.setdefault('profiles', {}).setdefault(user, {})
	entry = dict(params)
	if meta:
		entry.update(meta)
	prof.setdefault('trusted', {})[phase] = entry
	return write(cfg)


def remove_trusted(user, phase):
	"""Drop one phase from `user`'s trusted set. Returns True if it existed."""
	cfg = load()
	table = cfg.get('profiles', {}).get(user, {}).get('trusted', {})
	if phase not in table:
		return False
	del table[phase]
	write(cfg)
	return True


def _is_readable(path):
	"""True if the file parses as TOML. Used to tell "no config yet" apart from
	"config we must not clobber"."""
	if tomllib is None:
		return False
	try:
		with open(path, 'rb') as fh:
			tomllib.load(fh)
		return True
	except Exception:
		return False


def write(cfg):
	"""Serialise the whole config back to disk. Returns the path written.

	The file is rewritten from a parsed copy rather than appended to, so repeated
	saves don't accumulate duplicate tables. Comments in the existing file are
	not preserved -- an accepted trade for not depending on a round-tripping TOML
	writer, and the file is machine-managed anyway.
	"""
	# A save must never quietly destroy a config it could not read. load() returns
	# {} for an unparseable file, so writing straight over it would drop every
	# profile the user had -- the exact moment their data matters most. Move the
	# broken file aside first; the rewrite then starts from a known-empty state
	# and the original is still recoverable by hand.
	path = config_path()
	if path.exists() and not _is_readable(path):
		import datetime
		stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
		salvage = path.with_suffix(f'.toml.corrupt-{stamp}')
		try:
			path.replace(salvage)
			print(f'[!] {path.name} could not be parsed; kept a copy at {salvage.name} '
			      f'before rewriting.')
		except OSError as e:
			print(f'[!] {path.name} is unreadable and could not be moved aside ({e}). '
			      f'Refusing to overwrite it.')
			return path

	lines = ['# ACH Diffraction Analysis Suite configuration.',
	         '# Managed by the tools; safe to hand-edit.',
	         '# Precedence: CLI flag > env var > [profiles.<ID>] > [defaults] > built-in.',
	         '']

	defaults = cfg.get('defaults', {})
	if defaults:
		_emit_table(lines, ['defaults'], defaults)

	aliases = cfg.get('aliases', {})
	if aliases:
		lines.append('# User-defined command shorthands, created by `achdiff alias set`.')
		_emit_table(lines, ['aliases'], aliases)

	for pid in sorted(cfg.get('profiles', {})):
		_emit_table(lines, ['profiles', _fmt_toml_key(pid)], cfg['profiles'][pid])

	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text('\n'.join(lines), encoding='utf-8')
	return path


def _emit_table(lines, path, table, force_header=True):
	"""Write `[path]` with its scalar keys, then recurse into its sub-tables.

	Generic rather than a fixed list of the tables the tools happen to write
	today. The old version emitted a profile's scalars and its `trusted` set and
	nothing else, which meant any other sub-table -- one added by hand, or by a
	later feature -- survived being read and then vanished at the next save,
	silently and at the moment the rest of the file was being preserved. A dict
	under [defaults] fared worse: it was passed to the value formatter and
	written out as a quoted Python repr.

	Scalars are emitted before any sub-table header, because a header opened
	above them would swallow every remaining plain key into itself -- that is how
	a profile's `cif_loc` would end up inside its trusted set.

	Sub-tables holding nothing are skipped. `trusted = {}` and no trusted table
	at all read back identically, so emitting a bare header for one would only
	leave `[profiles.CN.trusted]` behind forever after the last phase is removed.

	`force_header` keeps the top-level headers -- [defaults], [aliases],
	[profiles.<ID>] -- even when everything under them lives in a sub-table, so
	the roster stays readable at a glance. A purely intermediate table like
	`trusted` gets no header of its own: TOML infers it from the phase tables
	beneath, and printing it would add a bare line that says nothing.
	"""
	scalars = {k: v for k, v in table.items() if not isinstance(v, dict)}
	subtables = {k: v for k, v in table.items() if isinstance(v, dict)}

	if scalars or force_header or not subtables:
		lines.append('[' + '.'.join(path) + ']')
		for k, v in sorted(scalars.items()):
			lines.append(f'{_fmt_toml_key(k)} = {_fmt_toml_value(v)}')
		lines.append('')

	for k in sorted(subtables):
		if subtables[k]:
			_emit_table(lines, path + [_fmt_toml_key(k)], subtables[k],
			            force_header=False)


def save_profile(user, settings):
	"""Create or update [profiles.<user>] with `settings`, preserving everything
	else in the file. Returns the path written."""
	cfg = load()
	cfg.setdefault('profiles', {}).setdefault(user, {}).update(settings)
	return write(cfg)


def save_defaults(settings):
	"""Create or update [defaults] with `settings`. These apply to everyone who
	has no value of their own, so a shared machine can be set up once and used
	without -u. Returns the path written."""
	cfg = load()
	cfg.setdefault('defaults', {}).update(settings)
	return write(cfg)
