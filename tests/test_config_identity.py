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

# People write the separator both ways, and a prefix that only counts with a
# hyphen makes inference look broken for whoever happens to use underscores.
d_us = tempfile.mkdtemp()
touch(d_us, 'XX_Mg3(PO4)2-II_pawley_01_X_Yobs.txt', 'XX_Mg3(PO4)2-II_pawley_01_2Th_Ip_18.txt')
check('an underscore separates a prefix just as a hyphen does',
      identity.candidate_prefixes(d_us), ['XX'])
check('...and still only when the ID is registered',
      (identity.infer_from_filenames(d_us, known=['XX']),
       identity.infer_from_filenames(d_us, known=['AB'])), ('XX', None))

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

# A profile decides which CIF library, which style sheet, AND whether filename
# inference recognises this person at all. Someone who wants only the last two
# should not have to invent a setting to get them.
config.save_profile('NC', {})
check('a profile with no settings is still registered',
      'NC' in config.profile_ids(), True)
config.save_profile('MG', {'qall': False})
check('...and survives an unrelated save', 'NC' in config.profile_ids(), True)

d_nc = tempfile.mkdtemp()
touch(d_nc, 'NC-sample1.xy', 'NC-sample2.xy')
check('...and is enough for filename inference to recognise the person',
      identity.infer_from_filenames(d_nc, known=config.profile_ids()), 'NC')


# ---------- style sheets ----------
import re  # noqa: E402

from achdiff import styles  # noqa: E402
from achdiff.tools import plotter  # noqa: E402

_STYLE_DIR = Path(_TMP) / styles.STYLES_DIRNAME
_STYLE_DIR.mkdir(parents=True, exist_ok=True)


def write_style(stem, text):
	path = _STYLE_DIR / f'{stem}.toml'
	path.write_text(text, encoding='utf-8')
	return path


def applied(user=None, explicit=None, **seed):
	"""Run a style over a throwaway settings dict and hand back the result."""
	target = dict(plotter.settings)
	target.update(seed)
	styles.apply(target, user=user, explicit=explicit)
	return target


write_style('default', "[legend]\nlegend_frame = false\nlegend_fontsize = 7\n")
write_style('SS', "[legend]\nlegend_fontsize = 9\n\n[annotations]\nshow_quality = false\n")

check('a style maps its public key onto the plotter setting',
      applied('SS')['legend_fontsize'], 9.0)
check('show_quality reaches the setting that gates the R_wp annotation',
      applied('SS')['show_info'], False)
check('default.toml applies underneath a personal style',
      applied('SS')['legend_frame'], False)
check('a personal style outranks default.toml on a shared key',
      (applied()['legend_fontsize'], applied('SS')['legend_fontsize']), (7.0, 9.0))
check('no profile means default.toml alone',
      applied()['show_info'], True)

# Group headers are readability sugar, so a flat file has to work identically.
write_style('FLAT', "legend_fontsize = 12\n")
check('a file without group headers is read the same way',
      applied('FLAT')['legend_fontsize'], 12.0)

# A style sheet is decoration: nothing in it may stop a figure being drawn.
write_style('BAD', "\n".join([
	"legend_fontsize = 'large'",       # wrong type
	"observed_color = 'nosuchcolour'",  # not a colour
	"tick_direction = 'sideways'",      # not one of the choices
	"figsize = [6]",                    # wrong shape
	"legend_columsn = 2",               # typo'd key
	"legend_loc = 'lower left'",        # ... and one good value among them
]))
bad = applied('BAD')
# legend_fontsize falls back to 7 rather than the built-in 8: default.toml above
# set it, and a rejected value drops through to the layer beneath, not to zero.
check('a rejected value leaves the layer beneath it in place',
      (bad['legend_fontsize'], bad['X_Yobs_color'], bad['tick_direction']),
      (7.0, 'k', 'in'))
check('a wrongly shaped figsize is rejected', bad['figsize'], (6, 4))
check('good values in a file with bad ones still apply',
      bad['legend_loc'], 'lower left')

try:
	styles.apply(dict(plotter.settings), explicit=str(_STYLE_DIR / 'nope.toml'))
	check('a --style file that does not exist is an error', 'no raise', 'FileNotFoundError')
except FileNotFoundError:
	check('a --style file that does not exist is an error',
	      'FileNotFoundError', 'FileNotFoundError')

# `--style narrow` should find styles/narrow.toml, the way `-r ZIF-8` finds a
# CIF in the library. Typing the full path to a file the suite wrote itself is
# friction with nothing behind it.
write_style('narrow', '[figure]\nfigsize = [3.3, 4.0]\n')
check('--style takes a bare name from the styles directory',
      styles.resolve_named_style('narrow').name, 'narrow.toml')
check('...and the same name with its suffix',
      styles.resolve_named_style('narrow.toml').name, 'narrow.toml')
check('a bare name layers on top of the personal style',
      applied('SS', explicit='narrow')['figsize'], (3.3, 4.0))
check('a name matching nothing comes back as typed, for the error to quote',
      styles.resolve_named_style('nope').name, 'nope')

# `style install` checks a file before copying it, so a typo in something a
# colleague sent is caught while it is still obvious what to do about it.
_check_src = Path(tempfile.mkdtemp()) / 'sent.toml'
_check_src.write_text("[axes]\ny_label = 'ok'\n"
                      "legend_columsn = 2\n"
                      "tick_direction = 'sideways'\n", encoding='utf-8')
_good, _unknown, _invalid = styles.validate(_check_src)
check('validate reports the keys that would apply', _good, ['y_label'])
check('...the ones it does not know', _unknown, ['legend_columsn'])
check('...and the ones it cannot use, with a reason',
      [n for n, _reason in _invalid], ['tick_direction'])

# `achdiff style init` writes the catalogue people edit. Every line in it must be
# a key the loader knows and a value it accepts, or the first thing anyone
# uncomments is a warning.
tpl = styles.template('SS')
uncommented = re.sub(r'^# (?=\w+ = )', '', tpl, flags=re.MULTILINE)
parsed = config.tomllib.loads(uncommented)
flat = {}
for _k, _v in parsed.items():
	flat.update(_v) if isinstance(_v, dict) else flat.update({_k: _v})
check('the template lists every setting in the schema',
      sorted(flat) == sorted(styles.BY_NAME), True)
write_style('TPL', uncommented)
round_tripped = applied('TPL')
check('reading the template back reproduces the built-in values exactly',
      [k.name for k in styles.BY_NAME.values()
       if round_tripped[k.target] != plotter.settings[k.target]], [])


# ---------- Bragg legend naming ----------
def bragg(label, colors, substances=None):
	substances = substances or [f'S{i}' for i in range(len(colors))]
	meta = [{'color': c, 'substance': s, 'label': f'L{i}'}
	        for i, (c, s) in enumerate(zip(colors, substances))]
	before = plotter.settings['bragg_label']
	plotter.settings['bragg_label'] = label
	try:
		return plotter._bragg_labels(meta)
	finally:
		plotter.settings['bragg_label'] = before


check('without a fixed name each row keeps its own space group and substance',
      bragg('', ['k', 'b']), ['L0', 'L1'])
check('one phase takes the fixed name as written',
      bragg('Bragg reflections', ['k']), ['Bragg reflections'])
check('rows sharing a colour share one name, for legend_dedupe to collapse',
      bragg('Bragg reflections', ['k', 'k']),
      ['Bragg reflections', 'Bragg reflections'])
check('rows in different colours are told apart, since both need a legend entry',
      bragg('Bragg reflections', ['k', 'b'], ['ZIF-4', 'ZIF-zni']),
      ['Bragg reflections (ZIF-4)', 'Bragg reflections (ZIF-zni)'])
check('a row with no substance falls back to its space-group label',
      bragg('Bragg reflections', ['k', 'b'], ['ZIF-4', None]),
      ['Bragg reflections (ZIF-4)', 'Bragg reflections (L1)'])



# ---------- config.write preserves what it does not recognise ----------
# Until this was fixed, write() emitted a profile's scalars and its `trusted` set
# and nothing else: any other sub-table was read successfully and then discarded
# at the next unrelated save, and a dict under [defaults] came back as a quoted
# Python repr.
cfg = config.load()
nest = cfg.setdefault('profiles', {}).setdefault('NEST', {})
nest['cif_loc'] = r'D:\N'
nest['notes'] = {'instrument': 'D8'}
nest['deep'] = {'a': {'b': {'value': 7}}}
cfg.setdefault('defaults', {})['style'] = {'dpi': 300, 'legend_frame': False}
config.write(cfg)

config.save_trusted('NEST', 'ZIF-4', {'a': 15.4})   # the unrelated save that used to lose it
back = config.load()
nest_back = back.get('profiles', {}).get('NEST', {})

check('an unrecognised profile sub-table survives a later save',
      nest_back.get('notes'), {'instrument': 'D8'})
check('a dict under [defaults] round-trips as a table, not a repr string',
      back.get('defaults', {}).get('style'), {'dpi': 300, 'legend_frame': False})
check('nesting deeper than the tools themselves write survives',
      nest_back.get('deep'), {'a': {'b': {'value': 7}}})
check('trusted parameters still round-trip alongside it',
      nest_back.get('trusted', {}).get('ZIF-4', {}).get('a'), 15.4)
check('plain settings are untouched by any of it', nest_back.get('cif_loc'), r'D:\N')

# Values write() has to escape rather than stringify. An apostrophe used to be
# doubled, which ends a TOML literal string early and makes the whole file
# unparseable -- so the check is that it survives a round trip at all.
cfg = config.load()
cfg['profiles']['NEST']['cif_loc'] = "D:\\Bob's data"
cfg['profiles']['NEST']['palette'] = ['k', 'b']
config.write(cfg)
back = config.load()
nest_back = back.get('profiles', {}).get('NEST', {})
check('a value containing an apostrophe round-trips',
      nest_back.get('cif_loc'), "D:\\Bob's data")
check('a list value round-trips as a TOML array', nest_back.get('palette'), ['k', 'b'])

config.remove_trusted('NEST', 'ZIF-4')
written = config.config_path().read_text(encoding='utf-8')
check('removing the last phase leaves no empty trusted table behind',
      '[profiles.NEST.trusted]' in written, False)
check('an intermediate table gets no bare header of its own',
      '[profiles.NEST.deep]' in written, False)


# ---------- CIF loading ----------
import numpy as np  # noqa: E402

from achdiff.core import cif as cifcore  # noqa: E402


def _raises(fn):
	"""True if `fn` raised anything. The check is that a bad input is refused,
	not which exception type carries the news."""
	try:
		fn()
		return False
	except Exception:
		return True


def cell_volume_is_nan():
	value = cifcore.cell_volume(a=1.0, b=1.0, c=1.0, alpha=10.0, beta=10.0, gamma=170.0)
	return value != value   # NaN is the only value unequal to itself

# The crystallography comes from the vendored MoloM core, not pymatgen. These
# pin the two things the switch had to get right: files pymatgen refuses must
# load, and the arithmetic must not have moved.
_CIF_DIR = Path(tempfile.mkdtemp())


def write_cif(name, occupancy='1.0', extra_site=''):
	"""A minimal P1 cell with one carbon, plus whatever the caller adds."""
	path = _CIF_DIR / name
	path.write_text('\n'.join([
		'data_test',
		'_cell_length_a 5.0',
		'_cell_length_b 6.0',
		'_cell_length_c 7.0',
		'_cell_angle_alpha 90.0',
		'_cell_angle_beta 90.0',
		'_cell_angle_gamma 90.0',
		"_symmetry_space_group_name_H-M 'P 1'",
		'loop_',
		'_atom_site_label',
		'_atom_site_type_symbol',
		'_atom_site_fract_x',
		'_atom_site_fract_y',
		'_atom_site_fract_z',
		'_atom_site_occupancy',
		f'C1 C 0.0 0.0 0.0 {occupancy}',
		extra_site,
		'']), encoding='utf-8')
	return path


# A site occupancy of 4.0 is how several refinement programs spell "four atoms
# on this site". pymatgen's default tolerance of 1.0 does not warn about it --
# it discards the whole data block, and a single-block file then raises
# "Invalid CIF file with no structures!".
_full = write_cif('full.cif', occupancy='1.0')
_over = write_cif('overfull.cif', occupancy='4.0')

phase = cifcore.load_phase(_over, announce=False)
check('a CIF pymatgen would reject on occupancy still loads', len(phase.symbols), 1)
check('an over-full site is rescaled to one atom, not left scattering four times',
      round(float(phase.occupancy[0]), 6), 1.0)
check('a site that is merely full is left exactly as written',
      round(float(cifcore.load_phase(_full, announce=False).occupancy[0]), 6), 1.0)

# The rescale is per site, not per atom in the expanded cell: a site repeats
# once per symmetry operator, and totalling occupancies there would shrink every
# ordinary structure in a high-symmetry group.
check('rescaling leaves an ordinary full structure untouched',
      [round(float(v), 6) for v in
       cifcore.load_phase(Path('examples/H2bdc.cif'), announce=False).occupancy],
      [1.0] * 18)

check('reflection positions are unchanged by the backend switch',
      [round(float(v), 5) for v in
       cifcore.simulate_reflections('examples/H2bdc.cif', 5, (5, 50))],
      [17.37534, 25.28043, 27.9579, 39.94131, 40.60582])

# Straining the cell must move the peaks and leave the contents alone: that is
# the whole of what prefit's sliders do.
_phase = cifcore.load_phase('examples/H2bdc.cif', announce=False)
_wide = _phase.with_cell(a=_phase.cell.a * 1.10)
check('straining a cell keeps the contents', len(_wide.symbols), len(_phase.symbols))
check('straining a cell changes the volume',
      round(_wide.volume / _phase.volume, 4), 1.1)
_p0, _i0, _h0 = _phase.peaks((5, 50))
_p1, _i1, _h1 = _wide.peaks((5, 50))
# Compared on the strongest peak rather than element-wise: a longer a axis pulls
# extra reflections into the window, so the two lists are not the same length.
check('stretching an axis moves the peaks to lower angle',
      float(_p1[int(_i1.argmax())]) < float(_p0[int(_i0.argmax())]), True)
check('peaks come back sorted by angle', bool((np.diff(_p1) >= 0).all()), True)
check('every peak carries an hkl', len(_h1), len(_p1))

check('an impossible cell is refused before anything plots it',
      _raises(lambda: _phase.with_cell(alpha=10.0, beta=10.0, gamma=170.0)), True)
check('and cell_volume reports it as NaN rather than raising',
      cell_volume_is_nan(), True)

check('crystal system comes back in the spelling the TOPAS macros use',
      _phase.crystal_system, 'triclinic')

# H2bdc.cif declares P1 and lists a whole cell whose atoms have an inversion
# centre. Both answers are available; which one is used is a decision, not an
# implementation detail, so each is pinned separately.
check('what the file declares is what is reported',
      (_phase.space_group_number, _phase.space_group_symbol), (1, 'P1'))
check('...and the atoms can be asked separately, when someone asks',
      _phase.detected_symmetry(symprec=0.01), (2, 'P-1'))
check('the derived system agrees with the derived group',
      _phase.detected_crystal_system(symprec=0.01), 'triclinic')

from achdiff.tools import wizard  # noqa: E402

# A CIF whose header disagrees with its own atoms is a CIF with a fault in it.
# The wizard reports the header, so the fault stays visible rather than being
# quietly corrected into a .inp nobody asked for.
check('the wizard writes the space group the file declares',
      wizard.get_cif_parameters('examples/H2bdc.cif'),
      {'a': '5.0374', 'b': '5.3641', 'c': '7.0068',
       'al': '72.004', 'be': '76.098', 'ga': '87.219', 'V': '174.727',
       'sg_num': '1', 'sg_HM': 'P1', 'cryst_sys': 'triclinic'})
check('--derive-symmetry is what asks the atoms instead',
      {k: v for k, v in
       wizard.get_cif_parameters('examples/H2bdc.cif', derive_symmetry=True).items()
       if k in ('sg_num', 'sg_HM')},
      {'sg_num': '2', 'sg_HM': 'P-1'})
# The fixture's header says P 1, so that is what comes back. Asking the atoms
# instead finds Pmmm -- one atom at the origin of a 5 x 6 x 7 box.
check('and reads a CIF pymatgen refused outright',
      wizard.get_cif_parameters(_over)['sg_num'], '1')
check('...where --derive-symmetry would have found the fuller group',
      wizard.get_cif_parameters(_over, derive_symmetry=True)['sg_num'], '47')


# ---------- only macros that exist in topas.inc may be written ----------
# An undefined macro is not a warning at run time; it is a refinement that will
# not start. `Rhombohedral` is not defined in this group's topas.inc, so no code
# path may reach it -- and it is easy to reach by accident, because it is the
# honest macro for a trigonal group on rhombohedral axes.
check('no macro is written that topas.inc does not define',
      'rhombohedral' in wizard.CRYSTAL_MACROS, False)
check('every fallback lands on a macro that does exist',
      [s for s in wizard.MACRO_FALLBACKS.values() if s not in wizard.CRYSTAL_MACROS], [])


def _rhombohedral_cif(name, a, c, alpha, gamma):
	path = _CIF_DIR / name
	path.write_text('\n'.join([
		'data_r',
		f'_cell_length_a {a}',
		f'_cell_length_b {a}',
		f'_cell_length_c {c}',
		f'_cell_angle_alpha {alpha}',
		f'_cell_angle_beta {alpha}',
		f'_cell_angle_gamma {gamma}',
		"_symmetry_space_group_name_H-M 'R -3 c'",
		'loop_',
		'_atom_site_label',
		'_atom_site_type_symbol',
		'_atom_site_fract_x',
		'_atom_site_fract_y',
		'_atom_site_fract_z',
		'_atom_site_occupancy',
		'Al1 Al 0.35216 0.35216 0.35216 1.0' if c == a else 'Al1 Al 0.0 0.0 0.35216 1.0',
		'O1 O 0.5560 0.9440 0.2500 1.0' if c == a else 'O1 O 0.30624 0.0 0.25 1.0',
		'']), encoding='utf-8')
	return wizard.get_cif_parameters(path)


_rhomb = _rhombohedral_cif('rhomb.cif', 5.4280, 5.4280, 55.280, 55.280)
_hexax = _rhombohedral_cif('hexax.cif', 4.7590, 12.9910, 90.0, 120.0)

check('a cell on rhombohedral axes is recognised as such',
      _rhomb['cryst_sys'], 'rhombohedral')
check('...but still writes the Trigonal macro, the one topas.inc has',
      'Trigonal(' in wizard.build_phase_section([_rhomb], '_p_', 'out'), True)
check('...and never writes Rhombohedral(',
      'Rhombohedral(' in wizard.build_phase_section([_rhomb], '_p_', 'out'), False)
check('the same group on hexagonal axes is untouched, as it always was',
      _hexax['cryst_sys'], 'trigonal')

check('a CIF with no atoms is an error, not an empty plot',
      _raises(lambda: cifcore.load_phase(_CIF_DIR / 'nope.cif')), True)



# ---------- GIF animation of a sequential run ----------
from achdiff.core import animate  # noqa: E402

# A run is numbered, and plain string order plays the timeline out of sequence.
check('frames sort numerically, not lexically',
      sorted(['s_10', 's_2', 's_1'], key=animate.natural_key), ['s_1', 's_2', 's_10'])

check('a TOPAS token splits into value and uncertainty',
      animate.parse_value_error('15.475318`_0.000986'), (15.475318, 0.000986))
check('diagnostics after the esd are not part of it',
      animate.parse_value_error('7.38`_0.002`_LIMIT_MAX_9'), (7.38, 0.002))
check('a value with no esd still gives a value',
      animate.parse_value_error('90.0'), (90.0, None))
check('an unparseable token is dropped rather than plotted as zero',
      animate.parse_value_error('not a number'), None)

# Cell edges as they actually come out of a sequential run: a and c nearly 3 A
# apart, each moving by well under a tenth of an Angstrom.
_series = animate.CellSeries('test')
_series.add('run_1', {'a': '15.475`_0.001', 'c': '18.075`_0.001', r'\beta': '104.21`_0.003'})
_series.add('run_2', {'a': '15.520`_0.002', 'c': '18.040`_0.002', r'\beta': '104.42`_0.003'})
_series.add('run_3', {'a': '15.565`_0.004', r'\beta': '104.63`_0.003'})   # c missing here

check('only parameters present in every frame are animated',
      _series.keys(), ['a', r'\beta'])
check('the baseline is the first frame',
      _series.baselines(['a']), {'a': 15.475})

# The whole reason relative mode exists: an axis wide enough to hold both a and
# c is far too coarse to show either of them move.
_lengths = ['a', 'c']
_abs = _series.span(_lengths)
_rel = _series.span(_lengths, _series.baselines(_lengths))
check('absolute span has to cover both edges', _abs[0] < 15.475 and _abs[1] > 18.075, True)
check('relative span is an order of magnitude tighter, which is the point',
      (_rel[1] - _rel[0]) < (_abs[1] - _abs[0]) / 10, True)
check('relative span brackets zero, so a shrinking parameter has somewhere to go',
      _rel[0] < 0 < _rel[1], True)

# Two axes on one plot do not share a scale; in relative mode their zeros must
# still land at the same height or one grey rule is wrong for one of them.
_a, _b = animate.align_zero((-0.067, 0.087), (-0.1, 0.5))
_fa = -_a[0] / (_a[1] - _a[0])
_fb = -_b[0] / (_b[1] - _b[0])
check('aligned axes put zero at the same height', round(_fa - _fb, 12), 0.0)
check('...without cropping either axis\'s own data',
      (_a[0] <= -0.067 and _a[1] >= 0.087 and _b[0] <= -0.1 and _b[1] >= 0.5), True)
check('a lone axis is left alone', animate.align_zero((-1.0, 2.0), None),
      [(-1.0, 2.0), None])

# Frames must all be one size or the GIF cannot be assembled; catching it here
# beats a Pillow traceback after a minute of rendering.
_frames = animate.render_cell_frames(_series, figsize=(4, 3), dpi=60)
check('a frame is rendered per fit', len(_frames), 3)
check('and every frame is the same size', len({f.size for f in _frames}), 1)

_gif = Path(tempfile.mkdtemp()) / 'series.gif'
animate.write_gif(_frames, _gif, delay_ms=120)
check('the gif is written and holds every frame', _gif.is_file(), True)
try:
	from PIL import Image
	with Image.open(_gif) as _im:
		check('...as an animation, not a single image', _im.n_frames, 3)
except ImportError:
	pass

check('mismatched frame sizes are refused with a reason',
      _raises(lambda: animate.write_gif(
          [_frames[0], _frames[0].resize((10, 10))], _gif)), True)


# ---------- ordering a run: --sort-key ----------
# Natural sort splits "0.5" at the point and compares the pieces, so it puts
# 0.5GPa before 0GPa. That is the case the flag exists for.
_press = ['c_0.5GPa', 'c_0GPa', 'c_1.5GPa', 'c_1GPa', 'c_10GPa', 'c_2GPa']
check('natural sort gets decimal pressures wrong -- why --sort-key exists',
      sorted(_press, key=animate.natural_key)[:2], ['c_0.5GPa', 'c_0GPa'])
check('a sort key compares what it captures as numbers',
      animate.sort_by_pattern(_press, r'_([0-9.]+)GPa'),
      (['c_0GPa', 'c_0.5GPa', 'c_1GPa', 'c_1.5GPa', 'c_2GPa', 'c_10GPa'], []))
check('several groups sort left to right',
      animate.sort_by_pattern(['T300_r2', 'T100_r10', 'T100_r2'], r'T(\d+)_r(\d+)')[0],
      ['T100_r2', 'T100_r10', 'T300_r2'])
check('a decimal comma counts as a decimal point',
      animate.sort_by_pattern(['p_1,5GPa', 'p_0,5GPa', 'p_10GPa'], r'_([0-9,]+)GPa')[0],
      ['p_0,5GPa', 'p_1,5GPa', 'p_10GPa'])
check('names the key does not match are kept and handed back, not dropped',
      animate.sort_by_pattern(['r_2GPa', 'calib', 'r_1GPa'], r'_(\d+)GPa'),
      (['r_1GPa', 'r_2GPa'], ['calib']))
check('an invalid expression is refused rather than sorting by nothing',
      _raises(lambda: animate.sort_by_pattern(['a'], '_([0-9')), True)


# ---------- x values: --x-values ----------
check('a plain list', animate.parse_x_values('0,0.5,1,2'), [0.0, 0.5, 1.0, 2.0])
check('a range includes its stop', animate.parse_x_values('0:10:2'),
      [0.0, 2.0, 4.0, 6.0, 8.0, 10.0])
check('a range counts rather than accumulates, so 0:1:0.1 has eleven values',
      len(animate.parse_x_values('0:1:0.1')), 11)
check('a range can step down, for a decompression run',
      animate.parse_x_values('4:0:-2'), [4.0, 2.0, 0.0])
check('lists and ranges join in the order written',
      animate.parse_x_values('0,0.5,1:2:0.5'), [0.0, 0.5, 1.0, 1.5, 2.0])
check('whitespace separates as well as commas',
      animate.parse_x_values('0 1  2'), [0.0, 1.0, 2.0])
for _bad in ('0:10:-1', '0:10:0', '0:10', 'a,b', ''):
	check(f'refused: {_bad!r}', _raises(lambda: animate.parse_x_values(_bad)), True)


# ---------- the trend plot ----------
_trend = animate.CellSeries('cubic')
_trend.add('p0', {'a': '17.0000`_0.0010', 'V': '4913.0`_0.9'}, x=0.0)
_trend.add('p1', {'a': '16.8300`_0.0020', 'V': '4767.1`_1.7'}, x=2.5)
_trend.add('p2', {'a': '16.6600`_0.0020', 'V': '4624.0`_1.7'}, x=10.0)
_ratios = animate.ratio_series(_trend)

check('the trend carries the volume as well as the cell edge',
      sorted(_ratios), ['V', 'a'])
check('x comes from the values given, not the position in the run',
      _ratios['a'][0], [0.0, 2.5, 10.0])
check('every parameter starts at exactly 1',
      [_ratios[k][1][0] for k in ('a', 'V')], [1.0, 1.0])
check('...and the first point carries no error, since it is 1 by definition',
      [_ratios[k][2][0] for k in ('a', 'V')], [0.0, 0.0])
check('the ratio is the value over the first value',
      round(_ratios['a'][1][2], 6), round(16.66 / 17.0, 6))
# sigma(r) = r * sqrt((s/p)^2 + (s0/p0)^2), independent errors
check('uncertainty is propagated through the division, not copied across',
      round(_ratios['a'][2][2], 9),
      round((16.66 / 17.0) * ((0.002 / 16.66) ** 2 + (0.001 / 17.0) ** 2) ** 0.5, 9))

_even = animate.CellSeries('cubic')
for _i, _a in enumerate(('17.0`_0.001', '16.9`_0.001', '16.8`_0.001')):
	_even.add(f'p{_i}', {'a': _a})
check('without x values the axis is the fit number, from 1',
      animate.ratio_series(_even)['a'][0], [1.0, 2.0, 3.0])

# A fit whose .out held no cell is absent from the series but still used up its
# x value. Aligning by position would slide every later point onto its
# neighbour's pressure.
_gap = animate.CellSeries('gap')
_gap.add('p0', {'a': '17.0`_0.001'}, x=0.0)
_gap.add('p1', {}, x=1.0)                          # nothing parsed: not recorded
_gap.add('p2', {'a': '16.8`_0.001'}, x=5.0)
check('a fit with no cell keeps later points on their own x values',
      animate.ratio_series(_gap)['a'][0], [0.0, 5.0])

check('the volume stays out of the bar chart, which has no axis for it',
      _trend.keys(), ['a'])


# ---------- animated SVG ----------
import matplotlib.pyplot as _plt  # noqa: E402

_svg_frames = []
for _k in range(3):
	_fig, _ax = _plt.subplots(figsize=(3, 2))
	_ax.plot([0, 1, 2], [_k, 1, 2 - _k], 'x-')
	_ax.set_title(f'frame {_k}')
	_svg_frames.append(animate.figure_to_svg(_fig))
	_plt.close(_fig)
_svg_path = Path(tempfile.mkdtemp()) / 'anim.svg'
animate.write_animated_svg(_svg_frames, _svg_path, delay_ms=200)
_svg_text = _svg_path.read_text(encoding='utf-8')

import re as _re  # noqa: E402
_ids = _re.findall(r'\bid="([^"]+)"', _svg_text)
check('one group per frame', len(_re.findall(r'<g id="frame\d+"', _svg_text)), 3)
check('every id is unique once the frames share one document',
      len(_ids) - len(set(_ids)), 0)
check('every reference points at an id that exists',
      sorted(set(_re.findall(r'(?:url\(#|href="#)([^)"]+)', _svg_text)) - set(_ids)), [])
check('only the first frame is drawn when the animation does not run',
      _re.findall(r'<g id="frame\d+" display="(\w+)"', _svg_text),
      ['inline', 'none', 'none'])
check('the cycle lasts one delay per frame and loops',
      ('dur="0.600s"' in _svg_text, 'repeatCount="indefinite"' in _svg_text), (True, True))
check('frames on different canvases are refused',
      _raises(lambda: animate.write_animated_svg(
          [_svg_frames[0], _svg_frames[0].replace('width="216pt"', 'width="300pt"', 1)],
          _svg_path)), True)

# Exact only: a style identical to the marker's own does nothing and goes; one
# that adds a property (a Bragg tick's fill) is load-bearing and stays.
_body = ('<path id="m1" d="M 0 0" style="stroke: #000000; stroke-width: 0.6"/>'
         '<path id="m2" d="M 0 0" style="stroke: #0000ff"/>'
         '<use xlink:href="#m1" x="1" y="2" style="stroke: #000000; stroke-width: 0.6"/>'
         '<use xlink:href="#m2" x="1" y="2" style="fill: #0000ff; stroke: #0000ff"/>')
_compact = animate._compact(_body)
check('a <use> style identical to its marker\'s is dropped',
      '<use xlink:href="#m1" x="1" y="2"/>' in _compact, True)
check('a <use> style that adds anything is kept',
      'style="fill: #0000ff; stroke: #0000ff"' in _compact, True)
check('coordinates are left exactly as written',
      _compact.count('x="1" y="2"'), 2)


# ---------- return legs: --x-map ----------
# A reversibility run goes up and comes back over the same pressures. No sort
# order recovers that and no value list is safe to count across forty fits, so
# the order and the values come from a file the user edits.
_map_dir = Path(tempfile.mkdtemp())
_run = ['c_up_0GPa', 'c_up_5GPa', 'c_up_10GPa', 'c_down_5GPa', 'c_down_0GPa']
_tpl = _map_dir / 'run.txt'
animate.write_x_map_template(_tpl, _run, [0.0, 5.0, 10.0, None, 0.0], 'a test')
check('a blank x in a template is refused, not read as zero',
      _raises(lambda: animate.read_x_map(_tpl)), True)
_tpl.write_text(_tpl.read_text(encoding='utf-8').replace('c_down_5GPa\n', 'c_down_5GPa  5\n'),
                encoding='utf-8')
check('a template reads back once its blanks are filled, in the order written',
      animate.read_x_map(_tpl),
      [('c_up_0GPa', 0.0), ('c_up_5GPa', 5.0), ('c_up_10GPa', 10.0),
       ('c_down_5GPa', 5.0), ('c_down_0GPa', 0.0)])
check('the template says where pre-filled values came from',
      'pre-filled from a test' in _tpl.read_text(encoding='utf-8'), True)

_edited = _map_dir / 'edited.txt'
_edited.write_text('# compression\n'
                   'c_up_0GPa    0\n'
                   'c_up_5GPa    5\n'
                   'c_up_10GPa   10   # turning point\n'
                   '\n'
                   '# back down\n'
                   'c_down_5GPa  5\n'
                   'c_down_0GPa  0\n', encoding='utf-8')
check('the file is the timeline, repeated x values and all',
      animate.read_x_map(_edited),
      [('c_up_0GPa', 0.0), ('c_up_5GPa', 5.0), ('c_up_10GPa', 10.0),
       ('c_down_5GPa', 5.0), ('c_down_0GPa', 0.0)])

_spaced = _map_dir / 'spaced.txt'
_spaced.write_text('MgHPO4 1.2 H2O run 3   2.5\n', encoding='utf-8')
check('a fit name may contain spaces; the x value is the last token',
      animate.read_x_map(_spaced), [('MgHPO4 1.2 H2O run 3', 2.5)])

_excel = _map_dir / 'excel.txt'
_excel.write_text('c_up_0GPa;0\nc_up_0.5GPa;0,5\n', encoding='utf-8')
check('a spreadsheet export with ; and a decimal comma is read',
      animate.read_x_map(_excel), [('c_up_0GPa', 0.0), ('c_up_0.5GPa', 0.5)])

_dup = _map_dir / 'dup.txt'
_dup.write_text('a 0\nb 1\na 2\n', encoding='utf-8')
check('a fit listed twice is refused -- it would be a frame never measured',
      _raises(lambda: animate.read_x_map(_dup)), True)

check('pre-filling reads the number a sort pattern captures',
      animate.first_number(['c_up_0.5GPa', 'calib', 'c_down_10GPa'], r'_([0-9.]+)GPa'),
      [0.5, None, 10.0])

check('a run up and back is two legs sharing the turning point',
      animate.monotonic_legs([0, 5, 10, 5, 0]),
      [([0, 1, 2], True), ([2, 3, 4], False)])
check('a repeated value does not start a new leg',
      animate.monotonic_legs([0, 5, 5, 10]), [([0, 1, 2, 3], True)])
check('a plain run is a single rising leg', animate.monotonic_legs([1, 2, 3]),
      [([0, 1, 2], True)])
check('several reversals are several legs',
      [rising for _i, rising in animate.monotonic_legs([0, 10, 0, 10])],
      [True, False, True])

_rev = animate.CellSeries('rev')
for _n, _x, _a in (('u0', 0, '17.0`_0.001'), ('u10', 10, '16.5`_0.001'),
                   ('d0', 0, '17.0`_0.001')):
	_rev.add(_n, {'a': _a}, x=float(_x))
_fig = animate.render_trend(_rev, x_label='p / GPa')
check('a trend with a return leg says which marker is which way',
      'x decreasing' in [t.get_text() for t in _fig.axes[0].get_legend().get_texts()], True)
_plt.close(_fig)


print()
print(f'{len(fails)} failure(s)' + (': ' + ', '.join(fails) if fails else ''))
sys.exit(1 if fails else 0)
