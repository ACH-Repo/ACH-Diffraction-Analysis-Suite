import os
import re
from glob import glob
from pathlib import Path
import argparse
from decimal import Decimal, getcontext, InvalidOperation, ROUND_HALF_UP
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.lines import Line2D
from matplotlib.ticker import AutoMinorLocator, MultipleLocator

from .. import cmdline, config, identity, styles
from ..core import animate, overlays
from ..progname import prog_name
from ..core.rounding import cryst_round, split_value_bracket
from ..core import cif as cifcore

# ==========================================
# CONFIGURATION & SETTINGS (Static parameters)
# ==========================================

settings = {
	'start_dir': '.', 
	'pawley_ident': '_pawley_01_', 
	'pawley_ext': ('.txt', '.xy'),  # data file extensions to scan (any iterable of suffixes)
	'2Th_Ip_ident': '2Th_Ip', 
	'X_Yobs_ident': 'X_Yobs', 
	'Out_X_Ycalc_ident': 'Out_X_Ycalc', 
	'X_Difference_ident': 'X_Difference', 
	'figsize': (6, 4), 
	'X_Yobs_color': 'k', 
	'Out_X_Ycalc_color': 'r', 
	'2Th_Ip_colors': ['b', 'orange', 'pink', 'gold', 'red'], 
	'X_Difference_color': 'g', 
	'X_Yobs_label': 'Observed', 
	'Out_X_Ycalc_label': 'Calculated', 
	'2Th_Ip_label': 'Reflections', 
	'X_Difference_label': 'Difference', 
	'X_Yobs_markersize': 5, 
	'Out_X_Ycalc_markersize': 0, 
	'2Th_Ip_markersize': 10, 
	'X_Difference_markersize': 0, 
	'y_off_dashes': 1.5, 
	'x_lims': 'auto', 
	'legend_fontsize': 8, 
	'dpi': 300, 
	'transparent': True, 
	'extension': 'svg', 
	'title': None, 
	'title_font_weight': 'bold', 
	'title_font_size': 12, 
	'show_info': True,
	'use_sg_from_outfile': True,
	'use_sg_format': 'HERMANN-MAUGUIN+SUBSTANCE',

	# PRESENTATION (everything a style sheet is allowed to reach -- see styles.py).
	# These used to be literals inside style(), add_legend() and the plot calls in
	# main(), which is why a per-person look was impossible without editing the
	# package. The values below reproduce that original look exactly.
	'X_Yobs_markeredgewidth': .6,    # stroke weight of the 'x' symbols
	'Out_X_Ycalc_linewidth': 1,
	'X_Difference_linewidth': .3,
	'2Th_Ip_markeredgewidth': .6,
	'x_label_text': r'$2\theta \quad / \quad \mathrm{^\circ}$',
	'y_label_text': r'$\mathrm{Intensity} \quad / \quad \mathrm{a.u.}$',
	'size_axis_labels': 11,
	'size_tick_labels': 10,
	'x_tick_step': 0,               # degrees between numbered x ticks; 0 = matplotlib's choice
	'ticks_top': False,             # mirror the x ticks onto the top edge
	'tick_direction': 'in',
	# Taken from the live rcParams rather than hardcoded, so that leaving these
	# alone means "whatever matplotlib would have done", exactly as before.
	'tick_length_major': plt.rcParams['xtick.major.size'],
	'tick_length_minor': plt.rcParams['xtick.minor.size'],
	'show_legend': True,
	'legend_loc': 'upper right',
	'legend_frame': True,
	'legend_columns': 1,
	'legend_dedupe': True,          # collapse entries identical in wording AND appearance
	# One fixed name for every Bragg row. Empty means each row names itself from
	# its own space group and substance, which is the historic behaviour.
	'bragg_label': '',
	'quality_fontsize': 12,
	# Frame resolution for --gif. Separate from `dpi`, which is print
	# resolution: a 6-inch figure at 300 dpi is 1800 px per frame, and fifty
	# of those make a GIF nobody can email.
	'gif_dpi': 150,

	# VERTICAL LAYOUT CONTROLS (all values are axes-coordinate fractions, 0–1)
	'bragg_spacing': 0.01,          # Gap between multiple Bragg tick rows
	'tick_top_clearance': 0.02,     # Gap between data floor and the topmost Bragg tick row
	'tick_bottom_clearance': 0.02,  # Gap between the bottommost Bragg tick row and the top edge of the difference band
	'difference_band_height': 0.12, # Height of the band reserved for the difference curve (not the gap above it)
	'y_tol_top': 0.05,              # Headroom above the data ceiling (must be ≥ 0)
	'y_tol_bottom': 0.03,           # Headroom below the difference band (must be ≥ 0;
	                                # negative values push the band off the axes)
	'min_data_fraction': 0.25,      # Minimum axes fraction guaranteed to the data region
	'diff_shift_factor': 0.8,       # Max fraction of the difference band the curve may occupy.
	                                # If the natural amplitude would exceed this, the band auto-expands
	                                # so the curve fits with (1 - diff_shift_factor) of visual padding.
	'box_y_top': 0.67,              # Fallback ceiling for the first box when no legend is present
	'box_x': 0.98,                  # Fallback right-edge x-position (axes coords) when no legend
	'box_fontsize': 7,              # Default / largest font size (pt) for unit-cell info box text
	'box_fontsize_min': 5,          # Smallest font (pt) the layout will shrink to before accepting overlap
	'box_pad': 0.3,                 # Padding (in fontsize units) inside the rounded info box
	'box_gap': 0.01,                # Vertical gap (axes coords) between vertically stacked boxes
	'box_col_gap': 0.012,           # Horizontal gap (axes coords) between side-by-side boxes
	'box_legend_gap': 0.015,        # Whitespace tolerance between the legend's bottom and the first box
	'box_data_clearance': 0.02,     # Minimum clearance (axes coords) to keep above the data envelope
	'pastel_weight': 0.78,          # Blend factor toward white for info-box background tinting
	'multiply_label_y': 0.98,       # Axes-coord y for the 'x N' annotation from -m
	'multiply_label_size': 10,      # Point size of that annotation
	'band_color': 'gainsboro',      # -b strip colour when the strip names none
	'band_width': 1.0,              # -b strip width when the strip names none, % of the x range

	# REFLECTION OVERLAY (-r): CIF-simulated markers for phases outside the fit
	'cif_dir_path': r'D:\Workfolder\<you>\CIF_LOC',  # bare -r names resolve against this
	'cif_wavelength': 1.54060,      # Cu Kalpha1, used to simulate the CIF pattern
	'reflection_n_top': 10,         # Default count of strongest reflections per set
	# Hues deliberately disjoint from every trace colour above — X_Yobs 'k',
	# Out_X_Ycalc 'r', 2Th_Ip blue/orange/pink/gold/red, X_Difference 'g' — so an
	# overlay never reads as fit output. This intentionally differs from the palette
	# in quickplot, whose 'black' and 'goldenrod' would collide here.
	'reflection_color_cycle': ['magenta', 'teal', 'darkviolet', 'saddlebrown', 'olive'],
	'reflection_linestyle': ':',
	'reflection_linewidth': 0.7,
	'reflection_alpha': 0.75,
}

# Argument-parser defaults only. This table used to carry a second, parallel copy
# of the presentation values -- colours, label text, font sizes -- that nothing
# ever read: style() and main() used their own literals, so editing
# `defaults['y_label_text']` changed nothing and only misled whoever tried. The
# presentation keys now live in `settings` above, where they are read, and this
# is reduced to the two values argparse genuinely needs.
defaults = {
	'input': 'AUTOBATCH',
	'silent': False,
}

def _build_parser():
	parser = argparse.ArgumentParser(
		prog=prog_name('pp'),
		description='Plots the result of a TOPAS Pawley fit using output files.')
	parser.add_argument('-i', '--input', type=str, nargs='+', default=defaults['input'])
	parser.add_argument('-s', '--silent', action='store_true', default=defaults['silent'],
	                    help='Save each plot without opening a window.')
	parser.add_argument('-v', '--verbose', action='store_true',
	                    help='Print extra info while running.')
	parser.add_argument('-c', '--cell_info', action='store_true', help='Include unit cell parameter boxes on the plot.')
	overlays.add_arguments(parser)
	parser.add_argument('-t', '--title', nargs='?', const=True, default=None,
	                    help='Title every plot with this text, or pass -t alone to use '
	                         'each fit\'s name.')
	parser.add_argument('--size', nargs=2, type=float, default=None, metavar=('W', 'H'),
	                    help='Figure size in inches, over the style sheet\'s figsize.')
	parser.add_argument('--dpi', type=int, default=None,
	                    help='Resolution of raster output, over the style sheet\'s dpi.')
	# Default None rather than settings['extension']: argparse captures its default
	# at parser-build time, so a concrete one here would be indistinguishable from
	# a flag the user typed and would silently outrank a style sheet's `extension`.
	parser.add_argument('-x', '--extension', type=str, default=None,
	                    help='Output image format used with -s, e.g. svg, png, pdf '
	                         '(default: %s).' % settings['extension'])
	parser.add_argument('--qall', action='store_true',
	                    help='Show all three fit-quality factors (R_wp, R_exp, chi) instead of R_wp alone.')
	parser.add_argument('-r', '--reflections', default=None, type=str,
	                    help='Overlay reflection markers from CIFs as fine vertical dotted '
	                         'lines. Format: "(name,N,color),(name,N,color),...". '
	                         'N (count of strongest reflections) defaults to %d; color '
	                         'defaults to a hue not used by the fit traces. Bare CIF names '
	                         'resolve against cif_dir_path. Useful for checking an impurity '
	                         'phase that is not part of the fit.'
	                         % settings['reflection_n_top'])
	parser.add_argument('--cif-loc', dest='cif_loc', default=None,
	                    help='CIF library directory for -r. Overrides the CIF_LOC env '
	                         'var and any saved profile.')
	parser.add_argument('--gif', action='store_true',
	                    help='Animate every fit in this directory, in order, as one '
	                         'GIF -- plus a second GIF of the cell parameters as bars '
	                         'that change with it. For sequential refinements: a '
	                         'variable-temperature or time-resolved run is only worth '
	                         'anything next to itself. Implies -s.')
	parser.add_argument('--gif-delay', type=int, default=animate.DEFAULT_DELAY_MS,
	                    metavar='MS',
	                    help='Milliseconds each frame is held (default: %(default)s).')
	parser.add_argument('--gif-absolute', action='store_true',
	                    help='Draw the cell bars as the parameters themselves rather '
	                         'than as their change since the first fit. Reads more '
	                         'naturally, but hides the motion: a and c can sit 3 A '
	                         'apart while each moves 0.05 A, and an axis wide enough '
	                         'for both is far too coarse to show either one move.')
	parser.add_argument('--gif-name', default=None, metavar='NAME',
	                    help='Stem for the GIF filenames. Defaults to the name of the '
	                         'directory being animated.')
	parser.add_argument('--gif-format', default='gif', metavar='FMT',
	                    help='Animation format: gif, svg, or gif,svg for both '
	                         '(default: %(default)s). An animated SVG stays sharp at '
	                         'any size and plays in a browser, but PowerPoint shows '
	                         'SVG as a still image -- use gif for slides.')
	parser.add_argument('--gif-rolling', type=int, default=animate.DEFAULT_ROLLING, metavar='N',
	                    help='Window of the rolling mean drawn over the step chart, in '
	                         'steps (default: %(default)s; 0 turns it off). Only drawn once '
	                         'a full window exists within one leg of the run, and never '
	                         'across a turning point. Meaningful for evenly spaced steps: '
	                         'with uneven ones, each bar also carries its step size.')
	parser.add_argument('--x-values', default=None, metavar='SPEC',
	                    help='The x value of each fit for the trend plot, in the '
	                         'order the fits are drawn: a list "0,0.5,1,2", a range '
	                         '"0:10:2" (stop included), or both "0,0.5,1:5:1". '
	                         'Without it the x axis is the fit number, which assumes '
	                         'evenly spaced steps -- with uneven ones the curve can '
	                         'even bend the wrong way. Not checked for sense, only '
	                         'that there is one value per fit.')
	parser.add_argument('--x-label', default=None, metavar='TEXT',
	                    help='Axis label for --x-values or --x-map, e.g. "p / GPa".')
	parser.add_argument('--x-map', default=None, metavar='FILE',
	                    help='A text file giving the run order and x value of each fit, '
	                         'one "fit-name  x" per line. The file is the timeline: fits '
	                         'play in the order listed, only listed fits play, and the '
	                         'same x may repeat -- which is what a run that goes up and '
	                         'comes back down to test reversibility needs, and what '
	                         '--sort-key and --x-values cannot express. Replaces both.')
	parser.add_argument('--x-map-template', default=None, metavar='FILE',
	                    help='Write a starting --x-map file listing every fit, in the '
	                         'current order, and exit. With --sort-key, x values are '
	                         'pre-filled from the number it captures; edit the order '
	                         'and values, then pass the file back with --x-map.')
	parser.add_argument('--sort-key', default=None, metavar='REGEX',
	                    help='Order the fits by what this regular expression captures '
	                         'from each fit name, compared as numbers where they are '
	                         'numbers: "_([0-9.]+)GPa" sorts by pressure. Fits it does '
	                         'not match are kept, reported, and put last. The order is '
	                         'taken as given, not checked.')
	parser.add_argument('--style', default=None, metavar='FILE',
	                    help='Style sheet to layer on top of the one -u already '
	                         'selects. Use it for a one-off look -- a journal\'s '
	                         'column width, say -- without editing your own. See '
	                         '`achdiff style --help`.')
	identity.add_user_argument(parser)
	cmdline.add_arguments(parser)
	return parser


# Populated by main(). Module-level so the helpers above can read it, which is
# how this script has always worked -- keeping that contract avoids threading
# `args` through a dozen call sites for no behavioural gain.
args = None

# Short Hermann-Mauguin symbols for all 230 space groups, as LaTeX math strings.
# Inversion axes use \overline{N} (renders a clean full-width bar over the digit);
# screw axes use single-digit subscripts (e.g. 2_1, 6_3); glide/mirror planes use '/'.
sgs_HM = {
	# Triclinic
	'1':   r'$P1$',
	'2':   r'$P\overline{1}$',
	# Monoclinic
	'3':   r'$P2$',
	'4':   r'$P2_1$',
	'5':   r'$C2$',
	'6':   r'$Pm$',
	'7':   r'$Pc$',
	'8':   r'$Cm$',
	'9':   r'$Cc$',
	'10':  r'$P2/m$',
	'11':  r'$P2_1/m$',
	'12':  r'$C2/m$',
	'13':  r'$P2/c$',
	'14':  r'$P2_1/c$',
	'15':  r'$C2/c$',
	# Orthorhombic
	'16':  r'$P222$',
	'17':  r'$P222_1$',
	'18':  r'$P2_12_12$',
	'19':  r'$P2_12_12_1$',
	'20':  r'$C222_1$',
	'21':  r'$C222$',
	'22':  r'$F222$',
	'23':  r'$I222$',
	'24':  r'$I2_12_12_1$',
	'25':  r'$Pmm2$',
	'26':  r'$Pmc2_1$',
	'27':  r'$Pcc2$',
	'28':  r'$Pma2$',
	'29':  r'$Pca2_1$',
	'30':  r'$Pnc2$',
	'31':  r'$Pmn2_1$',
	'32':  r'$Pba2$',
	'33':  r'$Pna2_1$',
	'34':  r'$Pnn2$',
	'35':  r'$Cmm2$',
	'36':  r'$Cmc2_1$',
	'37':  r'$Ccc2$',
	'38':  r'$Amm2$',
	'39':  r'$Aem2$',
	'40':  r'$Ama2$',
	'41':  r'$Aea2$',
	'42':  r'$Fmm2$',
	'43':  r'$Fdd2$',
	'44':  r'$Imm2$',
	'45':  r'$Iba2$',
	'46':  r'$Ima2$',
	'47':  r'$Pmmm$',
	'48':  r'$Pnnn$',
	'49':  r'$Pccm$',
	'50':  r'$Pban$',
	'51':  r'$Pmma$',
	'52':  r'$Pnna$',
	'53':  r'$Pmna$',
	'54':  r'$Pcca$',
	'55':  r'$Pbam$',
	'56':  r'$Pccn$',
	'57':  r'$Pbcm$',
	'58':  r'$Pnnm$',
	'59':  r'$Pmmn$',
	'60':  r'$Pbcn$',
	'61':  r'$Pbca$',
	'62':  r'$Pnma$',
	'63':  r'$Cmcm$',
	'64':  r'$Cmce$',
	'65':  r'$Cmmm$',
	'66':  r'$Cccm$',
	'67':  r'$Cmme$',
	'68':  r'$Ccce$',
	'69':  r'$Fmmm$',
	'70':  r'$Fddd$',
	'71':  r'$Immm$',
	'72':  r'$Ibam$',
	'73':  r'$Ibca$',
	'74':  r'$Imma$',
	# Tetragonal
	'75':  r'$P4$',
	'76':  r'$P4_1$',
	'77':  r'$P4_2$',
	'78':  r'$P4_3$',
	'79':  r'$I4$',
	'80':  r'$I4_1$',
	'81':  r'$P\overline{4}$',
	'82':  r'$I\overline{4}$',
	'83':  r'$P4/m$',
	'84':  r'$P4_2/m$',
	'85':  r'$P4/n$',
	'86':  r'$P4_2/n$',
	'87':  r'$I4/m$',
	'88':  r'$I4_1/a$',
	'89':  r'$P422$',
	'90':  r'$P42_12$',
	'91':  r'$P4_122$',
	'92':  r'$P4_12_12$',
	'93':  r'$P4_222$',
	'94':  r'$P4_22_12$',
	'95':  r'$P4_322$',
	'96':  r'$P4_32_12$',
	'97':  r'$I422$',
	'98':  r'$I4_122$',
	'99':  r'$P4mm$',
	'100': r'$P4bm$',
	'101': r'$P4_2cm$',
	'102': r'$P4_2nm$',
	'103': r'$P4cc$',
	'104': r'$P4nc$',
	'105': r'$P4_2mc$',
	'106': r'$P4_2bc$',
	'107': r'$I4mm$',
	'108': r'$I4cm$',
	'109': r'$I4_1md$',
	'110': r'$I4_1cd$',
	'111': r'$P\overline{4}2m$',
	'112': r'$P\overline{4}2c$',
	'113': r'$P\overline{4}2_1m$',
	'114': r'$P\overline{4}2_1c$',
	'115': r'$P\overline{4}m2$',
	'116': r'$P\overline{4}c2$',
	'117': r'$P\overline{4}b2$',
	'118': r'$P\overline{4}n2$',
	'119': r'$I\overline{4}m2$',
	'120': r'$I\overline{4}c2$',
	'121': r'$I\overline{4}2m$',
	'122': r'$I\overline{4}2d$',
	'123': r'$P4/mmm$',
	'124': r'$P4/mcc$',
	'125': r'$P4/nbm$',
	'126': r'$P4/nnc$',
	'127': r'$P4/mbm$',
	'128': r'$P4/mnc$',
	'129': r'$P4/nmm$',
	'130': r'$P4/ncc$',
	'131': r'$P4_2/mmc$',
	'132': r'$P4_2/mcm$',
	'133': r'$P4_2/nbc$',
	'134': r'$P4_2/nnm$',
	'135': r'$P4_2/mbc$',
	'136': r'$P4_2/mnm$',
	'137': r'$P4_2/nmc$',
	'138': r'$P4_2/ncm$',
	'139': r'$I4/mmm$',
	'140': r'$I4/mcm$',
	'141': r'$I4_1/amd$',
	'142': r'$I4_1/acd$',
	# Trigonal
	'143': r'$P3$',
	'144': r'$P3_1$',
	'145': r'$P3_2$',
	'146': r'$R3$',
	'147': r'$P\overline{3}$',
	'148': r'$R\overline{3}$',
	'149': r'$P312$',
	'150': r'$P321$',
	'151': r'$P3_112$',
	'152': r'$P3_121$',
	'153': r'$P3_212$',
	'154': r'$P3_221$',
	'155': r'$R32$',
	'156': r'$P3m1$',
	'157': r'$P31m$',
	'158': r'$P3c1$',
	'159': r'$P31c$',
	'160': r'$R3m$',
	'161': r'$R3c$',
	'162': r'$P\overline{3}1m$',
	'163': r'$P\overline{3}1c$',
	'164': r'$P\overline{3}m1$',
	'165': r'$P\overline{3}c1$',
	'166': r'$R\overline{3}m$',
	'167': r'$R\overline{3}c$',
	# Hexagonal
	'168': r'$P6$',
	'169': r'$P6_1$',
	'170': r'$P6_5$',
	'171': r'$P6_2$',
	'172': r'$P6_4$',
	'173': r'$P6_3$',
	'174': r'$P\overline{6}$',
	'175': r'$P6/m$',
	'176': r'$P6_3/m$',
	'177': r'$P622$',
	'178': r'$P6_122$',
	'179': r'$P6_522$',
	'180': r'$P6_222$',
	'181': r'$P6_422$',
	'182': r'$P6_322$',
	'183': r'$P6mm$',
	'184': r'$P6cc$',
	'185': r'$P6_3cm$',
	'186': r'$P6_3mc$',
	'187': r'$P\overline{6}m2$',
	'188': r'$P\overline{6}c2$',
	'189': r'$P\overline{6}2m$',
	'190': r'$P\overline{6}2c$',
	'191': r'$P6/mmm$',
	'192': r'$P6/mcc$',
	'193': r'$P6_3/mcm$',
	'194': r'$P6_3/mmc$',
	# Cubic
	'195': r'$P23$',
	'196': r'$F23$',
	'197': r'$I23$',
	'198': r'$P2_13$',
	'199': r'$I2_13$',
	'200': r'$Pm\overline{3}$',
	'201': r'$Pn\overline{3}$',
	'202': r'$Fm\overline{3}$',
	'203': r'$Fd\overline{3}$',
	'204': r'$Im\overline{3}$',
	'205': r'$Pa\overline{3}$',
	'206': r'$Ia\overline{3}$',
	'207': r'$P432$',
	'208': r'$P4_232$',
	'209': r'$F432$',
	'210': r'$F4_132$',
	'211': r'$I432$',
	'212': r'$P4_332$',
	'213': r'$P4_132$',
	'214': r'$I4_132$',
	'215': r'$P\overline{4}3m$',
	'216': r'$F\overline{4}3m$',
	'217': r'$I\overline{4}3m$',
	'218': r'$P\overline{4}3n$',
	'219': r'$F\overline{4}3c$',
	'220': r'$I\overline{4}3d$',
	'221': r'$Pm\overline{3}m$',
	'222': r'$Pn\overline{3}n$',
	'223': r'$Pm\overline{3}n$',
	'224': r'$Pn\overline{3}m$',
	'225': r'$Fm\overline{3}m$',
	'226': r'$Fm\overline{3}c$',
	'227': r'$Fd\overline{3}m$',
	'228': r'$Fd\overline{3}c$',
	'229': r'$Im\overline{3}m$',
	'230': r'$Ia\overline{3}d$',
}

# Aliases mapping raw HM strings (as they may appear in .out / .inp files,
# in any case and with/without underscore subscripts) to canonical sg-number keys.
# Lookup is done case-insensitively on a normalised form.
_hm_aliases = {
	'p1':         '1',
	'p-1':        '2',  'pbar1': '2',
	'p2/m':       '10',
	'p2_1/m':     '11', 'p21/m': '11',
	'p2_1/c':     '14', 'p21/c': '14',
	'p2_12_12_1': '19', 'p212121': '19',
	'pbca':       '61',
	'i4_1cd':     '110', 'i41cd': '110',
	'r-3':        '148', 'rbar3': '148', 'r3bar': '148',
	'p6_122':     '178', 'p6122': '178',
	'p6_3/mmc':   '194', 'p63/mmc': '194',
	'i-43m':      '217', 'ibar43m': '217', 'i4bar3m': '217',
	'i-43d':      '220', 'ibar43d': '220', 'i4bar3d': '220',
}

def _norm_hm(s):
	"""Normalise an HM string for alias lookup: lowercase, strip whitespace."""
	return str(s).strip().lower() if s is not None else ''

def resolve_sg(raw):
	"""Given a raw space-group token (number string or HM symbol, with or without quotes),
	return (canonical_sg_number, latex_label).
	Either may be None / a best-effort fallback if the token isn't recognised."""
	if raw is None:
		return None, None
	s = str(raw).strip().strip('"').strip()
	if not s:
		return None, None
	if s.isdigit():
		return s, sgs_HM.get(s)
	key = _hm_aliases.get(_norm_hm(s))
	if key:
		return key, sgs_HM.get(key)
	# Unknown HM string — keep the raw token wrapped in LaTeX math mode as a fallback label.
	return None, f'${s}$'

# ==========================================
# COLOR TRANSFORM ENGINE
# ==========================================

def to_pastel(color, weight=settings['pastel_weight']):
	"""Blends an input color map key safely with pure white to generate a pastel background."""
	rgb = mcolors.to_rgb(color)
	return [(1.0 - weight) * c + weight for c in rgb]

# ==========================================
# CRYSTALLOGRAPHIC ROUNDING FUNCTION
# ==========================================


# ==========================================
# FILE WRANGLING FUNCTIONS
# ==========================================

def get_file_dicts():
	"""Discover TOPAS data file groups by recognising the data-type suffix at the end
	of each filename. Works regardless of whether the group uses `_pawley_NN_`,
	`_fit_NN_`, or no ident at all — the prefix up to the data-type marker becomes
	the group key."""
	all_group_dicts = {}
	# Recognised data-type suffixes. 2Th_Ip may optionally have an `_<sg>` suffix.
	data_idents = [
		settings['X_Yobs_ident'],
		settings['Out_X_Ycalc_ident'],
		settings['X_Difference_ident'],
		settings['2Th_Ip_ident'],
	]

	# Accept either a single extension string or any iterable of them
	exts = settings['pawley_ext']
	if isinstance(exts, str):
		exts = (exts,)
	all_data_files = [p for ext in exts for p in glob('*' + ext)]

	for f in all_data_files:
		base = os.path.splitext(os.path.basename(f))[0]
		for ident in data_idents:
			# Match: <prefix>_<ident>[_<extra>]   where <extra> is digits or HM-ish chars
			pat = rf'^(.*?)_({re.escape(ident)})(_[\w/+\-]+)?$'
			m = re.match(pat, base)
			if not m:
				continue
			prefix = m.group(1)
			ident_part = m.group(2) + (m.group(3) or '')
			all_group_dicts.setdefault(prefix, {})[ident_part] = f
			break
	return all_group_dicts


def sort_filegroup(group_dict):
	prios = {
		settings['X_Yobs_ident']: 0,
		settings['Out_X_Ycalc_ident']: 1,
		settings['2Th_Ip_ident']: 2,
		settings['X_Difference_ident']: 3,
	}
	
	def get_prio(tup):
		ident = tup[0]
		matched_keys = [key for key in prios if key in ident]
		return prios[matched_keys[0]] if matched_keys else 99

	return sorted(group_dict.items(), key=get_prio)


def get_x_y(path):
	filestring = Path(path).read_text()
	lines = [line.strip().split() for line in filestring.strip().split('\n') if line.strip()]
	x, y = np.array(lines, dtype=float).transpose()
	return x, y


def find_outfile_for_group(group_key, all_out_files=None):
	"""Locate the .out (TOPAS log) file that belongs to a data group.

	The .out filename is not always `{group_key}.out` — common variants:
	  - `{group_key}.out`                      (same ident as data files)
	  - `{base}.out`                            (no ident on .out)
	  - `{base}_pawley_NN.out` / `{base}_fit_NN.out`  (different ident than data)
	where `{base}` is `{group_key}` with any trailing `_pawley_NN` / `_fit_NN` stripped.

	Returns the matching filename or None if nothing is found.
	"""
	if all_out_files is None:
		all_out_files = glob('*.out')
	all_out_files = set(all_out_files)

	# 1. Exact ident match
	direct = f'{group_key}.out'
	if direct in all_out_files:
		return direct

	# 2. Strip trailing _pawley_NN / _fit_NN to get the bare "base" name
	base = re.sub(r'_(?:pawley|fit)_\d+$', '', group_key)
	if base != group_key and f'{base}.out' in all_out_files:
		return f'{base}.out'

	# 3. Any .out whose basename starts with base_<known-ident>
	for suffix in ('_pawley_01.out', '_pawley_02.out', '_fit_01.out', '_fit_02.out'):
		cand = f'{base}{suffix}'
		if cand in all_out_files:
			return cand

	# 4. Final fallback: any .out starting with `{base}_` (deterministic ordering)
	prefix_matches = sorted(f for f in all_out_files if f.startswith(f'{base}_'))
	if prefix_matches:
		return prefix_matches[0]

	return None

# ==========================================
# PARSING & DATA EXTRACTION
# ==========================================

def get_substances_from_outfile(path):
	"""Parse the wizard's `Selected phases:` audit line into an ORDERED list of
	(substance_name, sg_token) tuples, one per phase, in declaration order.

	Order and duplicates are preserved on purpose: two phases that share a space
	group are two distinct entries here. (The previous sg-keyed dict silently
	collapsed them, which is why same-SG fits lost a substance.) Phases are matched
	to ticks by their ordinal position downstream, not by space group. Returns []
	when the line is absent (e.g. a hand-written .out)."""
	if not os.path.exists(path):
		return []

	phases = []
	try:
		with open(path, 'r', encoding='utf-8') as inf:
			for line in inf:
				if 'Selected phases:' in line:
					phases = re.findall(r'"([^"]+)"\s*\((\d+)\)', line)
					break  # only the first audit line is authoritative
	except Exception as e:
		print(f"Warning: Error encountered reading metadata from {path}: {e}")
	return phases


def get_outfile_info(path):
	"""Parse the fit-quality factors TOPAS writes on one line of the .out:
	`r_wp <v> r_exp <v> r_p <v> ... gof <v>`. Returns whichever of r_wp / r_exp /
	gof were found (keys are simply absent when the .out is missing or a factor
	can't be located), so the caller can skip annotations rather than invent a
	placeholder value. The `\\s+` after each key keeps the `_dash` variants
	(`r_wp_dash`, `r_exp_dash`) on the same line from being mistaken for the
	plain factors."""
	info = {}
	if not os.path.exists(path):
		return info

	try:
		filestring = Path(path).read_text()
		_float = r'([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)'
		for key in ('r_wp', 'r_exp', 'gof'):
			m = re.search(r'\b' + key + r'\s+' + _float, filestring)
			if m:
				info[key] = float(m.group(1))
	except Exception:
		pass
	return info


def _strip_topas_comments(text):
	"""Blank out TOPAS comment lines (lines whose first non-whitespace char is `'`).
	Returns the cleaned text with the same line count, so per-line regex matches
	preserve their semantic locations."""
	return '\n'.join(
		'' if re.match(r"\s*'", line) else line
		for line in text.split('\n')
	)


def _extract_cell_parts(label, raw_string):
	"""Round a raw `value` or `value`_uncertainty` token to crystallographic form and
	split into (label, main, bracket). Returns None if the token can't be parsed."""
	rounded = cryst_round(raw_string)
	if rounded is None:
		return None
	m = re.match(r"^([^(]+)(\(.*\))$", rounded)
	if m:
		return label, m.group(1), m.group(2)
	return label, rounded, ""


def get_unit_cell_info(path):
	"""Cell parameters rounded for display: [(sg_raw, [(label, main, bracket)]), ...].

	The rounding half of `get_unit_cell_raw`, which does the parsing. Split
	because the two callers want different things from the same text: an info box
	wants `15.484(2)` to print, while an error bar wants 15.484 and 0.002 back as
	numbers, and rounding to a string throws exactly that away.
	"""
	out = []
	for sg_raw, cell_raw in get_unit_cell_raw(path):
		cell_data = []
		for label, token in cell_raw:
			try:
				parts = _extract_cell_parts(label, token)
			except Exception as e:
				print(f"Warning: skipping cell param '{label}' (couldn't parse '{token}'): {e}")
				parts = None
			if parts:
				cell_data.append(parts)
		out.append((sg_raw, cell_data))
	return out


def get_unit_cell_raw(path):
	"""Parse cell parameters, volume, and space group from a TOPAS .out file.

	Returns [(raw_sg_token, [(label, raw_token), ...]), ...], one entry per phase
	in the order the file declares them, with the TOPAS tokens untouched --
	``15.484`_0.002`` -- so a caller can round them or read the uncertainty out
	of them as it needs.

	Handles:
	  - Commented-out template lines (leading `'`) — ignored
	  - Single-line crystal-system macros: `Cubic(a)`, `Tetragonal(a, c)`,
	    `Orthorhombic(a, b, c)`, `Monoclinic(a, b, c, beta)`, `Triclinic(a, b, c, al, be, ga)`,
	    plus Hexagonal / Trigonal (same shape as Tetragonal)
	  - Loose per-line declarations: `a @ ...`, `b lpa ...`, `c @ ...`,
	    `al @ ...`, `be @ ...`, `ga @ ...` (also without the @)
	  - Volume keyword variants: `cell_volume` and `volume`
	  - Space-group syntaxes: quoted numeric `"61"`, quoted HM `"P63/mmc"`,
	    quoted lowercase `"p1"`, unquoted `Pbca`, hyphenated `R-3`

	raw_sg_token may be either a number string or an HM symbol; downstream callers
	should pass it through `resolve_sg`.
	"""
	if not os.path.exists(path):
		return []

	try:
		raw = Path(path).read_text(encoding='utf-8', errors='replace')
	except Exception as e:
		print(f"Warning: cannot read {path}: {e}")
		return []

	content = _strip_topas_comments(raw)

	# Each phase begins at `hkl_Is`. The preamble before the first marker is dropped.
	blocks = re.split(r'\bhkl_Is\b', content)
	phase_blocks = blocks[1:] if len(blocks) > 1 else [content]

	# Volumes (cell_volume or volume) collected in document order, assigned to phases
	# by index. They can appear inside or outside the hkl_Is block.
	all_vols = re.findall(r'\b(?:cell_volume|volume)\s+(\S+)', content)

	# Crystal-system macros recognised on a single line, e.g.  Cubic(@ 17.09...)
	macro_pat = re.compile(
		r'\b(Cubic|Tetragonal|Hexagonal|Trigonal|Orthorhombic|Monoclinic|Triclinic)'
		r'\s*\(([^)]+)\)'
	)

	# Loose per-line declarations. The leading word boundary keeps `a` from
	# matching `al`, `axial`, etc.; the (?:[a-zA-Z@]+\s+)* skips tokens like
	# `@` or `lpa` between the key and the numeric value.
	#
	# The angle labels are the LaTeX names, matching the macro branch below. They
	# used to be the plain words here, which meant the same file produced `\alpha`
	# or `alpha` depending only on how its cell happened to be written -- and the
	# info box renders its labels as mathtext, so the loose form came out as an
	# italic "alpha" instead of a Greek letter.
	loose_param_keys = (('a', 'a'), ('b', 'b'), ('c', 'c'),
	                    (r'\alpha', 'al'), (r'\beta', 'be'), (r'\gamma', 'ga'))

	phases_data = []

	# Safety cap to avoid pathological inputs creating dozens of phantom phases
	for phase_idx, block in enumerate(phase_blocks[:5]):
		if not block.strip():
			continue

		# Space group: quoted form preferred (it can contain '/' and '-'),
		# otherwise the first whitespace-delimited token after `space_group`.
		sg_m = re.search(r'space_group\s+"([^"]+)"', block) \
		       or re.search(r'space_group\s+(\S+)', block)
		sg_raw = sg_m.group(1).strip() if sg_m else None

		cell_raw = []

		# 1. Try the crystal-system macro form
		sys_m = macro_pat.search(block)
		if sys_m:
			param_str = sys_m.group(2)
			raw_tokens = [p.replace('@', '').strip() for p in param_str.split(',') if p.strip()]
			n_params = len(raw_tokens)
			if n_params == 1:
				labels = ['a']
			elif n_params == 2:
				labels = ['a', 'c']
			elif n_params == 3:
				labels = ['a', 'b', 'c']
			elif n_params == 4:
				labels = ['a', 'b', 'c', r'\beta']
			elif n_params == 6:
				labels = ['a', 'b', 'c', r'\alpha', r'\beta', r'\gamma']
			else:
				labels = [f'p{i+1}' for i in range(n_params)]
			for label, token in zip(labels, raw_tokens):
				cell_raw.append((label, token))
		else:
			# 2. Loose per-line declarations
			for label, key in loose_param_keys:
				pat = rf'^\s*{key}\b\s+(?:[a-zA-Z@]+\s+)*(\S+)'
				m = re.search(pat, block, re.MULTILINE)
				if m:
					cell_raw.append((label, m.group(1)))

		# 3. Volume (one per phase, by document order)
		if phase_idx < len(all_vols):
			cell_raw.append(('V', all_vols[phase_idx]))

		phases_data.append((sg_raw, cell_raw))

	return phases_data

# ==========================================
# REFLECTION OVERLAY (-r)
# ==========================================
# Shared with quickplot via core.cif. The Bragg tick rows above come from the fit itself
# (TOPAS 2Th_Ip files); this overlay is the opposite — reflections simulated from a
# CIF that is NOT in the fit, to check whether a leftover feature belongs to a
# suspected impurity phase.









def draw_reflection_lines(ax, ref_sets):
	"""Draw each set as fine dotted verticals behind the data (zorder below the traces).

	Only the first line of a set carries the label — matplotlib would otherwise emit one
	legend entry per reflection. Each set therefore contributes exactly one entry to the
	plot's existing upper-right legend. That legend is why this doesn't reuse
	pxrd_quickplot's corner-stacked text labels: here the top-right corner already holds
	the legend and, with -c, the unit-cell boxes."""
	for label, positions, color in ref_sets:
		for i, p in enumerate(positions):
			ax.axvline(p, color=color,
			           linestyle=settings['reflection_linestyle'],
			           linewidth=settings['reflection_linewidth'],
			           alpha=settings['reflection_alpha'],
			           zorder=1,
			           label=label if i == 0 else '_nolegend_')


# ==========================================
# MATPLOTLIB COMPOSITION ARRAYS
# ==========================================

def stack_artists_vertically(ax, N_lines,
                             bragg_spacing=settings['bragg_spacing'],
                             top_clearance=settings['tick_top_clearance'],
                             bottom_clearance=settings['tick_bottom_clearance'],
                             y_tol_top=settings['y_tol_top'],
                             y_tol_bottom=settings['y_tol_bottom'],
                             d_difference=settings['difference_band_height'],
                             min_data_fraction=settings['min_data_fraction'],
                             diff_shift_factor=settings['diff_shift_factor'],
                             common_scale=None):
	"""
	Positions Bragg tick rows and the difference curve using axes-coordinate fractions
	so the layout is invariant to data amplitude (e.g. range multiplications).

	Layout from top to bottom (axes coords, 0 = bottom edge, 1 = top edge):
	  y_tol_top | data region | top_clearance | tick rows | bottom_clearance | difference | y_tol_bottom

	`common_scale` is `(y_min, y_max, diff_amplitude)` taken across a whole series
	instead of from this fit alone. Without it every frame of an animation is
	scaled to its own maximum, so a peak that halves and an axis that halves with
	it look exactly alike -- the one thing a sequential experiment is being filmed
	to show. Passing it makes the intensities comparable from frame to frame and
	holds the tick rows and the difference band at one height throughout.
	"""
	try:
		fig = ax.figure
		fig.canvas.draw()

		N_pos = N_lines - 3  # number of Bragg tick row artists
		if N_pos <= 0 or len(ax.lines) < N_lines:
			return

		# Physical marker height expressed as an axes-coordinate fraction
		bbox = ax.get_window_extent()
		if bbox.height == 0:
			return
		marker_height_axes = (settings['2Th_Ip_markersize'] / 72.0 * fig.dpi) / bbox.height

		# All N_pos tick rows, each one marker tall, separated by bragg_spacing
		total_ticks_frac = N_pos * marker_height_axes + max(0, N_pos - 1) * bragg_spacing

		# Actual data range from observed + calculated profiles
		y0 = ax.lines[0].get_ydata()
		y1 = ax.lines[1].get_ydata()
		y_data_min = min(y0.min(), y1.min())
		y_data_max = max(y0.max(), y1.max())
		if common_scale is not None:
			y_data_min, y_data_max = float(common_scale[0]), float(common_scale[1])
		dy_data = y_data_max - y_data_min
		if dy_data == 0:
			return

		# Difference curve amplitude (full peak-to-trough span). Used both to anchor
		# the curve and to grow d_difference if the natural amplitude wouldn't fit.
		# We read it before laying out so the band can be expanded in a single pass.
		diff_line = ax.lines[N_lines - 1]
		y_diff = diff_line.get_ydata()
		diff_amplitude = float(y_diff.max() - y_diff.min())
		if common_scale is not None:
			# The band is sized for the worst difference curve in the series, so it
			# does not grow and shrink under a curve that is meant to be compared.
			diff_amplitude = float(common_scale[2])

		# Everything except the data region and the diff band is fixed
		fixed_non_diff = (y_tol_top + y_tol_bottom + bottom_clearance
		                  + total_ticks_frac + top_clearance)

		# Auto-expand d_difference so the natural diff amplitude fits inside
		# `diff_shift_factor` of the band (e.g. 0.8 leaves a 20% safety margin).
		# Derivation: we require D * dy_data / (1 - fixed_non_diff - D) ≥ diff_amplitude / sf
		# Solving for the minimum D yields the expression below.
		if diff_amplitude > 0 and 0 < diff_shift_factor <= 1:
			sf = diff_shift_factor
			denom = dy_data * sf + diff_amplitude
			if denom > 0:
				d_diff_needed = diff_amplitude * (1.0 - fixed_non_diff) / denom
				d_difference = max(d_difference, d_diff_needed)

		# Data region: whatever's left after reserving every other band
		d_calc_exp = 1.0 - (fixed_non_diff + d_difference)
		d_calc_exp = max(d_calc_exp, min_data_fraction)

		# Compute ylim so data fills exactly d_calc_exp of the axes height,
		# with y_data_max sitting at axes coord (1 - y_tol_top).
		ylim_range = dy_data / d_calc_exp
		ylim_max   = y_data_max + y_tol_top * ylim_range
		ylim_min   = ylim_max - ylim_range

		# Axes-coord → data-coord converter
		def ac2dc(ac):
			return ylim_min + ac * ylim_range

		# Axes coord where the data floor (y_data_min) sits
		data_bottom_axes = 1.0 - y_tol_top - d_calc_exp

		# Place each Bragg tick row below the data floor
		first_tick_center_axes = data_bottom_axes - top_clearance - marker_height_axes / 2
		for i in range(N_pos):
			tick_center_axes = first_tick_center_axes - i * (marker_height_axes + bragg_spacing)
			tick_y_data = ac2dc(tick_center_axes)
			line_idx = i + 2
			ax.lines[line_idx].set_ydata(
				np.full_like(ax.lines[line_idx].get_xdata(), tick_y_data)
			)

		# Anchor the difference curve at the centre of d_difference.
		# Using the median (rather than the geometric midpoint) is robust against
		# the occasional large spike. Note: no multiplier here — the previous
		# `* diff_shift_factor` was an operator-precedence bug that shifted the
		# curve upward (toward the Bragg ticks) by ~20% of |ac2dc(baseline)|.
		# Use N_lines - 1 (not -1) because the -m range markers are axvlines
		# appended to ax.lines after the original data lines were plotted.
		diff_baseline_axes = y_tol_bottom + d_difference / 2
		shift = float(np.median(y_diff)) - ac2dc(diff_baseline_axes)
		diff_line.set_ydata(y_diff - shift)

		ax.set_ylim(ylim_min, ylim_max)

	except Exception as e:
		print(f"Warning: Skipping vertical scaling alignment due to formatting error: {e}")


def style(ax):
	ax.set_xlabel(settings['x_label_text'], size=settings['size_axis_labels'], labelpad=7)
	ax.set_ylabel(settings['y_label_text'], size=settings['size_axis_labels'], labelpad=7)
	# No y ticks: a Pawley fit's intensities are on an arbitrary scale, so numbering
	# them would invite a reading they cannot support.
	ax.set_yticks([])
	if settings['x_tick_step']:
		ax.xaxis.set_major_locator(MultipleLocator(settings['x_tick_step']))
	ax.xaxis.set_minor_locator(AutoMinorLocator())
	ax.tick_params(axis='both', which='both',
	               labelsize=settings['size_tick_labels'],
	               direction=settings['tick_direction'],
	               top=settings['ticks_top'])
	ax.tick_params(axis='both', which='major', length=settings['tick_length_major'])
	ax.tick_params(axis='both', which='minor', length=settings['tick_length_minor'])

	if len(ax.lines) > 1:
		xmin = ax.lines[1].get_xdata().min()
		xmax = ax.lines[1].get_xdata().max()
		ax.set_xlim(xmin, xmax)


def _legend_artists(ax):
	"""The lines that should appear in the legend, in plot order.

	With `legend_dedupe`, a line is dropped when an earlier one already says the
	same thing *and* looks the same. Wording alone is not enough: a fixed
	`bragg_label` names every tick row identically, and collapsing two rows drawn
	in different colours would leave a colour in the plot that the key never
	accounts for.
	"""
	visible = [l for l in ax.lines if not l.get_label().startswith('_')]
	if not settings['legend_dedupe']:
		return visible

	seen = set()
	kept = []
	for line in visible:
		fingerprint = (line.get_label(), line.get_color(),
		               line.get_marker(), line.get_linestyle())
		if fingerprint in seen:
			continue
		seen.add(fingerprint)
		kept.append(line)
	return kept


def add_legend(ax):
	if not settings['show_legend']:
		return
	visible = _legend_artists(ax)
	# Proxies rather than the artists themselves: a 0.3 pt difference curve is
	# invisible at legend size, so the swatch is drawn at lw=1 regardless. Marker
	# stroke weight *is* carried over, since that is a shape the reader matches
	# against the plot rather than a hairline that vanishes.
	leg_lines = [Line2D([0], [0], marker=l.get_marker(), ms=l.get_ms(),
	                    mew=l.get_markeredgewidth(), ls=l.get_ls(),
	                    c=l.get_color(), lw=1) for l in visible]
	leg_labs = [l.get_label() for l in visible]
	ax.legend(leg_lines, leg_labs,
	          fontsize=settings['legend_fontsize'],
	          frameon=settings['legend_frame'],
	          ncol=settings['legend_columns'],
	          loc=settings['legend_loc'])


def add_quality(ax, info, show_all=False):
	"""Annotate the fit-quality factor(s) in the bottom-right corner.

	Default: the weighted profile R-factor R_wp alone (falling back to chi if
	R_wp wasn't parsed). With ``show_all`` (the --qall flag): R_wp, R_exp and chi
	on one line, in the same italic style. R-factors carry a `%` since TOPAS
	reports them as percentages; chi is dimensionless. Any factor that wasn't
	found in the .out is silently dropped, and if none are available no text is
	drawn at all."""
	if show_all:
		wanted = [('R_{wp}', 'r_wp', r'\%'), ('R_{exp}', 'r_exp', r'\%'), (r'\chi', 'gof', '')]
	elif info.get('r_wp') is not None:
		wanted = [('R_{wp}', 'r_wp', r'\%')]
	else:
		wanted = [(r'\chi', 'gof', '')]

	parts = []
	for symbol, key, unit in wanted:
		val = info.get(key)
		if val is not None:
			parts.append(r'%s = %.2f%s' % (symbol, val, unit))
	if not parts:
		return

	text = '$' + r',\ '.join(parts) + '$'
	ax.text(.99, .01, text, ha='right', va='bottom',
	        size=settings['quality_fontsize'], style='italic', transform=ax.transAxes)


def _renderer(fig):
	"""Best-effort renderer fetch that works across the Agg-family backends."""
	try:
		return fig.canvas.get_renderer()
	except AttributeError:
		fig.canvas.draw()
		return fig.canvas.get_renderer()


def _frac_bbox(artist, ax, renderer):
	"""Window extent of an artist (its rounded bbox patch, if any) in axes-fraction coords."""
	getter = getattr(artist, 'get_bbox_patch', None)
	target = getter() if getter and getter() is not None else artist
	bb = target.get_window_extent(renderer)
	(x0, y0), (x1, y1) = ax.transAxes.inverted().transform([(bb.x0, bb.y0), (bb.x1, bb.y1)])
	return x0, y0, x1, y1


def _data_envelope_frac(ax):
	"""The observed + calculated traces expressed in axes-fraction coordinates.
	transLimits maps data → axes fraction purely from the view limits, so the result
	is independent of figure size and can be computed once."""
	chunks = []
	for ln in ax.lines[:2]:  # plot order: [0] observed, [1] calculated
		xd = np.asarray(ln.get_xdata(), dtype=float)
		yd = np.asarray(ln.get_ydata(), dtype=float)
		if xd.size:
			chunks.append(ax.transLimits.transform(np.column_stack([xd, yd])))
	return np.vstack(chunks) if chunks else np.empty((0, 2))


def _envelope_ceiling(env, x_left, x_right):
	"""Highest data y-fraction within the axes-fraction x-span [x_left, x_right]."""
	if env.size == 0:
		return 0.0
	mask = (env[:, 0] >= x_left) & (env[:, 0] <= x_right)
	return float(env[mask, 1].max()) if mask.any() else 0.0


def _measure_boxes(boxes, fontsize, ax, fig):
	"""Set all boxes to `fontsize`, draw once, and return per-box
	(width, height, off_right, off_top) in axes fraction. The offsets are the gap
	between the text anchor and the patch's right/top edges, so a caller can place
	the patch's corner exactly by anchoring at (target - offset). All four values
	depend only on the font size and the figure's physical size, not on position."""
	for b in boxes:
		b.set_fontsize(fontsize)
	fig.canvas.draw()
	renderer = _renderer(fig)
	dims = []
	for b in boxes:
		x0, y0, x1, y1 = _frac_bbox(b, ax, renderer)
		ax_x, ax_y = b.get_position()
		dims.append((x1 - x0, y1 - y0, x1 - ax_x, y1 - ax_y))
	return dims


def _apply_vertical(boxes, dims, top, right, vgap):
	"""Right-aligned single column, stacked downward from `top`."""
	y = top
	for b, (w, h, off_r, off_t) in zip(boxes, dims):
		b.set_position((right - off_r, y - off_t))
		y -= h + vgap


def _apply_horizontal(boxes, dims, top, right, hgap):
	"""Right-aligned single row, top edges level with `top`."""
	r = right
	for b, (w, h, off_r, off_t) in zip(boxes, dims):
		b.set_position((r - off_r, top - off_t))
		r -= w + hgap


def add_unit_cell_boxes(ax, phases_cell_info, phase_colors, x=settings['box_x']):
	"""Place one info box per phase, coloured to match its Bragg reflections, packed
	tightly under the legend. The arrangement adapts to the space actually available
	between the legend and the plotted data, following this hierarchy:

	  1. vertical stack (one column) at the default font size;
	  2. else a horizontal row (side by side) at the default font size;
	  3. else shrink the font (retrying vertical, then horizontal) down to
	     `box_fontsize_min`;
	  4. else accept overlap, using whichever candidate descends least into the data.

	The layout is measured against the live renderer and recomputed on every resize,
	so the interactive window and the saved file agree regardless of window size."""
	if not phases_cell_info:
		return
	fig = ax.figure

	# Build the text artists once; positions and font size are set later by relayout.
	boxes = []
	for idx, (sg_num, cell_info) in enumerate(phases_cell_info):
		if not cell_info:
			continue
		color = phase_colors[idx] if idx < len(phase_colors) \
			else settings['2Th_Ip_colors'][idx % len(settings['2Th_Ip_colors'])]
		max_val_len = max(len(mv + brk) for _, mv, brk in cell_info)
		lines = [f"${lbl}$: {(mv + brk):>{max_val_len}}" for lbl, mv, brk in cell_info]
		boxes.append(ax.text(
			settings['box_x'], settings['box_y_top'], "\n".join(lines),
			transform=ax.transAxes, family='monospace',
			fontsize=settings['box_fontsize'], ha='right', va='top',
			multialignment='left',
			bbox=dict(boxstyle=f"round,pad={settings['box_pad']}",
					  facecolor=to_pastel(color), edgecolor='none')))
	if not boxes:
		return

	env = _data_envelope_frac(ax)
	clearance = settings['box_data_clearance']
	vgap = settings['box_gap']
	hgap = settings['box_col_gap']

	def relayout():
		renderer = _renderer(fig)

		# Anchor right below the legend; fall back to fixed coords if it's absent.
		leg = ax.get_legend()
		if leg is not None:
			lx0, ly0, lx1, ly1 = _frac_bbox(leg, ax, renderer)
			top, right = ly0 - settings['box_legend_gap'], lx1
		else:
			top, right = settings['box_y_top'], settings['box_x']

		best = None  # (arrangement, fontsize, block_bottom) — least-intrusive fallback
		for fs in range(settings['box_fontsize'], settings['box_fontsize_min'] - 1, -1):
			dims = _measure_boxes(boxes, fs, ax, fig)
			ws = [d[0] for d in dims]
			hs = [d[1] for d in dims]

			# Vertical: one right-aligned column.
			v_left = right - max(ws)
			v_bottom = top - (sum(hs) + vgap * (len(boxes) - 1))
			v_fits = v_left >= 0 and v_bottom >= _envelope_ceiling(env, v_left, right) + clearance

			# Horizontal: one right-aligned row.
			h_left = right - (sum(ws) + hgap * (len(boxes) - 1))
			h_bottom = top - max(hs)
			h_fits = h_left >= 0 and h_bottom >= _envelope_ceiling(env, h_left, right) + clearance

			if v_fits:
				_apply_vertical(boxes, dims, top, right, vgap)
				return
			if h_fits:
				_apply_horizontal(boxes, dims, top, right, hgap)
				return

			for arrange, bottom in (('V', v_bottom), ('H', h_bottom)):
				if best is None or bottom > best[2]:
					best = (arrange, fs, bottom)

		# Nothing fit at any size — accept overlap with the least-descending candidate.
		arrange, fs, _ = best
		dims = _measure_boxes(boxes, fs, ax, fig)
		(_apply_vertical if arrange == 'V' else _apply_horizontal)(
			boxes, dims, top, right, vgap if arrange == 'V' else hgap)

	relayout()

	# Re-pack when the interactive window is resized so the look stays consistent.
	state = {'busy': False}

	def _on_resize(event):
		if state['busy']:
			return
		state['busy'] = True
		try:
			relayout()
		finally:
			state['busy'] = False
		fig.canvas.draw_idle()

	fig.canvas.mpl_connect('resize_event', _on_resize)

# ==========================================
# MAIN ROUTINE EXECUTION
# ==========================================

def _pick_by_ident(sorted_filegroup, ident_substr):
	"""First (ident, path) in the group whose ident contains the substring, or None."""
	for ident, path in sorted_filegroup:
		if ident_substr in ident:
			return ident, path
	return None


def _parse_tick_ident(ident):
	"""Extract (phase_index, sg_token) from a 2Th_Ip file's ident suffix.

	Recognised forms of the suffix after `2Th_Ip_`:
	  'p<idx>_<sg>'  -> (idx,  '<sg>')   current wizard, e.g. 'p2_14' -> (2, '14')
	  '<sg>_<n>'     -> (None, '<sg>')   manual de-dup rename,  e.g. '14_2' -> (None, '14')
	  '<sg>'         -> (None, '<sg>')   legacy single token,   e.g. '14' or 'Pbca'

	phase_index is 1-based (or None when the filename doesn't declare one); sg_token
	may be a number or an HM symbol and is passed through resolve_sg downstream. The
	explicit index is what makes same-space-group phases unambiguous; the older forms
	are still accepted so existing output keeps plotting."""
	m = re.search(rf'^{re.escape(settings["2Th_Ip_ident"])}_(\S+)$', ident)
	if not m:
		return None, None
	suffix = m.group(1).strip()
	mp = re.match(r'^p(\d+)_(.+)$', suffix)
	if mp:
		return int(mp.group(1)), mp.group(2)
	md = re.match(r'^(\d+)_(\d+)$', suffix)   # legacy manual `<sg>_<copy>` rename
	if md:
		return None, md.group(1)
	return None, suffix


def _phase_ordinal(explicit_idx, canon_sg, phase_sgs, used):
	"""Resolve which phase (0-based ordinal into the .out's phase list) a tick belongs
	to, given its explicit p<idx> (or None) and resolved space group (or None).

	Precedence:
	  1. explicit filename index   — authoritative for current wizard output;
	  2. an unclaimed space-group match — order-independent for legacy files whose
	     phases have distinct SGs;
	  3. the next unclaimed phase in declaration order — last-resort positional.

	`used` holds ordinals already claimed by earlier ticks. Returns an int ordinal,
	or None when no phase is left to assign."""
	n = len(phase_sgs)
	if explicit_idx is not None and 0 <= explicit_idx - 1 < n:
		return explicit_idx - 1
	if canon_sg:
		unused_hits = [k for k, sg in enumerate(phase_sgs) if sg == canon_sg and k not in used]
		if unused_hits:
			return unused_hits[0]
	return next((k for k in range(n) if k not in used), None)


def _legend_label_for(canon_sg, hm_label, substance):
	"""Build a legend entry from whatever pieces are available, gracefully degrading
	when the substance is unknown."""
	fmt = settings['use_sg_format'] if settings['use_sg_from_outfile'] else None
	if fmt == 'SUBSTANCE' and substance:
		return substance
	if fmt == 'NUMBER' and canon_sg:
		return canon_sg
	if fmt == 'HERMANN-MAUGUIN' and hm_label:
		return hm_label
	if fmt == 'HERMANN-MAUGUIN+SUBSTANCE':
		if hm_label and substance:
			return f"{hm_label} | {substance}"
		if hm_label:
			return hm_label
		if substance:
			return substance
	# Last-ditch fallbacks
	if hm_label:
		return hm_label
	if canon_sg:
		return canon_sg
	return settings['2Th_Ip_label'] if isinstance(settings['2Th_Ip_label'], str) else 'Reflections'


def _bragg_labels(tick_meta):
	"""Legend text for each Bragg tick row.

	Without a fixed `bragg_label`, every row names itself after its own space group
	and substance, which is the historic behaviour.

	With one, the reader is being told these are all the same kind of thing -- so
	while the rows are also drawn alike, one entry says it and `legend_dedupe`
	collapses the repeats. The moment two rows differ in colour that stops being
	true: there are now two things on the plot to tell apart, and a key that names
	only one of them leaves the second colour unexplained. Each row therefore
	keeps its phase in brackets, preferring the substance name over the space
	group because that is what people actually call it.
	"""
	fixed = settings['bragg_label']
	if not fixed:
		return [tick['label'] for tick in tick_meta]
	if len({tick['color'] for tick in tick_meta}) <= 1:
		return [fixed] * len(tick_meta)
	return [f"{fixed} ({tick['substance'] or tick['label']})" for tick in tick_meta]


def _series_scale(group_names, file_dicts):
	"""`(y_min, y_max, max_diff_amplitude)` over every fit in the series.

	Read straight from the data files before any plotting, because the scale has
	to be known before the first frame is drawn. Returns None if nothing could be
	read, in which case each frame falls back to scaling itself and the animation
	is no worse than it would have been.
	"""
	lows, highs, amplitudes = [], [], []
	for group_name in group_names:
		group_dict = file_dicts[group_name]
		if len(group_dict) < 3:
			continue
		sorted_filegroup = sort_filegroup(group_dict)
		exp_file = _pick_by_ident(sorted_filegroup, settings['X_Yobs_ident'])
		calc_file = _pick_by_ident(sorted_filegroup, settings['Out_X_Ycalc_ident'])
		dif_file = _pick_by_ident(sorted_filegroup, settings['X_Difference_ident'])
		if not (exp_file and calc_file and dif_file):
			continue
		try:
			for path in (exp_file[1], calc_file[1]):
				_x, y = get_x_y(path)
				lows.append(float(np.min(y)))
				highs.append(float(np.max(y)))
			_x, y_diff = get_x_y(dif_file[1])
			amplitudes.append(float(np.max(y_diff) - np.min(y_diff)))
		except Exception as e:
			print(f'[!] {group_name}: could not pre-read for the common scale ({e}).')
			continue

	if not lows:
		return None
	return min(lows), max(highs), max(amplitudes or [0.0])


def _missing_pieces(group_dict):
	"""The file types a group lacks, or [] when it can be plotted.

	Shared by the plotting loop and the up-front count that --x-values is checked
	against, so the two can never disagree about which fits make it into the run.
	"""
	if len(group_dict) < 3:
		return ['(fewer than three files)']
	sorted_filegroup = sort_filegroup(group_dict)
	pieces = (('X_Yobs', _pick_by_ident(sorted_filegroup, settings['X_Yobs_ident'])),
	          ('Out_X_Ycalc', _pick_by_ident(sorted_filegroup, settings['Out_X_Ycalc_ident'])),
	          ('X_Difference', _pick_by_ident(sorted_filegroup, settings['X_Difference_ident'])),
	          ('2Th_Ip', [t for t in sorted_filegroup if settings['2Th_Ip_ident'] in t[0]]))
	return [name for name, val in pieces if not val]


def _collect_cell_series(cell_series, group_name, outfile_path, tick_meta, x=None):
	"""Record this fit's cell parameters into a per-phase series.

	Keyed by phase ordinal rather than by name: a phase's substance can be
	missing from one .out in a run and present in the next, and a series that
	split in two halfway through would animate as two half-length GIFs.
	"""
	if not outfile_path:
		return
	names = {}
	for tick in tick_meta:
		if tick['phase_i'] is not None and tick['phase_i'] not in names:
			names[tick['phase_i']] = tick['substance'] or tick['label']

	for phase_i, (_sg_raw, cell_raw) in enumerate(get_unit_cell_raw(outfile_path)):
		params = {label: token for label, token in cell_raw
		          if label in animate.TREND_KEYS}
		if not params:
			continue
		series = cell_series.get(phase_i)
		if series is None:
			series = animate.CellSeries(names.get(phase_i, f'phase {phase_i + 1}'))
			cell_series[phase_i] = series
		series.add(group_name, params, x=x)


def _write_animation(frames, fmt, path, delay_ms):
	if fmt == 'svg':
		animate.write_animated_svg(frames, path, delay_ms=delay_ms)
	else:
		animate.write_gif(frames, path, delay_ms=delay_ms)


def _write_animations(frames_by_format, cell_series, stem, delay_ms, relative=True,
                      x_label=None, have_x=False, rolling=animate.DEFAULT_ROLLING):
	"""Write the fit animation and, per phase, the cell and step animations and the trend plot."""
	stem = stem or Path(os.path.abspath(settings['start_dir'])).name or 'fits'
	formats = list(frames_by_format)
	n_frames = max((len(f) for f in frames_by_format.values()), default=0)

	if not n_frames:
		print('[!] No fits to animate.')
		return
	if n_frames < 2:
		print('[!] Only one fit here, so there is nothing to animate. '
		      'Use -s for a single plot.')
		return

	for fmt in formats:
		fits_path = f'{stem}-fits.{fmt}'
		_write_animation(frames_by_format[fmt], fmt, fits_path, delay_ms)
		print(f'[+] {fits_path}  ({n_frames} frames, {delay_ms} ms each)')

	multi = len(cell_series) > 1
	capture = {'gif': lambda fig: animate.figure_to_frame(fig, dpi=settings['gif_dpi']),
	           'svg': animate.figure_to_svg}
	for phase_i in sorted(cell_series):
		series = cell_series[phase_i]
		suffix = f'-p{phase_i + 1}' if multi else ''
		if len(series) < 2:
			print(f'[!] {series.name}: only {len(series)} fit(s) carried cell '
			      f'parameters, so no cell animation or trend plot was written.')
			continue

		for fmt in formats:
			cell_frames = animate.render_cell_frames(
				series, figsize=settings['figsize'], dpi=settings['gif_dpi'],
				title=series.name if multi else None, relative=relative,
				capture=capture[fmt])
			if not cell_frames:
				continue
			cell_path = f'{stem}-cell{suffix}.{fmt}'
			_write_animation(cell_frames, fmt, cell_path, delay_ms)
			print(f'[+] {cell_path}  ({len(cell_frames)} frames, '
			      f'{", ".join(k.lstrip(chr(92)) for k in series.keys())})')

			step_frames = animate.render_step_frames(
				series, figsize=settings['figsize'], dpi=settings['gif_dpi'],
				title=series.name if multi else None, x_label=x_label, have_x=have_x,
				window=rolling, label_size=settings['size_axis_labels'] - 1,
				tick_size=settings['size_tick_labels'] - 1,
				legend_size=settings['legend_fontsize'], capture=capture[fmt])
			if step_frames:
				step_path = f'{stem}-steps{suffix}.{fmt}'
				_write_animation(step_frames, fmt, step_path, delay_ms)
				print(f'[+] {step_path}  ({len(step_frames)} frames, change since previous fit)')

		fig = animate.render_trend(
			series, x_label=x_label if have_x else None,
			figsize=settings['figsize'], title=series.name if multi else None,
			label_size=settings['size_axis_labels'], tick_size=settings['size_tick_labels'],
			legend_size=settings['legend_fontsize'])
		if fig is None:
			continue
		trend_path = f'{stem}-trend{suffix}.{settings["extension"]}'
		fig.savefig(trend_path, dpi=settings['dpi'], bbox_inches='tight',
		            transparent=settings['transparent'])
		plt.close(fig)
		keys = ', '.join(k.lstrip(chr(92)) for k in series.keys(order=animate.TREND_KEYS))
		print(f'[+] {trend_path}  ({keys} relative to the first fit)')

	if cell_series and not have_x:
		# Said once, not per file: the plot is still right in the usual case of
		# evenly spaced steps, but a slope read off it is only as good as that
		# assumption, and nothing on the plot itself would say it was made.
		print('[*] Trend x axis is the fit number, which assumes evenly spaced steps. '
		      'Pass --x-values for a quantitative axis.')


def vprint(*a, **kw):
	if args.verbose:
		print(*a, **kw)


def main():
	global args
	# Strict parsing, not parse_known_args: a mistyped flag used to be dropped
	# without a word, so `--multply 20,40,10` drew an unscaled plot -- and with
	# -d, wrote that into a file that claimed otherwise. --gif saves too, so it
	# counts as a silent run.
	args = cmdline.parse_args(_build_parser(), 'pp', 'achdiff.tools.plotter',
	                          silent=lambda a: a.silent or a.gif)

	# Resolve the person, then their settings. Announced rather than silent: a
	# wrong profile means a wrong CIF library, and that should never be invisible.
	user, source = identity.resolve(args.user)
	if args.user or user:
		print(identity.describe(user, source))

	# The style sheet goes on before anything is measured or drawn: several of its
	# settings (figsize, marker sizes) feed the vertical layout, which would
	# otherwise be computed against values the figure no longer uses. Announced
	# for the same reason the profile is -- a figure that silently came out in
	# someone else's house style is a figure you republish by accident.
	try:
		applied = styles.apply('pp', settings, user=user, explicit=args.style)
	except FileNotFoundError as e:
		print(f'[!] {e}')
		raise SystemExit(2)
	if applied:
		print(f'[*] Style: {applied}')

	# Resolved after the style, so `extension` in a style sheet is honoured while
	# an explicit -x still wins. --size and --dpi likewise.
	settings['extension'] = (args.extension or settings['extension']).lstrip('.').lower()
	if args.size:
		settings['figsize'] = tuple(args.size)
	if args.dpi:
		settings['dpi'] = args.dpi

	# Parsed once, so a bad group is reported once rather than once per fit.
	multiply = overlays.parse_multiply(args.multiply)
	bands = overlays.parse_bands(args.band)

	settings['cif_dir_path'] = config.get('cif_loc', cli_value=args.cif_loc, user=user)
	# A profile's `qall = true` arrives as a default --qall (cmdline.SETTING_FLAGS),
	# so --no-defaults turns it off and -d writes it down like any other flag.
	qall = args.qall

	if args.save_profile:
		if not args.user:
			print('[!] --save-profile needs -u ID to say which profile to write.')
		else:
			saved = {'cif_loc': settings['cif_dir_path']}
			if args.qall:
				saved['qall'] = True
			path = config.save_profile(args.user, saved)
			print(f'[+] Saved profile {args.user} to {path}')

	file_dicts = get_file_dicts()
	all_out_files = glob('*.out')

	# Natural order, so scan_2 comes before scan_10. It matters most for --gif,
	# where the order is the timeline, but a batch that saves or shows its plots
	# out of numerical order was never what anyone wanted either.
	group_names = sorted(file_dicts, key=animate.natural_key)

	if args.x_map and (args.sort_key or args.x_values is not None):
		print('[!] --x-map sets both the order and the x values, so it cannot be combined '
		      'with --sort-key or --x-values. Use one or the other.')
		raise SystemExit(2)

	# An explicit order replaces the natural one. Natural sort cannot see that
	# `0.5GPa` belongs after `0GPa` -- it splits at the point and compares the
	# pieces -- and no filename convention is universal enough to guess from.
	if args.sort_key:
		try:
			group_names, unmatched = animate.sort_by_pattern(group_names, args.sort_key)
		except ValueError as e:
			print(f'[!] --sort-key: {e}')
			raise SystemExit(2)
		if unmatched:
			print(f'[!] --sort-key matched nothing in {len(unmatched)} fit(s); '
			      f'they are kept and placed last: {", ".join(unmatched)}')
			group_names = group_names + unmatched
		print(f'[*] Order from --sort-key: {", ".join(group_names)}')

	# Everything about the run that can be refused is refused here, before any
	# frame is rendered -- a mistyped value list should cost a second, not the
	# minute it takes to draw forty plots first.
	formats = []
	x_by_group = {}
	if args.gif:
		formats = [f.strip().lower() for f in str(args.gif_format).split(',') if f.strip()]
		bad = [f for f in formats if f not in animate.ANIMATION_FORMATS]
		if bad or not formats:
			print(f'[!] --gif-format: {", ".join(bad) or "nothing given"} is not one of '
			      f'{", ".join(animate.ANIMATION_FORMATS)}.')
			raise SystemExit(2)
		formats = list(dict.fromkeys(formats))   # "gif,gif" means gif once

	runnable = [g for g in group_names if not _missing_pieces(file_dicts[g])]
	vprint(f'[v] {len(runnable)} complete fit(s) here'
	       + (f': {", ".join(runnable)}' if runnable else ''))

	if args.x_map_template:
		prefill, source = None, ''
		if args.sort_key:
			prefill = animate.first_number(runnable, args.sort_key)
			if any(v is not None for v in prefill):
				source = f'the --sort-key pattern {args.sort_key!r}'
			else:
				prefill = None
		animate.write_x_map_template(args.x_map_template, runnable, prefill, source)
		filled = sum(v is not None for v in (prefill or []))
		print(f'[+] {args.x_map_template}  ({len(runnable)} fits'
		      + (f', {filled} x value(s) pre-filled' if filled else ', x values to fill in') + ')')
		print('    Put the lines in measurement order, check every x value, then run:')
		print(f'      pp --gif --x-map "{args.x_map_template}"')
		return

	if args.x_map:
		if not args.gif:
			print('[!] --x-map only applies to --gif; ignoring it.')
		else:
			try:
				entries = animate.read_x_map(args.x_map)
			except (OSError, ValueError) as e:
				print(f'[!] --x-map {args.x_map}: {e}')
				raise SystemExit(2)
			# Names are checked against the fits that can actually be drawn, so a
			# typo, a renamed file or a fit missing its difference curve is refused
			# here -- not discovered as a gap in the finished animation.
			known = set(runnable)
			unknown = [name for name, _x in entries if name not in known]
			if unknown:
				print(f'[!] --x-map lists {len(unknown)} fit(s) that are not here, or are '
				      f'missing a data file:')
				for name in unknown:
					incomplete = name in file_dicts
					print(f'      {name}' + ('   (incomplete)' if incomplete else ''))
				print('    `pp --x-map-template FILE` lists the names exactly as pp sees them.')
				raise SystemExit(2)
			group_names = [name for name, _x in entries]
			x_by_group = dict(entries)
			left_out = [g for g in runnable if g not in x_by_group]
			print(f'[*] --x-map: {len(entries)} of {len(runnable)} fits, in the order listed.')
			if left_out:
				print(f'    Not listed, so not drawn: {", ".join(left_out)}')

	if args.x_values is not None:
		if not args.gif:
			print('[!] --x-values only applies to the trend plot written by --gif; ignoring it.')
		else:
			try:
				x_values = animate.parse_x_values(args.x_values)
			except ValueError as e:
				print(f'[!] --x-values: {e}')
				raise SystemExit(2)
			if len(x_values) != len(runnable):
				print(f'[!] --x-values gives {len(x_values)} value(s) for {len(runnable)} fit(s). '
				      f'There has to be exactly one per fit, in the order they are drawn:')
				for i, g in enumerate(runnable, start=1):
					print(f'      {i:>3}  {g}')
				print('    For a run that comes back down, or to leave fits out, write the order')
				print('    and values to a file instead:  pp --gif --x-map-template run.txt')
				raise SystemExit(2)
			x_by_group = dict(zip(runnable, x_values))

	# An animation has to be scaled to the whole series before its first frame is
	# drawn, so the data is read once up front. Cheap next to the plotting, and it
	# is the only way the frames can be comparable to each other.
	common_scale = None
	frames_by_format = {fmt: [] for fmt in formats}
	cell_series = {}
	if args.gif:
		args.silent = True
		common_scale = _series_scale(group_names, file_dicts)

	for group_name in group_names:
		group_dict = file_dicts[group_name]
		if len(group_dict) < 3:
			continue

		# The same test the --x-values count was made against, so a fit is either
		# drawn and given its value or skipped and given none -- never one of each.
		missing = _missing_pieces(group_dict)
		if missing:
			print(f"Skipping group '{group_name}': missing file type(s) {missing}.")
			continue

		sorted_filegroup = sort_filegroup(group_dict)

		# Resolve files by type rather than positional index, so groups with missing
		# pieces are detected explicitly instead of silently mis-pairing.
		exp_file  = _pick_by_ident(sorted_filegroup, settings['X_Yobs_ident'])
		calc_file = _pick_by_ident(sorted_filegroup, settings['Out_X_Ycalc_ident'])
		dif_file  = _pick_by_ident(sorted_filegroup, settings['X_Difference_ident'])
		pos_files = [t for t in sorted_filegroup if settings['2Th_Ip_ident'] in t[0]]

		# Locate the .out — may be at a different basename than the data files,
		# or absent entirely (in which case metadata silently disappears but the
		# core obs/calc/ticks/difference still plot).
		outfile_path = find_outfile_for_group(group_name, all_out_files) or ''
		outfile_info       = get_outfile_info(outfile_path)
		phases_cell_info   = get_unit_cell_info(outfile_path)         # [(sg_raw, cell_data), ...] in phase order
		ordered_substances = get_substances_from_outfile(outfile_path)  # [(name, sg), ...] in phase order

		# Per-phase space group, indexed by phase ordinal. A phase is identified by its
		# position in the .out (1st hkl_Is block, 2nd, ...) — never by its space group,
		# which is only an attribute and may repeat across phases. Cell-info SG is
		# preferred; the audit line's SG is a fallback when cells didn't parse.
		n_phases = max(len(phases_cell_info), len(ordered_substances))
		phase_sgs = []
		for k in range(n_phases):
			sg = resolve_sg(phases_cell_info[k][0])[0] if k < len(phases_cell_info) else None
			if not sg and k < len(ordered_substances):
				sg = resolve_sg(ordered_substances[k][1])[0]
			phase_sgs.append(sg)

		# Parse each tick file's (explicit phase index, sg token). When every tick carries
		# an explicit index, sort into phase order so the join is robust to the filesystem
		# glob ordering; otherwise keep discovery order for legacy/un-indexed files.
		parsed = [_parse_tick_ident(ident) for ident, _ in pos_files]
		if pos_files and all(idx is not None for idx, _ in parsed):
			order     = sorted(range(len(pos_files)), key=lambda k: parsed[k][0])
			pos_files = [pos_files[k] for k in order]
			parsed    = [parsed[k] for k in order]

		# Resolve each tick to a phase ordinal once and reuse it for both the legend label
		# (via substance) and the unit-cell box pairing, so the two can never disagree.
		used = set()
		tick_meta = []
		for i, (ident, path) in enumerate(pos_files):
			explicit_idx, sg_token = parsed[i]
			canon_sg, hm_label = resolve_sg(sg_token)
			phase_i = _phase_ordinal(explicit_idx, canon_sg, phase_sgs, used)
			if phase_i is not None:
				used.add(phase_i)

			# Space group: filename token first, then the matched phase's sg from the .out.
			if not canon_sg and phase_i is not None and phase_sgs[phase_i]:
				canon_sg = phase_sgs[phase_i]
			if canon_sg:
				hm_label = sgs_HM.get(canon_sg, hm_label)

			# Substance: looked up by phase ordinal into the ordered list — never by sg.
			substance = ordered_substances[phase_i][0] \
				if phase_i is not None and phase_i < len(ordered_substances) else None

			tick_meta.append({
				'idx':       i,
				'phase_i':   phase_i,
				'path':      path,
				'color':     settings['2Th_Ip_colors'][i % len(settings['2Th_Ip_colors'])],
				'sg_num':    canon_sg,
				'substance': substance,
				'label':     _legend_label_for(canon_sg, hm_label, substance),
			})

		# Unit-cell boxes follow the same tick→phase ordinals, so each box appears in the
		# same top-to-bottom order (and colour) as its legend Bragg entry.
		ordered_phases     = []
		ordered_box_colors = []
		for tick in tick_meta:
			j = tick['phase_i']
			if j is not None and j < len(phases_cell_info):
				ordered_phases.append(phases_cell_info[j])
				ordered_box_colors.append(tick['color'])

		# Tick legend labels in (phase-ordered) pos_files order
		bragg_labels = _bragg_labels(tick_meta)
		settings['2Th_Ip_label'] = bragg_labels

		# ---- Plot the core artists ----
		fig, ax = plt.subplots(figsize=settings['figsize'], layout='constrained')

		# Trace 1: Observed
		x, y = get_x_y(exp_file[1])
		ax.plot(x, y, ls='', marker='x', mew=settings['X_Yobs_markeredgewidth'],
		        color=settings['X_Yobs_color'],
		        label=settings['X_Yobs_label'], ms=settings['X_Yobs_markersize'])

		# Trace 2: Calculated
		x, y = get_x_y(calc_file[1])
		ax.plot(x, y, ls='-', lw=settings['Out_X_Ycalc_linewidth'], marker='',
		        color=settings['Out_X_Ycalc_color'],
		        label=settings['Out_X_Ycalc_label'], ms=settings['Out_X_Ycalc_markersize'])

		# Trace 3+: Bragg tick rows (one per phase)
		for i, (ident, path) in enumerate(pos_files):
			x, y = get_x_y(path)
			ax.plot(x, np.zeros_like(x), ls='', marker='|',
			        mew=settings['2Th_Ip_markeredgewidth'],
			        color=tick_meta[i]['color'], label=bragg_labels[i],
			        ms=settings['2Th_Ip_markersize'])

		# Trace N: Difference
		x, y = get_x_y(dif_file[1])
		ax.plot(x, y, ls='-', marker='', lw=settings['X_Difference_linewidth'],
		        color=settings['X_Difference_color'],
		        label=settings['X_Difference_label'], ms=settings['X_Difference_markersize'])

		# Layout, legend, optional decorations
		N_files = 2 + len(pos_files) + 1  # exp + calc + Bragg rows + diff
		x_lo = ax.lines[1].get_xdata().min()
		x_hi = ax.lines[1].get_xdata().max()
		if multiply:
			ranges = overlays.resolve(multiply, x_lo, x_hi)
			# Every range is applied before any marker is drawn: the markers are
			# lines too, and the difference curve is found by its position.
			for line in (ax.lines[0], ax.lines[1], ax.lines[N_files - 1]):
				xs, ys = line.get_data()
				line.set_data(xs, overlays.scale(xs, ys, ranges))
			overlays.draw_multiply_marks(ax, ranges, x_lo, x_hi,
			                             label_y=settings['multiply_label_y'],
			                             fontsize=settings['multiply_label_size'])
		overlays.draw_bands(ax, bands, x_lo, x_hi,
		                    default_width_pct=settings['band_width'],
		                    default_color=settings['band_color'])
		stack_artists_vertically(ax, N_files, common_scale=common_scale)
		# Reflection overlay goes in after both of the above and before the legend:
		# stack_artists_vertically finds the difference curve by its position in
		# ax.lines, and add_legend builds its entries from whatever is in ax.lines
		# when it runs.
		if args.reflections:
			draw_reflection_lines(ax, cifcore.collect_reflection_sets(
				args.reflections,
				(ax.lines[1].get_xdata().min(), ax.lines[1].get_xdata().max()),
				palette=settings['reflection_color_cycle'],
				cif_dir=settings['cif_dir_path'],
				wavelength=settings['cif_wavelength'],
				default_n_top=settings['reflection_n_top']))
		add_legend(ax)

		if settings['show_info']:
			add_quality(ax, outfile_info, show_all=qall)
		if args.cell_info:
			add_unit_cell_boxes(ax, ordered_phases, ordered_box_colors)
		if args.title:
			ax.set_title(args.title if isinstance(args.title, str) else group_name,
			             fontsize=settings['title_font_size'],
			             fontweight=settings['title_font_weight'])
		style(ax)

		if args.gif:
			# No bbox_inches='tight' here, unlike the saved-file path: tight crops
			# to the artists, so a frame whose labels are a character wider comes
			# out a different size and the animation cannot be assembled at all.
			if 'gif' in frames_by_format:
				frames_by_format['gif'].append(
					animate.figure_to_frame(fig, dpi=settings['gif_dpi']))
			if 'svg' in frames_by_format:
				frames_by_format['svg'].append(animate.figure_to_svg(fig))
			_collect_cell_series(cell_series, group_name, outfile_path, tick_meta,
			                     x=x_by_group.get(group_name))
			plt.close(fig)
		elif args.silent:
			outfile_name = f"{group_name}.{settings['extension']}"
			plt.savefig(outfile_name, dpi=settings['dpi'], bbox_inches='tight',
			            transparent=settings['transparent'])
			vprint(f'[+] Saved -> {outfile_name}')
			plt.close(fig)
		else:
			plt.show()

	if args.gif:
		_write_animations(frames_by_format, cell_series, args.gif_name, args.gif_delay,
		                  relative=not args.gif_absolute,
		                  x_label=args.x_label or 'x', have_x=bool(x_by_group),
		                  rolling=max(int(args.gif_rolling), 0))


if __name__ == '__main__':
	main()
