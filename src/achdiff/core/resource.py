"""Load the lattice-table resource: the HTML column template and the
space-group -> (formatted symbol, crystal system) lookup.

`resource.htm` is a real file shipped alongside the package, not a blob baked
into the source. It used to be embedded as ~300 lines of gzip+base64 inside the
tables script, which made it invisible to diffs and impossible to edit without
a regeneration step.

The reason it was embedded is real, though: parsing 900 KB of HTML with
BeautifulSoup takes about 1.3 s, against ~9 ms to decode the pre-derived blob.
So the file stays external and authoritative, and the *derived* data is cached
after the first parse:

    resource.htm  --parse (~1.3 s, once)-->  cache  --load (~10 ms, thereafter)

The cache key is a hash of the resource file's contents, so editing or replacing
resource.htm invalidates it automatically -- no manual regeneration step, which
is the failure mode the embedded blob had.
"""

import copy
import gzip
import hashlib
import json
import os
from pathlib import Path

APP_NAME = 'ach-diffraction'
_CACHE_VERSION = 1  # bump when the derived structure changes


def default_resource_path():
	"""The resource.htm shipped with the package."""
	return Path(__file__).resolve().parent.parent / 'data' / 'resource.htm'


def resolve_resource_path(explicit=None):
	"""Locate resource.htm: an explicit path, else ACH_RESOURCE_HTM, else the
	packaged copy. Raises FileNotFoundError if an explicit choice is missing --
	silently falling back would hide a typo in a user's own resource file."""
	for candidate, source in ((explicit, 'the --resource argument'),
	                          (os.environ.get('ACH_RESOURCE_HTM'), 'ACH_RESOURCE_HTM')):
		if candidate:
			path = Path(candidate)
			if not path.is_file():
				raise FileNotFoundError(f'resource.htm from {source} not found: {path}')
			return path

	packaged = default_resource_path()
	if not packaged.is_file():
		raise FileNotFoundError(
			f'Packaged resource.htm is missing ({packaged}). Reinstall the package, '
			f'or point at your own copy with --resource or ACH_RESOURCE_HTM.')
	return packaged


def _cache_dir():
	override = os.environ.get('ACH_CACHE_DIR')
	if override:
		return Path(override)
	try:
		from platformdirs import user_cache_dir
		return Path(user_cache_dir(APP_NAME, appauthor=False))
	except ImportError:
		base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
		return Path(base) / APP_NAME / 'cache'


def _digest(raw_bytes):
	h = hashlib.sha256()
	h.update(f'v{_CACHE_VERSION}\n'.encode())
	h.update(raw_bytes)
	return h.hexdigest()[:16]


def _parse(raw_bytes):
	"""Derive (template_html, space2cryst) from the resource HTML.

	Takes **bytes**, not str, and hands them straight to BeautifulSoup so it can
	detect the encoding from the document's own charset declaration. The file is
	not UTF-8, so decoding it here with errors='replace' silently turns the
	Angstrom sign in `a/A` row headers into U+FFFD, and the table lookup then
	fails with KeyError. dump_resource.py opened it 'rb' for exactly this reason.

	Ported from that script, which used to run this at packaging time. One parse
	is shared between both outputs; the original parsed twice.
	"""
	from bs4 import BeautifulSoup

	soup = BeautifulSoup(raw_bytes, 'html.parser')

	# Lookup table: the last <table> maps space-group keys to a formatted symbol
	# and a crystal system. One row may list several ';'-separated keys.
	space2cryst = {}
	table = soup.find_all('table')[-1]
	for tr in table.find_all('tr')[1:]:
		tds = tr.find_all('td')
		if len(tds) < 3:
			continue
		keys = tds[0].text.strip().split(';')
		formatted = ''.join(str(c) for c in tds[1].p.contents)
		system = tds[2].text.strip()
		for k in keys:
			space2cryst[k.lower().strip()] = [formatted, system]

	# Column template: everything except the lookup table and the trailing
	# stray <p> tags.
	tpl = copy.copy(soup)
	tpl.find_all('table')[-1].decompose()
	for p in tpl.find_all('p')[-2:]:
		p.decompose()

	return str(tpl), space2cryst


def _load_cached(path):
	"""(template_html, space2cryst), parsing only on a cache miss.

	Every cache failure degrades to a direct parse: a stale, corrupt or
	unwritable cache must cost time, never correctness.
	"""
	raw_bytes = Path(path).read_bytes()
	key = _digest(raw_bytes)
	cache_file = _cache_dir() / f'resource-{key}.json.gz'

	try:
		if cache_file.is_file():
			with gzip.open(cache_file, 'rt', encoding='utf-8') as fh:
				data = json.load(fh)
			return data['template'], data['space2cryst']
	except Exception:
		pass  # fall through and re-derive

	template, space2cryst = _parse(raw_bytes)

	try:
		cache_file.parent.mkdir(parents=True, exist_ok=True)
		tmp = cache_file.with_suffix('.tmp')
		with gzip.open(tmp, 'wt', encoding='utf-8') as fh:
			json.dump({'template': template, 'space2cryst': space2cryst}, fh)
		tmp.replace(cache_file)  # atomic, so a concurrent reader never sees a partial file
		# Drop caches from older resource versions rather than accumulating them.
		for old in cache_file.parent.glob('resource-*.json.gz'):
			if old != cache_file:
				try:
					old.unlink()
				except OSError:
					pass
	except Exception as e:
		print(f'[!] Could not write resource cache ({e}); '
		      f'parsing resource.htm each run will be slower.')

	return template, space2cryst


def load(explicit=None):
	"""(template_soup, space2cryst) ready for the tables tool."""
	from bs4 import BeautifulSoup

	path = resolve_resource_path(explicit)
	template_html, space2cryst = _load_cached(path)
	return BeautifulSoup(template_html, 'html.parser'), space2cryst
