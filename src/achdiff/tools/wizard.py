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

from .. import config, identity
from ..progname import prog_name

# Clear the screen helper to keep the interactive wizard clean
def clear_terminal():
	os.system('cls' if os.name == 'nt' else 'clear')

# Suppress noisy external library warnings (e.g., from pymatgen)
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
	# Trusted starting cell parameters from previous well-converged fits.
	# These override CIF values when use_trusted_params is True (the default).
	# Only supply the parameters relevant to the crystal system; all others
	# remain as read from the CIF. Values may include TOPAS backtick-sigma
	# notation (e.g. 23.45`_0.003) to seed the refinement uncertainty estimate.
	'use_trusted_params': True,
	'trusted_params': {
		'ZIF-zni': {
			'a': '23.450081`_0.003374',
			'c': '12.457945`_0.004831',
		},
		'ZIF-4': {
			'a': '15.484356`_0.000738',
			'b': '15.511304`_0.000704',
			'c': '18.103277`_0.000892',
		},
		'ZIF-62': {
			'a': '15.495146`_0.002522',
			'b': '15.547521`_0.002173',
			'c': '17.927694`_0.002978',
		},
		'H2adp': {
			'a': '7.386179`_0.002941',
			'b': '5.236263`_0.002965',
			'c': '9.944893`_0.004057',
			'be': '110.52250`_0.00791' 
		},
		'H2pPDA': {
			'a': '10.360238`_0.002127',
			'b': '4.807089`_0.000728',
			'c': '10.353990`_0.002195',
			'be': '116.93473`_0.01202' 
		},
		'HpPyBz': {
			'a': '10.838163`_0.010591',
			'b': '11.790409`_0.009458',
			'c': '14.843892`_0.012730'
		},
	}
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

CRYSTAL_MACROS = {
	'triclinic': 'Triclinic(@ $a, @ $b, @ $c, @ $al, @ $be, @ $ga)',
	'monoclinic': 'Monoclinic(@ $a, @ $b, @ $c, @ $be)',
	'rhombohedral': 'Rhombohedral(@ $a, @ $al)',
	'orthorhombic': 'Orthorhombic(@ $a, @ $b, @ $c)',
	'tetragonal': 'Tetragonal(@ $a, @ $c)',
	'trigonal': 'Trigonal(@ $a, @ $c)',
	'hexagonal': 'Hexagonal(@ $a, @ $c)',
	'cubic': 'Cubic(@ $a)'
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


def get_parms_pymatgen(file_path: str) -> dict:
	"""Extracts required lattice parameters and symmetry systems using pymatgen."""
	from pymatgen.io.cif import CifParser
	from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

	parser = CifParser(file_path)
	struct = parser.parse_structures()[0]
	sga = SpacegroupAnalyzer(struct, symprec=0.01, angle_tolerance=5)
	lattice = struct.lattice

	return {
		'a': f'{lattice.a:g}', 'b': f'{lattice.b:g}', 'c': f'{lattice.c:g}',
		'al': f'{lattice.alpha:g}', 'be': f'{lattice.beta:g}', 'ga': f'{lattice.gamma:g}',
		'V': f'{lattice.volume:g}',
		'sg_num': str(sga.get_space_group_number()),
		'sg_HM': str(sga.get_space_group_symbol()),
		'cryst_sys': str(sga.get_crystal_system()).lower()
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

def _build_parser():
	parser = argparse.ArgumentParser(
		prog=prog_name('rp'),
		description='Interactive wizard generating TOPAS Pawley .inp files.')
	parser.add_argument('--cif-loc', dest='cif_loc', default=None,
	                    help='CIF library directory. Overrides the CIF_LOC env var '
	                         'and any saved profile.')
	identity.add_user_argument(parser)
	return parser


def main():
	args = _build_parser().parse_known_args()[0]

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
			available_phases[name] = get_parms_pymatgen(path)
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
	trusted_phases_applied = []
	if SETTINGS.get('use_trusted_params'):
		for i, name in enumerate(user_input_phases):
			if name in SETTINGS['trusted_params']:
				selected_phase_data[i] = {**selected_phase_data[i], **SETTINGS['trusted_params'][name]}
				trusted_phases_applied.append(name)
		if trusted_phases_applied:
			print(f"  [*] Trusted starting parameters applied for: {', '.join(trusted_phases_applied)}")

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

		# Launch engine cleanly using subprocess
		engine_executable = r"C:\TOPAS7\tc.exe"
		if os.path.exists(engine_executable):
			print('\nLaunching calculation engine subprocess...')
			subprocess.run([engine_executable, inp_file_path], check=True)
			print("[+] TOPAS optimization run complete.")
		else:
			print(f"[-] Warning: The file was saved, but 'tc.exe' was not found at {engine_executable}")
	else:
		print("\n[-] Operation cancelled. No files were saved.")

if __name__ == '__main__':
	main()
