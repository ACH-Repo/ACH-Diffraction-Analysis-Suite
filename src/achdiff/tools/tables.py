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


def find_space_group(raw,data):

	'''Finds the space group in outfile (str). If not found, add "Not found" to data dict.'''

	rexes = [r'space_group\s+"*([\w\d/-]+)"*'] # Error index 3 in backs.log

	for rex in rexes:
		match = re.search(rex,raw)
		if match:
			data['space_group'] = match.group(1)
			break
		else:
			pass

	try:
		data['space_group']
	except KeyError:
		data['space_group'] = 'Not found'
		print('The space group could not be found in the .out file!!!: %s'%data['filename'])

	return data





def find_volume(raw,data):

	'''Finds the volume in the .out file (str) If none found, adds "Not found".'''

	rexes = [r'volume\s+(\d+\.\d+`_\d+\.\d+)',
			 r'volume\s+(\d+\.\d+)`*',
			 r'cell_volume\s+(\d+\.\d+`_\d+\.\d+)',
			 r'cell_volume\s+(\d+\.\d+)`*'] # Error index 3 in backs.log

	for rex in rexes: # iterate over patterns and break at first match
		match = re.search(rex,raw)
		if match:
			data['volume'] = match.group(1)
			break
		else:
			pass # move on to next pattern

	try:
		data['volume']
	except KeyError:
		data['volume'] = 'Not found'
		# print('The volume could not be found in the .out file!!!')
		# print('In rare cases, this is because there simply is no volume.')
		# print('More likely, however, none of the regexes (rex) in the list of regexes (rexes), can match the pattern of the volume inside the .out file.')

	return data


def complete_lengths(raw,data,crystal_system,found):

	'''Completes the lengths based on the crystal system, if possible.
	If the number of lengths is still smaller than 3, print out error and add "Not found" to data for those lengths.'''

	equal_lengths = {'triclinic':{'a':0,'b':0,'c':0},
					 'monoclinic':{'a':0,'b':0,'c':0},
					 'orthorhombic':{'a':1,'b':1,'c':0},
					 'tetragonal':{'a':1,'b':1,'c':0},
					 'hexagonal':{'a':1,'b':1,'c':0},
					 'cubic':{'a':1,'b':1,'c':1},
					 'rhombohedral':{'a':1,'b':1,'c':1}}

	equals = equal_lengths[crystal_system]
	a = data['a']

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
		print('Not alt notation, yet not all parameters found. This is weird.')
		print('Make a bug report at: "https://github.com/p3rAsperaAdAstra/TOPAS-Param-Tables-public-"')


	return data
	



def complete_angles(raw,data,crystal_system,found):

	'''Completes the lengths based on the crystal system, if possible.
	If the number of lengths is still smaller than 3, print out error and add "Not found" to data for those lengths.'''

	fix_angles = {'triclinic':{},
				  'monoclinic':{'al':'90','ga':'90'},
				  'orthorhombic':{'al':'90','be':'90','ga':'90'},
				  'tetragonal':{'al':'90','be':'90','ga':'90'},
				  'hexagonal':{'al':'90','be':'90','ga':'120'},
				  'cubic':{'al':'90','be':'90','ga':'90'},
				  'rhombohedral':{'al':'90','be':'90'}}

	givens = fix_angles[crystal_system]

	for angle in givens.keys():
		data[angle] = givens[angle]
		if angle not in found:
			found.append(angle)

	if len(found) == 3:
		pass
	else:
		for angle in ['al','be','ga']:
			if angle not in found:
				data[angle] = 'Not found'

	return data





def find_alt_parms(raw,data):

	'''If the number of lengths found by find_lengths() is equal to zero, a search for the alternative notation
	of TOPAS .out files is executed. If the number of lengths is still zero after this, print out error and add 
	"Not found" to data for those lengths.'''


	# Patterns are ordered so wider matches (more length groups) are tried first;
	# otherwise an Orthorhombic line would match a 2-length pattern and lose c.
	rexes = [# 3 lengths with error (Orthorhombic)
			 r'([a-zA-Z]+)\(\s*@*\s*(\d+\.\d+`*_\d+\.\d+)[a-zA-Z_]*\d*\.*\d*,\s*@*\s*(\d+\.\d+`*_\d+\.\d+)[a-zA-Z_]*\d*\.*\d*,\s*@*\s*(\d+\.\d+`*_\d+\.\d+)[a-zA-Z_]*\d*\.*\d*',
			 # 3 lengths without error
			 r'([a-zA-Z]+)\(\s*@*\s*(\d+\.\d+)[a-zA-Z_]*\d*\.*\d*`*,\s*@*\s*(\d+\.\d+)[a-zA-Z_]*\d*\.*\d*`*,\s*@*\s*(\d+\.\d+)[a-zA-Z_]*\d*\.*\d*`*',
			 # 2 lengths, various error combinations
			 r'([a-zA-Z]+)\(\s*@*\s*(\d+\.\d+`*_\d+.\d+)[a-zA-Z_]*\d*\.*\d*,\s*@*\s*(\d+\.\d+`*_\d+\.\d+)[a-zA-Z_]*\d*\.*\d*',
			 r'([a-zA-Z]+)\(\s*@*\s*(\d+\.\d+`*_\d+\.\d+)[a-zA-Z_]*\d*\.*\d*,\s*@*\s*(\d+\.\d+)[a-zA-Z_]*\d*\.*\d*`*',
			 r'([a-zA-Z]+)\(\s*@*\s*(\d+\.\d+`*_\d+\.\d+)[a-zA-Z_]*\d*\.*\d*,\s*@*\s*(\d+\.\d+)[a-zA-Z_]*\d*\.*\d*`*',
			 r'([a-zA-Z]+)\(\s*@*\s*(\d+\.\d+)[a-zA-Z_]*\d*\.*\d*`*,\s*@*\s*(\d+\.\d+)[a-zA-Z_]*\d*\.*\d*`*',
			 # 1 length (cubic)
			 r'([a-zA-Z]+)\(\s*@*\s*(\d+.\d+`*_\d+.\d+)[a-zA-Z_]*\d*\.*\d*',
			 r'([a-zA-Z]+)\(\s*@*\s*(\d+.\d+)[a-zA-Z_]*\d*\.*\d*`*\s*']

	match = None
	sys = None
	for rex in rexes:
		match = re.search(rex, raw)
		if match:
			sys = match.group(1)
			break

	if sys:
		if sys == 'Cubic':
			a = match.group(2)
			data['a'] = a; data['b'] = a; data['c'] = a; data['al'] = '90'; data['be'] = '90'; data['ga'] = '90'
			data['crystal_system'] = 'cubic'
		elif sys == 'Hexagonal':
			a,c = match.group(2,3)
			data['a'] = a; data['b'] = a; data['c'] = c; data['al'] = '90'; data['be'] = '90'; data['ga'] = '120'
			data['crystal_system'] = 'hexagonal'
		elif sys == 'Rhombohedral':
			a,ga = match.group(2,3)
			data['a'] = a; data['b'] = a; data['c'] = a; data['al'] = '90'; data['be'] = '90'; data['ga'] = ga
			data['crystal_system'] = 'rhombohedral'
		elif sys == 'Tetragonal':
			a,c = match.group(2,3)
			data['a'] = a; data['b'] = a; data['c'] = c; data['al'] = '90'; data['be'] = '90'; data['ga'] = '90'
			data['crystal_system'] = 'tetragonal'
		elif sys == 'Orthorhombic':
			a,b,c = match.group(2,3,4)
			data['a'] = a; data['b'] = b; data['c'] = c; data['al'] = '90'; data['be'] = '90'; data['ga'] = '90'
			data['crystal_system'] = 'orthorhombic'
		elif sys == 'Monoclinic':
			print('%s alt notation not implemented. format first encountered'%sys)
		elif sys == 'Triclinic':
			print('%s alt notation not implemented. format first encountered'%sys)
		elif sys == 'Trigonal':
			a,c = match.group(2,3)
			data['a'] = a; data['b'] = a; data['c'] = c; data['al'] = '90'; data['be'] = '90'; data['ga'] = '120'
			data['crystal_system'] = 'trigonal'

	else:
		print('No alt notation found.')


	parms = ['a','b','c','al','be','ga']

	for par in parms:
		if par not in data.keys():
			data[par] = 'Not found'
			print('Could not find %s in find_alt_parms(). FILE: %s'%(par,data['filename']))

	return data




def find_lengths(raw,data,crystal_system):

	'''Finds the lengths a,b,c in outfile (str). If not found, add "Not found" to data dict.
	Calls complete_lengths() to check if can be derived from crystal system.'''

	rexes = [r'%s\s+@*\s*(\d+\.\d+`*_\d+\.\d+)[a-zA-Z_]*\d*\.*\d*',
			 r'%s\s+@*\s*(\d+\.\d+)`*_[a-zA-Z_]*\d*\.*\d*',
			 r'%s\s+@*\s*(\d+\.\d+)`',
			 r'%s\s+@*\s*(\d+\.\d+)`*'] # might need to be modified later.

	lengths = ['a','b','c'] # lengths to be searched for
	found = [] # append found lengths so that they can be skipped

	for rex in rexes: # iterate over patterns and break at first match
		for length in lengths:
			if length in found:
				pass
			else:
				match = re.search(rex%length,raw)
				if match:
					data[length] = match.group(1)
					found.append(length)
				else:
					pass


	if len(found) == 3: # all lengths found
		pass
	elif 1 < len(found) < 3: # call complete_lengths()
		data = complete_lengths(raw,data,crystal_system,found)
	elif len(found) == 0: # call find_alt_lengths()
		data = find_alt_parms(raw,data)
	
	return data


def find_angles(raw,data,crystal_system):

	'''Finds the lengths a,b,c in outfile (str). If not found, add "Not found" to data dict.
	Calls complete_lengths() to check if can be derived from crystal system.'''

	rexes = [r'\s+%s\s*@*\s*(\d+.\d+`*_\d+.\d+)',
			 r'\s+%s\s*@*\s*(\d+.\d+)`*',
			 r'\s+%s\s*@*\s*(\d+)[^:]',] # might need to be modified later.

	angles = ['al','be','ga'] # lengths to be searched for
	found = [] # append found lengths so that they can be skipped

	for rex in rexes: # iterate over patterns and break at first match
		for angle in angles:
			if angle in found:
				pass
			else:
				match = re.search(rex%angle,raw)
				if match:
					data[angle] = match.group(1)
					found.append(angle)
				else:
					pass


	if len(found) == 3: # all lengths found
		pass
	elif 1 < len(found) < 3: # call complete_angles()
		data = complete_angles(raw,data,crystal_system,found)
	elif len(found) == 0: # call find_alt_angles()
		data = find_alt_parms(raw,data)
	
	return data


############ new code 
def format_quality(parm, value):
	"""Fit-quality factors (chi/rwp/rexp) carry no esd, so they get plain 2-decimal
	formatting. This used to live inside cryst_round as a `parm` special case; it is
	a presentation choice, so it belongs to this tool rather than to rounding."""
	if re.search(r'\d+\.\d+', value) and parm in ['chi', 'rwp', 'rexp']:
		return '{:.2f}'.format(Decimal(value))
	return value


def get_data(path,data):

	'''Finds all the available data in a TOPAS output file.'''

	with open(path,'r',encoding='utf8',errors='ignore') as inf:
		raw = inf.read()

	data = find_space_group(raw,data) # find space group first
	try:
		data['crystal_system'] = space2cryst[data['space_group'].lower()][1] # now based on new and improved space2cryst
	except KeyError:
		data['crystal_system'] = space2cryst[data['space_group'].lower()][1] # now based on new and improved space2cryst
	data = find_volume(raw,data) # find volume of ??unit cell??

	data = find_lengths(raw,data,data['crystal_system']) # find lengths
	data = find_angles(raw,data,data['crystal_system']) # find angles
	
	# find rwp, rexp and gof (these should be easy)
	rwp = re.search(r'r_wp\s+(\d+\.*\d*)',raw).group(1)
	rexp = re.search(r'r_exp\s+(\d+\.*\d*)',raw).group(1)
	chi = re.search(r'gof\s+(\d+\.*\d*)',raw).group(1)

	data['rwp'] = rwp
	data['rexp'] = rexp
	data['chi'] = chi

	parms = ['a','b','c','al','be','ga','space_group','crystal_system','chi','rwp','rexp','volume']
	for par in parms:
		if par not in data.keys():
			data[par] = 'Not found'

	return data
	


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
			formatted_str = space2cryst[data['space_group'].lower()][0]
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
	# get_data() and make_new_column() read these as module globals. They used to
	# be assigned at module level, so wrapping this block in main() would make them
	# locals and break the lookups. (make_new_column also takes `data` as its
	# `params` argument but reads the global in one branch -- preserved as-is
	# rather than corrected, to keep this move behaviour-neutral.)
	global space2cryst, data

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
		data = {}
		data['filename'] = os.path.basename(file)
		print('%s: (%s/%s)'%(file,i+1,len(input_files)))
		data = get_data(file,data)
		outsoup = make_new_column(template,outsoup,data)
	
	write_soup(outsoup, output_path)
	print('\nWrote %s' % output_path)


if __name__ == '__main__':
	main()
