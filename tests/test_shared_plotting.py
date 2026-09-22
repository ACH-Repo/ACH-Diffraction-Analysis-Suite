"""Assertions for what pp and pq share: -d, -m, -b, and per-plotter style sheets.

Run: python tests/test_shared_plotting.py
Uses ACH_CONFIG_DIR to redirect config and style sheets into a temp dir, so a
test run can never touch -- or migrate -- the real ones.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

_TMP = tempfile.mkdtemp()
os.environ['ACH_CONFIG_DIR'] = _TMP
os.environ['MPLBACKEND'] = 'Agg'
for _v in ('CIF_LOC', 'ACH_USER', 'ACH_STYLE', 'ACH_STYLE_PP', 'ACH_STYLE_PQ'):
	os.environ.pop(_v, None)

import numpy as np  # noqa: E402

from achdiff import document, styles  # noqa: E402
from achdiff.core import overlays  # noqa: E402
from achdiff.tools import plotter, quickplot  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'

fails = []


def check(label, got, want):
	ok = got == want
	print(f'{"ok  " if ok else "FAIL"} {label}')
	print(f'       got={got!r}')
	if not ok:
		print(f'       want={want!r}')
		fails.append(label)


# ---------- -d: which spellings of -d are left out of the file ----------
_pp = plotter._build_parser()
_pq = quickplot._build_parser()

check('-d and --document are dropped',
      document.without_document_flag(_pp, ['-s', '-d', '-c', '--document']), ['-s', '-c'])
check('an abbreviation argparse would accept is dropped too',
      document.without_document_flag(_pp, ['--doc', '-s']), ['-s'])
check('-d inside a cluster of flags is taken out of it, either side',
      (document.without_document_flag(_pp, ['-sd']), document.without_document_flag(_pp, ['-dsc'])),
      (['-s'], ['-sc']))
# In -xd the d is -x's value: the extension "d". Taking it out would change the command.
check('a d that is the value of the flag before it stays',
      document.without_document_flag(_pp, ['-xd']), ['-xd'])
check('a value that merely starts with -d stays',
      document.without_document_flag(_pq, ['-t', '-d spacing', '-s']), ['-t', '-d spacing', '-s'])
check('--dpi is not an abbreviation of --document',
      document.without_document_flag(_pq, ['--dpi', '600', '-d']), ['--dpi', '600'])
check('everything after -- is kept as given',
      document.without_document_flag(_pp, ['-s', '--', '-d']), ['-s', '--', '-d'])

# ---------- -d: numbering ----------
_runs = Path(tempfile.mkdtemp())
check('the first file is run1', document.next_run_path(_runs, suffix='.bat').name, 'run1.bat')
check('a silent run gets _s', document.next_run_path(_runs, silent=True, suffix='.bat').name,
      'run1_s.bat')
for _name in ('run1.bat', 'run2_s.bat', 'run5.bat', 'runaway.bat', 'run7.txt'):
	(_runs / _name).write_text('')
# One counter across both kinds, one past the highest, gaps and all: run5 was
# kept and run3/run4 were deleted, and reusing 3 would make run3 newer than run5.
check('one counter covers both kinds and is never reused',
      (document.next_run_path(_runs, suffix='.bat').name,
       document.next_run_path(_runs, silent=True, suffix='.bat').name),
      ('run6.bat', 'run6_s.bat'))

# ---------- -d: what is written ----------
check('a plain argument is written as it is', document.bat_argument('20,40,10'), '20,40,10')
check('% is doubled, as a .bat line needs', document.bat_argument('2%'), '2%%')
check('...and doubled twice under CALL', document.bat_argument('2%', via_call=True), '2%%%%')
check('brackets are quoted, as pq -m needed at the prompt',
      document.bat_argument('((20,30,3))'), '"((20,30,3))"')
check('a trailing backslash is doubled before the closing quote',
      document.bat_argument('C:\\my dir\\'), '"C:\\my dir\\\\"')
check('an empty argument survives as ""', document.bat_argument(''), '""')

_w = Path(tempfile.mkdtemp())
_path = document.write_run_file(_pp, 'pp', 'achdiff.tools.plotter', silent=True,
                                argv=['-s', '-d', '-b', '23.4,2%'], directory=_w)
_body = _path.read_text(encoding='ascii') if _path else ''
check('write_run_file names a silent run _s', _path and _path.name,
      'run1_s.bat' if os.name == 'nt' else 'run1_s.sh')
check('the command is recorded without -d', '-s -b 23.4,2%' in _body, True)
if os.name == 'nt':
	check('a .bat runs where it lives, and stops on an error',
	      ('cd /d "%~dp0"' in _body, 'if errorlevel 1 pause' in _body), (True, True))
	check('an ASCII command needs no code page change', 'chcp' in _body, False)
_second = document.write_run_file(_pp, 'pp', 'achdiff.tools.plotter',
                                  argv=['-c'], directory=_w)
check('the next run takes the next number', _second and _second.stem, 'run2')


# ---------- -m ----------
check('a,b,N', overlays.parse_multiply(['20,40,10']), [overlays.Multiply(20.0, 40.0, 10.0, None)])
check('several ranges after one -m', len(overlays.parse_multiply(['20,40,10', '45,50,5'])), 2)
check('open ends are kept open until the data range is known',
      overlays.parse_multiply([',40,10', '45,,5']),
      [overlays.Multiply(None, 40.0, 10.0, None), overlays.Multiply(45.0, None, 5.0, None)])
check("pq's old bracketed form still parses, colour and all",
      overlays.parse_multiply('((20,30,3,r),(35,45,5))'),
      [overlays.Multiply(20.0, 30.0, 3.0, 'r'), overlays.Multiply(35.0, 45.0, 5.0, None)])
check('bounds typed the wrong way round are put right',
      overlays.parse_multiply(['40,20,2'])[0][:2], (20.0, 40.0))
check('a group that cannot be read is skipped, not fatal',
      overlays.parse_multiply(['20,40', 'a,b,c', '20,40,2,nosuchcolour']),
      [overlays.Multiply(20.0, 40.0, 2.0, None)])
check('resolve fills the open ends from the data range',
      overlays.resolve(overlays.parse_multiply([',40,10', '45,,5']), 5.0, 60.0),
      [overlays.Multiply(5.0, 40.0, 10.0, None), overlays.Multiply(45.0, 60.0, 5.0, None)])

_x = np.array([1.0, 2.0, 3.0, 4.0])
_y = np.array([2.0, 2.0, 2.0, 2.0])
check('scale multiplies the signal above the baseline, only inside the range',
      overlays.scale(_x, _y, [overlays.Multiply(2.0, 3.0, 3.0, None)], baseline=1.0).tolist(),
      [2.0, 4.0, 4.0, 2.0])
check('overlapping ranges multiply together',
      overlays.scale(_x, _y, [overlays.Multiply(1.0, 3.0, 2.0, None),
                              overlays.Multiply(3.0, 4.0, 5.0, None)]).tolist(),
      [4.0, 4.0, 20.0, 10.0])
check('scale leaves its input alone', _y.tolist(), [2.0, 2.0, 2.0, 2.0])

# ---------- -b ----------
check('x alone takes the default width and colour',
      overlays.parse_bands(['23.4']), [overlays.Band(23.4, None, None)])
check('a width in degrees, and one as a share of the plot',
      [b.width for b in overlays.parse_bands(['23.4,0.3', '31.2,2%'])],
      [('deg', 0.3), ('pct', 2.0)])
check('an empty width with a colour after it',
      overlays.parse_bands(['12,,lightblue']), [overlays.Band(12.0, None, 'lightblue')])
check('a width that is not positive falls back to the default',
      overlays.parse_bands(['12,-1', '13,zero'])[0].width, None)

import matplotlib.pyplot as plt  # noqa: E402

_fig, _ax = plt.subplots()
overlays.draw_bands(_ax, overlays.parse_bands(['20', '30,0.5', '40,10%,red']), 0.0, 50.0)
_spans = [(round(p.get_x() if hasattr(p, 'get_x') else p.get_xy()[0][0], 6),
           round((p.get_width() if hasattr(p, 'get_width')
                  else p.get_xy()[2][0] - p.get_xy()[0][0]), 6))
          for p in _ax.patches]
check('the default strip is 1 % of the plot width, centred on x',
      _spans[0], (19.75, 0.5))
check('a width in degrees is taken as given', _spans[1], (29.75, 0.5))
check('a percentage is of the plot width', _spans[2], (37.5, 5.0))
check('strips sit behind everything', {p.get_zorder() for p in _ax.patches}, {-1})
check('strips stay out of the legend',
      {p.get_label() for p in _ax.patches}, {'_nolegend_'})
plt.close(_fig)

_fig, _ax = plt.subplots()
overlays.draw_multiply_marks(_ax, overlays.resolve(overlays.parse_multiply(['20,40,10']), 0, 60), 0, 60)
check("the label reads 'x 10', not 'x 10.0'", [t.get_text() for t in _ax.texts], ['x 10'])
check('both edges are marked with dashed lines that stay out of the legend',
      [(l.get_xdata()[0], l.get_linestyle(), l.get_label()) for l in _ax.lines],
      [(20.0, '--', '_nolegend_'), (40.0, '--', '_nolegend_')])
plt.close(_fig)


# ---------- pp: every range reaches the difference curve ----------
# Before the shared code, pp drew each range's markers before scaling the next
# range, and found the difference curve as the last line -- so a second range
# reached a marker instead, and `pp -m 20,30,10 45,,5` died with a TypeError.
_fit = Path(tempfile.mkdtemp())
for _f in EXAMPLES.glob('sample-A-cryst_pawley_01_*.txt'):
	shutil.copy(_f, _fit)
shutil.copy(EXAMPLES / 'sample-A-cryst.out', _fit)

_captured = {}
_real_savefig = plotter.plt.savefig


def _capture(*a, **kw):
	fig = plotter.plt.gcf()
	_captured['lines'] = [(l.get_xdata().copy(), np.asarray(l.get_ydata(), float).copy())
	                      for l in fig.axes[0].lines]


_cwd = os.getcwd()
os.chdir(_fit)
sys.argv = ['pp', '-s', '-m', '20,30,10', '45,,5', '-b', '25']
plotter.plt.savefig = _capture
try:
	plotter.main()
finally:
	plotter.plt.savefig = _real_savefig
	os.chdir(_cwd)

_dx, _draw = plotter.get_x_y(str(_fit / 'sample-A-cryst_pawley_01_X_Difference.txt'))
_n_ticks = len(list(_fit.glob('*_2Th_Ip_*.txt')))
_px, _py = _captured['lines'][2 + _n_ticks]   # exp, calc, ticks..., difference


def _spread_ratio(lo, hi):
	"""How much wider the plotted difference curve swings than the raw one in
	[lo, hi]. Differences cancel the vertical shift the layout applies."""
	m = (_dx >= lo) & (_dx <= hi)
	return float(np.ptp(_py[m]) / np.ptp(_draw[m]))


check('pp scales the difference curve in the first range',
      round(_spread_ratio(20, 30), 6), 10.0)
check('...and in the second one too', round(_spread_ratio(45, 90), 6), 5.0)
check('...and leaves it alone outside both', round(_spread_ratio(31, 44), 6), 1.0)

sys.argv = ['pp', '-s', '--multply', '20,40,10']
try:
	plotter._build_parser().parse_args(sys.argv[1:])
	check('pp refuses a mistyped flag instead of ignoring it', 'accepted', 'SystemExit')
except SystemExit:
	check('pp refuses a mistyped flag instead of ignoring it', 'SystemExit', 'SystemExit')


# ---------- style sheets belong to one plotter ----------
_root = Path(_TMP) / styles.STYLES_DIRNAME
(_root / 'pp').mkdir(parents=True, exist_ok=True)
(_root / 'pq').mkdir(parents=True, exist_ok=True)
(_root / 'pp' / 'SS.toml').write_text("[axes]\naxis_label_size = 20\ntrace_label_size = 4\n",
                                      encoding='utf-8')
(_root / 'pq' / 'SS.toml').write_text("[axes]\naxis_label_size = 7\n", encoding='utf-8')

_pp_target, _pq_target = dict(plotter.settings), dict(quickplot.settings)
styles.apply('pp', _pp_target, user='SS')
styles.apply('pq', _pq_target, user='SS')
check("a pp sheet sets pp's value and a pq sheet pq's, for the same key",
      (_pp_target['size_axis_labels'], _pq_target['size_axis_labels']), (20.0, 7.0))
check("a pq setting written in a pp sheet does not reach pp",
      'trace_label_size' in _pp_target, False)
check('...and is reported as belonging to pq',
      styles._other_tools_keys('pp', ['trace_label_size', 'nonsense']), {'trace_label_size': 'pq'})

os.environ['ACH_STYLE'] = str(_root / 'pq' / 'SS.toml')
check('the old ACH_STYLE still means pp',
      ([p.name for p in styles.layer_paths('pp')], styles.layer_paths('pq')), (['SS.toml'], []))
os.environ.pop('ACH_STYLE')
os.environ['ACH_STYLE_PQ'] = 'SS'
check('ACH_STYLE_PQ names a pq sheet, looked up in styles/pq/',
      [p.parent.name for p in styles.layer_paths('pq')], ['pq'])
os.environ.pop('ACH_STYLE_PQ')

check('the -b and -m style settings exist in both plotters',
      [k in plotter.settings and k in quickplot.settings
       for k in ('band_color', 'band_width', 'multiply_label_size', 'x_tick_step')],
      [True] * 4)

# ---------- default flags ----------
from achdiff import cmdline, config  # noqa: E402

config.save_default_flags('pp', ['-c', '-m', '20,40,10'], user='FL')
config.save_default_flags('pq', ['-d'])                       # [defaults], for everyone
config.save_default_flags('pq', [], user='NOPE')              # opts NOPE out of it
check("a profile's flags come from the profile",
      config.default_flags('pp', 'FL'), (['-c', '-m', '20,40,10'], 'profile FL'))
check('[defaults] covers a profile with none of its own',
      config.default_flags('pq', 'FL'), (['-d'], '[defaults]'))
check('an empty list opts a profile out of [defaults]',
      config.default_flags('pq', 'NOPE'), ([], 'profile NOPE'))
config.save_default_flags('pq', None, user='NOPE')
check('clearing it falls back to [defaults] again',
      config.default_flags('pq', 'NOPE'), (['-d'], '[defaults]'))
config.save_default_flags('pq', None)

config.save_profile('FL', {'qall': True})
check("a profile's qall = true counts as a default --qall",
      cmdline.default_flags('pp', 'FL')[0], ['-c', '-m', '20,40,10', '--qall'])

check('defaults are checked by the tool\'s own parser',
      cmdline.check_defaults('pp', ['--multply', '2']), 'unrecognized arguments: --multply 2')
check('-u cannot be a default', cmdline.check_defaults('pp', ['-u', 'CN']).startswith('-u'), True)
check('nor --save-profile', 'save-profile' in cmdline.check_defaults('pq', ['--save-profile']), True)
check('nor a bare value such as an .inp file',
      cmdline.check_defaults('rp', ['fit.inp']) is not None, True)
check('good flags pass', cmdline.check_defaults('pp', ['-d', '-c', '-m', '20,40,10']), None)

check('a typed flag replaces the same default, and the record says so once',
      cmdline.merge(_pp, ['-c', '-m', '20,40,10', '-x', 'svg'], ['-s', '-m', '45,,5', '-xpng']),
      (['-c', '-s', '-m', '45,,5', '-xpng'], ['-m', '20,40,10', '-x', 'svg']))

_rec = Path(tempfile.mkdtemp())
os.chdir(_rec)
os.environ['ACH_USER'] = 'FL'
config.save_default_flags('pp', ['-d', '-c', '-m', '20,40,10'], user='FL')
try:
	_args = cmdline.parse_args(plotter._build_parser(), 'pp', 'achdiff.tools.plotter',
	                           argv=['-s'], silent=lambda a: a.silent)
finally:
	os.environ.pop('ACH_USER')
	os.chdir(_cwd)
check('default flags reach the run', (_args.cell_info, _args.multiply, _args.qall, _args.document),
      (True, ['20,40,10'], True, True))
_files = sorted(p.name for p in _rec.iterdir())
check('a default -d writes a record like a typed one',
      _files, ['run1_s.bat' if os.name == 'nt' else 'run1_s.sh'])
_line = [ln for ln in (_rec / _files[0]).read_text(encoding='utf-8').splitlines()
         if ln.startswith('pp ') or ' -m ' in ln][0]
check('the record spells out the defaults, skips them on replay, and pins the profile',
      _line.split(' ', 1)[1], '-c -m 20,40,10 --qall -s --no-defaults -u FL')

# The record must replay to the same run however the defaults change later.
config.save_default_flags('pp', ['-d', '-b', '12'], user='FL')
_replay = cmdline.parse_args(plotter._build_parser(), 'pp', 'achdiff.tools.plotter',
                             argv=_line.split(' ')[1:])
check('...and replays to the same flags after the defaults change',
      (_replay.cell_info, _replay.multiply, _replay.qall, _replay.band, _replay.document,
       _replay.user),
      (True, ['20,40,10'], True, None, False, 'FL'))


# ---------- the one-time move out of the flat layout ----------
_old = Path(tempfile.mkdtemp())
os.environ['ACH_CONFIG_DIR'] = str(_old)
(_old / 'styles' / 'pp').mkdir(parents=True)
(_old / 'styles' / 'CN.toml').write_text("legend_fontsize = 9\n", encoding='utf-8')
(_old / 'styles' / 'narrow.toml').write_text("figsize = [3.3, 4.0]\n", encoding='utf-8')
(_old / 'styles' / 'pp' / 'narrow.toml').write_text("figsize = [3.0, 4.0]\n", encoding='utf-8')
styles._migrated = False
styles.styles_root()
check('flat sheets move into styles/pp/', (_old / 'styles' / 'pp' / 'CN.toml').is_file(), True)
check('...and are not left behind as a second copy', (_old / 'styles' / 'CN.toml').exists(), False)
check('a name already taken in pp/ is left where it is, not overwritten',
      ((_old / 'styles' / 'narrow.toml').is_file(),
       (_old / 'styles' / 'pp' / 'narrow.toml').read_text(encoding='utf-8')),
      (True, "figsize = [3.0, 4.0]\n"))
os.environ['ACH_CONFIG_DIR'] = _TMP


print()
print(f'{len(fails)} failure(s)' + (': ' + ', '.join(fails) if fails else ''))
sys.exit(1 if fails else 0)
