"""Assertions for the config and identity layer.

Run: python tests/test_config_identity.py
Uses ACH_CONFIG_DIR to redirect config.toml into a temp dir, so a test run can
never touch the real %APPDATA% config.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

_TMP = tempfile.mkdtemp()
os.environ['ACH_CONFIG_DIR'] = _TMP
for _v in ('CIF_LOC', 'ACH_USER'):
	os.environ.pop(_v, None)

from achdiff import config, identity  # noqa: E402

fails = []


def check(label, got, want):
	ok = got == want
	print(f'{"ok  " if ok else "FAIL"} {label}')
	print(f'       got={got!r}')
	if not ok:
		print(f'       want={want!r}')
		fails.append(label)


def touch(d, *names):
	for n in names:
		Path(d, n).write_text('1 1\n')


# ---------- prefix scanning ----------
d = tempfile.mkdtemp()
touch(d, 'CN-sample1_pawley_01_X_Yobs.txt', 'CN-sample2.xy',
      'ZIF-4_pawley_01_X_Yobs.txt', 'MOF-5_ambient.xy', 'sample-A-cryst.out')

# CN has 2 files, ZIF and MOF one each; ties break alphabetically so the order
# is stable regardless of filesystem enumeration order.
check('scans all prefixes incl. material names, most common first',
      identity.candidate_prefixes(d), ['CN', 'MOF', 'ZIF'])

# ---------- the collision guard ----------
check('empty roster infers nothing',
      identity.infer_from_filenames(d, known=[]), None)
check('ZIF/MOF are NOT adopted when only CN is registered',
      identity.infer_from_filenames(d, known=['CN']), 'CN')
check('unregistered person prefix is not adopted',
      identity.infer_from_filenames(d, known=['AB']), None)

d2 = tempfile.mkdtemp()
touch(d2, 'ZIF-4_a.xy', 'ZIF-8_b.xy', 'MOF-5_c.xy')
check('a pure ZIF/MOF directory yields no profile',
      identity.infer_from_filenames(d2, known=['CN', 'AB']), None)
check('...but would if someone registered ZIF as their ID',
      identity.infer_from_filenames(d2, known=['ZIF']), 'ZIF')

d3 = tempfile.mkdtemp()
touch(d3, 'CN-a.xy', 'CN-b.xy', 'CN-c.xy', 'AB-x.xy')
check('most common registered prefix wins',
      identity.infer_from_filenames(d3, known=['CN', 'AB']), 'CN')

# ---------- config precedence ----------
config.save_profile('CN', {'cif_loc': r'D:\PersonOne\CIF', 'qall': True})
config.save_profile('AB', {'cif_loc': r'D:\PersonTwo\CIF'})
check('roster lists registered ids', config.profile_ids(), ['AB', 'CN'])

check('profile value used', config.get('cif_loc', user='CN'), r'D:\PersonOne\CIF')
check('other profile is separate', config.get('cif_loc', user='AB'), r'D:\PersonTwo\CIF')
check('no profile -> built-in default',
      config.get('cif_loc', user=None), config.BUILTIN_DEFAULTS['cif_loc'])
check('CLI beats profile',
      config.get('cif_loc', cli_value=r'E:\Explicit', user='CN'), r'E:\Explicit')

os.environ['CIF_LOC'] = r'F:\FromEnv'
check('env beats profile', config.get('cif_loc', user='CN'), r'F:\FromEnv')
check('CLI still beats env',
      config.get('cif_loc', cli_value=r'E:\Explicit', user='CN'), r'E:\Explicit')
del os.environ['CIF_LOC']

check('bool setting round-trips', config.get('qall', user='CN'), True)
check('unset bool falls back', config.get('qall', user='AB'), False)

# ---------- persistence across a simulated upgrade ----------
before = Path(config.config_path()).read_text(encoding='utf-8')
check('config lives outside site-packages',
      'site-packages' not in str(config.config_path()), True)
config.save_profile('CN', {'cif_loc': r'D:\PersonOne\CIF2'})
check('update preserves the other profile',
      config.get('cif_loc', user='AB'), r'D:\PersonTwo\CIF')
check('update applies', config.get('cif_loc', user='CN'), r'D:\PersonOne\CIF2')
check('no duplicate profile tables after re-save',
      Path(config.config_path()).read_text(encoding='utf-8').count('[profiles.CN]'), 1)

# ---------- resolve() ordering ----------
check('explicit flag wins', identity.resolve(cli_user='AB', directory=d3)[0], 'AB')
os.environ['ACH_USER'] = 'AB'
check('env used when no flag', identity.resolve(directory=d3)[0], 'AB')
del os.environ['ACH_USER']
check('inference used when no flag/env', identity.resolve(directory=d3)[0], 'CN')
check('source is reported', identity.resolve(directory=d3)[1], 'sample-name prefix')
check('ZIF dir resolves to no profile', identity.resolve(directory=d2)[0], None)

# ---------- unreadable config must not raise ----------
Path(config.config_path()).write_text('this is not valid toml {{{', encoding='utf-8')
check('broken config degrades to built-ins, no exception',
      config.get('cif_loc'), config.BUILTIN_DEFAULTS['cif_loc'])



# ---------- trusted parameters (per person, never shared) ----------
from achdiff.core import topas  # noqa: E402

check('no profile -> no trusted params', config.trusted_params(None), {})
check('unknown profile -> no trusted params', config.trusted_params('ZZ'), {})

config.save_trusted('CN', 'ZIF-4', {'a': "15.47`_0.001", 'b': "15.51`_0.001", 'c': "18.07`_0.001"},
                    {'source': 'fit.out', 'registered': '2026-07-21'})
config.save_trusted('AB', 'ZIF-4', {'a': "15.50`_0.002", 'b': "15.55`_0.002", 'c': "18.00`_0.002"})

check('same phase, different people, different values',
      (config.trusted_params('CN')['ZIF-4']['a'], config.trusted_params('AB')['ZIF-4']['a']),
      ("15.47`_0.001", "15.50`_0.002"))
check("one person's set never leaks into another's",
      set(config.trusted_params('AB')), {'ZIF-4'})

config.save_trusted('CN', 'H2adp', {'a': "7.38`_0.003", 'be': "110.5`_0.008"})
check('a second phase is added, not replacing the first',
      sorted(config.trusted_params('CN')), ['H2adp', 'ZIF-4'])

check('provenance is stored alongside the cell',
      config.trusted_params('CN')['ZIF-4']['source'], 'fit.out')

check('remove drops only the named phase', config.remove_trusted('CN', 'H2adp'), True)
check('...leaving the rest', sorted(config.trusted_params('CN')), ['ZIF-4'])
check('removing what is not there is reported', config.remove_trusted('CN', 'nope'), False)

# re-saving a phase replaces it wholesale: a cell is refined as a set, so mixing
# `a` from one fit with `c` from another would describe a cell never observed.
config.save_trusted('CN', 'ZIF-4', {'a': "99.9`_0.1"})
check('re-save replaces rather than merges',
      sorted(config.trusted_params('CN')['ZIF-4']), ['a'])

# hyphenated phase names must survive the TOML round-trip
config.save_trusted('CN', 'ZIF-zni', {'a': "23.45`_0.003", 'c': "12.45`_0.004"})
check('hyphenated phase name round-trips',
      config.trusted_params('CN')['ZIF-zni']['c'], "12.45`_0.004")
# The corruption test above deliberately broke the file. A save after that must
# not silently discard everything it could not read.
check('a corrupt config is moved aside, not overwritten in place',
      any(p.name.startswith('config.toml.corrupt-')
          for p in Path(config.config_dir()).glob('*')), True)

# ---------- harvesting from a .out ----------
check('TOPAS diagnostic suffixes are stripped for reuse as input',
      topas.clean_value("15.496374`_0.001842_SVD_ERR"), "15.496374`_0.001842")
check('LIMIT annotations too',
      topas.clean_value("7.38`_0.002`_LIMIT_MAX_9"), "7.38`_0.002")
check('a plain value is untouched', topas.clean_value("15.4"), "15.4")
check('symmetry-implied params are dropped from a harvested set',
      sorted(topas.free_params('Tetragonal', {'a': '1', 'b': '1', 'c': '2'})), ['a', 'c'])
check('unknown system keeps everything',
      sorted(topas.free_params(None, {'a': '1', 'b': '1'})), ['a', 'b'])



# ---------- `achdiff profile set` value coercion ----------
from achdiff import cli  # noqa: E402

check('bool setting coerces true', cli._coerce('qall', 'true'), True)
check('bool setting coerces False, not truthy string',
      cli._coerce('qall', 'false'), False)
check('bool accepts yes/no forms', (cli._coerce('qall', 'YES'), cli._coerce('qall', 'off')),
      (True, False))
try:
	cli._coerce('qall', 'maybe')
	check('a non-boolean value for a bool setting raises', 'no raise', 'ValueError')
except ValueError:
	check('a non-boolean value for a bool setting raises', 'ValueError', 'ValueError')
check('string settings pass through unchanged',
      cli._coerce('cif_loc', r'D:\Some\Path'), r'D:\Some\Path')

# settings merge rather than replace, so editing one does not drop the others
config.save_profile('MG', {'cif_loc': r'D:\A'})
config.save_profile('MG', {'qall': True})
check('a later save merges with the earlier one',
      sorted(config.profiles()['MG']), ['cif_loc', 'qall'])

print()
print(f'{len(fails)} failure(s)' + (': ' + ', '.join(fails) if fails else ''))
sys.exit(1 if fails else 0)
