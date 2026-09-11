"""Re-copy the vendored MoloM crystallography modules.

	python tools/sync_molom.py [path/to/ACH-MoloM]

Verbatim copies, never a merge: the adapter that adapts is
``achdiff/core/cif.py``, so these files can always be replaced wholesale from
upstream. The script reports the new version and commit for the header in
``achdiff/core/_molom/__init__.py``, which is the only thing that needs editing
by hand afterwards.
"""

import shutil
import subprocess
import sys
from pathlib import Path

MODULES = ('cif.py', 'pxrd.py', 'spacegroups.py', 'scattering.py', 'elements.py')

DEFAULT_SOURCES = (
	Path.home() / 'Documents' / 'Github' / 'ACH-MoloM',
	Path(__file__).resolve().parents[2] / 'ACH-MoloM',
)


def find_source(explicit=None):
	if explicit:
		path = Path(explicit)
		if not (path / 'molom' / 'core').is_dir():
			sys.exit(f'[!] Not a MoloM checkout: {path}')
		return path
	for candidate in DEFAULT_SOURCES:
		if (candidate / 'molom' / 'core').is_dir():
			return candidate
	sys.exit('[!] Could not find an ACH-MoloM checkout. Pass its path as an argument.')


def describe(repo):
	"""(version, commit) for the header, best effort."""
	version = commit = '?'
	pyproject = repo / 'pyproject.toml'
	if pyproject.is_file():
		for line in pyproject.read_text(encoding='utf-8').splitlines():
			if line.strip().startswith('version'):
				version = line.split('=', 1)[1].strip().strip('"\'')
				break
	try:
		commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=str(repo),
		                                 text=True).strip()
	except Exception:
		pass
	return version, commit


def main(argv):
	repo = find_source(argv[0] if argv else None)
	source = repo / 'molom' / 'core'
	target = Path(__file__).resolve().parents[1] / 'src' / 'achdiff' / 'core' / '_molom'
	target.mkdir(parents=True, exist_ok=True)

	changed = []
	for name in MODULES:
		src, dst = source / name, target / name
		if not src.is_file():
			sys.exit(f'[!] Missing upstream module: {src}')
		before = dst.read_bytes() if dst.is_file() else None
		shutil.copyfile(src, dst)
		if before != dst.read_bytes():
			changed.append(name)

	version, commit = describe(repo)
	print(f'[+] Synced from {repo}')
	print(f'    molom {version}, commit {commit}')
	if changed:
		print(f'    Updated: {", ".join(changed)}')
		print('    Update the Version/Commit lines in core/_molom/__init__.py,')
		print('    then run the tests -- they cross-check the pattern arithmetic.')
	else:
		print('    Already up to date.')
	return 0


if __name__ == '__main__':
	sys.exit(main(sys.argv[1:]))
