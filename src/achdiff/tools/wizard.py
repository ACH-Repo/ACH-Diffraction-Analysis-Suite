"""
TOPAS Pawley Input File Wizard
---------------------------------------------
An interactive guide to generating structureless profile fitting (.inp)
files for TOPAS using raw powder diffraction data and CIF files.

Author: <author>
"""

import os
import re
import argparse
import warnings
import zipfile
import subprocess
from glob import glob
from pathlib import Path
from datetime import datetime, timezone
from string import Template

from .. import cmdline, config, identity
from ..core import cif as cifcore
from ..progname import prog_name

# Clear the screen helper to keep the interactive wizard clean
def clear_terminal():
	os.system('cls' if os.name == 'nt' else 'clear')

# Third-party UserWarnings would break up the wizard's step-by-step prompts.
# CIF problems are not among them: core.cif reports those itself, as one line.
warnings.filterwarnings('ignore', category=UserWarning)

# ==========================================
# CONFIGURATION & STATIC PARAMETERS
# ==========================================

SETTINGS = {
	'script_author': '<author>',
	'cif_dir_path': r'D:\Workfolder\<you>\CIF_LOC',
	'iters': '10000',
	'separator_ident': '_pawley_01_',
	'chi2_convergence_criteria': '0.000001',
	'background': {
		'silicon': '    bkg @  30.9618721`_0.240439549 -37.1396551`_0.468612083  33.8178878`_0.44923613 -25.90741`_0.433971233  20.050838`_0.4157879 -14.6562686`_0.404506321  10.8548316`_0.389354685 -7.72420954`_0.380662009  5.50074972`_0.366037733 -4.30996759`_0.357429541  3.47435625`_0.341449469 -2.72229109`_0.332590151  2.3111087`_0.314012948 -2.03661761`_0.303873676  1.95264549`_0.278450101 -1.41044712`_0.265500849  1.12996981`_0.229229818 -0.8580948`_0.213015975  0.397323392`_0.158635541 -0.0357493258`_0.146396987',
		'plastic': '    bkg @  860.753629`_0.723598354 -98.5554109`_1.16110493 -494.305045`_1.15182582  309.90145`_1.18903314 -130.200864`_1.14160424 -86.7379659`_1.10782238  221.728599`_1.1139766 -192.037649`_1.1060611  6.65642529`_1.08577461  175.77403`_1.08070801 -100.363605`_1.07551574 -42.0731558`_1.06762225  36.4692085`_1.05599806 -19.5143084`_1.05433552  28.3104228`_1.04599496 -7.22474793`_1.04126246 -23.2691724`_1.03036836  29.7258505`_1.02798308 -10.33057`_1.01607319 -12.5713769`_1.01343502  20.3515923`_1.0066962 -13.4776076`_1.00304506  2.25033519`_0.986478166  7.78199109`_0.982839888 -10.5541492`_0.947122343  3.31755524`_0.94576328  6.02889461`_0.931613918 -7.92327799`_0.921556634  4.18526805`_0.909967606  0.783985182`_0.909815486'
	},
	# Coefficient count for the zeroed polynomial offered as the default background.
	'background_default_order': 6,
	'diffractometer': {
		'siemens_5005': "\n    LP_Factor(!th2_monochromator, 26.6)\n    CuKa2(0.0001)\n    Specimen_Displacement(height,-0.04784`_0.00142)",
		'd08': "\n    LP_Factor(!th2_monochromator, 0)\n    CuKa2_analyt(0.0001)\n    Specimen_Displacement(height,0)"
	},
	# Trusted starting cell parameters are per person and live in the user's
	# config (achdiff trusted add/list), not here. They are one person's refined
	# result for one sample on one instrument, so shipping a set with the package
	# would seed everyone's refinements with a cell measured on somebody else's
	# material.
	'use_trusted_params': True,
}

# Python Template objects make text insertion safe and clear
INP_TEMPLATE = Template(''''--------------------------------------------------------------
'Input File for structureless profile fitting (Pawley).
'Created using python for <group> @ TU-Dortmund.
'Script name: $script_name
'Rundate: $run_date
'Script author $author
'--------------------------------------------------------------

'Fit-Quality Parameters: (No need to provide sensible initial values)
r_wp  0  r_exp  0  r_p  0  r_wp_dash  0  r_p_dash  0  r_exp_dash  0  weighted_Durbin_Watson  0  gof  0


'Fit-Settings: max-iterations, convergence criteria, etc.
iters $iters
chi2_convergence_criteria $chi2_convergence
do_errors


'Load experimental data to be fitted.
xdd $exp_file
	x_calculation_step = Yobs_dx_at(Xo); convolution_step 4

'Add Diffractometer settings
$background_str
$instrument_str

$phase_macros

Out_X_Yobs("${out_name}${sep}X_Yobs.txt")
Out_X_Ycalc("${out_name}${sep}Out_X_Ycalc.txt")
Out_X_Difference("${out_name}${sep}X_Difference.txt")
''')

# Cell parameters a trusted entry may carry. Anything else in the entry is
# provenance metadata (source, registered) and must never reach a macro call.
_CELL_KEYS = ('a', 'b', 'c', 'al', 'be', 'ga')

# Cell macros written into the .inp. Every name here must exist in the
# topas.inc of the machine that runs the file: TOPAS does not ship all of these,
# and this group's topas.inc carries hand-added definitions. An undefined macro
# is not a warning at run time, it is a refinement that will not start -- so
# nothing may be added to this table without the definition going in alongside it.
CRYSTAL_MACROS = {
	'triclinic': 'Triclinic(@ $a, @ $b, @ $c, @ $al, @ $be, @ $ga)',
	'monoclinic': 'Monoclinic(@ $a, @ $b, @ $c, @ $be)',
	'orthorhombic': 'Orthorhombic(@ $a, @ $b, @ $c)',
	'tetragonal': 'Tetragonal(@ $a, @ $c)',
	'trigonal': 'Trigonal(@ $a, @ $c)',
	'hexagonal': 'Hexagonal(@ $a, @ $c)',
	'cubic': 'Cubic(@ $a)'
}

# Systems with no macro of their own, and the one they borrow.
#
# `Rhombohedral(a, alpha)` is the honest macro for a trigonal group on
# rhombohedral axes, and it is deliberately NOT in the table above: it is not
# defined in this group's topas.inc, so emitting it would produce a .inp that
# TOPAS refuses to run. It used to be listed, but nothing could ever select it
# -- the crystal system came from pymatgen, which reports such a group as
# `trigonal` and has no name for the setting -- so the entry was unreachable and
# no .inp has ever contained the macro.
#
# Trigonal's macro assumes HEXAGONAL axes, so borrowing it for a rhombohedral
# cell writes a cell that is simply wrong rather than one that fails to start.
# That is the pre-existing behaviour and it stays, because a wrong cell can be
# spotted and corrected while an unstartable file blocks the whole run -- but it
# is now said out loud instead of happening silently. Define `Rhombohedral` in
# topas.inc and move it into the table above to fix it properly.
MACRO_FALLBACKS = {'rhombohedral': 'trigonal'}

_FALLBACK_WARNING = {
	'rhombohedral':
		'the cell is on rhombohedral axes (a = b = c, equal angles off 90) but is '
		'being written with Trigonal(a, c), which assumes hexagonal axes. The cell '
		'in the .inp will be wrong. Either convert the CIF to hexagonal axes, or '
		'define Rhombohedral(a, al) in your topas.inc and edit the macro call by hand.',
}

# TOPAS Kα2 macro names per anode: (no_secondary_mono, with_secondary_mono)
_KA2_MACROS = {
	'Cu': ('CuKa2_analyt', 'CuKa2'),
	'Mo': ('MoKa2_analyt', 'MoKa2'),
	'Co': ('CoKa2_analyt', 'CoKa2'),
	'Cr': ('CrKa2_analyt', 'CrKa2'),
	'Fe': ('FeKa2_analyt', 'FeKa2'),
	'Ag': ('AgKa2_analyt', 'AgKa2'),
}

# ==========================================
# WIZARD DATA FUNCTIONS
# ==========================================

def select_from_list(prompt: str, options: list) -> int:
	"""Prints a numbered list and returns the index the user selects."""
	for idx, option in enumerate(options):
		print(f"  [{idx}] -> {option}")
	while True:
		try:
			choice = int(input(prompt).strip())
			if 0 <= choice < len(options):
				return choice
			raise IndexError
		except (ValueError, IndexError):
			print("  Invalid choice. Please select from the listed indices.")


def prompt_positive_int(prompt: str) -> int:
	"""Reads a positive whole number, re-asking until it gets one."""
	while True:
		try:
			value = int(input(prompt).strip())
			if value > 0:
				return value
		except ValueError:
			pass
		print("  Invalid entry. Please give a positive whole number.")


def zero_background(order: int) -> str:
	"""A refined polynomial background of `order` coefficients, all starting at zero.
	The default and custom background options differ only in `order`, so both are
	built from here rather than being stored as separate literal presets."""
	return '    bkg @ ' + ' '.join(['0'] * order)


def comment_wrap(text: str, width: int = 80) -> str:
	"""Wraps user comments to keep them cleanly formatted inside the .inp file."""
	if not text.strip():
		return ""
	words = text.split()
	lines = []
	current_line = []

	for word in words:
		if sum(len(w) for w in current_line) + len(current_line) + len(word) > (width - 2):
			lines.append(f"' {' '.join(current_line)}")
			current_line = [word]
		else:
			current_line.append(word)
	if current_line:
		lines.append(f"' {' '.join(current_line)}")
	return "\n".join(lines)


def get_cif_parameters(file_path: str, derive_symmetry: bool = False) -> dict:
	"""Lattice parameters and symmetry for one CIF, as strings ready for a .inp.

	The space group is the one the FILE declares. It is not re-derived from the
	coordinates, and that is the point: a CIF whose header disagrees with its
	atoms is a CIF with something wrong in it, and quietly substituting a better
	answer hides the problem at exactly the moment it is cheapest to notice --
	while writing a group into `space_group` and into every tick file's name that
	the depositor never claimed.

	`derive_symmetry=True` (the wizard's --derive-symmetry) asks for the
	coordinates to decide instead, at the same symprec pymatgen used when this
	went through it. It is offered because the answer is genuinely useful on a
	file that has been expanded to P1 by a conversion tool -- but it is opt-in,
	so it is never something the .inp went through without anyone saying so.
	"""
	phase = cifcore.load_phase(file_path)
	cell = phase.cell_parameters()

	if derive_symmetry:
		sg_num, sg_hm = phase.detected_symmetry(symprec=0.01)
		cryst_sys = phase.detected_crystal_system(symprec=0.01)
	else:
		sg_num, sg_hm = phase.space_group_number, phase.space_group_symbol
		cryst_sys = phase.crystal_system

	return {
		'a': f'{cell["a"]:g}', 'b': f'{cell["b"]:g}', 'c': f'{cell["c"]:g}',
		'al': f'{cell["alpha"]:g}', 'be': f'{cell["beta"]:g}', 'ga': f'{cell["gamma"]:g}',
		'V': f'{phase.volume:g}',
		'sg_num': str(sg_num),
		'sg_HM': sg_hm,
		'cryst_sys': cryst_sys.lower(),
	}



def build_phase_section(phases: list, sep: str, out_name: str,
                        include_simple_axial: bool = True) -> str:
	"""Builds individual TOPAS block syntax strings for all selected target phases.

	include_simple_axial: set False when Full_Axial_Model is already in the
	instrument block (avoids double-counting axial divergence).
	"""
	axial_line = "\t\tSimple_Axial_Model(axial$idx, 3)\n" if include_simple_axial else ""
	sections = []
	peak_template = Template(
		"\thkl_Is\n"
		"\t\tTCHZ_Peak_Type(@ u$idx, 0.01, @ v$idx, 0.01, @ w$idx, 0.01, , 0, @ x$idx, 0.01, , 0)\n"
		+ axial_line +
		"\t\t$macro_call\n"
		"\t\tspace_group \"$sg_num\"\n\n"
		"\t\tcell_volume $vol\n\n\n"
		"\tCreate_2Th_Ip_file(\"${out_name}${sep}2Th_Ip_p${idx}_${sg_num}.txt\")\n\n"
	)

	for i, phase in enumerate(phases, start=1):
		cryst_sys = phase['cryst_sys']
		if cryst_sys in MACRO_FALLBACKS:
			warning = _FALLBACK_WARNING.get(cryst_sys, '')
			print(f'[!] Phase {i} ({phase.get("sg_HM", "?")}): {warning}')
			cryst_sys = MACRO_FALLBACKS[cryst_sys]
		if cryst_sys not in CRYSTAL_MACROS:
			continue

		macro_template = Template(CRYSTAL_MACROS[cryst_sys])
		macro_call = macro_template.substitute(
			a=phase['a'], b=phase['b'], c=phase['c'],
			al=phase['al'], be=phase['be'], ga=phase['ga']
		)

		section_str = peak_template.substitute(
			idx=i, macro_call=macro_call, sg_num=phase['sg_num'],
			vol=phase['V'], out_name=out_name, sep=sep
		)
		sections.append(section_str)

	return "".join(sections)


def parse_brml_instrument(brml_path: str) -> tuple:
	"""
	Parse a Bruker BRML file to derive a TOPAS instrument settings string.

	Reads Experiment0/MeasurementContainer.xml from the BRML archive and extracts:
	- Anode material → selects Kα2 correction macro and LP_Factor angle
	- Presence of a secondary crystal monochromator → LP_Factor angle (0 or 26.6°)
	- Goniometer radius
	- Primary and secondary Soller axial divergence angles

	Source-focus length (12 mm), sample length (20 mm), and detector aperture
	(14 mm) are Bruker D8 / LYNXEYE defaults and are not stored in the BRML.

	Returns (instrument_str, description, fp_axial_model_used).
	Raises ValueError if critical tube data is missing.
	"""
	with zipfile.ZipFile(brml_path, 'r') as z:
		with z.open('Experiment0/MeasurementContainer.xml') as f:
			xml = f.read().decode('utf-8')

	# --- Anode / tube material ---
	tube_block_match = re.search(
		r'xsi:type="TubeMountData"(.*?)</MountedComponent>', xml, re.DOTALL
	)
	if not tube_block_match:
		raise ValueError("No TubeMountData block found — cannot auto-detect instrument settings.")
	anode_match = re.search(r'<TubeMaterial Value="([^"]+)"', tube_block_match.group(1))
	if not anode_match:
		raise ValueError("TubeMaterial not found inside tube mount block.")
	anode = anode_match.group(1)
	if anode not in _KA2_MACROS:
		raise ValueError(f"Anode '{anode}' has no known TOPAS Kα2 macro — configure manually.")

	# --- Secondary crystal monochromator ---
	mounted_blocks = re.findall(
		r'<PositionStatus>Mounted</PositionStatus>.*?</MountedComponent>',
		xml, re.DOTALL
	)
	has_secondary_mono = any('monochromator' in b.lower() for b in mounted_blocks)
	lp_angle = 26.6 if has_secondary_mono else 0
	ka2_macro = _KA2_MACROS[anode][1 if has_secondary_mono else 0]

	# --- Goniometer radius ---
	radius_match = re.search(r'<Radius Unit="mm" Value="([1-9][0-9]+)"', xml)
	radius = int(float(radius_match.group(1))) if radius_match else None

	# --- Soller axial divergence angles ---
	# Primary track: Mini axial Soller (MountedOptic inside SollerMount MountedComponent)
	prim_soller_match = re.search(
		r'<MountedOptic[^>]*BeringClassPath="/Component/Optic/Soller/Axial/Mini[^"]*"'
		r'(.*?)</MountedOptic>',
		xml, re.DOTALL
	)
	# Secondary / detector-attached Soller
	sec_soller_match = re.search(
		r'<MountedOptic[^>]*BeringClassPath="/Component/Optic/Soller/Axial/DetectorAttached[^"]*"'
		r'(.*?)</MountedOptic>',
		xml, re.DOTALL
	)

	def _soller_angle(match):
		if not match:
			return None
		m = re.search(r'<AxialDivergence[^>]*Value="([^"]+)"', match.group(1))
		return float(m.group(1)) if m else None

	prim_soller = _soller_angle(prim_soller_match)
	sec_soller = _soller_angle(sec_soller_match)

	# If one of the two Soller angles is missing, fall back to the other
	if prim_soller is None and sec_soller is not None:
		prim_soller = sec_soller
	elif sec_soller is None and prim_soller is not None:
		sec_soller = prim_soller

	# --- Build the TOPAS instrument string ---
	use_fp_axial = radius is not None and prim_soller is not None

	lines = [
		f"\n    LP_Factor(!th2_monochromator, {lp_angle})",
		f"\n    {ka2_macro}(0.0001)",
	]
	if use_fp_axial:
		lines.append(f"\n    Radius({radius})")
		# Hardcoded geometry defaults: source focus 12 mm, flat-plate sample 20 mm,
		# detector aperture 14 mm (LYNXEYE-class). Adjust if geometry differs.
		lines.append(
			f"\n    Full_Axial_Model(12, 20, 14, {prim_soller:g}, {sec_soller:g})"
		)
	lines.append("\n    Specimen_Displacement(height,0)")

	instrument_str = "".join(lines)

	mono_label = "secondary monochromator" if has_secondary_mono else "no secondary monochromator"
	soller_label = (
		f"Soller {prim_soller:g}°/{sec_soller:g}°, Radius {radius} mm"
		if use_fp_axial else "no Soller/radius data"
	)
	description = f"{anode} anode, LP_Factor={lp_angle}° ({mono_label}), {soller_label}"
	return instrument_str, description, use_fp_axial

# ==========================================
# WIZARD INTERACTIVE CONSOLE FLOW
# ==========================================

def run_topas(inp_path, exe):
	"""Run the refinement engine on an existing .inp. Returns a process exit code.

	The engine runs with its working directory set to the .inp's own folder and
	is handed the bare filename, because a Pawley .inp names its outputs
	relatively (`Out_X_Yobs("name_pawley_01_X_Yobs.txt")`). Launching from
	elsewhere would otherwise scatter the results into whatever directory the
	command happened to be typed in.
	"""
	inp = Path(inp_path)
	if not inp.is_file():
		print(f'[-] No such file: {inp}')
		return 1
	if inp.suffix.lower() != '.inp':
		print(f'[!] {inp.name} does not end in .inp; passing it to TOPAS anyway.')
	if not os.path.exists(exe):
		print(f'[-] Refinement engine not found at {exe}')
		print('    Point at yours with --topas, the TOPAS_EXE environment variable,')
		print('    or: achdiff profile set -u <ID> topas_exe="C:\\...\\tc.exe"')
		return 1

	print(f'[*] Running {exe}')
	print(f'    on {inp.name}  (in {inp.parent.resolve()})')
	try:
		# check=False: a refinement that fails to converge is a normal outcome to
		# report, not a Python traceback.
		result = subprocess.run([exe, inp.name], cwd=str(inp.parent.resolve()))
	except OSError as e:
		print(f'[-] Could not start the engine: {e}')
		return 1
	if result.returncode == 0:
		print('[+] TOPAS run complete.')
	else:
		print(f'[-] TOPAS exited with code {result.returncode}.')
	return result.returncode


def _build_parser():
	parser = argparse.ArgumentParser(
		prog=prog_name('rp'),
		description='Interactive wizard generating TOPAS Pawley .inp files. '
		            'Given an existing .inp, runs the refinement on it instead.')
	parser.add_argument('inp', nargs='?', default=None, metavar='FILE.inp',
	                    help='Run TOPAS on this file and exit, skipping the wizard. '
	                         'For .inp files you have edited by hand.')
	parser.add_argument('--topas', dest='topas_exe', default=None, metavar='PATH',
	                    help='Path to the TOPAS executable (tc.exe). Overrides the '
	                         'TOPAS_EXE env var and any saved profile.')
	parser.add_argument('--cif-loc', dest='cif_loc', default=None,
	                    help='CIF library directory. Overrides the CIF_LOC env var '
	                         'and any saved profile.')
	parser.add_argument('--derive-symmetry', action='store_true',
	                    help='Work the space group out from the atomic coordinates '
	                         'instead of reading it from the CIF header. Useful for a '
	                         'file some conversion tool expanded to P1. Off by default: '
	                         'a header that disagrees with its own atoms is a fault in '
	                         'the file, and silently correcting it writes a group into '
	                         'your .inp that nobody claimed.')
	identity.add_user_argument(parser)
	cmdline.add_arguments(parser)
	return parser


def main():
	# parse_args, not parse_known_args: a mistyped flag must stop the run, not
	# be dropped -- least of all when -d is about to write it down.
	args = cmdline.parse_args(_build_parser(), 'rp', 'achdiff.tools.wizard')

	# `rp somefit.inp` is a direct engine run, not a wizard session: the file
	# already exists, usually because it was edited by hand after generation.
	if args.inp:
		user, _ = identity.resolve(args.user)
		exe = config.get('topas_exe', cli_value=args.topas_exe, user=user)
		return run_topas(args.inp, exe)

	clear_terminal()
	print("====================================================")
	print("      Welcome to the TOPAS Input File Wizard        ")
	print("====================================================")
	print("This tool will guide you step-by-step to generate a ")
	print("specialized .inp template for structureless Pawley fits.\n")

	# Resolve the person and their CIF library before Step 2 needs it.
	user, source = identity.resolve(args.user)
	if args.user or user:
		print(identity.describe(user, source))
	SETTINGS['cif_dir_path'] = config.get('cif_loc', cli_value=args.cif_loc, user=user)

	if args.save_profile:
		if not args.user:
			print('[!] --save-profile needs -u ID to say which profile to write.')
		else:
			path = config.save_profile(args.user, {'cif_loc': SETTINGS['cif_dir_path']})
			print(f'[+] Saved profile {args.user} to {path}')

	# Step 1: Locate Experimental Data File
	exp_files = glob('*.xy') + glob('*.raw') + glob('*.brml')
	if not exp_files:
		print("[-] Error: No powder data files found (*.xy, *.raw, *.brml) in this directory.")
		return

	print("[Step 1/6] Choose your experimental powder dataset:")
	file_idx = select_from_list('\nSelect experimental file by entering its index number: ', exp_files)
	exp_file = exp_files[file_idx]

	# Step 2: Read and Select Crystal Phases
	print(f"\n[Step 2/6] Reading database files from: {SETTINGS['cif_dir_path']} ...")
	cif_paths = glob(os.path.join(SETTINGS['cif_dir_path'], '*.cif'))

	available_phases = {}
	for path in cif_paths:
		name = Path(path).stem
		try:
			available_phases[name] = get_cif_parameters(
				path, derive_symmetry=bool(getattr(args, 'derive_symmetry', False)))
		except Exception:
			continue  # Silently skip malformed CIFs

	if not available_phases:
		print("[-] Error: No valid .cif structural templates found in the path directory.")
		return

	print("\nAvailable Crystallographic Reference Phases found:")
	print("  " + ", ".join(available_phases.keys()))

	selected_phase_data = []
	user_input_phases = []
	while True:
		user_raw = input('\nType desired phase names (space-separated, case-sensitive): ').strip().split()
		if user_raw and all(p in available_phases for p in user_raw):
			user_input_phases = user_raw
			selected_phase_data = [dict(available_phases[p]) for p in user_input_phases]
			break
		print("[-] Verification Error: One or more phase names were misspelled or missing. Try again.")

	# Apply trusted starting parameters when available and the toggle is on
	# Trusted parameters come from the running person's profile and nowhere else.
	# They are an empirical result from one person's sample on one instrument, so
	# inheriting a colleague's would seed the refinement with a cell that was
	# never measured on this material.
	trusted_phases_applied = []
	if SETTINGS.get('use_trusted_params'):
		trusted = config.trusted_params(user)
		for i, name in enumerate(user_input_phases):
			entry = trusted.get(name)
			if not entry:
				continue
			# Only cell parameters are merged; `source` / `registered` are
			# provenance metadata and must not reach the macro call.
			cell = {k: v for k, v in entry.items() if k in _CELL_KEYS}
			if not cell:
				continue
			selected_phase_data[i] = {**selected_phase_data[i], **cell}
			trusted_phases_applied.append(name)
			origin = entry.get('source')
			print(f"  [*] Trusted parameters for {name} "
			      f"({', '.join(sorted(cell))}{' from ' + origin if origin else ''})")
		if not trusted_phases_applied and trusted:
			print(f"  [*] No trusted parameters matched. {user} has: "
			      f"{', '.join(sorted(trusted))}")

	# Step 3: Device Configuration Selection
	# If a BRML file was selected, try to auto-detect settings from it first.
	instrument_str = None
	device_choice = None
	fp_axial_used = False

	if exp_file.lower().endswith('.brml'):
		print("\n[Step 3/6] Detecting instrument settings from BRML file ...")
		try:
			auto_instr_str, auto_desc, fp_axial_detected = parse_brml_instrument(exp_file)
			print(f"  [+] Detected: {auto_desc}")
			print("  Derived TOPAS instrument block:")
			for line in auto_instr_str.strip().splitlines():
				print(f"    {line}")
			answer = input('\nUse auto-detected settings? [Y/n]: ').strip().lower()
			if answer in ('', 'y'):
				instrument_str = auto_instr_str
				device_choice = f"brml_auto ({auto_desc})"
				fp_axial_used = fp_axial_detected
		except Exception as exc:
			print(f"  [-] Auto-detection failed: {exc}")

	if instrument_str is None:
		if exp_file.lower().endswith('.brml'):
			print("  Falling back to manual configuration.")
		else:
			print("\n[Step 3/6] Select the instrument configuration (Diffractometer):")
		devices = list(SETTINGS['diffractometer'].keys())
		dev_idx = select_from_list('Select instrument profile index: ', devices)
		device_choice = devices[dev_idx]
		instrument_str = SETTINGS['diffractometer'][device_choice]

	# Step 4: Background Configuration Selection
	# Order is fixed: the zeroed default first (it suits any holder and is the safe
	# starting point), then the measured holder presets, then the custom escape hatch.
	print("\n[Step 4/6] Select the sample holder for background math operations:")
	default_order = SETTINGS['background_default_order']
	presets = list(SETTINGS['background'].keys())
	bkg_labels = ([f'default ({default_order} zeros)'] + presets
	              + ['custom number of zeros'])
	bkg_idx = select_from_list('Select background profile index: ', bkg_labels)

	if bkg_idx == 0:
		order = default_order
		bkg_choice = f'default ({order} zeros)'
		background_str = zero_background(order)
	elif bkg_idx == len(bkg_labels) - 1:
		order = prompt_positive_int('How many zero coefficients? ')
		bkg_choice = f'custom ({order} zeros)'
		background_str = zero_background(order)
	else:
		bkg_choice = presets[bkg_idx - 1]
		background_str = SETTINGS['background'][bkg_choice]

	# Step 5: Name Strategy Definition
	print("\n[Step 5/6] Naming Strategy:")
	custom_name = input('Provide custom .inp filename root (Leave blank to use data file name): ').strip()
	out_name = custom_name if custom_name else Path(exp_file).stem

	# Step 6: Log Annotations
	print("\n[Step 6/6] Metadata Logging:")
	custom_user_comment = input('Add a specific run note/comment to the output file header? (optional): ').strip()
	wrapped_user_comment = comment_wrap(custom_user_comment)

	# Compile the final .inp content securely
	phase_macros_block = build_phase_section(
		selected_phase_data, SETTINGS['separator_ident'], out_name,
		include_simple_axial=not fp_axial_used
	)

	final_output_contents = INP_TEMPLATE.substitute(
		script_name=Path(__file__).name,
		run_date=datetime.now(timezone.utc).astimezone().strftime('%d/%m/%Y %H:%M:%S %Z'),
		author=SETTINGS['script_author'],
		iters=SETTINGS['iters'],
		chi2_convergence=SETTINGS['chi2_convergence_criteria'],
		exp_file=exp_file,
		background_str=background_str,
		instrument_str=instrument_str,
		phase_macros=phase_macros_block,
		out_name=out_name,
		sep=SETTINGS['separator_ident']
	)

	# Format automatic diagnostic logging parameters cleanly
	phase_strings = [f'"{n}" ({p["sg_num"]})' for n, p in zip(user_input_phases, selected_phase_data)]
	joined_phases = " | ".join(phase_strings)

	trusted_note = (
		f"Trusted params applied to: {', '.join(trusted_phases_applied)}\n"
		if trusted_phases_applied else ""
	)
	audit_trail = (
		f"Selected phases: {joined_phases}\n"
		f"Selected device: \"{device_choice}\"\n"
		f"Selected background: \"{bkg_choice}\"\n"
		+ trusted_note
	)
	formatted_audit = "\n".join([f"' {line}" for line in audit_trail.splitlines()])

	# Stitch full file syntax layout together
	full_file_str = ""
	if wrapped_user_comment:
		full_file_str += f"' USER LAB COMMENT:\n{wrapped_user_comment}\n"
	full_file_str += f"' ENGINE SYSTEM AUTOMATION LOG:\n{formatted_audit}\n{final_output_contents}"

	# Clear terminal before previewing output strings to look clean
	clear_terminal()
	print("====================================================")
	print("     GENERATED TOPAS RUNTIME SCRIPT PREVIEW         ")
	print("====================================================")
	# Print the first 25 lines as a sanity-check preview
	preview_lines = full_file_str.splitlines()[:25]
	print("\n".join(preview_lines))
	print(f"\n... [{len(preview_lines)} lines shown. Total file length: {len(full_file_str.splitlines())} lines] ...\n")

	# Final Output File generation and running engine step
	execute_run = input("Write template to storage and launch TOPAS execution? (y/n): ").strip().lower()
	if execute_run == 'y':
		inp_file_path = f"{out_name}.inp"
		with open(inp_file_path, 'w', encoding='utf-8') as out_file:
			out_file.write(full_file_str)
		print(f"[+] File written successfully to: '{inp_file_path}'")

		# Same launch path as `rp <file>.inp`, so engine location, error reporting
		# and working directory behave identically however the run was started.
		engine_executable = config.get('topas_exe', cli_value=args.topas_exe, user=user)
		print()
		run_topas(inp_file_path, engine_executable)
	else:
		print("\n[-] Operation cancelled. No files were saved.")

if __name__ == '__main__':
	main()
