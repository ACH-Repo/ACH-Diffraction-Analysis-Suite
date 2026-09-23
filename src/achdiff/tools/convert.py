"""conv: powder patterns to plain two-column .xy files.

For anyone who would rather plot in Origin or Excel: every .brml, .raw, .dat
and .cif here becomes <name>.xy -- 2theta, a tab, the intensity, one point per
line. A tab, not spaces, because Origin and Excel split a pasted line into
columns on it; TOPAS and pq read a tab like any other whitespace. No header
line, since one would stop both of those from reading the file.

Measured patterns come from core.readers, the code pq plots and pf fits them
with, so the .xy holds exactly what pq would draw. A CIF is simulated by
core.cif the way pq simulates one (Cu K-alpha1, Lorentzian FWHM 0.1 degrees,
scaled to a maximum of 1), on a grid of its own: 5 to 50 degrees in steps of
0.02 unless -g says otherwise.

An existing .xy is never overwritten without -f. It may be an export someone
made with another program, and it may be the only copy of it.
"""

import argparse
import sys
from glob import glob
from pathlib import Path

import numpy as np

from .. import cmdline, config, identity
from ..core import cif as cifcore
from ..core import readers
from ..progname import prog_name

# What conv picks up when no -i is given, in order of preference when two files
# share a name: the instrument's own .brml, then .raw, then a Riet7 .dat, whose
# header rounds 2theta to 3 decimals, and last a simulation -- a measured
# pattern always wins over a CIF of the same name. .txt and .csv are left out
# (a fit folder is full of .txt that are not patterns), but -i takes them.
AUTO_EXTENSIONS = ('brml', 'raw', 'dat', 'cif')
CONVERTIBLE = tuple(readers.READERS) + ('cif',)

# The 2theta grid a CIF is simulated on: start, stop, step, in degrees.
DEFAULT_GRID = (5.0, 50.0, 0.02)
MAX_GRID_POINTS = 1_000_000

WILDCARDS = set('*?[')


def _grid_points(start, stop, step):
	"""How many grid points fit from start to stop; the last is never past stop.
	The slack absorbs 45 / 0.02 coming out as 2249.9999999999995."""
	return int(np.floor((stop - start) / step + 1e-9)) + 1


def grid_spec(text):
	"""-g START,STOP,STEP as (start, stop, step). An empty slot keeps its
	default, as in -m: `-g ,60,` is 5 to 60 in steps of 0.02."""
	parts = text.split(',')
	if len(parts) != 3:
		# Four parts is most likely a decimal comma: 5,50,0,02.
		raise argparse.ArgumentTypeError(
			f'{text!r}: give START,STOP,STEP with decimal points, e.g. 5,50,0.02; '
			f'an empty slot keeps its default, e.g. ,60,')
	try:
		start, stop, step = (float(p) if p.strip() else d
		                     for p, d in zip(parts, DEFAULT_GRID))
	except ValueError:
		raise argparse.ArgumentTypeError(
			f'{text!r}: START, STOP and STEP must be numbers with a decimal point, '
			f'e.g. 5,50,0.02') from None
	if not 0 <= start < stop < 180:
		raise argparse.ArgumentTypeError(
			f'{text!r}: need 0 <= START < STOP < 180 degrees 2theta')
	if not 0 < step <= stop - start:
		raise argparse.ArgumentTypeError(
			f'{text!r}: STEP must be above 0 and no larger than STOP - START')
	if _grid_points(start, stop, step) > MAX_GRID_POINTS:
		raise argparse.ArgumentTypeError(
			f'{text!r}: over {MAX_GRID_POINTS:,} points; use a larger STEP')
	return start, stop, step


def grid(start, stop, step):
	"""The 2theta values a CIF is simulated at, start + i * step."""
	return start + step * np.arange(_grid_points(start, stop, step))


def _build_parser():
	parser = argparse.ArgumentParser(
		prog=prog_name('conv'),
		description='Converts PXRD files (.brml, .raw, .dat, and .cif, simulated) to '
		            'two-column, tab-separated .xy files, for plotting in Origin, '
		            'Excel and the like.')
	parser.add_argument('-i', '--input', nargs='+', default=None, metavar='FILE',
	                    help='Files to convert; wildcards work (-i *.raw). If omitted, '
	                         'every .brml, .raw, .dat and .cif in this folder. .xy, .txt '
	                         'and .csv are read too when named here, and a CIF not found '
	                         'here is looked for in your CIF library.')
	parser.add_argument('-g', '--grid', type=grid_spec, default=DEFAULT_GRID,
	                    metavar='START,STOP,STEP',
	                    help='2theta grid a CIF is simulated on, in degrees (default: '
	                         '%s). An empty slot keeps its default: -g ,60, runs to 60.'
	                         % ','.join(f'{v:g}' for v in DEFAULT_GRID))
	parser.add_argument('-o', '--out', default='.', metavar='DIR',
	                    help='Folder to write the .xy files to, made if it does not '
	                         'exist (default: this folder).')
	parser.add_argument('-f', '--force', action='store_true',
	                    help='Overwrite .xy files that already exist. Has to be typed: '
	                         'it cannot be one of your default flags.')
	parser.add_argument('-v', '--verbose', action='store_true',
	                    help='Print extra info while reading.')
	cmdline.add_arguments(parser)
	return parser


def _cif_library():
	"""The CIF library of whoever is running this, as pq finds it."""
	user, _source = identity.resolve(None)
	return config.get('cif_loc', user=user)


def collect(entries, cif_dir=None):
	"""The files to convert, in order, each once.

	No entries: every AUTO_EXTENSIONS file in the working directory. Otherwise
	each entry as named, a wildcard expanded here -- cmd.exe passes `*.raw`
	through untouched -- and a CIF that is not here looked up in `cif_dir`, the
	way pq -i finds one: `-i ZIF-4` does."""
	found = []
	if not entries:
		for ext in AUTO_EXTENSIONS:
			found.extend(sorted(glob(f'*.{ext}')))
	else:
		for entry in entries:
			path = Path(entry)
			if path.is_file():
				found.append(entry)
			elif path.is_dir():
				print(f'[!] Skipping {entry}: a folder. Run conv inside it, or name its files.')
			elif set(entry) & WILDCARDS and glob(entry):
				found.extend(sorted(p for p in glob(entry) if Path(p).is_file()))
			elif (path.suffix.lower() in ('', '.cif')
			      and cifcore.resolve_reflection_cif(entry, cif_dir)):
				found.append(cifcore.resolve_reflection_cif(entry, cif_dir))
			else:
				print(f'[!] Skipping {entry}: not found.')
	seen = set()
	return [p for p in found if not (p in seen or seen.add(p))]


def _number(value):
	"""A value as it goes into the file: at most 6 decimals, no trailing zeros,
	so 5.0204 stays 5.0204 and not 5.020400000000001, and 1523.0 is 1523."""
	return np.format_float_positional(value, precision=6, trim='-')


def write_xy(path, x, y, overwrite=False):
	"""Two tab-separated columns, no header. Without `overwrite`, an existing
	file is refused by the open itself -- a check beforehand can be raced, an
	exclusive create cannot -- with FileExistsError."""
	with open(path, 'w' if overwrite else 'x', encoding='utf-8') as f:
		f.writelines(f'{_number(a)}\t{_number(b)}\n' for a, b in zip(x, y))


def _simulate(src, cif_grid):
	"""(x, y, summary, note) for a CIF, the note qualifying its intensities or
	''. Raises OSError or ValueError, to be reported like an unreadable file."""
	start, stop, step = cif_grid
	x = grid(start, stop, step)
	try:
		y, n, note = cifcore.simulate(src, x)
	except (OSError, ValueError):
		raise
	except Exception as e:
		# Whatever the crystallography trips over in an odd file: one bad CIF
		# must not end a batch, and it is reported like any unreadable file.
		raise ValueError(f'{type(e).__name__}: {e}') from e
	if n == 0:
		raise ValueError(f'no reflections between {start:g} and {stop:g} degrees 2theta.')
	about = f'simulated, {n} reflections, step {step:g}'
	return x, y, about, note


def convert(paths, out_dir='.', force=False, verbose=False, cif_grid=DEFAULT_GRID):
	"""Convert each of `paths` to <stem>.xy in `out_dir`; CIFs are simulated on
	`cif_grid`, a (start, stop, step) triple.

	Returns {'written': [...], 'existing': [...], 'failed': [...]}, each a list
	of source paths; a file skipped for any other reason is reported and counted
	nowhere."""
	out_dir = Path(out_dir)
	result = {'written': [], 'existing': [], 'failed': []}
	made = {}   # target -> the source it was written from, this run

	for src in paths:
		ext = Path(src).suffix.lower().lstrip('.')
		if ext not in CONVERTIBLE:
			print(f'[!] Skipping {src}: not a pattern conv can read '
			      f'(.{", .".join(CONVERTIBLE)}).')
			continue

		target = out_dir / (Path(src).stem + '.xy')
		if target.exists() and target.resolve() == Path(src).resolve():
			print(f'[*] Skipping {src}: already an .xy.')
			continue
		key = str(target.resolve()).lower()
		if key in made:
			print(f'[*] Skipping {src}: {target} was just written from {made[key]}.')
			continue
		if target.exists() and not force:
			print(f'[*] Skipping {src}: {target} already exists.')
			result['existing'].append(src)
			continue

		try:
			if ext == 'cif':
				x, y, about, note = _simulate(src, cif_grid)
			else:
				x, y = readers.read(src, verbose=verbose)
				about, note = f'{x.size} points', ''
		except (OSError, ValueError) as e:
			print(f'[!] Could not {"simulate" if ext == "cif" else "read"} {src}: {e}')
			result['failed'].append(src)
			continue

		try:
			out_dir.mkdir(parents=True, exist_ok=True)
			write_xy(target, x, y, overwrite=force)
		except FileExistsError:
			# Appeared since the check above; still not ours to replace.
			print(f'[*] Skipping {src}: {target} already exists.')
			result['existing'].append(src)
			continue
		except OSError as e:
			print(f'[!] Could not write {target}: {e}')
			result['failed'].append(src)
			continue

		made[key] = src
		result['written'].append(src)
		print(f'[+] {src} -> {target}  ({about}, 2theta {x.min():.3f} to {x.max():.3f})')
		if note:
			# Nothing in an .xy says the intensities are qualified, so say it here.
			print(f'    [!] {note}')

	return result


def main(argv=None):
	args = cmdline.parse_args(_build_parser(), 'conv', 'achdiff.tools.convert', argv=argv)

	paths = collect(args.input, cif_dir=_cif_library() if args.input else None)
	if not paths:
		if args.input:
			print('[-] Nothing to convert.')
		else:
			print(f'[-] No .{", .".join(AUTO_EXTENSIONS)} files here. Name files with -i.')
		return 1

	result = convert(paths, args.out, force=args.force, verbose=args.verbose,
	                 cif_grid=args.grid)

	parts = [f'{len(result["written"])} written']
	if result['existing']:
		parts.append(f'{len(result["existing"])} left alone because the .xy exists (-f overwrites)')
	if result['failed']:
		parts.append(f'{len(result["failed"])} failed')
	print(f'[*] {", ".join(parts)}.')
	# Nothing written and nothing already there means every file was one conv
	# cannot use -- a PDF card, say -- which is no more a success than a failed read.
	done = result['written'] or result['existing']
	return 1 if result['failed'] or not done else 0


if __name__ == '__main__':
	sys.exit(main())
