"""Vendored copy of ACH-MoloM's crystallography core. Do not edit these files.

Source:   https://github.com/ACH-Repo/ACH-MoloM  (molom/core/)
Version:  molom 0.6.0
Commit:   8422d0b97d1adaf31fd50bc0bf9561b955254d3f
Licence:  MIT, same author and same terms as this package.

Re-sync with `python tools/sync_molom.py` (see that script for the file list).
The files are copied BYTE FOR BYTE so that re-syncing stays a copy rather than
a merge. Anything this suite needs that upstream does not provide belongs in
``achdiff/core/cif.py``, which is the adapter, not in here.

Why vendored rather than depended on
------------------------------------
`molom` is a desktop application: its install pulls PySide6, PyOpenGL, rdkit and
openbabel. This suite is five command-line tools that a lab installs on a TOPAS
PC, and making `pip install ach-diffraction-suite` drag a GUI stack in to draw a
Bragg tick row is the wrong trade. The five modules below are pure Python and
numpy, import nothing from the rest of molom on the paths used here, and total
about 220 KB.

What is used, and what is merely along for the ride
---------------------------------------------------
    cif.py          parse_cif, Cell, SymOp, CifData, expand, site_composition
    pxrd.py         compute, and the Pattern/Reflection types it returns
    spacegroups.py  identify, crystal_system, from_structure
    scattering.py   form-factor coefficients          (pxrd needs it)
    elements.py     atomic numbers and radii          (both need it)

`cif.py` also carries bonding, fragment and packing code for MoloM's viewport,
which lazily imports modules that are deliberately NOT vendored. Those functions
are unreachable from anything here -- `expand` is called with
``whole_molecules=False, boundary=False``, which is the cell-contents path and
touches none of it. If a future change reaches one, the failure is a loud
ImportError naming the missing module, not a wrong number.
"""
