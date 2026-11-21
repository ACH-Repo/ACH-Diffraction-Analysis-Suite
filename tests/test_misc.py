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

# Wildcard templates: * any text, ? one character, # the number, over the whole name.
_gh = ['00_GH077a_27_750_11112026_1bar_001_00000.xy', '17_GH077a_27_750_11112026_1700bar_001_00000.xy']
check('a template reads the number at its #', kit.template_numbers(_gh, '*_#bar_*'),
      [(1.0,), (1700.0,)])
check('...a whole number, never its tail', kit.template_numbers(_gh, '*#bar*'), [(1.0,), (1700.0,)])
check('...in any case', kit.template_numbers(_gh, '*_#BAR_*'), [(1.0,), (1700.0,)])
check('...decimals with a point or a comma', kit.template_numbers(['a_2.5GPa.xy', 'a_0,5GPa.xy'],
                                                                    '*_#GPa.xy'), [(2.5,), (0.5,)])
check('...several #s at once', kit.template_numbers(['T300_run2.xy'], 'T#_run#.xy'), [(300.0, 2.0)])
check('a template covers the whole name, as a wildcard does',
      kit.template_numbers(_gh, '#bar'), [None, None])
_err = None
try:
	kit.template_numbers(_gh, '*_#_*')
except ValueError as e:
	_err = str(e)
check('a template that fits a name two ways is refused, naming both readings',
      _err is not None and '27' in _err and '001' in _err and _gh[0] in _err, True)
check('kit.sort_by_pattern is pp --sort-key',
      kit.sort_by_pattern(['x_run10', 'x_run9', 'other'], r'run(\d+)'),
      (['x_run9', 'x_run10'], ['other']))


# ---------- heatmap ----------
# Synthetic patterns only: measured data stays out of a public repository.
def write_series(folder, pressures, zeros=0, shift=0.0, numbers=None,
                 name='{n:02d}_GH000_650_24062026_{p:g}bar_001.xy'):
	"""One .xy per pressure: a peak at 5 deg (moving by `shift` per bar) and one at
	9, on a flat background; the last `zeros` points zero, like a masked detector.
	`numbers` are the measurement numbers in the names (default 0, 1, 2 ...)."""
	folder = Path(folder)
	folder.mkdir(parents=True, exist_ok=True)
	x = np.round(np.arange(1.0, 20.0, 0.01), 4)
	for n, p in zip(numbers or range(len(pressures)), pressures):
		y = (50 + 1000 * np.exp(-0.5 * ((x - 5.0 - shift * p) / 0.03) ** 2)
		     + 300 * np.exp(-0.5 * ((x - 9.0) / 0.03) ** 2))
		if zeros:
			y[-zeros:] = 0.0
		np.savetxt(folder / name.format(n=n, p=p), np.column_stack([x, y]), fmt='%.6f')
	return folder


_hm = _all['heatmap']
check('heatmap ships with the package, its first docstring line as summary',
      _hm.summary, 'A pattern series as a heat map: 2theta or Q across, pressure up, intensity as '
                   'colour.')
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

_s = heatmap.series(['s_1000bar.xy', 's_200bar.xy', 's_1bar.xy'])
check('values come from the number before a unit, and label the axis as the paper does',
      (sorted(_s.values), _s.label, _s.unit), ([1.0, 200.0, 1000.0], '$p$ / bar', 'bar'))


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
_s = heatmap.series(['scan_10.xy', 'scan_2.xy'], y_values=[5.0, 7.0])
check('--y-values go to the files in measurement order, here the order names sort in',
      list(zip(_s.values, _s.paths)), [(5.0, 'scan_2.xy'), (7.0, 'scan_10.xy')])
check('...with no unit to label the axis', _s.label, '')
_s = heatmap.series(['a.xy', 'b.xy', 'c.xy'])
check('names with no values are numbered', (_s.values, _s.label), ([1.0, 2.0, 3.0], 'pattern'))

# Where the value is: a wildcard template or a regex.
_names = ['p0001_s-a.xy', 'p0250_s-b.xy']
check('--y-name reads the value at its #', heatmap.series(_names, y_name='p#_*').values,
      [1.0, 250.0])
check('--y-regex reads its first group', heatmap.series(_names, y_regex=r'p(\d+)_').values,
      [1.0, 250.0])
check('--y-name needs exactly one #', 'exactly one #' in (refused(
	heatmap.series, _names, y_name='p#_s-#.xy') or ''), True)
check('a template that misses a name says which, and how templates work',
      'p0250_s-b.xy' in (refused(heatmap.series, _names, y_name='p#_s-a.xy') or ''), True)
check('...and one that fits two ways is refused', 'more than one way' in (refused(
	heatmap.series, ['GH077a_27_750_1bar.xy'], y_name='*_#_*') or ''), True)
check('a value from a template keeps the unit off the axis', heatmap.series(
	['s_1bar_x2.xy', 's_2bar_x1.xy'], y_name='*_x#.xy').label, '')

# The measurement order: the order names sort in, a template, or a regex.
_runs = ['b_run1_100bar.xy', 'a_run2_200bar.xy', 'c_run10_300bar.xy']
check('by default, the order the names sort in',
      heatmap.measurement_order(_runs)[0], ['a_run2_200bar.xy', 'b_run1_100bar.xy',
                                             'c_run10_300bar.xy'])
check('--order-name takes it from the # instead',
      heatmap.measurement_order(_runs, template='*_run#_*')[0],
      ['b_run1_100bar.xy', 'a_run2_200bar.xy', 'c_run10_300bar.xy'])
check('--order-regex (pp\'s --sort-key) does the same with a regex',
      heatmap.measurement_order(_runs, regex=r'run(\d+)')[0],
      ['b_run1_100bar.xy', 'a_run2_200bar.xy', 'c_run10_300bar.xy'])
check('...and refuses names it does not match', 'other.xy' in (refused(
	heatmap.measurement_order, _runs + ['other.xy'], regex=r'run(\d+)') or ''), True)
check('--y-values follow the measurement order given',
      heatmap.series(_runs, y_values=[1.0, 2.0, 3.0], order_name='*_run#_*').paths[0],
      'b_run1_100bar.xy')
check('leading numbers are kept, to spot a measurement that is not there',
      heatmap.measurement_order(['00_a.xy', '01_a.xy', '03_a.xy'])[2], [0.0, 1.0, 3.0])
check('...which is a gap in a run of whole numbers', heatmap.sequence_gaps([0, 1, 2, 5]), [3, 4])
check('...and nothing when the numbers are no run',
      (heatmap.sequence_gaps([0.5, 1.5]), heatmap.sequence_gaps([1, 100])), ([], []))

# Steps: the grid the series was measured on, and what has no pattern.
check('1, 100, 200 ... is a series in steps of 100, the first at ambient',
      heatmap.nominal_step([1, 100, 200, 300, 500]), (100.0, 0.0))
check('a grid that does not pass through zero runs through the first value',
      heatmap.nominal_step([5, 15, 25]), (10.0, 5.0))
check('a series with no clear step has none', heatmap.nominal_step([0, 0.5, 1, 2, 4]), None)
check('--step that the values do not fit is refused',
      'do not sit one to a step' in (refused(heatmap.nominal_step, [0, 100, 250], 100) or ''), True)
_steps, _grid = heatmap.plan_steps([1, 100, 200, 300, 500, 600, 1000])
check('every step of the grid is a band, measured or not',
      [(s.centre, s.kind) for s in _steps if s.kind != 'measured'],
      [(400.0, 'missing'), (700.0, 'missing'), (800.0, 'missing'), (900.0, 'missing')])
_steps, _grid = heatmap.plan_steps([1, 100, 200, 300, 500, 600, 1000], fill=True)
check('--fill blends the measured steps either side, by distance',
      [s.mix for s in _steps if s.centre == 700.0], [((5, 0.75), (6, 0.25))])
check('off any grid each pattern is its own band',
      [s.kind for s in heatmap.plan_steps([0, 0.5, 1, 2, 4])[0]], ['measured'] * 5)
check('bands reach half way to the next step, and as far beyond the ends',
      heatmap.bands(heatmap.plan_steps([0, 100, 200])[0]), [(-50.0, 50.0), (50.0, 150.0),
                                                            (150.0, 250.0)])

# The image: each band is its pattern repeated; a step with no pattern is NaN.
_Z = np.array([[0.0], [8.0]])
_two = heatmap.plan_steps([0, 100])[0]
check('stacked, each row is the nearest step',
      heatmap.image(_Z, _two, -50, 150, n_rows=4).ravel().tolist(), [0.0, 0.0, 8.0, 8.0])
check('--smooth blends the steps either side, in proportion',
      heatmap.image(_Z, _two, 0, 100, smooth=True, n_rows=4).ravel().tolist(), [1.0, 3.0, 5.0, 7.0])
_gap = heatmap.plan_steps([0, 200], step=100)[0]
_rows = heatmap.image(_Z, _gap, -50, 250, n_rows=6).ravel().tolist()
check('a step without a pattern stays empty', [np.isnan(r) for r in _rows],
      [False, False, True, True, False, False])
_rows = heatmap.image(_Z, _gap, -50, 250, smooth=True, n_rows=6).ravel().tolist()
check('...smooth too: nothing is blended across it', [np.isnan(r) for r in _rows],
      [False, False, True, True, False, False])
check('the series axis gets the paper\'s ticks: 1, 2000, 4000, minors between',
      heatmap.series_ticks(1, 4000, -50, 4050), ([1.0, 2000.0, 4000.0], [1000.0, 3000.0]))

# The x axis: 2theta or Q, and converting between them.
check('Q = 4 pi sin(theta) / lambda', round(float(kit.convert_x(30.0, '2theta', 'q', 1.5406)), 4),
      round(4 * np.pi * np.sin(np.radians(15)) / 1.5406, 4))
check('...and back', round(float(kit.convert_x(kit.convert_x(30.0, '2theta', 'q', 1.5406), 'q',
                                               '2theta', 1.5406)), 9), 30.0)
check('Q in 1/nm is ten times Q in 1/angstrom, with no wavelength needed',
      float(kit.convert_x(2.0, 'q', 'q-nm')), 20.0)
check('2theta to Q without a wavelength is refused',
      'needs the wavelength' in (refused(kit.convert_x, 30.0, '2theta', 'q') or ''), True)
check('a Q the wavelength cannot reach is refused',
      'cannot' in (refused(kit.convert_x, 9.0, 'q', '2theta', 1.5406) or ''), True)
_hd = Path(tempfile.mkdtemp())
(_hd / 'pyfai.xy').write_text('# == pyFAI calibration ==\n# Wavelength: 2.0730e-11 m\n'
                              '#       q_A^-1             I\n0.1 5\n0.2 6\n', encoding='utf-8')
(_hd / 'dioptas.xy').write_text('# Dioptas export\n#       2th_deg             I\n1 5\n2 6\n',
                                encoding='utf-8')
(_hd / 'bare.xy').write_text('1 5\n2 6\n', encoding='utf-8')
check('a pyFAI header gives the x quantity and the wavelength, in angstrom',
      tuple(round(v, 6) if isinstance(v, float) else v for v in kit.x_from_header(_hd / 'pyfai.xy')),
      ('q', 0.2073))
check('...a DIOPTAS one the quantity',
      (kit.x_from_header(_hd / 'dioptas.xy'), kit.x_from_header(_hd / 'bare.xy')),
      (('2theta', None), (None, None)))
_xi = heatmap.x_setup([_hd / 'pyfai.xy'])
check('with no flags, the header decides', (_xi['data'], _xi['axis'], _xi['data_how']),
      ('q', 'q', 'from the file headers'))
_xi = heatmap.x_setup([_hd / 'bare.xy'])
check('with no header either, the files are taken as 2theta, and the notes say so',
      (_xi['data'], 'no header' in _xi['data_how']), ('2theta', True))
check('--x-data against the header is a warning, and --x-data wins',
      (heatmap.x_setup([_hd / 'pyfai.xy'], x_data='2theta')['data'],
       heatmap.x_setup([_hd / 'pyfai.xy'], x_data='2theta')['warning'] is not None), ('2theta', True))
check('headers that disagree are refused', 'disagree' in (refused(
	heatmap.x_setup, [_hd / 'pyfai.xy', _hd / 'dioptas.xy']) or ''), True)
check('a conversion takes the header\'s wavelength',
      heatmap.x_setup([_hd / 'pyfai.xy'], x_axis='2theta')['wavelength_how'], 'from the file headers')
check('...and without any wavelength is refused', 'needs the wavelength' in (refused(
	heatmap.x_setup, [_hd / 'bare.xy'], x_axis='q') or ''), True)
_grid, _Zg = heatmap.even_grid(np.array([0.0, 1.0, 3.0]), np.array([[0.0, 1.0, 3.0]]))
check('an uneven grid, as Q from 2theta is, goes onto an even one at its finest step',
      (_grid.tolist(), _Zg.tolist()), ([0.0, 1.0, 2.0, 3.0], [[0.0, 1.0, 2.0, 3.0]]))

import matplotlib  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
_args = heatmap.build_parser().parse_args(['--x-data', 'q'])
_st, _gr = heatmap.plan_steps([0, 100])
with plt.rc_context(heatmap.STYLE):
	_fig, _shape = heatmap.figure(np.linspace(1, 10, 50), np.ones((2, 50)) + np.arange(50), _st, 0,
	                              100, kit.X_QUANTITIES['q'].label, '$p$ / bar',
	                              heatmap.colormap('PuBu'), matplotlib.colors.Normalize(0, 60), _args)
check('the plot is labelled with the quantity, and holds no text by default',
      (_fig.axes[0].get_xlabel(), [t.get_text() for t in _fig.axes[0].texts]),
      (r'$Q$ / Å$^{-1}$', []))
plt.close(_fig)

# Style sheets: the heat map is a plotter like pp and pq, with sheets of its own.
from achdiff import styles  # noqa: E402
check('heatmap has style sheets of its own', 'heatmap' in styles.TOOLS, True)
_tpl = styles.template('heatmap')
check('...whose template lists every setting at the built-in value',
      ("# tick_direction = 'out'" in _tpl, '# tick_label_size = 8' in _tpl,
       "# colormap = 'PuBu:0.28'" in _tpl), (True, True, True))
check('...and the keys pp and pq have are spelled the same here',
      all(k in styles.BY_NAME['heatmap'] for k in (
	      'figsize', 'dpi', 'extension', 'tick_direction', 'tick_label_size', 'axis_label_size',
	      'ticks_top', 'tick_length_major', 'tick_length_minor', 'x_tick_step')), True)
check('every key drives a setting the heat map has',
      [k.target for k in styles.BY_NAME['heatmap'].values() if k.target not in heatmap.settings], [])
_sheet = Path(tempfile.mkdtemp()) / 'inside.toml'
_sheet.write_text("[axes]\ntick_direction = 'in'\ntick_label_size = 6\naxis_label_size = 7\n"
                  "ticks_right = true\nobserved_color = 'red'\n", encoding='utf-8')
_look = dict(heatmap.settings)
_applied, _text_s = quiet(kit.apply_style, 'heatmap', _look, explicit=str(_sheet))
_rc = heatmap.rc_params(_look)
check('a sheet turns the ticks in, shrinks numbers and labels, mirrors the ticks',
      (_rc['xtick.direction'], _rc['ytick.labelsize'], _rc['axes.labelsize'], _rc['ytick.right']),
      ('in', 6.0, 7.0, True))
check("...says it was used, and that a pp setting in it is pp's",
      ('[*] Style:' in _text_s, 'only pp has' in _text_s), (True, True))
check('...and leaves the built-in look as it was', heatmap.settings['tick_direction'], 'out')

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
_notes = (_w4 / 'heatmap_SI.txt').read_text(encoding='utf-8') if (_w4 / 'heatmap_SI.txt').is_file() else ''
check('...with SI notes beside it, saying how the map was made',
      ('For the supporting information' in _notes, 'nominal steps of 100 bar' in _notes,
       'Stretching' in _notes), (True, True, True))

# A series with gaps, as measured: no 400 bar, and numbers 6 and 7 missing.
_w7 = write_series(tempfile.mkdtemp(), [1, 100, 200, 300, 500, 600, 1000],
                   numbers=[0, 1, 2, 3, 4, 5, 8])
os.chdir(_w7)
try:
	_code, _text = quiet(heatmap.main, ['-s', '-x', 'png', '--name', 'gaps'], command=['heatmap'])
	_code_f, _text_f = quiet(heatmap.main, ['-s', '-x', 'png', '--fill', '--name', 'filled'],
	                         command=['heatmap'])
	_code_a, _text_a = quiet(heatmap.main, ['--y-name', '*_#_*', '-s'], command=['heatmap'])
finally:
	os.chdir(_cwd)

def notes_text(path):
	"""The SI notes with their line wrapping undone, to search for phrases."""
	return ' '.join(path.read_text(encoding='utf-8').split()) if path.is_file() else ''


_gaps, _filled = notes_text(_w7 / 'gaps_SI.txt'), notes_text(_w7 / 'filled_SI.txt')
check('steps without a pattern are named, and hatched',
      (_code, 'No pattern at 400, 700, 800 and 900 bar: hatched' in _text), (0, True))
check('...and the SI notes say so, and that numbers 6 and 7 are not there',
      ('these steps are shown hatched' in _gaps, 'without 6 and 7' in _gaps), (True, True))
check('--fill interpolates them, and the notes give the weights',
      (_code_f, 'interpolated: 0.75 x 600 + 0.25 x 1000' in _filled,
       'filled by linear interpolation' in _filled), (0, True, True))
check('a template that fits the names two ways stops the run, saying so',
      (_code_a, 'more than one way' in _text_a), (1, True))

# Q data: given with --x-data, read from a header, or converted from 2theta.
os.chdir(_w7)
try:
	_code_q, _text_q = quiet(heatmap.main, ['--x-data', 'q', '-s', '-x', 'png', '--name', 'q'],
	                         command=['heatmap'])
	_code_c, _text_c = quiet(heatmap.main, ['--x-axis', 'q', '--wavelength', '1.5406', '-s', '-x',
	                                        'png', '--name', 'conv'], command=['heatmap'])
finally:
	os.chdir(_cwd)
check('--x-data q puts Q on the axis and in the notes',
      (_code_q, 'Q 1 to 19.99 1/A' in _text_q,
       'Q in Å⁻¹, as in the files (given with --x-data)' in notes_text(_w7 / 'q_SI.txt')),
      (0, True, True))
check('--x-axis q converts from 2theta, and the notes say with what wavelength',
      (_code_c, 'converted from 2θ to Q with λ = 1.5406 Å' in notes_text(_w7 / 'conv_SI.txt')),
      (0, True))
_w9 = Path(tempfile.mkdtemp())
for _p in (1, 100, 200):
	(_w9 / f's_{_p}bar.xy').write_text(
		'# Wavelength: 2.0730e-11 m\n#   q_A^-1   I\n'
		+ ''.join(f'{q:.3f} {50 + 900 * np.exp(-0.5 * ((q - 2) / 0.02) ** 2):.3f}\n'
		          for q in np.arange(0.5, 5.0, 0.005)), encoding='utf-8')
os.chdir(_w9)
try:
	_code_h, _text_h = quiet(heatmap.main, ['-s', '-x', 'png'], command=['heatmap'])
finally:
	os.chdir(_cwd)
check('files whose header says Q are drawn in Q without a flag',
      (_code_h, 'x: Q in 1/A, from the file headers.' in _text_h), (0, True))
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

# The wizard, run bare in a console: Enter takes every pattern, 2theta, their
# order and the values from the names, no range, then a label, then save.
_answers = iter(['', '', '', '', '', 'Mg$_2$(dobdc)', 'y'])
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

# Names that sort out of order and carry no unit: the wizard asks for templates.
_w8 = Path(tempfile.mkdtemp())
_x = np.arange(1.0, 20.0, 0.01)
for _stem, _p in (('b_run1', 100), ('a_run2', 200), ('c_run3', 300)):
	np.savetxt(_w8 / f'{_stem}_p{_p}.xy',
	           np.column_stack([_x, 50 + 1000 * np.exp(-0.5 * ((_x - 5) / 0.03) ** 2)]))
_answers = iter(['', 'q', 'n', '*_run#_*', '*_p#.xy', '$p$ / MPa', '', '', 'y'])
kit.interactive = lambda: True
builtins.input = lambda prompt='': next(_answers)
os.chdir(_w8)
try:
	_code, _text = quiet(heatmap.main, [], command=['achdiff', 'misc', 'run', 'heatmap'])
finally:
	os.chdir(_cwd)
	builtins.input = _real_input
	kit.interactive = _real_interactive
check('the wizard takes Q, and the order and the values as templates',
      (_code, 'achdiff misc run heatmap -i *.xy --x-data q --order-name *_run#_* --y-name '
              '*_p#.xy --y-label "$p$ / MPa" -s' in _text), (0, True))
check('...showing what each template reads before taking it',
      ('In that order: b_run1_p100.xy' in _text, 'Reads 100, 200, 300 (3 values)' in _text),
      (True, True))

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

# A style sheet in a whole run: format, colours and size, and flags still win.
_sheet2 = Path(tempfile.mkdtemp()) / 'small-png.toml'
_sheet2.write_text("extension = 'png'\ncolormap = 'viridis'\nfigsize = [3.0, 1.0]\ndpi = 100\n",
                   encoding='utf-8')
os.chdir(_w5)
try:
	_code, _text = quiet(heatmap.main, ['-s', '--style', str(_sheet2), '--name', 'styled'],
	                     command=['heatmap'])
	_code2, _ = quiet(heatmap.main, ['-s', '--style', str(_sheet2), '--size', '4', '1', '--name',
	                                 'sized'], command=['heatmap'])
	_code3, _text3 = quiet(heatmap.main, ['-s', '--style', 'nosuchstyle'], command=['heatmap'])
finally:
	os.chdir(_cwd)
check('a sheet sets the format, colours and size of a run',
      (_code, 'Colours viridis' in _text, (_w5 / 'styled.png').is_file()
       and plt.imread(str(_w5 / 'styled.png')).shape[:2]), (0, True, (100, 300)))
check('...and a flag still overrides it for one plot',
      (_code2, (_w5 / 'sized.png').is_file() and plt.imread(str(_w5 / 'sized.png')).shape[:2]),
      (0, (100, 400)))
check('a --style that is not there stops the run, saying where it looked',
      (_code3, 'Style file not found' in _text3), (2, True))

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
