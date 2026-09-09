import re
import os
import fnmatch
import json
from bs4 import BeautifulSoup
from bs4.element import Tag as Bs4Tag
from decimal import Decimal, getcontext
import copy
import argparse
from ..core.rounding import cryst_round
from ..core import resource
from ..progname import prog_name


# Resource loading lives in core.resource: resource.htm is a real file next to
# the package, and the parsed result is cached. It used to be ~300 lines of
# gzip+base64 right here.


def load_resource(explicit=None):
	'''(column_template_soup, space2cryst) from resource.htm.'''
	return resource.load(explicit)


def _build_parser():
	parser = argparse.ArgumentParser(
		prog=prog_name('pt'),
		description='Build an HTML table of refined lattice parameters from TOPAS .out files.')
	parser.add_argument('--resource', default=None, metavar='PATH',
	                    help='Use a different resource.htm (table template and space-group '
	                         'lookup). Also settable via ACH_RESOURCE_HTM. Defaults to the '
	                         'copy shipped with the package.')
	return parser


# A TOPAS value: a number, optionally followed by `_<esd>. Anything TOPAS appends
# after the esd (_LIMIT_MIN_..., _SVD_ERR) is left for cryst_round to strip. The
# lookbehind stops the digits of a parameter name ("a1", "u2") being read as a value.
_NUM = r'[+-]?\d+\.?\d*(?:[eE][+-]?\d+)?'
_VAL = r'(?<![\w.])(%s(?:`?_%s)?)' % (_NUM, _NUM)

# Phase keywords. A multi-phase refinement repeats the space group, cell macro and
# cell volume once per phase, so each block has to be searched on its own.
_PHASE_START = re.compile(r'^[ \t]*(?:str|hkl_Is|xo_Is)\b', re.M)

# `load hkl_m_d_th2 I { ... }` reflection tables: thousands of numbers that can
# only ever produce false positives for the cell searches.
_PEAK_LIST = re.compile(r'\bload\b[^{]*\{[^{}]*\}', re.S)


def strip_peak_lists(text):

	'''Removes the reflection tables from a phase block.'''

	return _PEAK_LIST.sub(' ', text)


def split_phases(raw):

	'''Splits a TOPAS .out into one text block per refined phase.

	Everything before the first phase keyword (fit quality, background, device)
	is dropped: it belongs to the refinement as a whole, not to any one phase.'''

	starts = [m.start() for m in _PHASE_START.finditer(raw)]
	if not starts:
		return [raw]
	bounds = starts + [len(raw)]
	return [raw[bounds[i]:bounds[i + 1]] for i in range(len(starts))]


def phase_names(raw):

	'''(name, space group) pairs from the wizard's audit-trail header:
	' Selected phases: "ZIF-62" (61) | "H2pPDA" (14)'''

	match = re.search(r'Selected phases:(.*)', raw)
	if not match:
		return []
	return re.findall(r'"([^"]*)"\s*\(([^)]*)\)', match.group(1))


def uniquify(labels):

	'''Appends a running index, from zero, to any label used more than once.'''

	counts = {}
	for label in labels:
		counts[label] = counts.get(label, 0) + 1

	running = {}
	out = []
	for label in labels:
		if counts[label] > 1:
			out.append('%s #%d'%(label, running.get(label, 0)))
			running[label] = running.get(label, 0) + 1
		else:
			out.append(label)
	return out


def phase_labels(blocks, names, phases):

	'''One suffix per phase, unique within the file. The filename stays the column
	heading; these only tell that file's phases apart, so they carry the substance
	where one is named and the space group where none is.'''

	pending = list(names) # header entries not yet claimed by a block
	sg_index = {}
	labels = []

	for i, (block, data) in enumerate(zip(blocks, phases)):
		sg = data['space_group']

		match = re.search(r'^[ \t]*phase_name\s+"?([^"\n]+)"?', block, re.M)
		if match:
			labels.append(match.group(1).strip())
			continue

		# Claim the first unused header entry carrying this space group. Matching
		# on the space group rather than on position survives the wizard dropping
		# a phase whose crystal system it has no macro for.
		claimed = next((pair for pair in pending if pair[1] == sg), None)
		if claimed:
			pending.remove(claimed)
			labels.append(claimed[0])
		elif sg == 'Not found':
			labels.append('phase %d'%(i + 1))
		else:
			# A refinement may list the same space group twice or more, so the
			# fallback carries a running index rather than the bare number.
			labels.append('SG %s #%d'%(sg, sg_index.get(sg, 0)))
			sg_index[sg] = sg_index.get(sg, 0) + 1

	return uniquify(labels)


def find_space_group(raw,data):

	'''Finds the space group in outfile (str). If not found, add "Not found" to data dict.'''

	match = re.search(r'^[ \t]*space_group\s+"*([\w\d/-]+)"*', raw, re.M)
	if match:
		data['space_group'] = match.group(1)
	else:
		data['space_group'] = 'Not found'
		print('The space group could not be found in the .out file!!!: %s'%data['filename'])

	return data


def find_quality(raw):

	'''Fit-quality factors. These sit outside the phase blocks -- one refinement,
	one set of numbers -- so every phase column of a file repeats them.'''

	quality = {}
	for key, keyword in (('rwp', 'r_wp'), ('rexp', 'r_exp'), ('chi', 'gof')):
		match = re.search(r'\b%s\s+(\d+\.?\d*)' % keyword, raw)
		quality[key] = match.group(1) if match else 'Not found'
	return quality



def find_volume(raw,data):

	'''Finds the volume in the .out file (str) If none found, adds "Not found".'''

	match = re.search(r'^[ \t]*(?:cell_)?volume\s+' + _VAL, raw, re.M)
	data['volume'] = match.group(1) if match else 'Not found'

	return data


def complete_lengths(raw,data,crystal_system,found):

	'''Completes the lengths based on the crystal system, if possible.
	If the number of lengths is still smaller than 3, print out error and add "Not found" to data for those lengths.'''

	equal_lengths = {'triclinic':{'a':0,'b':0,'c':0},
					 'monoclinic':{'a':0,'b':0,'c':0},
					 'orthorhombic':{'a':1,'b':1,'c':0},
					 'tetragonal':{'a':1,'b':1,'c':0},
					 'trigonal':{'a':1,'b':1,'c':0},
					 'hexagonal':{'a':1,'b':1,'c':0},
					 'cubic':{'a':1,'b':1,'c':1},
					 'rhombohedral':{'a':1,'b':1,'c':1}}

	equals = equal_lengths.get(crystal_system, {})
	a = data.get('a')

	if a is not None:
		for length in equals.keys():
			if equals[length] == 1:
				data[length] = a
				if length not in found:
					found.append(length)

	if len(found) == 3:
		pass
	else:
		for length in ['a','b','c']:
			if length not in found:
				data[length] = 'Not found'
		print('Could not resolve all lengths for crystal system %r. FILE: %s'
			  %(crystal_system, data.get('filename')))
		print('Make a bug report at: "https://github.com/p3rAsperaAdAstra/TOPAS-Param-Tables-public-"')


	return data




def complete_angles(raw,data,crystal_system,found):

	'''Completes the lengths based on the crystal system, if possible.
	If the number of lengths is still smaller than 3, print out error and add "Not found" to data for those lengths.'''

	fix_angles = {'triclinic':{},
				  'monoclinic':{'al':'90','ga':'90'},
				  'orthorhombic':{'al':'90','be':'90','ga':'90'},
				  'tetragonal':{'al':'90','be':'90','ga':'90'},
				  'trigonal':{'al':'90','be':'90','ga':'120'},
				  'hexagonal':{'al':'90','be':'90','ga':'120'},
				  'cubic':{'al':'90','be':'90','ga':'90'},
				  'rhombohedral':{}}

	givens = fix_angles.get(crystal_system, {})

	for angle in givens.keys():
		data[angle] = givens[angle]
		if angle not in found:
			found.append(angle)

	# Rhombohedral axes have al=be=ga, and TOPAS's macro spells out only al.
	if crystal_system == 'rhombohedral' and 'al' in data:
		for angle in ('be','ga'):
			data[angle] = data['al']
			if angle not in found:
				found.append(angle)

	if len(found) == 3:
		pass
	else:
		for angle in ['al','be','ga']:
			if angle not in found:
				data[angle] = 'Not found'

	return data





_CELL_MACRO = re.compile(
	r'^[ \t]*(Triclinic|Monoclinic|Orthorhombic|Tetragonal|Trigonal|Hexagonal|'
	r'Rhombohedral|Cubic)\s*\(([^)]*)\)', re.M)

# Which cell parameters each TOPAS lattice macro spells out, in argument order.
# The rest follow from the crystal system and are filled in by complete_*().
_MACRO_PARAMS = {'triclinic':    ('a','b','c','al','be','ga'),
				 'monoclinic':   ('a','b','c','be'),
				 'orthorhombic': ('a','b','c'),
				 'tetragonal':   ('a','c'),
				 'trigonal':     ('a','c'),
				 'hexagonal':    ('a','c'),
				 'rhombohedral': ('a','al'),
				 'cubic':        ('a',)}


def find_cell_macro(raw,data):

	'''Reads a TOPAS lattice macro, e.g. `Orthorhombic(@ 15.506`_0.006, ...)`, and
	returns its crystal system, or None if the block has no such line.

	Tried before the plain `a <value>` notation, because the macro is unambiguous:
	a bare-name search will happily read `chi2_convergence_criteria 0.000001` as a.'''

	match = _CELL_MACRO.search(raw)
	if not match:
		return None

	system = match.group(1).lower()
	for name, arg in zip(_MACRO_PARAMS[system], match.group(2).split(',')):
		value = re.search(_VAL, arg)
		if value:
			data[name] = value.group(1)

	return system


def find_lengths(raw,data,crystal_system):

	'''Finds the lengths a,b,c in outfile (str). If not found, add "Not found" to data dict.
	Calls complete_lengths() to check if can be derived from crystal system.'''

	found = [] # append found lengths so that they can be skipped

	for length in ['a','b','c']:
		match = re.search(r'^[ \t]*%s\s+@?\s*%s'%(length,_VAL), raw, re.M)
		if match:
			data[length] = match.group(1)
			found.append(length)

	if len(found) < 3:
		data = complete_lengths(raw,data,crystal_system,found)

	return data


def find_angles(raw,data,crystal_system):

	'''Finds the lengths a,b,c in outfile (str). If not found, add "Not found" to data dict.
	Calls complete_lengths() to check if can be derived from crystal system.'''

	found = [] # append found angles so that they can be skipped

	for angle in ['al','be','ga']:
		match = re.search(r'^[ \t]*%s\s+@?\s*%s'%(angle,_VAL), raw, re.M)
		if match:
			data[angle] = match.group(1)
			found.append(angle)

	if len(found) < 3:
		data = complete_angles(raw,data,crystal_system,found)

	return data


############ new code 
def format_quality(parm, value):
	"""Fit-quality factors (chi/rwp/rexp) carry no esd, so they get plain 2-decimal
	formatting. This used to live inside cryst_round as a `parm` special case; it is
	a presentation choice, so it belongs to this tool rather than to rounding."""
	if re.search(r'\d+\.\d+', value) and parm in ['chi', 'rwp', 'rexp']:
		return '{:.2f}'.format(Decimal(value))
	return value


def get_phase_data(block,data):

	'''Finds the cell of a single phase within its own block of a TOPAS .out file.'''

	block = strip_peak_lists(block)

	data = find_space_group(block,data)

	# The macro wins over the space-group lookup, because it names the axis
	# setting actually refined: R-3c is listed as rhombohedral, but a file
	# writing `Trigonal(a, c)` is on hexagonal axes, and completing it as
	# rhombohedral would overwrite c with a.
	macro_system = find_cell_macro(block,data)
	if macro_system:
		data['crystal_system'] = macro_system
	else:
		entry = space2cryst.get(data['space_group'].lower())
		data['crystal_system'] = entry[1] if entry else 'Not found'

	if macro_system:
		lengths = [k for k in ('a','b','c') if k in data]
		angles = [k for k in ('al','be','ga') if k in data]
		if len(lengths) < 3:
			complete_lengths(block,data,macro_system,lengths)
		if len(angles) < 3:
			complete_angles(block,data,macro_system,angles)
	else:
		data = find_lengths(block,data,data['crystal_system'])
		data = find_angles(block,data,data['crystal_system'])

	data = find_volume(block,data)

	return data


def get_data(path,base):

	'''Parses a TOPAS output file into one data dict per refined phase.'''

	with open(path,'r',encoding='utf8',errors='ignore') as inf:
		raw = inf.read()

	quality = find_quality(raw)
	names = phase_names(raw)
	blocks = split_phases(raw)

	phases = []
	for block in blocks:
		data = dict(base)
		data = get_phase_data(block,data)
		data.update(quality)

		parms = ['a','b','c','al','be','ga','space_group','crystal_system','chi','rwp','rexp','volume']
		for par in parms:
			if par not in data.keys():
				data[par] = 'Not found'

		phases.append(data)

	for data, label in zip(phases, phase_labels(blocks,names,phases)):
		data['phase_label'] = label

	return phases



def write_soup(soup,path='check.htm'):

	'''Write a temporary soup so it can be displayed in the browser and checked.'''

	with open(path,'w',encoding='utf-8') as outf:
		outf.write(str(soup))


def make_new_column(template,outsoup,params):

	'''Takes the data from get_data and adds a new data column to the template.htm soup.'''

	template2data = {'Compound':'filename',
					 'crystalsystem':'crystal_system',
					 'spacegroup':'space_group',
					 'a/Å':'a',
					 'b/Å':'b',
					 'c/Å':'c',
					 'α/°':'al',
					 'β/°':'be',
					 'γ/°':'ga',
					 'V/Å3':'volume',
					 'Rwp/%':'rwp',
					 'Rexp/%':'rexp',
					 'χ':'chi'}

	trs_template = template.find_all('tr')
	trs_outsoup = outsoup.find_all('tr')

	for i in range(len(trs_template)):
		tr_template = trs_template[i]
		tr_outsoup = trs_outsoup[i]

		td_rowname = tr_template.find_all('td')[0]
		td_template = tr_template.find_all('td')[-1]

		row_name = re.sub(r'\s+', '', td_rowname.text)
		key = template2data[row_name]
		val = params[key]

		if key in ['a','b','c','al','be','ga','volume','rwp','rexp','chi'] and key != 'Not found':
			if '_' in val:
				val = cryst_round(val)
			else:
				val = format_quality(key, val)

		new_td = copy.copy(td_template)

		if key == 'space_group' and val != 'Not found': # use embedded formatted space group
			entry = space2cryst.get(val.lower())
			formatted_str = entry[0] if entry else val
			new_td_str = str(new_td)
			new_td_str = new_td_str.replace('Blank',formatted_str)
			new_td = BeautifulSoup(new_td_str, 'html.parser')
		else:
			new_td.span.string = val

		tr_outsoup.append(new_td)
		

	return outsoup



def find_out_files(root='.'):

	'''Walks `root` and returns every .out file found, sorted by relative path.'''

	hits = []
	for dirpath, dirnames, filenames in os.walk(root):
		for name in filenames:
			if name.lower().endswith('.out'):
				rel = os.path.relpath(os.path.join(dirpath, name), root)
				hits.append(rel)
	hits.sort()
	return hits


def parse_selection(raw, files):

	'''Resolves a user selection string against `files`.
	Accepts:
	  - "all"                          -> every file
	  - indices "1,3,5" or "1 3 5"     -> matching entries (1-based)
	  - ranges "1-3"                   -> inclusive range
	  - wildcards "*IV*", "sample-?*"  -> fnmatch against basename and rel-path
	  - mix of the above, comma/space separated
	Returns a de-duplicated list preserving the order files were listed in.
	Raises ValueError on bad input.'''

	raw = raw.strip()
	if not raw:
		raise ValueError('empty selection')
	if raw.lower() == 'all':
		return list(files)

	picked_idx = set()
	tokens = re.split(r'[,\s]+', raw)
	for tok in tokens:
		if not tok:
			continue
		# range "a-b"
		m = re.fullmatch(r'(\d+)-(\d+)', tok)
		if m:
			lo, hi = int(m.group(1)), int(m.group(2))
			if lo < 1 or hi > len(files) or lo > hi:
				raise ValueError('range out of bounds: %s' % tok)
			for i in range(lo, hi + 1):
				picked_idx.add(i - 1)
			continue
		# plain index
		if tok.isdigit():
			i = int(tok)
			if not (1 <= i <= len(files)):
				raise ValueError('index out of bounds: %s' % tok)
			picked_idx.add(i - 1)
			continue
		# wildcard — match against basename and full relative path
		matched = False
		for i, f in enumerate(files):
			if fnmatch.fnmatch(os.path.basename(f), tok) or fnmatch.fnmatch(f, tok):
				picked_idx.add(i)
				matched = True
		if not matched:
			raise ValueError('no files match pattern: %s' % tok)

	return [files[i] for i in sorted(picked_idx)]


def select_files_wizard(root='.'):

	'''Finds .out files under `root` and asks the user which to include.'''

	files = find_out_files(root)
	if not files:
		print('No .out files found under %s' % os.path.abspath(root))
		return []

	print('\nFound %d .out file(s) under %s:\n' % (len(files), os.path.abspath(root)))
	width = len(str(len(files)))
	for i, f in enumerate(files, 1):
		print('  [%*d] %s' % (width, i, f))

	print('\nSelect files by:')
	print('  - "all"')
	print('  - indices, e.g. "1,3,5" or "1 3 5"')
	print('  - ranges, e.g. "2-4"')
	print('  - wildcards (fnmatch), e.g. "*IV*" or "sample-?_*"')
	print('  - any mix of the above, comma/space separated')

	while True:
		try:
			raw = input('\nSelection: ')
		except EOFError:
			return []
		try:
			picked = parse_selection(raw, files)
		except ValueError as e:
			print('  -> %s. Try again.' % e)
			continue
		if not picked:
			print('  -> nothing selected. Try again.')
			continue
		print('\nSelected %d file(s):' % len(picked))
		for f in picked:
			print('  - %s' % f)
		confirm = input('Proceed? [Y/n]: ').strip().lower()
		if confirm in ('', 'y', 'yes'):
			return picked


def prompt_output_filename(default='done.htm'):

	'''Ask the user for an output filename. Empty input -> `default`. Appends
	'.htm' if no extension was given. If the target already exists, asks for
	confirmation before returning (so a previous run doesn't get clobbered).'''

	while True:
		try:
			raw = input('\nOutput filename [%s]: ' % default).strip()
		except EOFError:
			return default
		name = raw or default
		# add .htm if no extension
		if not os.path.splitext(name)[1]:
			name = name + '.htm'
		if os.path.exists(name):
			try:
				confirm = input('  %s already exists — overwrite? [y/N]: ' % name).strip().lower()
			except EOFError:
				return None
			if confirm not in ('y', 'yes'):
				continue
		return name


# Main Loop
def main():
	# get_phase_data() and make_new_column() read this as a module global. It used
	# to be assigned at module level, so wrapping this block in main() would make
	# it a local and break the lookups.
	global space2cryst

	args = _build_parser().parse_known_args()[0]

	input_files = select_files_wizard('.')
	if not input_files:
		raise SystemExit('No files selected — exiting.')

	output_path = prompt_output_filename()
	if not output_path:
		raise SystemExit('No output filename — exiting.')

	try:
		template, space2cryst = load_resource(args.resource)
	except FileNotFoundError as e:
		raise SystemExit(f'[!] {e}')
	outsoup = copy.copy(template)
	for tr in outsoup.find_all('tr'): tr.find_all('td')[-1].decompose() # remove blank column. Change later if useful.

	for i,file in enumerate(input_files):
		print('%s: (%s/%s)'%(file,i+1,len(input_files)))
		phases = get_data(file,{'filename':os.path.basename(file)})
		for phase in phases:
			# One column per phase; without the suffix a multi-phase file would
			# produce several identically-headed columns.
			if len(phases) > 1:
				phase['filename'] = '%s (%s)'%(phase['filename'],phase['phase_label'])
				print('  - %s'%phase['filename'])
			outsoup = make_new_column(template,outsoup,phase)

	write_soup(outsoup, output_path)
	print('\nWrote %s' % output_path)


if __name__ == '__main__':
	main()
