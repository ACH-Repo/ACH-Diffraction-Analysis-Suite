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

Profiles store *settings*, not command-line strings. A profile that set
``--qall`` as a flag could never be overridden back off for a single run without
inventing a ``--no-qall`` counter-flag for every such option; storing ``qall =
true`` as a value the tool reads as its default avoids that entire surface.
"""

import os
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
	import tomllib
else:  # 3.10 has no tomllib; tomli is the same API and a pymatgen dependency already
	try:
		import tomli as tomllib
	except ImportError:
		tomllib = None

APP_NAME = 'ach-diffraction'
CONFIG_FILENAME = 'config.toml'

# Settings the suite manages, mapped to the environment variable that overrides
# them. CIF_LOC keeps its historic name: pawley_prefit.py has always honoured it
# and people's existing shells already set it.
ENV_OVERRIDES = {
	'cif_loc': 'CIF_LOC',
}

# Built-in fallbacks, used when nothing else supplies a value.
BUILTIN_DEFAULTS = {
	'cif_loc': r'D:\Workfolder\<you>\CIF_LOC',
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
		print(f'[!] Cannot read {path}: no TOML parser available '
		      f'(Python < 3.11 needs `pip install tomli`). Using defaults.')
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


def _fmt_toml_value(value):
	if isinstance(value, bool):
		return 'true' if value else 'false'
	if isinstance(value, (int, float)):
		return str(value)
	# Single-quoted TOML literal strings need no backslash escaping, which is
	# exactly what Windows paths want.
	return "'" + str(value).replace("'", "''") + "'"


def save_profile(user, settings):
	"""Create or update [profiles.<user>] with `settings`, preserving everything
	else in the file. Returns the path written.

	The file is rewritten from a parsed copy rather than appended to, so repeated
	saves don't accumulate duplicate tables. Comments in the existing file are
	not preserved -- an accepted trade for not depending on a round-tripping TOML
	writer, and the file is machine-managed anyway.
	"""
	cfg = load()
	cfg.setdefault('profiles', {}).setdefault(user, {}).update(settings)

	lines = ['# ACH Diffraction Analysis Suite configuration.',
	         '# Managed by the tools; safe to hand-edit.',
	         '# Precedence: CLI flag > env var > [profiles.<ID>] > [defaults] > built-in.',
	         '']

	defaults = cfg.get('defaults', {})
	if defaults:
		lines.append('[defaults]')
		for k, v in sorted(defaults.items()):
			lines.append(f'{k} = {_fmt_toml_value(v)}')
		lines.append('')

	for pid in sorted(cfg.get('profiles', {})):
		lines.append(f'[profiles.{pid}]')
		for k, v in sorted(cfg['profiles'][pid].items()):
			lines.append(f'{k} = {_fmt_toml_value(v)}')
		lines.append('')

	path = config_path()
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text('\n'.join(lines), encoding='utf-8')
	return path
