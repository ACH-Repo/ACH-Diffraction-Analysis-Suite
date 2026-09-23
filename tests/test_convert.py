"""Assertions for conv, and for the readers and CIF simulation it shares with pq.

Run: python tests/test_convert.py
Uses ACH_CONFIG_DIR to redirect config into a temp dir, and converts copies of
the example files in another, so a test run touches nothing real.
"""

import argparse
import contextlib
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

_TMP = tempfile.mkdtemp()
os.environ['ACH_CONFIG_DIR'] = _TMP
os.environ['MPLBACKEND'] = 'Agg'
for _v in ('ACH_USER', 'CIF_LOC'):
	os.environ.pop(_v, None)

import numpy as np  # noqa: E402

from achdiff import cli, cmdline, config  # noqa: E402
from achdiff.core import cif as cifcore, readers  # noqa: E402
from achdiff.tools import convert, prefit, quickplot  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'
BRML = 'sample-A-P4-cryst.brml'
DAT = 'sample-B-F-0.20-dry.dat'
XY = 'sample-C_300_001_00000.xy'
CIF = 'H2bdc.cif'

fails = []


def check(label, got, want):
	ok = got == want
	print(f'{"ok  " if ok else "FAIL"} {label}')
	print(f'       got={got!r}')
	if not ok:
		print(f'       want={want!r}')
		fails.append(label)


def run(*argv):
	"""conv's exit code and what it printed."""
	out = io.StringIO()
	with contextlib.redirect_stdout(out):
		code = convert.main(list(argv))
	return code, out.getvalue()


def workdir(*names):
	"""A fresh folder holding copies of the named example files, made current."""
	d = Path(tempfile.mkdtemp())
	for name in names:
		shutil.copy(EXAMPLES / name, d / name)
	os.chdir(d)
	return d


# ---------- one reader for pq, pf and conv ----------
check('pq reads the measured formats through core.readers',
      [quickplot.READERS[e] for e in ('xy', 'txt', 'csv', 'brml')],
      [readers.read_xy] * 3 + [readers.read_brml])
check('pf reads through core.readers',
      [a.tolist() for a in prefit.read_experimental(str(EXAMPLES / DAT))],
      [a.tolist() for a in readers.read(str(EXAMPLES / DAT))])

try:
	readers.read('x.foo')
	_refused = None
except ValueError as e:
	_refused = str(e)
check('an unknown extension is refused, naming it', _refused, 'No reader for .foo: x.foo')


# ---------- the file conv writes ----------
d = workdir(BRML, DAT)
code, out = run()
check('with no -i, every .brml/.raw/.dat here is converted', code, 0)
check('...each to <stem>.xy beside it',
      sorted(p.name for p in d.glob('*.xy')),
      ['sample-A-P4-cryst.xy', 'sample-B-F-0.20-dry.xy'])

first = (d / 'sample-A-P4-cryst.xy').read_bytes().splitlines()[0]
check('two columns separated by one tab, no header', first.count(b'\t'), 1)
check('...and no float noise in 2theta', first.split(b'\t')[0], b'3.0001')

for src in (BRML, DAT):
	x0, y0 = readers.read(src)
	x1, y1 = readers.read(Path(src).stem + '.xy')
	check(f'{src}: the .xy reads back as the pattern it came from',
	      (x1.size == x0.size, bool(np.allclose(x1, x0, rtol=0, atol=1e-6)),
	       bool(np.allclose(y1, y0, rtol=0, atol=1e-6))),
	      (True, True, True))

check('_number trims zeros and keeps six decimals at most',
      [convert._number(v) for v in (5.0, 1523.0, 3.0205000000000002, 0.1234567891, -2.5)],
      ['5', '1523', '3.0205', '0.123457', '-2.5'])


# ---------- what it leaves alone ----------
(d / 'sample-B-F-0.20-dry.xy').write_text('keep me\n', encoding='utf-8')
code, out = run()
check('an existing .xy is not overwritten',
      (d / 'sample-B-F-0.20-dry.xy').read_text(encoding='utf-8'), 'keep me\n')
check('...and the run says how to overwrite it', '-f overwrites' in out, True)
code, out = run('-f')
check('-f overwrites it', (d / 'sample-B-F-0.20-dry.xy').read_text(encoding='utf-8')[:1], '5')

d = workdir(XY)
before = (d / XY).read_bytes()
code, out = run('-i', XY, '-f')
check('an .xy named with -i is never rewritten over itself, even with -f',
      ((d / XY).read_bytes() == before, 'already an .xy' in out), (True, True))

d = workdir(BRML)
shutil.copy(d / BRML, d / 'sample-A-P4-cryst.dat')
code, out = run()
check('two files with one name: the .brml is converted, the other skipped',
      ('just written from sample-A-P4-cryst.brml' in out,
       (d / 'sample-A-P4-cryst.xy').read_bytes().splitlines()[0].split(b'\t')[0]),
      (True, b'3.0001'))


# ---------- -i, -o ----------
d = workdir(BRML, DAT)
code, out = run('-i', '*.dat', '-o', 'xy')
check('-i expands a wildcard itself, as cmd.exe does not; -o makes the folder',
      (code, sorted(p.name for p in (d / 'xy').glob('*'))), (0, ['sample-B-F-0.20-dry.xy']))
check('...and writes nothing beside the sources', list(d.glob('*.xy')), [])

code, out = run('-i', 'missing.raw')
check('nothing to convert is exit 1', (code, 'not found' in out), (1, True))

(d / 'bad.dat').write_text('not a pattern\n', encoding='utf-8')
code, out = run('-i', 'bad.dat', DAT, '-o', 'xy2')
check('an unreadable file fails, the rest are still converted',
      (code, [p.name for p in (d / 'xy2').glob('*')]), (1, ['sample-B-F-0.20-dry.xy']))

shutil.copy(EXAMPLES / 'example-pdf-card.xml', d / 'card.xml')
code, out = run('-i', 'card.xml')
check('a PDF card is not something conv reads, and converting nothing is exit 1',
      ('not a pattern conv can read' in out, code), (True, 1))


# ---------- CIFs, simulated ----------
def columns(path):
	rows = [line.split('\t') for line in Path(path).read_text(encoding='utf-8').splitlines()]
	return [r[0] for r in rows], np.array([float(r[1]) for r in rows])


d = workdir(CIF, DAT)
code, out = run()
xs, ys = columns('H2bdc.xy')
check('with no -i, a CIF here is simulated too', (code, 'simulated' in out), (0, True))
check('...on 5 to 50 in steps of 0.02 by default', (len(xs), xs[0], xs[1], xs[-1]),
      (2251, '5', '5.02', '50'))
_x = convert.grid(*convert.DEFAULT_GRID)
_y, _n, _note = cifcore.simulate(CIF, _x)
check('...as core.cif simulates it, scaled to a maximum of 1',
      (bool(np.allclose(ys, _y, rtol=0, atol=1e-6)), float(ys.max())), (True, 1.0))
check('...and a note on the intensities is passed on', _note != '' and _note in out, True)

code, out = run('-i', CIF, '-g', '3,60,0.01', '-o', 'fine')
xs, _ = columns(d / 'fine' / 'H2bdc.xy')
check('-g START,STOP,STEP sets the grid', (len(xs), xs[0], xs[-1]), (5701, '3', '60'))
code, out = run('-i', CIF, '-g', ',60,', '-o', 'wide')
xs, _ = columns(d / 'wide' / 'H2bdc.xy')
check('an empty slot in -g keeps its default', (xs[0], xs[1], xs[-1]), ('5', '5.02', '60'))

check('a grid that does not divide evenly stops short of STOP, never past it',
      float(convert.grid(5, 50, 0.07)[-1]) <= 50, True)
for bad in ('5,50', '5,50,0,02', '50,5,0.02', '5,50,0', '5,50,x', '5,50,90', '5,200,1', '5,50,0.00001'):
	try:
		convert.grid_spec(bad)
		_ok = False
	except argparse.ArgumentTypeError:
		_ok = True
	check(f'-g {bad} is refused with a reason', _ok, True)
check('a stored default -g is checked when it is set',
      (cmdline.check_defaults('conv', ['-g', '3,60,0.01']), cmdline.check_defaults('conv', ['-g', '5,50']) is None),
      (None, False))

code, out = run('-i', CIF, '-g', '1,2,0.01', '-o', 'none')
check('no reflections on the grid is a failure, not a flat file',
      (code, 'no reflections' in out, (d / 'none' / 'H2bdc.xy').exists()), (1, True, False))

d = workdir(DAT)
shutil.copy(EXAMPLES / CIF, d / 'sample-B-F-0.20-dry.cif')
code, out = run()
check('a measured pattern wins over a CIF of the same name',
      'just written from sample-B-F-0.20-dry.dat' in out, True)

_lib = Path(tempfile.mkdtemp())
shutil.copy(EXAMPLES / CIF, _lib / CIF)
os.environ['CIF_LOC'] = str(_lib)
d = workdir()
code, out = run('-i', 'H2bdc')
check('-i finds a CIF in the CIF library, as pq -i does, and writes it here',
      (code, (d / 'H2bdc.xy').is_file()), (0, True))
del os.environ['CIF_LOC']


# ---------- one of the tools ----------
check('conv is a tool: default flags and -d work for it',
      cmdline.TOOL_MODULES.get('conv'), 'achdiff.tools.convert')
check('...and an alias can run it', (cli.TOOLS.get('convert'), cli.BUILTIN_COMMANDS.get('conv')),
      ('achdiff.tools.convert', 'convert'))
check('default flags are checked by conv\'s own parser',
      (cmdline.check_defaults('conv', ['-v', '-o', 'xy']), cmdline.check_defaults('conv', ['-s']) is None),
      (None, False))

d = workdir(DAT)
code, out = run('-d', '-o', 'xy')
record = next(d.glob('run*.bat'), None)
text = record.read_text(encoding='utf-8') if record else ''
check('-d records the run', (record is not None, '-o xy --no-defaults' in text), (True, True))


# ---------- -f has to be typed ----------
check('-f cannot be stored as a default flag',
      [(cmdline.check_defaults('conv', f) or '').startswith('-f cannot')
       for f in (['-f'], ['--force'], ['-vf'], ['-o', 'xy', '-f'])],
      [True] * 4)

d = workdir(DAT)
(d / 'sample-B-F-0.20-dry.xy').write_text('keep me\n', encoding='utf-8')
# As a config edited by hand, or saved by 0.15.0, would have it.
config.save_default_flags('conv', ['-f', '-v'])
code, out = run()
check('a -f already in the config is ignored, with the rest of those defaults',
      ((d / 'sample-B-F-0.20-dry.xy').read_text(encoding='utf-8'), 'Ignoring the default conv flags' in out),
      ('keep me\n', True))
code, out = run('-f')
check('...while a typed -f still overwrites',
      (d / 'sample-B-F-0.20-dry.xy').read_text(encoding='utf-8')[:1], '5')
config.save_default_flags('conv', None)

_target = d / 'raced.xy'
_target.write_text('keep me\n', encoding='utf-8')
try:
	convert.write_xy(_target, [1.0], [2.0])
	_raised = False
except FileExistsError:
	_raised = True
check('the write itself refuses an existing file without -f, whatever checked before it',
      (_raised, _target.read_text(encoding='utf-8')), (True, 'keep me\n'))
convert.write_xy(_target, [1.0], [2.0], overwrite=True)
check('...and replaces it with -f', _target.read_text(encoding='utf-8'), '1\t2\n')


print()
print(f'{len(fails)} failure(s)' + (': ' + ', '.join(fails) if fails else ''))
sys.exit(1 if fails else 0)
