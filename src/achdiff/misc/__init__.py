"""Misc scripts: one-off analyses kept in case they are needed again.

Some analyses are too specific to be a tool -- one figure for one paper, one
comparison for one talk -- but come up again a year later as "we did this
before, do we still have it?". These live here, where `achdiff misc` can list
them, explain them, run them, and copy one out to be edited by hand.

Where scripts come from
-----------------------
  - the package, in achdiff/misc/scripts/: reviewed, and on every machine after
    an upgrade;
  - the lab's own folder, if `misc_dir` is set (`achdiff profile set --global
    misc_dir=D:\\...`, or ACH_MISC_DIR): anything dropped there is picked up
    without a release. A script there with a packaged script's name replaces it.

What makes a file a misc script
-------------------------------
A .py file whose name does not start with `_`, with:

  - a module docstring. Its first line is the one-line summary `achdiff misc`
    lists; the rest is what `achdiff misc show` prints.
  - optionally, a literal `ABOUT = {'for': ..., 'author': ..., 'written': ...}`,
    saying which paper or talk it was written for. That is what someone searching
    for "the thing we did for that paper" will recognise.
  - `main(argv=None, command=None)`. With no arguments it asks for what it needs,
    so it explains itself; with arguments it runs straight through.

Scripts import from the suite only through achdiff.misc.kit, and only with
absolute imports, so a copy runs wherever it is put. See kit.py.

Descriptions are read with `ast`, without importing the script: listing should
cost nothing, and one broken script must not hide the others.
"""

import ast
import importlib
import importlib.util
import shutil
from collections import namedtuple
from pathlib import Path

from .. import config

PACKAGED_DIR = Path(__file__).resolve().parent / 'scripts'

Script = namedtuple('Script', 'name path source summary about doc')


def lab_dir(user=None):
	"""The lab's own misc folder, or None when it is not set or not there."""
	value = config.get('misc_dir', user=user)
	if not value:
		return None
	path = Path(value)
	return path if path.is_dir() else None


def _describe(path, source):
	"""A Script for `path`, read without importing it. None if it is not one."""
	try:
		tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
	except (OSError, SyntaxError) as e:
		return Script(path.stem, path, source, f'(cannot be read: {e})', {}, '')
	doc = ast.get_docstring(tree) or ''
	about = {}
	for node in tree.body:
		if (isinstance(node, ast.Assign) and len(node.targets) == 1
				and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'ABOUT'):
			try:
				value = ast.literal_eval(node.value)
			except ValueError:
				value = {}
			if isinstance(value, dict):
				about = {str(k): str(v) for k, v in value.items()}
	summary = doc.strip().splitlines()[0] if doc.strip() else '(no description)'
	return Script(path.stem, path, source, summary, about, doc)


def _scan(directory, source):
	if directory is None or not directory.is_dir():
		return []
	return [_describe(p, source) for p in sorted(directory.glob('*.py'))
	        if not p.name.startswith('_')]


def available(user=None):
	"""Every misc script, by name. A lab script shadows a packaged one."""
	found = {s.name: s for s in _scan(PACKAGED_DIR, 'packaged')}
	for script in _scan(lab_dir(user), 'lab'):
		found[script.name] = script
	return dict(sorted(found.items()))


def find(name, user=None):
	"""The script called `name` (with or without .py), or None."""
	return available(user).get(Path(name).stem)


def load(script):
	"""Import a script as a module. Packaged ones import by name, so their own
	tracebacks read normally; a lab file is loaded from its path."""
	if script.source == 'packaged':
		return importlib.import_module(f'{__name__}.scripts.{script.name}')
	spec = importlib.util.spec_from_file_location(f'achdiff_misc_{script.name}', script.path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def run(script, argv):
	"""Run a script's main() as `achdiff misc run NAME`. Returns its exit code."""
	module = load(script)
	if not hasattr(module, 'main'):
		print(f'[!] {script.path} has no main() to run.')
		return 1
	return module.main(list(argv), command=['achdiff', 'misc', 'run', script.name]) or 0


def copy(script, directory, force=False):
	"""Copy a script into `directory` to be edited by hand. Returns the new path,
	or None if a file of that name is there and `force` was not given."""
	directory = Path(directory)
	directory.mkdir(parents=True, exist_ok=True)
	target = directory / script.path.name
	if target.exists() and not force:
		return None
	shutil.copyfile(str(script.path), str(target))
	return target
