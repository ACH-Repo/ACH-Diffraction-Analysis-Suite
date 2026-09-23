"""Assertions for conv, and for the readers it shares with pq and pf.

Run: python tests/test_convert.py
Uses ACH_CONFIG_DIR to redirect config into a temp dir, and converts copies of
the example files in another, so a test run touches nothing real.
"""

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
for _v in ('ACH_USER',):
	os.environ.pop(_v, None)

import numpy as np  # noqa: E402

from achdiff import cli, cmdline  # noqa: E402
from achdiff.core import readers  # noqa: E402
from achdiff.tools import convert, prefit, quickplot  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'
BRML = 'sample-A-P4-cryst.brml'
DAT = 'sample-B-F-0.20-dry.dat'
XY = 'sample-C_300_001_00000.xy'

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

(d / 'H2bdc.cif').write_text('data_x\n', encoding='utf-8')
code, out = run('-i', 'H2bdc.cif')
check('a CIF is not a measured pattern', ('not a measured pattern' in out, code), (True, 1))


# ---------- one of the tools ----------
check('conv is a tool: default flags and -d work for it',
      cmdline.TOOL_MODULES.get('conv'), 'achdiff.tools.convert')
check('...and an alias can run it', (cli.TOOLS.get('convert'), cli.BUILTIN_COMMANDS.get('conv')),
      ('achdiff.tools.convert', 'convert'))
check('default flags are checked by conv\'s own parser',
      (cmdline.check_defaults('conv', ['-f', '-o', 'xy']), cmdline.check_defaults('conv', ['-s']) is None),
      (None, False))

d = workdir(DAT)
code, out = run('-d', '-o', 'xy')
record = next(d.glob('run*.bat'), None)
text = record.read_text(encoding='utf-8') if record else ''
check('-d records the run', (record is not None, '-o xy --no-defaults' in text), (True, True))


print()
print(f'{len(fails)} failure(s)' + (': ' + ', '.join(fails) if fails else ''))
sys.exit(1 if fails else 0)
