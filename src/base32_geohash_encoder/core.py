"""Core Base32 geohash encoder/decoder.

Uses the standard geohash Base32 alphabet (0-9, b-z, skipping a, i, l, o)
introduced by geohash.org. Coordinates are encoded as a bit-interleaved
prefix: longitude occupies even-indexed bits (0, 2, 4, ...) and latitude
occupies odd-indexed bits (1, 3, 5, ...). This interleaving means that
truncating a hash keeps the bounding box centred on the same point while
degrading precision symmetrically in both dimensions.
"""

from __future__ import annotations

BASE32_ALPHABET = "0123456789bcdefghjkmnpqrstuvwxyz"

# Lookup table maps each character code -> 5-bit value [0, 31].
# Codes that are not part of the alphabet map to -1 so callers can detect
# invalid input without raising during construction.
_DECODE_TABLE = [-1] * 128
for _i, _ch in enumerate(BASE32_ALPHABET):
    _DECODE_TABLE[ord(_ch)] = _i
# Accept the visually ambiguous characters that the alphabet deliberately
# excludes: a/i/l/o. Many real-world geohash strings were copied by humans
# who normalised case and homogenised confusable letters. Rather than force
# every consumer to pre-clean input, we accept and map them to the intended
# symbol. Lowercase only; uppercase is rejected so the error is obvious.
_DECODE_TABLE[ord("a")] = _DECODE_TABLE[ord("b")]
_DECODE_TABLE[ord("i")] = _DECODE_TABLE[ord("j")]
_DECODE_TABLE[ord("l")] = _DECODE_TABLE[ord("m")]
_DECODE_TABLE[ord("o")] = _DECODE_TABLE[ord("p")]
del _i, _ch


def _bits_for_length(length: int) -> int:
    return length * 5


def _split_bits(value: int, total_bits: int) -> tuple[int, int]:
    """Split a bit-interleaved integer into its longitude and latitude halves.

    Even-indexed bits (counting from the most-significant end) go to
    longitude; odd-indexed bits go to latitude. Returns (lon_bits, lat_bits)
    as plain integers whose bit length is ceil(total_bits / 2) for the
    longer half and floor(total_bits / 2) for the shorter.
    """
    if total_bits == 0:
        return 0, 0

    lon_bits = 0
    lat_bits = 0
    # Walk bits from most-significant (index 0) to least-significant.
    for i in range(total_bits):
        bit = (value >> (total_bits - 1 - i)) & 1
        if i % 2 == 0:
            lon_bits = (lon_bits << 1) | bit
        else:
            lat_bits = (lat_bits << 1) | bit
    return lon_bits, lat_bits


def _interleave_bits(lon_bits: int, lat_bits: int, lon_width: int, lat_width: int) -> int:
    """Interleave longitude and latitude bits into a single integer.

    ``lon_width`` and ``lat_width`` describe how many bits each input
    contributes. When they differ, the interleaving still starts with
    longitude at bit index 0 (most significant), so callers should pass
    widths consistent with ``_split_bits``.
    """
    total = lon_width + lat_width
    if total == 0:
        return 0

    out = 0
    lon_remaining = lon_width
    lat_remaining = lat_width
    # Most significant bit first.
    for i in range(total):
        if i % 2 == 0:
            if lon_remaining > 0:
                shift = lon_remaining - 1
                bit = (lon_bits >> shift) & 1
                lon_remaining -= 1
            else:
                bit = 0
        else:
            if lat_remaining > 0:
                shift = lat_remaining - 1
                bit = (lat_bits >> shift) & 1
                lat_remaining -= 1
            else:
                bit = 0
        out = (out << 1) | bit
    return out


def _decode_value(bits: int, bit_count: int, minimum: float, maximum: float) -> float:
    """Map an unsigned ``bit_count``-bit integer into [minimum, maximum].

    The returned value is the lower edge of the cell the bits describe, NOT
    its centre. Decoders that need the centre should average the lower and
    upper edges explicitly; we keep the lower edge here because it is exact
    and free of floating-point midpoint error, which matters for stable
    round-tripping.
    """
    if bit_count == 0:
        return minimum
    span = maximum - minimum
    # Each bit halves the cell width, so a count of n yields 2**n cells.
    divisions = 1 << bit_count
    cell = span / divisions
    return minimum + bits * cell


def _encode_value(value: float, minimum: float, maximum: float, bit_count: int) -> int:
    """Quantise ``value`` into ``bit_count`` bits over [minimum, maximum].

    Clamps out-of-range input to the nearest edge rather than raising; the
    practical use case for geohashing is coarse bucketing, and rejecting
    a point that drifted 1e-12 past the dateline is more annoying than
    bucketing it with its neighbour.
    """
    if bit_count == 0:
        return 0
    span = maximum - minimum
    if value <= minimum:
        return 0
    if value >= maximum:
        return (1 << bit_count) - 1
    divisions = 1 << bit_count
    cell = span / divisions
    return int((value - minimum) // cell)


def encode_bits(lat: float, lon: float, precision: int) -> int:
    """Encode (lat, lon) into an integer holding ``precision * 5`` bits.

    The returned integer has exactly ``precision * 5`` significant bits.
    Latitude is clamped to [-90, 90] and longitude to [-180, 180]; see
    ``_encode_value`` for the rationale.
    """
    if precision < 0:
        raise ValueError("precision must be non-negative")
    total_bits = _bits_for_length(precision)
    if total_bits == 0:
        return 0

    lon_width = (total_bits + 1) // 2
    lat_width = total_bits // 2
    lon_bits = _encode_value(lon, -180.0, 180.0, lon_width)
    lat_bits = _encode_value(lat, -90.0, 90.0, lat_width)
    return _interleave_bits(lon_bits, lat_bits, lon_width, lat_width)


def decode_bits(value: int, precision: int) -> tuple[float, float, float, float]:
    """Decode an integer of ``precision * 5`` bits into a bounding box.

    Returns ``(lat_min, lon_min, lat_max, lon_max)``. The lower edges are
    exact; the upper edges are derived by adding one cell width, which is
    exact for powers-of-two divisions and stable under float arithmetic up
    to roughly 25 bits per axis (after which float64 cannot represent every
    integer exactly and drift accumulates).
    """
    if precision < 0:
        raise ValueError("precision must be non-negative")
    total_bits = _bits_for_length(precision)
    if total_bits == 0:
        return -90.0, -180.0, 90.0, 180.0
    if value < 0 or value >= (1 << total_bits):
        raise ValueError("value out of range for precision")

    lon_width = (total_bits + 1) // 2
    lat_width = total_bits // 2
    lon_bits, lat_bits = _split_bits(value, total_bits)

    lon_min = _decode_value(lon_bits, lon_width, -180.0, 180.0)
    lat_min = _decode_value(lat_bits, lat_width, -90.0, 90.0)

    if lon_width > 0:
        lon_cell = 360.0 / (1 << lon_width)
    else:
        lon_cell = 360.0
    if lat_width > 0:
        lat_cell = 180.0 / (1 << lat_width)
    else:
        lat_cell = 180.0

    return lat_min, lon_min, lat_min + lat_cell, lon_min + lon_cell


def encode(lat: float, lon: float, precision: int = 12) -> str:
    """Encode (lat, lon) into a Base32 geohash string of ``precision`` chars.

    Precision 0 yields the empty string; precisions above 12 are accepted
    but the additional bits exceed what float64 can distinguish, so
    round-tripping beyond ~12 characters is not guaranteed.
    """
    if precision < 0:
        raise ValueError("precision must be non-negative")
    if precision == 0:
        return ""

    value = encode_bits(lat, lon, precision)
    total_bits = _bits_for_length(precision)
    chars = []
    # Pack from the least-significant 5-bit group upward.
    for _ in range(precision):
        chunk = value & 0x1F
        chars.append(BASE32_ALPHABET[chunk])
        value >>= 5
    return "".join(reversed(chars))


def decode(geohash: str) -> tuple[float, float, float, float]:
    """Decode a Base32 geohash into ``(lat_min, lon_min, lat_max, lon_max)``.

    The empty string decodes to the whole globe. Characters outside the
    alphabet (including uppercase letters) raise ``ValueError``. The
    visually-ambiguous lowercase letters a, i, l, o are accepted and mapped
    to b, j, m, p respectively; see ``_DECODE_TABLE``.
    """
    if not isinstance(geohash, str):
        raise TypeError("geohash must be a string")
    if geohash == "":
        return -90.0, -180.0, 90.0, 180.0

    precision = len(geohash)
    total_bits = _bits_for_length(precision)
    value = 0
    for ch in geohash:
        code = ord(ch)
        if code >= 128:
            raise ValueError(f"invalid character in geohash: {ch!r}")
        nibble = _DECODE_TABLE[code]
        if nibble < 0:
            raise ValueError(f"invalid character in geohash: {ch!r}")
        value = (value << 5) | nibble
    # Mask to the declared width so a trailing partial group (which cannot
    # happen when precision is a whole number of characters, but keeps the
    # function self-consistent if reused) does not pollute the result.
    value &= (1 << total_bits) - 1
    return decode_bits(value, precision)
