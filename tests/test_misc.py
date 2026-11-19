"""Assertions for the misc scripts: the registry, the kit, cell_drift and heatmap.

Run: python tests/test_misc.py
Uses ACH_CONFIG_DIR and ACH_MISC_DIR to keep the real config and any real lab
folder out of it.
"""

import builtins
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

_TMP = tempfile.mkdtemp()
os.environ['ACH_CONFIG_DIR'] = _TMP
os.environ['MPLBACKEND'] = 'Agg'
for _v in ('ACH_USER', 'ACH_MISC_DIR'):
	os.environ.pop(_v, None)

import numpy as np  # noqa: E402

from achdiff import misc  # noqa: E402
from achdiff.misc import kit  # noqa: E402
from achdiff.misc.scripts import cell_drift  # noqa: E402
from achdiff.misc.scripts import heatmap  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'
MIX = EXAMPLES / 'sample-A-cryst.out'     # ZIF-4 + ZIF-zni
PURE = EXAMPLES / 'sample-B-cryst.out'    # ZIF-4 alone

fails = []


def check(label, got, want):
	ok = got == want
	print(f'{"ok  " if ok else "FAIL"} {label}')
	print(f'       got={got!r}')
	if not ok:
		print(f'       want={want!r}')
		fails.append(label)


def quiet(fn, *a, **kw):
	"""Run fn with its printing captured: (result, text)."""
	out = io.StringIO()
	with contextlib.redirect_stdout(out):
		try:
			result = fn(*a, **kw)
		except SystemExit as e:
			result = SystemExit(e.code)
	return result, out.getvalue()


def workdir(*files):
	d = Path(tempfile.mkdtemp())
	for f in files:
		shutil.copy(f, d)
	return d


# ---------- the registry ----------
_all = misc.available()
check('cell_drift ships with the package', 'cell_drift' in _all, True)
_cd = _all['cell_drift']
check('its summary is the first line of its docstring', _cd.summary,
      'Cell parameters of each phase in a mixture fit, against its single-phase fit.')
check('ABOUT is read without importing the script',
      sorted(_cd.about), ['author', 'for', 'written'])
check('every packaged script has a main() to run',
      [n for n, s in _all.items() if not hasattr(misc.load(s), 'main')], [])

_lab = Path(tempfile.mkdtemp())
(_lab / 'hello.py').write_text(
	'"""Say hello.\n\nA lab script."""\nABOUT = {"for": "a test"}\n'
	'def main(argv=None, command=None):\n    print("hello", argv, command)\n    return 3\n',
	encoding='utf-8')
(_lab / 'cell_drift.py').write_text('"""A lab copy that shadows the packaged one."""\n',
                                    encoding='utf-8')
(_lab / 'broken.py').write_text('def (:\n', encoding='utf-8')
(_lab / '_private.py').write_text('"""Not a script."""\n', encoding='utf-8')
os.environ['ACH_MISC_DIR'] = str(_lab)
_with_lab = misc.available()
check('the lab folder is scanned too, skipping _files',
      sorted(n for n, s in _with_lab.items() if s.source == 'lab'),
      ['broken', 'cell_drift', 'hello'])
check('...beside the packaged scripts', set(_all) - {'cell_drift'} <= set(_with_lab), True)
check('a lab script with a packaged name replaces it',
      (_with_lab['cell_drift'].source, _with_lab['cell_drift'].summary),
      ('lab', 'A lab copy that shadows the packaged one.'))
check('a script that will not parse is still listed, saying so',
      _with_lab['broken'].summary.startswith('(cannot be read'), True)
_code, _text = quiet(misc.run, _with_lab['hello'], ['--x'])
check('a lab script runs from its path, told how it was started',
      (_code, _text.strip()), (3, "hello ['--x'] ['achdiff', 'misc', 'run', 'hello']"))
os.environ.pop('ACH_MISC_DIR')

_dest = Path(tempfile.mkdtemp())
_copied = misc.copy(_cd, _dest)
check('copy puts the script where it was asked to', _copied, _dest / 'cell_drift.py')
check('...and will not overwrite without --force', misc.copy(_cd, _dest), None)
check('...but will with it', misc.copy(_cd, _dest, force=True), _dest / 'cell_drift.py')

# ---------- kit ----------
check('choose reads numbers and ranges', kit._selection('1, 3-4', 5), [0, 2, 3])
check('...all and none', (kit._selection('all', 3), kit._selection('none', 3)), ([0, 1, 2], []))
check('...and refuses what is out of range', kit._selection('0,6', 5), None)
_ph = kit.phases(MIX)
check('phases carry the names from the audit line',
      [(p['name'], p['space_group']) for p in _ph], [('ZIF-4', '61'), ('ZIF-zni', '110')])
check('...and the refined volume', _ph[0]['volume'], '4339.512`_0.494')


# ---------- cell_drift: matching ----------
def phase(name, sg, **params):
	return {'name': name, 'space_group': sg, 'params': params, 'volume': None,
	        'system': None, 'file': f'{name}.out'}


_refs = [phase('ZIF-4', '61'), phase(None, '14'), phase('ZIF-zni', '110')]
check('a phase is matched by name', cell_drift.match(phase('zif-4', '61'), _refs)[1], 'name')
check('an unnamed side falls back to a unique space group',
      cell_drift.match(phase(None, '14'), _refs)[1], 'space group')
check('two named phases are never matched on space group alone',
      cell_drift.match(phase('H2bdc', '110'), _refs)[0], None)
check('...but a named mixture phase can match an unnamed pure fit',
      cell_drift.match(phase('H2pPDA', '14'), _refs)[0]['space_group'], '14')

_refs_bad, _t = quiet(cell_drift.load_pure, [str(MIX), str(PURE)])
check('a two-phase file given as pure is refused, and says why',
      ([r['file'] for r in _refs_bad], 'should refine one phase' in _t), ([str(PURE)], True))
_named, _t = quiet(cell_drift.load_pure, [f'Mine={PURE}'])
check('NAME=file names the pure phase', _named[0]['name'], 'Mine')

# ---------- cell_drift: numbers ----------
_rows = {r['label']: r for r in cell_drift.compare(kit.phases(PURE)[0], kit.phases(MIX)[0])}
check('only parameters both fits refined, plus V', sorted(_rows), ['V', 'a', 'b', 'c'])
check('delta is mixture minus pure', round(_rows['a']['delta'], 6), round(15.475318 - 15.516777, 6))
check('delta % is relative to the pure value',
      round(_rows['a']['delta_pct'], 4), round(100 * (15.475318 - 15.516777) / 15.516777, 4))
check('the esd is the two combined in quadrature',
      round(_rows['a']['sigma'], 7), round((0.001995 ** 2 + 0.000986 ** 2) ** 0.5, 7))
check('a TOPAS diagnostic after the esd does not spoil it',
      _rows['b']['pure_esd'], 0.001842)

# ---------- cell_drift: whole runs ----------
_cwd = os.getcwd()
_w = workdir(MIX, PURE)
os.chdir(_w)
try:
	_code, _text = quiet(cell_drift.main,
	                     ['--pure', PURE.name, '--mix', MIX.name, '-s', '-x', 'png', '-d'],
	                     command=['achdiff', 'misc', 'run', 'cell_drift'])
finally:
	os.chdir(_cwd)
check('a run with every argument given succeeds', _code, 0)
check('...writes the table and the figure', sorted(p.name for p in _w.glob('cell_drift.*')),
      ['cell_drift.csv', 'cell_drift.png'])
check('...lists the phase it could not match', 'ZIF-zni (110): skipped' in _text, True)
_rec = next(_w.glob('run*.bat'), None) or next(_w.glob('run*.sh'), None)
check('-d records it as an achdiff misc run command',
      _rec is not None and 'achdiff misc run cell_drift --pure sample-B-cryst.out --mix '
                           'sample-A-cryst.out -s -x png' in _rec.read_text(), True)

# Nobody at the console: missing inputs are an error, not a hang.
_real_interactive = kit.interactive
kit.interactive = lambda: False
_code, _ = quiet(cell_drift.main, [], command=['cell_drift'])
check('without a console, missing inputs stop it with a usage error',
      isinstance(_code, SystemExit) and _code.code, 2)

# The wizard: Enter takes the suggestions -- single-phase fits as pure, the rest
# as mixtures -- then "y" saves.
_answers = iter(['', '', 'y'])
_real_input = builtins.input
kit.interactive = lambda: True
builtins.input = lambda prompt='': next(_answers)
_w2 = workdir(MIX, PURE)
os.chdir(_w2)
try:
	_code, _text = quiet(cell_drift.main, [], command=['achdiff', 'misc', 'run', 'cell_drift'])
finally:
	os.chdir(_cwd)
	builtins.input = _real_input
	kit.interactive = _real_interactive
check('the wizard runs through on its suggestions', _code, 0)
check('...and prints the command that skips it next time',
      'achdiff misc run cell_drift --pure sample-B-cryst.out --mix sample-A-cryst.out -s'
      in _text, True)
check('...having saved the output', (_w2 / 'cell_drift.csv').is_file(), True)

# A copy runs on its own, anywhere: the point of importing only the kit, absolutely.
_w3 = workdir(MIX, PURE)
shutil.copy(_copied, _w3)
_proc = subprocess.run([sys.executable, 'cell_drift.py', '--pure', PURE.name, '--mix', MIX.name,
                        '-s'], cwd=_w3, capture_output=True, text=True,
                       env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'),
                                PYTHONIOENCODING='utf-8'))
check('a copied script runs on its own from another folder',
      (_proc.returncode, (_w3 / 'cell_drift.svg').is_file()), (0, True))
if _proc.returncode:
	print(_proc.stderr[-800:])


# ---------- kit: patterns and series ----------
check('kit reads the pattern types the tools read',
      all(s in kit.PATTERN_TYPES for s in ('.xy', '.dat', '.raw', '.brml')), True)
check('kit.values speaks pp --x-values, stop included',
      kit.values('1,100:300:100'), [1.0, 100.0, 200.0, 300.0])
check('kit.natural_key puts scan_2 before scan_10',
      sorted(['scan_10', 'scan_2'], key=kit.natural_key), ['scan_2', 'scan_10'])


# ---------- heatmap ----------
# Synthetic patterns only: measured data stays out of a public repository.
def write_series(folder, pressures, zeros=0, shift=0.0):
	"""One .xy per pressure: a peak at 5 deg (moving by `shift` per bar) and one at
	9, on a flat background; the last `zeros` points zero, like a masked detector."""
	folder = Path(folder)
	folder.mkdir(parents=True, exist_ok=True)
	x = np.round(np.arange(1.0, 20.0, 0.01), 4)
	for k, p in enumerate(pressures):
		y = (50 + 1000 * np.exp(-0.5 * ((x - 5.0 - shift * p) / 0.03) ** 2)
		     + 300 * np.exp(-0.5 * ((x - 9.0) / 0.03) ** 2))
		if zeros:
			y[-zeros:] = 0.0
		np.savetxt(folder / f'{k:02d}_GH000_650_24062026_{p:g}bar_001.xy',
		           np.column_stack([x, y]), fmt='%.6f')
	return folder


_hm = _all['heatmap']
check('heatmap ships with the package, its first docstring line as summary',
      _hm.summary, 'A pattern series as a heat map: 2theta across, pressure up, intensity as colour.')
check('...and says what it was written for', 'J. Am. Chem. Soc. 2025' in _hm.about.get('for', ''), True)

# Values from the names: the number before a unit, not the sample code or date.
check('the number before a unit, not the sample code or the date',
      heatmap.from_units(['00_GH072a_650_24062026_1bar_001_00000.xy',
                          '01_GH072a_650_24062026_100bar_001_00000.xy']), ([1.0, 100.0], 'bar'))
check('a unit whose number never changes is passed over',
      heatmap.from_units(['CO2_25C_10bar.xy', 'CO2_25C_20bar.xy']), ([10.0, 20.0], 'bar'))
check('a decimal comma reads', heatmap.from_units(['x_0,5GPa.xy', 'x_1,5GPa.xy']),
      ([0.5, 1.5], 'GPa'))
check('a temperature series labels T', heatmap.axis_label(heatmap.from_units(
	['r_300K.xy', 'r_350K.xy'])[1]), '$T$ / K')
check('names without a unit give nothing', heatmap.from_units(['a.xy', 'b.xy']), (None, None))

_pairs, _label = heatmap.series(['s_1000bar.xy', 's_200bar.xy', 's_1bar.xy'])
check('the map goes by value, not by name', [v for v, _p in _pairs], [1.0, 200.0, 1000.0])
check('...and the unit labels the axis as the paper does', _label, '$p$ / bar')


def refused(fn, *a, **kw):
	try:
		fn(*a, **kw)
	except ValueError as e:
		return str(e)
	return None


check('a name without a value among named ones is refused, by name',
      'ambient.xy' in (refused(heatmap.series, ['s_1bar.xy', 's_100bar.xy', 'ambient.xy']) or ''),
      True)
check('two patterns at one value are refused: a return leg is its own map',
      'one map per leg' in (refused(heatmap.series, ['up_100bar.xy', 'down_100bar.xy']) or ''),
      True)
check('--y-values must give one value per pattern, and lists the order it uses',
      (refused(heatmap.series, ['a.xy', 'b.xy', 'c.xy'], y_values=[1.0, 2.0]) or '').count('.xy'), 3)
_pairs, _label = heatmap.series(['scan_10.xy', 'scan_2.xy'], y_values=[5.0, 7.0])
check('--y-values go to the files in natural name order',
      [(v, p) for v, p in _pairs], [(5.0, 'scan_2.xy'), (7.0, 'scan_10.xy')])
check('...with no unit to label the axis', _label, '')
_pairs, _label = heatmap.series(['s_x3_10bar.xy', 's_x1_20bar.xy'], sort_key=r'_x(\d+)_')
check('--sort-key takes its first capture group', [v for v, _p in _pairs], [1.0, 3.0])
check('...and keeps the unit off the axis when it took other numbers', _label, '')
_pairs, _label = heatmap.series(['a.xy', 'b.xy', 'c.xy'])
check('names with no values are numbered', ([v for v, _p in _pairs], _label),
      ([1.0, 2.0, 3.0], 'pattern'))

# Stacked bands: every row is the pattern nearest to it.
_c, _lo, _up, _w = heatmap.rows([0, 100, 300], 300)
check('each band reaches half way to its neighbours; the ends are half bands',
      np.bincount(_lo).tolist(), [50, 150, 100])
check('--smooth blends the two patterns either side, in proportion',
      heatmap.image(np.array([[0.0], [8.0]]), [0, 100], smooth=True, n_rows=4).ravel().tolist(),
      [1.0, 3.0, 5.0, 7.0])
check('the series axis gets the paper\'s ticks: 1, 2000, 4000',
      heatmap.series_ticks(1, 4000), ([1.0, 2000.0, 4000.0], 1000.0))

_x1 = np.linspace(1, 10, 91)
_x2 = np.linspace(2, 12, 51)
_tt, _Z = heatmap.common_grid([(_x1, _x1 * 2), (_x2, _x2 * 2)])
check('patterns on different grids meet on the range they share, at the finer step',
      (round(_tt[0], 6), round(_tt[-1], 6), round(_tt[1] - _tt[0], 6), _Z.shape),
      (2.0, 10.0, 0.1, (2, 81)))
check('...interpolated, not shifted', np.allclose(_Z, _tt * 2), True)
_tt, _Z = heatmap.crop(np.arange(6.0), np.array([[0, 1, 2, 3, 0, 0], [0, 0, 5, 1, 0, 0.0]]))
check('columns zero in every pattern are cut from the ends', _tt.tolist(), [1.0, 2.0, 3.0])
check('a range outside the data is refused',
      'holds no data' in (refused(heatmap.crop, np.arange(6.0), np.ones((2, 6)), (20, 30)) or ''),
      True)

import matplotlib  # noqa: E402
_pubu = matplotlib.colormaps['PuBu']
check('the default colours are PuBu from 0.28, as measured off the paper',
      np.allclose(heatmap.colormap(heatmap.DEFAULT_CMAP)(0.0), _pubu(0.28)), True)
check('a colormap name is found whatever its case', heatmap.colormap('pubu').name, 'PuBu')
check('colours to blend make a colormap',
      np.allclose(heatmap.colormap('white,#08306b')(0.0), (1, 1, 1, 1)), True)
check('a misspelt colormap is refused with suggestions',
      'Did you mean PuBu' in (refused(heatmap.colormap, 'PuBuu') or ''), True)
check('an empty part of a colormap is refused', refused(heatmap.colormap, 'PuBu:0.5:0.2') is None,
      False)
check('a log scale starts above zero',
      heatmap.colour_limits(np.array([[0.0, 2.0, 50.0]]), 'log'), (2.0, 50.0))

# Whole runs.
_w4 = write_series(tempfile.mkdtemp(), [1, 100, 200, 300, 400], zeros=50)
os.chdir(_w4)
try:
	_code, _text = quiet(heatmap.main, ['-s', '-x', 'png', '-d', '--label', 'Mg$_2$(dobdc)'],
	                     command=['achdiff', 'misc', 'run', 'heatmap'])
finally:
	os.chdir(_cwd)
check('a run on a folder of patterns succeeds', _code, 0)
check('...draws every pattern in the folder', '5 patterns from 1 to 400 bar' in _text, True)
check('...leaves the zeroed detector edge out', 'left out' in _text, True)
check('...and writes the figure', (_w4 / 'heatmap.png').is_file(), True)
_rec = next(_w4.glob('run*.bat'), None) or next(_w4.glob('run*.sh'), None)
check('-d records it as an achdiff misc run command',
      _rec is not None and 'achdiff misc run heatmap -s -x png --label' in _rec.read_text(), True)

os.chdir(_w4)
try:
	_code, _text = quiet(heatmap.main, ['-i', '*.xy', '--smooth', '--scale', 'log', '--cmap',
	                                    'viridis', '--colorbar', '--range', '3', '12', '-s',
	                                    '--name', 'every_option'], command=['heatmap'])
	_code_one, _text_one = quiet(heatmap.main, ['-i', '00_*.xy', '-s'], command=['heatmap'])
	_code_cmap, _text_cmap = quiet(heatmap.main, ['--cmap', 'nosuchmap', '-s'], command=['heatmap'])
finally:
	os.chdir(_cwd)
check('a wildcard in -i is expanded by the script, and every option draws',
      (_code, (_w4 / 'every_option.svg').is_file()), (0, True))
check('one pattern is not a map, and it says so',
      (_code_one, 'at least two patterns' in _text_one), (1, True))
check('an unknown colormap stops it before anything is read',
      (_code_cmap, 'no colormap called' in _text_cmap), (1, True))

# The wizard, run bare in a console: Enter takes every pattern and the values
# from the names, no range, then a label, then save.
_answers = iter(['', '', '', 'Mg$_2$(dobdc)', 'y'])
kit.interactive = lambda: True
builtins.input = lambda prompt='': next(_answers)
_w5 = write_series(tempfile.mkdtemp(), [1, 250, 500])
os.chdir(_w5)
try:
	_code, _text = quiet(heatmap.main, [], command=['achdiff', 'misc', 'run', 'heatmap'])
finally:
	os.chdir(_cwd)
	builtins.input = _real_input
	kit.interactive = _real_interactive
check('the wizard runs through on its suggestions', _code, 0)
check('...shows the values it read from the names', '1, 250, 500 bar (3 values)' in _text, True)
check('...prints the command that skips it next time, with a wildcard',
      'achdiff misc run heatmap -i *.xy --label "Mg$_2$(dobdc)" -s' in _text, True)
check('...having saved the figure', (_w5 / 'heatmap.svg').is_file(), True)

# Given any argument it runs straight through, asking nothing.
kit.interactive = lambda: True
builtins.input = lambda prompt='': (_ for _ in ()).throw(AssertionError('asked'))
os.chdir(_w5)
try:
	_code, _text = quiet(heatmap.main, ['-s', '--name', 'straight'], command=['heatmap'])
finally:
	os.chdir(_cwd)
	builtins.input = _real_input
	kit.interactive = _real_interactive
check('with arguments it asks nothing', (_code, (_w5 / 'straight.svg').is_file()), (0, True))

# A copy runs on its own: it needs only the kit.
_w6 = write_series(tempfile.mkdtemp(), [1, 100, 200])
shutil.copy(misc.copy(_hm, Path(tempfile.mkdtemp())), _w6)
_proc = subprocess.run([sys.executable, 'heatmap.py', '-s', '-x', 'png'], cwd=_w6,
                       capture_output=True, text=True,
                       env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'),
                                PYTHONIOENCODING='utf-8'))
check('a copied heatmap runs on its own from another folder',
      (_proc.returncode, (_w6 / 'heatmap.png').is_file()), (0, True))
if _proc.returncode:
	print(_proc.stderr[-800:])


print()
print(f'{len(fails)} failure(s)' + (': ' + ', '.join(fails) if fails else ''))
sys.exit(1 if fails else 0)
