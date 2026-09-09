"""Native readers for Bruker AXS powder-diffraction files.

``.raw`` (DIFFRAC "RAW1.01") is Bruker's own binary scan format. It used to be
read here by shelling out to TOPAS (``tc.exe``) to convert it to ``.xy``, which
made a plain plot depend on a licensed, Windows-only, per-machine install. The
layout below was reverse-engineered from the bytes and cross-checked against a
PowDLL RIET7 ``.dat`` export of the same scan: the 2theta grid and every
intensity match exactly, so the conversion step is no longer needed.

Format (little-endian throughout)::

    byte    0  : "RAW1.01"                    magic
    byte   12  : int32   number of ranges in the file
    byte  712  : start of the first range header

Fields *within* a range header::

    +0    int32   range-header length (typically 304)
    +4    int32   number of steps N
    +8    double  theta / omega start   -- NOT the scan axis (half of 2theta)
    +16   double  2theta start          -- the scan-axis start
    +176  double  step size in 2theta

The float32 intensity array follows the range header, i.e. at
``712 + range_header_length``.

The +8 / +16 distinction is the one real trap: in Bragg-Brentano geometry
theta = 2theta / 2, so reading +8 yields a pattern whose peaks are all at half
their true angle. It still *looks* like a plausible diffractogram, which is
exactly why it has to be checked against a known-good export rather than by eye.
"""

import struct
from pathlib import Path

import numpy as np


RAW_FILE_HEADER = 712     # bytes before the first range header
_RH_NSTEPS = 4            # int32   step count
_RH_START_2THETA = 16     # double  2theta start (NOT +8, which is theta)
_RH_STEP = 176            # double  step size


def read_raw(path, verbose=False):
    """Read a Bruker ``.raw`` (RAW1.01) scan natively.

    Returns ``(two_theta, intensity)`` as float64 arrays. Only the first range
    is returned, which is the norm for a single powder scan; a file with more
    ranges reports how many it skipped when ``verbose`` is set.

    Raises ``ValueError`` with an actionable message for unsupported RAW
    variants (RAW2/RAW3/RAW4 and the ancient DIFFRAC-AT formats), which still
    need PowDLL or TOPAS to convert.
    """
    raw = Path(path).read_bytes()
    n = len(raw)

    if raw[:7] not in (b'RAW1.01', b'RAW1.02'):
        raise ValueError(
            f'{Path(path).name}: unsupported Bruker RAW variant '
            f'(file starts with {raw[:4]!r}). Only RAW1.01 is read natively; '
            'convert other RAW generations with PowDLL or TOPAS first.')

    n_ranges = struct.unpack_from('<i', raw, 12)[0]

    pos = RAW_FILE_HEADER
    if pos + 184 > n:
        raise ValueError(f'{Path(path).name}: file truncated before range header.')

    header_len = struct.unpack_from('<i', raw, pos)[0]
    n_steps = struct.unpack_from('<i', raw, pos + _RH_NSTEPS)[0]
    start_2theta = struct.unpack_from('<d', raw, pos + _RH_START_2THETA)[0]
    step = struct.unpack_from('<d', raw, pos + _RH_STEP)[0]

    if not (0 < n_steps < 10 ** 7) or not (0 < header_len < n):
        raise ValueError(
            f'{Path(path).name}: implausible RAW range header '
            f'(steps={n_steps}, header_len={header_len}).')
    if not (0 < step < 100):
        raise ValueError(
            f'{Path(path).name}: implausible RAW step size ({step}).')

    data_off = pos + header_len
    if data_off + n_steps * 4 > n:
        raise ValueError(
            f'{Path(path).name}: RAW data block runs past end of file '
            f'(need {n_steps * 4} bytes at {data_off}, file is {n}).')

    y = np.frombuffer(raw, dtype='<f4', count=n_steps, offset=data_off).astype(float)
    x = start_2theta + step * np.arange(n_steps)

    if verbose:
        print(f'    .raw RAW1.01: {n_steps} steps, '
              f'2theta {x[0]:.3f}..{x[-1]:.3f} deg, step {step:g}')
    if n_ranges > 1:
        print(f'[!] {Path(path).name}: {n_ranges} ranges in file; '
              'reading only the first.')

    return x, y
