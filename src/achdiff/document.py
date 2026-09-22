"""-d / --document: keep the command that made a plot, as a file you can re-run.

The habit this replaces is `echo pp -c --qall>run.bat`, typed after a plot came
out right. Built in, the tool writes the file itself: `run<N>.bat` in the working
directory, or `run<N>_s.bat` when the run saves its plot silently. Double-click it
to redraw the plot; the image never needs keeping, because the recipe is kept.

One counter covers both kinds, so run3_s.bat is always newer than run2.bat and a
number never names two files. A number is never reused: the next one is one past
the highest already in the directory, gaps included.

What the file has to get right
------------------------------
The command runs a second time under cmd.exe, not under the shell that typed it.
Three things differ there, all verified against cmd on Windows 11:

  - `%` is expanded even inside quotes, so a literal one is written `%%`. A
    command reached through CALL is expanded twice and needs `%%%%`; CALL is used
    only for a .cmd alias, which otherwise would not return to run the lines
    after it.
  - `& | < > ^ ( )` are cmd syntax. An argument holding one is quoted -- which is
    what `pq -m "((20,40,10))"` needed at the prompt too -- and quoting follows
    the C runtime's rules, since that is what the program's argv is built from.
  - A .bat is read in the console's code page. Plain ASCII reads the same in all
    of them. Anything else (an umlaut in a filename, a 2-theta in a title) is
    written as UTF-8 behind `chcp 65001`, which reads correctly whatever page the
    console had; an OEM-encoded file did not, once a console was already UTF-8.
"""

import os
import re
import shutil
import stat
import sys
from datetime import datetime
from pathlib import Path

from .progname import prog_name

RUN_RE = re.compile(r'^run(\d+)(_s)?\.(?:bat|sh)$', re.IGNORECASE)

# Characters that make an argument need quotes in a .bat line. Commas, semicolons
# and equals signs split arguments only for batch labels and %1-style parameters,
# not for a program's command line, so `-m 20,40,10` stays readable unquoted.
_CMD_SPECIAL = set(' \t"&|<>^()')


def add_document_argument(parser):
	"""Attach the shared -d/--document flag. -d was checked free in all five tools."""
	parser.add_argument('-d', '--document', action='store_true',
	                    help='Also write this command to run<N>.bat in the current '
	                         'directory (run<N>_s.bat when it saves silently), so '
	                         'the plot can be redrawn later with a double-click. '
	                         '-d itself is left out of the file.')


# ------------------------------------------------------------------ argv

def _looks_like_value(parser, token):
	"""Whether argparse would read `token` as a value rather than as options.

	Mirrors argparse's own test: no prefix character, a negative number, or a
	space inside. Needed so a title like "-d spacing" is never taken apart."""
	if not token or token[0] not in parser.prefix_chars:
		return True
	if ' ' in token:
		return True
	return bool(parser._negative_number_matcher.match(token)) and \
	       not parser._has_negative_number_optionals


def without_document_flag(parser, argv):
	"""`argv` with every spelling of -d removed.

	If -d stayed in, running the .bat would write another .bat. argparse accepts
	more spellings than the two in the help: an abbreviated `--doc`, and -d inside
	a cluster of short flags (`-sd`). The cluster is only taken apart while each
	letter is a flag without a value -- in `-xd`, the d is -x's argument."""
	actions = parser._option_string_actions
	doc = actions.get('-d')
	if doc is None:
		return list(argv)
	longs = [o for o in actions if o.startswith('--')]

	out = []
	for i, tok in enumerate(argv):
		if tok == '--':
			out.extend(argv[i:])      # everything after is positional, as given
			break
		if _looks_like_value(parser, tok):
			out.append(tok)
			continue
		if tok.startswith('--'):
			if actions.get(tok) is doc:
				continue
			hits = {actions[o] for o in longs if o.startswith(tok)}
			if parser.allow_abbrev and hits == {doc}:
				continue
			out.append(tok)
			continue
		if tok in actions or len(tok) <= 2:
			if actions.get(tok) is not doc:
				out.append(tok)
			continue
		kept = ''
		for j, ch in enumerate(tok[1:], start=1):
			action = actions.get(tok[0] + ch)
			if action is doc:
				continue
			kept += ch
			if action is None or action.nargs != 0:
				kept += tok[j + 1:]
				break
		if kept:
			out.append(tok[0] + kept)
	return out


# ------------------------------------------------------------------ quoting

def _msvcrt_quote(arg):
	"""Wrap `arg` in double quotes the way the C runtime parses them back.

	Backslashes are literal except before a quote, so a run of them is doubled
	only where a quote follows -- including the closing one. The same rules as
	subprocess.list2cmdline, which only quotes on whitespace and so cannot be used
	for an argument whose only problem is a bracket."""
	out = ['"']
	slashes = 0
	for ch in arg:
		if ch == '\\':
			slashes += 1
			continue
		if ch == '"':
			out.append('\\' * (slashes * 2 + 1) + '"')
		else:
			out.append('\\' * slashes + ch)
		slashes = 0
	out.append('\\' * (slashes * 2) + '"')
	return ''.join(out)


def bat_argument(arg, via_call=False):
	"""One argument as it must be written on a .bat line.

	CALL doubles every caret, and one inside quotes stays doubled, so under CALL
	an argument whose only special character is a caret goes unquoted instead.
	Unquoted, a caret is halved by this line, doubled by CALL, halved again as
	CALL re-reads it, and halved once more when the alias shim expands %* -- so
	one caret is written as four. A caret alongside a space, under CALL, and a
	`"` followed by `&` -- which flips cmd's idea of what is quoted -- are the
	cases left unhandled; neither turns up in a plotting command."""
	special = set(arg) & _CMD_SPECIAL
	if arg and not special:
		text = arg
	elif via_call and special == {'^'}:
		text = arg.replace('^', '^^^^')
	else:
		text = _msvcrt_quote(arg)
	return text.replace('%', '%%%%' if via_call else '%%')


def _sh_quote(arg):
	import shlex
	return shlex.quote(arg)


# ------------------------------------------------------------------ the file

def _command(fallback, module):
	"""The command to write, as (tokens, is_batch_script).

	The name typed -- pp, or an alias -- is kept when it is still on PATH, so the
	file reads the way the command was typed. Otherwise the interpreter and module
	are spelled out, which is what `python -m achdiff.tools.plotter` needs."""
	name = prog_name(fallback)
	found = shutil.which(name)
	if found:
		return [name], Path(found).suffix.lower() in ('.cmd', '.bat')
	return [sys.executable, '-m', module], False


def next_run_path(directory='.', silent=False, suffix=None):
	"""The first unused run<N>[_s] path: one past the highest N present."""
	suffix = suffix or ('.bat' if os.name == 'nt' else '.sh')
	directory = Path(directory)
	highest = 0
	for entry in directory.iterdir():
		m = RUN_RE.match(entry.name)
		if m:
			highest = max(highest, int(m.group(1)))
	return directory / f'run{highest + 1}{"_s" if silent else ""}{suffix}'


def render_bat(command, args, via_call, stamp):
	line = ' '.join([bat_argument(t) for t in command]
	                + [bat_argument(a, via_call) for a in args])
	if via_call:
		line = 'call ' + line
	lines = ['@echo off', f'rem {stamp}']
	if not line.isascii():
		lines.append('chcp 65001 >nul')
	lines += [
		# The directory the file sits in, not whichever one it was started from,
		# so a double-click in Explorer and `..\run3.bat` both redraw the same plot.
		'cd /d "%~dp0"',
		line,
		# A silent run that fails would otherwise close its window before anyone
		# read why.
		'if errorlevel 1 pause',
	]
	return '\r\n'.join(lines) + '\r\n'


def render_sh(command, args, stamp):
	line = ' '.join(_sh_quote(t) for t in command + list(args))
	return '\n'.join(['#!/bin/sh', f'# {stamp}',
	                  'cd "$(dirname "$0")" || exit 1', line]) + '\n'


def write_run_file(parser, fallback, module, silent=False, argv=None, directory='.'):
	"""Write run<N>[_s].bat for this invocation. Returns the path, or None.

	`fallback` is the tool's own command name and `module` its module, for when
	the name typed is not on PATH. Call it once the arguments have parsed, so a
	typo or -h leaves no file behind. A failure to write is reported, never
	raised: the plot is the job, the record of it is a courtesy.
	"""
	argv = list(sys.argv[1:] if argv is None else argv)
	args = without_document_flag(parser, argv)
	command, via_call = _command(fallback, module)
	stamp = f'{" ".join(command)} -d, {datetime.now():%Y-%m-%d %H:%M}'

	is_bat = os.name == 'nt'
	body = (render_bat(command, args, via_call, stamp) if is_bat
	        else render_sh(command, args, stamp))
	encoding = 'ascii' if body.isascii() else 'utf-8'

	for _ in range(100):      # another run may take the same number between look and write
		path = next_run_path(directory, silent)
		try:
			with open(path, 'x', encoding=encoding, newline='') as fh:
				fh.write(body)
			break
		except FileExistsError:
			continue
		except OSError as e:
			print(f'[!] -d: could not write {path.name}: {e}')
			return None
	else:
		print('[!] -d: could not find a free run<N> name.')
		return None

	if not is_bat:
		path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
	print(f'[+] Recorded this command as {path.name}')
	return path
