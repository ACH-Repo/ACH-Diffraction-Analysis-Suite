"""Work out which person is running a tool.

Everyone shares one Windows login on the TOPAS PCs, so the OS cannot tell people
apart -- ``%APPDATA%`` is common to all of them. Identity therefore has to be
explicit. People already carry IDs as sample-name prefixes (``CN-sample1.xy``),
so the common case can be inferred from the files in the working directory.

Resolution order, first hit wins:

    1. -u / --user CN        explicit flag
    2. ACH_USER=CN           environment variable
    3. filename prefix       ONLY when it matches a registered profile
    4. None                  no profile; [defaults] applies

Why step 3 is guarded by the roster
-----------------------------------
The prefix pattern is roughly ``[A-Z]{2,3}-``, which also matches the material
names this lab works on every day::

    CN-sample1_pawley_01_X_Yobs.txt  ->  CN    a person
    ZIF-4_pawley_01_X_Yobs.txt       ->  ZIF   NOT a person
    MOF-5_ambient.xy                 ->  MOF   NOT a person
    MIL-101_run.xy                   ->  MIL   NOT a person

ZIF-4, ZIF-62 and ZIF-zni appear in the wizard's own trusted_params. Matching an
open-ended pattern would misread real data constantly, so a prefix is only
accepted when it is already a registered profile ID. An unknown prefix is never
adopted: the tools fall back to [defaults] and say so, rather than silently
loading someone else's CIF library.
"""

import os
import re
from glob import glob

from . import config

# Sample-name prefix: 2-3 capitals followed by a hyphen, at the start of the name.
PREFIX_RE = re.compile(r'^([A-Z]{2,3})-')

ENV_USER = 'ACH_USER'

# Extensions worth scanning for a prefix: raw data the tools consume, plus the
# TOPAS outputs they produce.
_SCAN_GLOBS = ('*.xy', '*.raw', '*.brml', '*.dat', '*.txt', '*.out', '*.inp')


def add_user_argument(parser):
	"""Attach the shared -u/--user flag. Verified free of collisions across all
	five tools before being chosen."""
	parser.add_argument('-u', '--user', default=None, metavar='ID',
	                    help='Person ID selecting a saved profile (e.g. CN). '
	                         'Defaults to ACH_USER, else inferred from the sample-name '
	                         'prefix of files here when it matches a registered profile.')
	parser.add_argument('--save-profile', action='store_true',
	                    help='Register/update the profile for -u with the settings '
	                         'given on this command line, then continue.')


def candidate_prefixes(directory='.'):
	"""Every distinct ``[A-Z]{2,3}-`` prefix among the data files in `directory`,
	in descending order of how many files carry it."""
	counts = {}
	for pattern in _SCAN_GLOBS:
		for path in glob(os.path.join(directory, pattern)):
			m = PREFIX_RE.match(os.path.basename(path))
			if m:
				counts[m.group(1)] = counts.get(m.group(1), 0) + 1
	return [p for p, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def infer_from_filenames(directory='.', known=None, cfg=None):
	"""The most common filename prefix that is a registered profile ID, or None.

	`known` overrides the roster (used by tests). Unregistered prefixes -- ZIF,
	MOF, MIL and friends -- are skipped, which is the whole point of the guard."""
	roster = set(config.profile_ids(cfg) if known is None else known)
	if not roster:
		return None
	for prefix in candidate_prefixes(directory):
		if prefix in roster:
			return prefix
	return None


def resolve(cli_user=None, directory='.', cfg=None, announce=True):
	"""Resolve the active profile ID. Returns (user_or_None, source_label).

	`source_label` names where the answer came from, so a tool can tell the user
	which profile it picked -- silent identity selection is how someone ends up
	fitting with the wrong CIF library and not noticing.
	"""
	cfg = config.load() if cfg is None else cfg
	roster = config.profile_ids(cfg)

	if cli_user:
		if roster and cli_user not in roster:
			# Not an error: --save-profile registers new IDs, and this is how a
			# first-time user gets one.
			return cli_user, 'command line (new profile)'
		return cli_user, 'command line'

	env_user = os.environ.get(ENV_USER)
	if env_user:
		return env_user, f'{ENV_USER} environment variable'

	inferred = infer_from_filenames(directory, cfg=cfg)
	if inferred:
		return inferred, 'sample-name prefix'

	return None, 'defaults (no profile)'


def describe(user, source):
	"""One-line summary for tools to print, so the choice is never invisible."""
	if user:
		return f'[*] Profile: {user}  (from {source})'
	return f'[*] Profile: none  (using [defaults])'
