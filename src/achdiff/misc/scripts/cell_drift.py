"""Cell parameters of each phase in a mixture fit, against its single-phase fit.

A multi-phase Pawley fit of a mixture refines every cell at once, and each can
settle somewhere other than where the same phase refines on its own: overlapping
peaks trade intensity, a shared zero error or sample displacement is soaked up by
the wrong phase, or the mixture really does change something. This puts each
phase of a mixture fit next to a single-phase fit of the pure substance -- both
refined against measured patterns, not simulated from a CIF -- and shows how far
each parameter moved.

Inputs are TOPAS .out files:
  --pure  single-phase fits, one per substance. NAME=file.out names the phase
          yourself, for a fit whose .out does not say what it is.
  --mix   one or more multi-phase fits of mixtures.

Phases are matched by the names rp writes into every .out ("Selected phases:").
Where either side has no name, a space group held by exactly one pure fit is
used instead. Two differently named phases are never matched on space group
alone -- P2_1/c is far too common for that -- so rename one with NAME=file.out.
A mixture phase with no pure fit to compare against is listed and skipped.

For every parameter both fits refined, and the cell volume:
  delta      mixture - pure, with the combined esd in brackets
  delta %    relative to the pure value
  delta/esd  delta over sqrt(esd_pure^2 + esd_mix^2), marked * from 3 up. TOPAS
             esds are known to come out too small, often several times over, so
             read a large value as "worth a look" rather than as proof.

Output: the table, and a figure of delta % per parameter -- one panel per phase,
one bar per mixture, the combined esd as the error bar. -s saves the figure and
writes the table as CSV instead of opening a window.

Run with no arguments in a folder of fits to be asked for everything.
"""

ABOUT = {
	'for': 'two-phase fits of homogeneous mixtures vs. the pure-phase fits',
	'author': 'Christian Nelle',
	'written': '2026-09-22',
}

import argparse
import csv
import math
import os
import sys
from glob import glob
from pathlib import Path

from achdiff.misc import kit

# The cell parameters in the order they are shown, with ASCII names for the
# table and CSV (a console may not take Greek) and mathtext for the figure.
PARAMS = [
	('a', 'a', '$a$'),
	('b', 'b', '$b$'),
	('c', 'c', '$c$'),
	('al', 'alpha', r'$\alpha$'),
	('be', 'beta', r'$\beta$'),
	('ga', 'gamma', r'$\gamma$'),
	('volume', 'V', '$V$'),
]
FLAG_AT = 3.0


def build_parser():
	parser = argparse.ArgumentParser(
		description=__doc__.strip().splitlines()[0],
		epilog='Run with no arguments to be asked for everything.')
	parser.add_argument('--pure', nargs='+', metavar='[NAME=]FILE',
	                    help='Single-phase fits (.out), one per substance.')
	parser.add_argument('--mix', nargs='+', metavar='FILE',
	                    help='Multi-phase fits (.out) of mixtures.')
	parser.add_argument('--name', default='cell_drift',
	                    help='File name stem for -s output (default: %(default)s).')
	kit.add_common_arguments(parser)
	return parser


# ------------------------------------------------------------------ the wizard

def fill(args, parser):
	"""Ask for --pure and --mix when they were not given. Returns the answers
	as command-line tokens."""
	if args.pure and args.mix:
		return []
	if not kit.interactive():
		parser.error('give both --pure and --mix, or run it in a console to be asked')

	# What it is and why, then the questions: run bare, it has to explain itself.
	print('\n\n'.join(__doc__.strip().split('\n\n')[:2]))
	print()
	print('Enter takes the suggestion in [brackets].')
	print()
	outs = sorted(glob('*.out'))
	if not outs:
		parser.error(f'no .out files in {os.getcwd()}. Run it in the folder with '
		             f'your fits, or pass --pure and --mix.')
	found = [kit.phases(p) for p in outs]
	width = max(len(p) for p in outs)
	labels = []
	for path, phases in zip(outs, found):
		names = ', '.join(ph['name'] or f'unnamed ({ph["space_group"]})' for ph in phases)
		labels.append(f'{path:<{width}}  {len(phases)} phase{"s" * (len(phases) != 1)}'
		              + (f': {names}' if phases else ''))
	print('Fits in this folder:')

	extra = []
	pure_idx = []
	if not args.pure:
		pure_idx = kit.choose(labels, 'Which are the single-phase (pure) fits?',
		                      default=[i for i, ph in enumerate(found) if len(ph) == 1])
		extra.append('--pure')
		for i in pure_idx:
			phases = found[i]
			if len(phases) == 1 and not phases[0]['name']:
				name = kit.ask(f'  {outs[i]} does not say which phase it is. Name it '
				               f'(Enter to match it by space group only):')
				extra.append(f'{name}={outs[i]}' if name else outs[i])
			else:
				extra.append(outs[i])
	if not args.mix:
		taken = set(pure_idx)
		kit_default = [i for i, ph in enumerate(found) if len(ph) > 1 and i not in taken]
		mix_idx = kit.choose(labels, 'Which are the mixture fits?', default=kit_default,
		                     show=bool(args.pure))
		extra += ['--mix'] + [outs[i] for i in mix_idx]
	if not args.silent and kit.ask_yes('Save the figure and a CSV instead of opening a window?'):
		extra.append('-s')
	return extra


# ------------------------------------------------------------------ comparing

def load_pure(specs):
	"""The pure fits as a list of reference phases. Unusable ones are reported."""
	refs = []
	for spec in specs:
		name, path = None, spec
		if '=' in spec and not os.path.exists(spec):
			name, path = spec.split('=', 1)
		if not os.path.exists(path):
			print(f'[!] --pure {path}: no such file.')
			continue
		phases = kit.phases(path)
		if len(phases) != 1:
			held = ', '.join(ph['name'] or ph['space_group'] or '?' for ph in phases)
			print(f'[!] --pure {path}: a pure fit should refine one phase; it refines '
			      f'{len(phases)}{" (" + held + ")" if held else ""}. Skipped.')
			continue
		ref = dict(phases[0], file=path)
		if name:
			ref['name'] = name
		refs.append(ref)
	return refs


def match(phase, refs):
	"""(reference, how) for a mixture phase, or (None, why not)."""
	if phase['name']:
		named = [r for r in refs if r['name'] and r['name'].lower() == phase['name'].lower()]
		if len(named) == 1:
			return named[0], 'name'
		if len(named) > 1:
			return None, f'{len(named)} pure fits are called {phase["name"]}'
	# Space group only where a name is missing on one side: two named phases
	# that disagree are two substances, whatever group they share.
	candidates = [r for r in refs if not (phase['name'] and r['name'])
	              and r['space_group'] and r['space_group'] == phase['space_group']]
	if len(candidates) == 1:
		return candidates[0], 'space group'
	if len(candidates) > 1:
		return None, f'{len(candidates)} unnamed pure fits share space group {phase["space_group"]}'
	return None, 'no pure fit of it was given'


def compare(ref, phase):
	"""One row per parameter refined in both fits, plus the volume."""
	rows = []
	for key, label, _math in PARAMS:
		pure_t = ref['volume'] if key == 'volume' else ref['params'].get(key)
		mix_t = phase['volume'] if key == 'volume' else phase['params'].get(key)
		pure_v, mix_v = kit.value(pure_t), kit.value(mix_t)
		if pure_v is None or mix_v is None:
			continue
		(p, p_esd), (m, m_esd) = pure_v, mix_v
		delta = m - p
		sigma = math.hypot(p_esd or 0.0, m_esd or 0.0)
		rows.append({
			'key': key, 'label': label,
			'pure': pure_t, 'pure_value': p, 'pure_esd': p_esd,
			'mix': mix_t, 'mix_value': m, 'mix_esd': m_esd,
			'delta': delta, 'sigma': sigma,
			'delta_pct': 100.0 * delta / p if p else float('nan'),
			'sigma_pct': 100.0 * sigma / abs(p) if p else float('nan'),
			'z': delta / sigma if sigma > 0 else None,
		})
	return rows


def _delta_text(row):
	if row['sigma'] > 0:
		return kit.rounded(f'{row["delta"]:.10f}`_{row["sigma"]:.10f}')
	return f'{row["delta"]:+.6g}'


def print_table(mix_path, results, unmatched):
	print(f'{mix_path}')
	for phase, ref, how, rows in results:
		print(f'  {phase["name"] or "unnamed"} ({phase["space_group"]})  vs  {ref["file"]}'
		      f'   [matched by {how}]')
		print(f'    {"":<6}{"pure":>16}{"mixture":>16}{"delta":>16}{"delta %":>10}{"delta/esd":>11}')
		for r in rows:
			z = f'{r["z"]:+.1f}' if r['z'] is not None else '-'
			flag = ' *' if r['z'] is not None and abs(r['z']) >= FLAG_AT else ''
			print(f'    {r["label"]:<6}{kit.rounded(r["pure"]):>16}{kit.rounded(r["mix"]):>16}'
			      f'{_delta_text(r):>16}{r["delta_pct"]:>+10.3f}{z:>11}{flag}')
	for phase, why in unmatched:
		print(f'  {phase["name"] or "unnamed"} ({phase["space_group"]}): skipped -- {why}.')
	print()


def _num(x):
	"""A number for the CSV: eight significant figures, not float noise."""
	return '' if x is None else f'{x:.8g}'


def write_csv(path, all_results):
	with open(path, 'w', newline='', encoding='utf-8') as fh:
		out = csv.writer(fh)
		out.writerow(['mixture', 'phase', 'space_group', 'pure_fit', 'matched_by', 'parameter',
		              'pure', 'pure_esd', 'mixture_value', 'mixture_esd',
		              'delta', 'combined_esd', 'delta_pct', 'delta_over_esd'])
		for mix_path, results, _unmatched in all_results:
			for phase, ref, how, rows in results:
				for r in rows:
					out.writerow([mix_path, phase['name'] or '', phase['space_group'] or '',
					              ref['file'], how, r['label'],
					              *(_num(r[k]) for k in ('pure_value', 'pure_esd', 'mix_value',
					                                     'mix_esd', 'delta', 'sigma',
					                                     'delta_pct', 'z'))])


def figure(all_results):
	"""delta % per parameter: a panel per phase, a bar per mixture."""
	import matplotlib.pyplot as plt

	panels = {}       # phase label -> {mixture: {param key: row}}
	for mix_path, results, _unmatched in all_results:
		for phase, _ref, _how, rows in results:
			label = f'{phase["name"] or "unnamed"} ({phase["space_group"]})'
			panels.setdefault(label, {})[mix_path] = {r['key']: r for r in rows}
	mixtures = [m for m, _r, _u in all_results]
	colors = plt.rcParams['axes.prop_cycle'].by_key()['color']

	fig, axes = plt.subplots(len(panels), 1, figsize=(6.0, 2.6 * len(panels) + 0.6),
	                         squeeze=False, layout='constrained')
	for ax, (label, by_mix) in zip(axes[:, 0], panels.items()):
		keys = [k for k, _l, _m in PARAMS if any(k in rows for rows in by_mix.values())]
		width = 0.8 / max(len(mixtures), 1)
		for j, mix in enumerate(mixtures):
			rows = by_mix.get(mix, {})
			xs = [i + (j - (len(mixtures) - 1) / 2) * width for i, k in enumerate(keys) if k in rows]
			ys = [rows[k]['delta_pct'] for k in keys if k in rows]
			es = [rows[k]['sigma_pct'] for k in keys if k in rows]
			ax.bar(xs, ys, width=width * 0.9, yerr=es, capsize=2, color=colors[j % len(colors)],
			       label=Path(mix).stem, error_kw={'lw': 0.8})
		ax.axhline(0, color='k', lw=0.6)
		ax.set_xticks(range(len(keys)))
		ax.set_xticklabels([m for k, _l, m in PARAMS if k in keys])
		ax.set_ylabel(r'$\Delta$ vs. pure / %')
		ax.set_title(label, fontsize=10)
		ax.tick_params(direction='in')
	if len(mixtures) > 1:
		axes[0, 0].legend(fontsize=8, frameon=False)
	else:
		fig.suptitle(f'{Path(mixtures[0]).stem} vs. pure-phase fits', fontsize=11)
	return fig


def run(args):
	refs = load_pure(args.pure)
	if not refs:
		print('[!] None of the --pure fits can be used.')
		return 1

	all_results = []
	for mix_path in args.mix:
		if not os.path.exists(mix_path):
			print(f'[!] --mix {mix_path}: no such file.')
			continue
		results, unmatched = [], []
		for phase in kit.phases(mix_path):
			ref, how = match(phase, refs)
			if ref is None:
				unmatched.append((phase, how))
				continue
			rows = compare(ref, phase)
			if rows:
				results.append((phase, ref, how, rows))
			else:
				unmatched.append((phase, 'the two fits refined no parameter in common'))
		print_table(mix_path, results, unmatched)
		all_results.append((mix_path, results, unmatched))

	if not any(results for _m, results, _u in all_results):
		print('[!] No mixture phase could be matched to a pure fit, so there is nothing '
		      'to compare.')
		return 1
	print(f'* |delta/esd| >= {FLAG_AT:g}. TOPAS esds tend to be too small, so treat that as '
	      f'a pointer, not a verdict.')

	import matplotlib.pyplot as plt
	fig = figure(all_results)
	if args.silent:
		csv_path = f'{args.name}.csv'
		fig_path = f'{args.name}.{args.extension.lstrip(".")}'
		write_csv(csv_path, all_results)
		fig.savefig(fig_path, dpi=300, bbox_inches='tight')
		plt.close(fig)
		print(f'[+] {csv_path}')
		print(f'[+] {fig_path}')
	else:
		plt.show()
	return 0


def main(argv=None, command=None):
	return kit.main(build_parser(), fill, run, argv=argv, command=command,
	                script_file=__file__)


if __name__ == '__main__':
	sys.exit(main())
