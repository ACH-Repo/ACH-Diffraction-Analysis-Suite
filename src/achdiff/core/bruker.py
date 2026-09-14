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

RAW4.00
-------
The generation DIFFRAC.SUITE writes, and what ``BrmlToV4Converter`` produces
from a ``.brml``. Unrelated to RAW1.01 beyond the magic, and a structure of
length-prefixed records rather than fixed offsets::

    byte    0  : "RAW4.00"                    magic
    byte   56  : uint32  total length of the metadata records below
    byte   61  : metadata records, each [uint32 type][uint32 length][...]
                   type 10 = key/value: 24-byte NUL-padded key at +12,
                             value from +36 to the record's end
                   type 30 = source: wavelengths and anode
    61 + meta  : the first scan range

A range is a 160-byte header, then sub-records, then the data::

    +32   char[24] scan type, e.g. "Locked Coupled"
    +72   double   start of the scan's driving axis
    +80   double   step size
    +88   uint32   number of points N
    +136  uint32   bytes per data point (4: float32)
    +140  uint32   total length of the sub-records that follow the header
    +160           sub-records; type 50 describes one axis: uint32 id at +8,
                   name at +12 ("2Theta", "Theta", ...), double start at +56
                   N x float32 intensities, after the sub-records

Validated the same way as RAW1.01, but more widely: 37 RAW4 files with an
independent copy of the same scan beside them -- four ``.brml`` originals and
thirty-three ``.xy`` + ``.dat`` exports. Every intensity matched exactly, and
2theta agreed within each reference's own rounding (the ``.xy`` files carry
five decimals, the ``.brml`` four).

Where RAW4 has the same trap, it is handled explicitly rather than by
position: the 2theta start is taken from the range's own "2Theta" axis record,
not from +72, which holds the start of whatever axis drives the scan. For a
coupled scan the two are the same number -- they were in all 38 files seen --
and if they ever differ, the scan does not step in 2theta and is refused
rather than drawn on the wrong axis.

Everything seen so far came from one converter, all single-range and all
"Locked Coupled". Other scan types are read with a warning that they have not
been checked against a reference, and multi-range handling follows the layout
rather than an observed file.
"""

import struct
from pathlib import Path

import numpy as np


RAW_FILE_HEADER = 712     # bytes before the first range header
_RH_NSTEPS = 4            # int32   step count
_RH_START_2THETA = 16     # double  2theta start (NOT +8, which is theta)
_RH_STEP = 176            # double  step size


def read_raw(path, verbose=False):
    """Read a Bruker ``.raw`` (RAW1.01 or RAW4.00) scan natively.

    Returns ``(two_theta, intensity)`` as float64 arrays. Only the first range
    is returned, which is the norm for a single powder scan; a file with more
    ranges reports how many it skipped when ``verbose`` is set.

    Raises ``ValueError`` with an actionable message for unsupported RAW
    variants (RAW2/RAW3 and the ancient DIFFRAC-AT formats), which still need
    PowDLL or TOPAS to convert.
    """
    raw = Path(path).read_bytes()
    n = len(raw)

    if raw[:7] == b'RAW4.00':
        return read_raw4(raw, Path(path).name, verbose=verbose)

    if raw[:7] not in (b'RAW1.01', b'RAW1.02'):
        raise ValueError(
            f'{Path(path).name}: unsupported Bruker RAW variant '
            f'(file starts with {raw[:4]!r}). RAW1.01 and RAW4.00 are read natively; '
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


# ------------------------------------------------------------------- RAW4.00

RAW4_FILE_HEADER = 61      # bytes before the first metadata record
_R4_META_LENGTH = 56       # uint32  total length of the metadata records
RAW4_RANGE_HEADER = 160    # bytes in a range header, before its sub-records
_R4_SCAN_TYPE = 32         # char[24]
_R4_START = 72             # double  start of the driving axis
_R4_STEP = 80              # double
_R4_NPOINTS = 88           # uint32
_R4_DATUM = 136            # uint32  bytes per point
_R4_EXTRA = 140            # uint32  length of the sub-records after the header
_R4_KEYVALUE = 10          # record type
_R4_AXIS = 50              # sub-record type
_R4_COUPLED = 'Locked Coupled'


def _u32(raw, offset, name):
    if offset + 4 > len(raw):
        raise ValueError(f'{name}: RAW4 file truncated (needed bytes {offset}-{offset + 4}).')
    return struct.unpack_from('<I', raw, offset)[0]


def _f64(raw, offset, name):
    if offset + 8 > len(raw):
        raise ValueError(f'{name}: RAW4 file truncated (needed bytes {offset}-{offset + 8}).')
    return struct.unpack_from('<d', raw, offset)[0]


def _raw4_records(raw, start, end):
    """Walk length-prefixed records between `start` and `end`: [(type, offset, length)].

    Stops quietly at a record that does not fit rather than raising. These records
    carry metadata and axis descriptions that the data itself does not depend on,
    so a record this reader cannot make sense of is a reason to know less about the
    scan, not a reason to refuse a file whose data block checks out.
    """
    out = []
    pos = start
    while pos + 8 <= end:
        rtype = struct.unpack_from('<I', raw, pos)[0]
        length = struct.unpack_from('<I', raw, pos + 4)[0]
        if length < 8 or pos + length > end:
            break
        out.append((rtype, pos, length))
        pos += length
    return out


def raw4_metadata(raw):
    """The key/value metadata of a RAW4 file, e.g. {'SAMPLEID': 'CN-empty-ref'}."""
    end = RAW4_FILE_HEADER + struct.unpack_from('<I', raw, _R4_META_LENGTH)[0]
    meta = {}
    for rtype, pos, length in _raw4_records(raw, RAW4_FILE_HEADER, min(end, len(raw))):
        if rtype == _R4_KEYVALUE and length >= 36:
            key = raw[pos + 12:pos + 36].split(b'\0')[0].decode('latin-1')
            meta[key] = raw[pos + 36:pos + length].decode('latin-1')
    return meta


def _raw4_range(raw, pos, name):
    """Read one range starting at `pos`. Returns a dict; raises ValueError if unusable."""
    if pos + RAW4_RANGE_HEADER > len(raw):
        raise ValueError(f'{name}: RAW4 file truncated inside a range header.')

    n_points = _u32(raw, pos + _R4_NPOINTS, name)
    datum = _u32(raw, pos + _R4_DATUM, name)
    extra = _u32(raw, pos + _R4_EXTRA, name)
    start = _f64(raw, pos + _R4_START, name)
    step = _f64(raw, pos + _R4_STEP, name)
    scan_type = raw[pos + _R4_SCAN_TYPE:pos + _R4_SCAN_TYPE + 24].split(b'\0')[0].decode('latin-1')

    if not (0 < n_points < 10 ** 7):
        raise ValueError(f'{name}: implausible RAW4 point count ({n_points}).')
    if datum != 4:
        # Every file seen stores float32. A different width would need a different
        # dtype, and guessing one silently turns the pattern into noise.
        raise ValueError(f'{name}: RAW4 stores {datum} bytes per point; only 4 (float32) '
                         'is understood. Convert with PowDLL or TOPAS.')
    if not (np.isfinite(step) and 0 < abs(step) < 100):
        raise ValueError(f'{name}: implausible RAW4 step size ({step}).')
    if not np.isfinite(start):
        raise ValueError(f'{name}: RAW4 start angle is not a number.')

    data_off = pos + RAW4_RANGE_HEADER + extra
    data_end = data_off + n_points * datum
    if data_end > len(raw):
        raise ValueError(f'{name}: RAW4 data block runs past the end of the file '
                         f'(need {n_points * datum} bytes at {data_off}, file is {len(raw)}).')

    two_theta = None
    for rtype, rpos, length in _raw4_records(raw, pos + RAW4_RANGE_HEADER, data_off):
        if rtype == _R4_AXIS and length >= 64:
            axis = raw[rpos + 12:rpos + 56].split(b'\0')[0].decode('latin-1')
            if axis == '2Theta':
                two_theta = struct.unpack_from('<d', raw, rpos + 56)[0]
                break

    if two_theta is not None:
        if abs(two_theta - start) > 1e-6:
            # The driving axis is not 2theta, so the step is not a 2theta step
            # either. Drawing it would give a plausible-looking pattern on the
            # wrong axis, which is the one failure worse than refusing.
            raise ValueError(
                f'{name}: this "{scan_type}" scan does not step in 2theta (its 2Theta '
                f'axis starts at {two_theta:g} but the scan starts at {start:g}). '
                'Only scans driven in 2theta can be read as a powder pattern.')
        start = two_theta
    elif scan_type != _R4_COUPLED:
        raise ValueError(
            f'{name}: RAW4 "{scan_type}" scan has no 2Theta axis record, so its x axis '
            'cannot be identified. Convert with PowDLL or TOPAS.')

    y = np.frombuffer(raw, dtype='<f4', count=n_points, offset=data_off).astype(float)
    x = start + step * np.arange(n_points)
    return {'x': x, 'y': y, 'end': data_end, 'scan_type': scan_type, 'step': step}


def read_raw4(raw, name='file', verbose=False):
    """Read a RAW4.00 scan from its bytes. Returns ``(two_theta, intensity)``.

    Only the first range is returned, as for RAW1.01. Called through `read_raw`,
    which dispatches on the magic; exposed separately so it can be tested on bytes.
    """
    if len(raw) < RAW4_FILE_HEADER or raw[:7] != b'RAW4.00':
        raise ValueError(f'{name}: not a RAW4.00 file.')

    first_range = RAW4_FILE_HEADER + _u32(raw, _R4_META_LENGTH, name)
    if first_range + RAW4_RANGE_HEADER > len(raw):
        raise ValueError(f'{name}: RAW4 metadata length ({first_range - RAW4_FILE_HEADER} bytes) '
                         'runs past the first scan range.')

    first = _raw4_range(raw, first_range, name)

    if first['scan_type'] != _R4_COUPLED:
        print(f'[!] {name}: RAW4 "{first["scan_type"]}" scan. Only "{_R4_COUPLED}" scans have '
              'been checked against a reference export; check this one against one.')

    # Count what else is in the file, for the same note RAW1.01 gives. A later
    # range that cannot be read does not cost the first, which already checked out.
    ranges, pos = 1, first['end']
    while pos + RAW4_RANGE_HEADER <= len(raw):
        try:
            pos = _raw4_range(raw, pos, name)['end']
        except ValueError:
            break
        ranges += 1

    if verbose:
        meta = raw4_metadata(raw)
        sample = meta.get('SAMPLEID')
        x = first['x']
        print(f'    .raw RAW4.00: {len(x)} steps, 2theta {x[0]:.3f}..{x[-1]:.3f} deg, '
              f'step {first["step"]:g}' + (f', sample "{sample}"' if sample else ''))
    if ranges > 1:
        print(f'[!] {name}: {ranges} ranges in file; reading only the first.')

    return first['x'], first['y']
