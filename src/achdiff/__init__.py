"""ACH Diffraction Analysis Suite — PXRD and TOPAS analysis tools."""

from importlib.metadata import PackageNotFoundError, version as _version

# Read from the installed distribution rather than repeating the number here.
# A hardcoded literal silently drifted from pyproject.toml once already, and a
# wrong __version__ is the kind of thing nobody notices until they are trying to
# work out which release a colleague is actually running.
try:
	__version__ = _version('ach-diffraction-suite')
except PackageNotFoundError:  # a source tree with nothing installed
	__version__ = '0.0.0+unknown'
