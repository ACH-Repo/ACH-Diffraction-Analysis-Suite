"""conv: measured patterns to plain two-column .xy files.

For anyone who would rather plot in Origin or Excel: every .brml, .raw and .dat
here becomes <name>.xy -- 2theta, a tab, the intensity, one point per line. A
tab, not spaces, because Origin and Excel split a pasted line into columns on it;
TOPAS and pq read a tab like any other whitespace. No header line, since one
would stop both of those from reading the file.

The patterns come from core.readers, the code pq plots and pf fits them with,
so the .xy holds exactly what pq would draw.

An existing .xy is never overwritten without -f. It may be an export someone
made with another program, and it may be the only copy of it.
"""

import argparse
import sys
from glob import glob
from pathlib import Path

import numpy as np

from .. import cmdline
from ..core import readers
from ..progname import prog_name

# What conv picks up when no -i is given, in order of preference when two files
# share a name: the instrument's own .brml, then .raw, then a Riet7 .dat, whose
# header rounds 2theta to 3 decimals. .txt and .csv are left out -- a fit folder
# is full of .txt that are not patterns -- but -i takes them.
AUTO_EXTENSIONS = ('brml', 'raw', 'dat')

WILDCARDS = set('*?[')


def _build_parser():
	parser = argparse.ArgumentParser(
		prog=prog_name('conv'),
		description='Converts measured PXRD files (.brml, .raw, .dat) to two-column, '
		            'tab-separated .xy files, for plotting in Origin, Excel and the like.')
	parser.add_argument('-i', '--input', nargs='+', default=None, metavar='FILE',
	                    help='Files to convert; wildcards work (-i *.raw). If omitted, '
	                         'every .brml, .raw and .dat in this folder. .xy, .txt and '
	                         '.csv are read too when named here.')
	parser.add_argument('-o', '--out', default='.', metavar='DIR',
	                    help='Folder to write the .xy files to, made if it does not '
	                         'exist (default: this folder).')
	parser.add_argument('-f', '--force', action='store_true',
	                    help='Overwrite .xy files that already exist.')
	parser.add_argument('-v', '--verbose', action='store_true',
	                    help='Print extra info while reading.')
	cmdline.add_arguments(parser)
	return parser


def collect(entries):
	"""The files to convert, in order, each once.

	No entries: every AUTO_EXTENSIONS file in the working directory. Otherwise
	each entry as named, a wildcard expanded here -- cmd.exe passes `*.raw`
	through untouched."""
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
			else:
				print(f'[!] Skipping {entry}: not found.')
	seen = set()
	return [p for p in found if not (p in seen or seen.add(p))]


def _number(value):
	"""A value as it goes into the file: at most 6 decimals, no trailing zeros,
	so 5.0204 stays 5.0204 and not 5.020400000000001, and 1523.0 is 1523."""
	return np.format_float_positional(value, precision=6, trim='-')


def write_xy(path, x, y):
	"""Two tab-separated columns, no header."""
	with open(path, 'w', encoding='utf-8') as f:
		f.writelines(f'{_number(a)}\t{_number(b)}\n' for a, b in zip(x, y))


def convert(paths, out_dir='.', force=False, verbose=False):
	"""Convert each of `paths` to <stem>.xy in `out_dir`.

	Returns {'written': [...], 'existing': [...], 'failed': [...]}, each a list
	of source paths; a file skipped for any other reason is reported and counted
	nowhere."""
	out_dir = Path(out_dir)
	result = {'written': [], 'existing': [], 'failed': []}
	made = {}   # target -> the source it was written from, this run

	for src in paths:
		ext = Path(src).suffix.lower().lstrip('.')
		if ext not in readers.READERS:
			print(f'[!] Skipping {src}: not a measured pattern conv can read '
			      f'(.{", .".join(readers.READERS)}).')
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
			x, y = readers.read(src, verbose=verbose)
		except (OSError, ValueError) as e:
			print(f'[!] Could not read {src}: {e}')
			result['failed'].append(src)
			continue

		try:
			out_dir.mkdir(parents=True, exist_ok=True)
			write_xy(target, x, y)
		except OSError as e:
			print(f'[!] Could not write {target}: {e}')
			result['failed'].append(src)
			continue

		made[key] = src
		result['written'].append(src)
		print(f'[+] {src} -> {target}  ({x.size} points, 2theta {x.min():.3f} to {x.max():.3f})')

	return result


def main(argv=None):
	args = cmdline.parse_args(_build_parser(), 'conv', 'achdiff.tools.convert', argv=argv)

	paths = collect(args.input)
	if not paths:
		if args.input:
			print('[-] Nothing to convert.')
		else:
			print(f'[-] No .{", .".join(AUTO_EXTENSIONS)} files here. Name files with -i.')
		return 1

	result = convert(paths, args.out, force=args.force, verbose=args.verbose)

	parts = [f'{len(result["written"])} written']
	if result['existing']:
		parts.append(f'{len(result["existing"])} left alone because the .xy exists (-f overwrites)')
	if result['failed']:
		parts.append(f'{len(result["failed"])} failed')
	print(f'[*] {", ".join(parts)}.')
	# Nothing written and nothing already there means every file was one conv
	# cannot use -- a CIF, say -- which is no more a success than a failed read.
	done = result['written'] or result['existing']
	return 1 if result['failed'] or not done else 0


if __name__ == '__main__':
	sys.exit(main())
