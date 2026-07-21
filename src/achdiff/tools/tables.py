import re
import os
import fnmatch
import json
import gzip
import base64
from bs4 import BeautifulSoup
from bs4.element import Tag as Bs4Tag
from decimal import Decimal, getcontext
import copy
import argparse
from ..core.rounding import cryst_round


# === EMBEDDED RESOURCE DATA — generated from resource.htm; regenerate with dump_resource.py ===
# _SG_B64   : gzip+base64 of JSON dict { sg_key_lower: [formatted_html_str, crystal_system] }
# _TPL_B64  : gzip+base64 of the resource HTML with the space-group lookup table and trailing
#             stray <p> tags already stripped — ready to use as the column template.
_SG_B64 = (
    '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'
)

_TPL_B64 = (
    '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'
    'yEuUCNqTTeWRZUjfZn/RnxIZKvVS+1Jdy0j/k5NXiTmR+7Z70Hs1UJpM5SknGXKPOdYTCxz+pEzF'
    'yjyalRY/sfuAS/tLf5F6zRpmCkp6kKYpWWndVf+xBq/6sm3zv/20WW5Ll/VdZ797pOqwtNTrfMG7'
    'jsqwpGJbU7mSNn266qja9DX9bcLWRSl69MRldd7/rHpSKujvt0y+/JgNTbpSmnqaOKW/fz/k/lLF'
    '+NLqpLD3P79eKsOLnJeG+BduCBkrBouKVngdiar+0j3W7uXZDgPQWibmX63abLFSF8KrT4Tyb9TH'
    'GPK/BwW92FUjtalhjqoPzGXMsXwxqhejYjvRHMm1tht51mvr//33F/N8Mc/dmNPsxTxfzPOPa572'
    'i3m+mOcf1zz////avX3+3//5Yp8v9rkj+/zfL/b5Yp9/YPv8Py/2+WKff1z7/Pxdws8wXr7vScny'
    'Py+m+mKquzGt+w1TjWc7Efq0XgjdlUjZBf7uxepfrP4PbPX024vZ/ys1+2Q3GbH9DNxs/rfQV/7p'
    'fxQ7C3zf/9+aNr+75b7WeTXvf5D/9/Nrhz2qX6mUHp3hE/ne+x/+GbXpJIz6UgEA'
)
# === END EMBEDDED RESOURCE DATA ===


def _decode_blob(b64):

	'''Inverse of the gzip+base64 encoding used by dump_resource.py.'''

	return gzip.decompress(base64.b64decode(b64)).decode('utf-8')


def load_embedded_template():

	'''Return the resource HTML as a bs4 soup, with the space-group lookup table
	and trailing stray <p> tags already removed (i.e. ready for use as the
	per-file column template).'''

	return BeautifulSoup(_decode_blob(_TPL_B64), 'html.parser')


def load_embedded_space2cryst():

	'''Return the space-group lookup dict: { sg_key_lower: (formatted_html, crystal_system) }.
	`formatted_html` is a pre-serialized HTML string ready to splice into a <td>.'''

	raw = json.loads(_decode_blob(_SG_B64))
	return {k: (v[0], v[1]) for k, v in raw.items()}








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

	input_files = select_files_wizard('.')
	if not input_files:
		raise SystemExit('No files selected — exiting.')

	output_path = prompt_output_filename()
	if not output_path:
		raise SystemExit('No output filename — exiting.')

	template = load_embedded_template()
	outsoup = copy.copy(template)
	for tr in outsoup.find_all('tr'): tr.find_all('td')[-1].decompose() # remove blank column. Change later if useful.
	space2cryst = load_embedded_space2cryst()

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
