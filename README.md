# Base32 Geohash Encoder

A small, dependency-free library for encoding and decoding geographic coordinates as Base32 geohash strings, using the standard geohash.org alphabet (`0-9b-z`, skipping `a`, `i`, `l`, `o`).

```python
from base32_geohash_encoder import encode, decode

h = encode(48.137, 11.575, precision=10)   # -> "u2818y0e4p"
lat_min, lon_min, lat_max, lon_max = decode(h)
```

The bit-level API is also exported for callers that want the raw interleaved integer:

```python
from base32_geohash_encoder import encode_bits, decode_bits

bits = encode_bits(48.137, 11.575, precision=10)
lat_min, lon_min, lat_max, lon_max = decode_bits(bits, precision=10)
```

Exported names: `encode`, `decode`, `encode_bits`, `decode_bits`, `BASE32_ALPHABET`.

## Why this exists

Geohashing is a common requirement for map tiling and proximity bucketing, but pulling in a full geospatial stack to get a 30-line encoder is overkill. This library implements only the Base32 variant geohash.org uses, with no transitive dependencies and no C extensions, so it can be vendored into a constrained environment or a lambda layer without review concerns.

The trade-off: `decode` returns the bounding box (lower-left and upper-right edges) rather than a representative point. The lower edges are exact; the upper edges are derived by adding one cell width. Callers that want a "centre" should average the two edges themselves. This keeps decode free of the floating-point midpoint error that accumulates when you try to be clever about the centre, and it makes round-tripping deterministic.

## The awkward edge

The geohash alphabet deliberately omits `a`, `i`, `l`, `o` because they are visually confusable with other characters. Real-world geohash strings are frequently copied by humans who normalise those letters anyway. This library accepts lowercase `a`, `i`, `l`, `o` on decode and maps them to `b`, `j`, `m`, `p` respectively. Uppercase letters are rejected, so a stray `S` will raise `ValueError` rather than silently being treated as `s`. If you need strict alphabet validation, filter your input before calling `decode`.

Latitude is clamped to `[-90, 90]` and longitude to `[-180, 180]` on encode, rather than raising. This means a point at `180.000000001` hashes identically to `180.0`. If you need to detect out-of-range input, validate before encoding.

Beyond roughly 12 characters of precision, float64 cannot distinguish adjacent cells, so round-tripping is not guaranteed. The library does not enforce a precision cap, but the README documents the limit.

## Design notes

The window stores values eagerly rather than keeping running aggregates. Running
sums drift with floating point over long streams, and recomputing from a small
buffer is cheap enough that the drift is not worth the speed.

## Limitations

Values are coerced to floats, so very large integers lose precision. If you need
exact integer aggregates over a window, this is the wrong tool.

