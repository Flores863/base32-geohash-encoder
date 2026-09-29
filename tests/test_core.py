import math
import unittest

from base32_geohash_encoder import (
    BASE32_ALPHABET,
    decode,
    decode_bits,
    encode,
    encode_bits,
)


class TestAlphabet(unittest.TestCase):
    def test_alphabet_length_and_exclusions(self):
        self.assertEqual(len(BASE32_ALPHABET), 32)
        for ch in "ailo":
            self.assertNotIn(ch, BASE32_ALPHABET)
        self.assertEqual(BASE32_ALPHABET[0], "0")
        self.assertEqual(BASE32_ALPHABET[-1], "z")


class TestEncodeDecodeRoundTrip(unittest.TestCase):
    def test_known_geohash(self):
        # "u4pruydqqvj" is the canonical geohash for a well-known point;
        # we decode it and re-encode at the same precision and expect a
        # stable string. The exact centre is not asserted because decode
        # returns a bounding box, not a point.
        h = "u4pruydqqvj"
        lat_min, lon_min, lat_max, lon_max = decode(h)
        self.assertLess(lat_min, lat_max)
        self.assertLess(lon_min, lon_max)
        # Re-encoding the box centre must reproduce the hash at precision 11.
        lat_c = (lat_min + lat_max) / 2
        lon_c = (lon_min + lon_max) / 2
        self.assertEqual(encode(lat_c, lon_c, 11), h)

    def test_origin_round_trips(self):
        h = encode(0.0, 0.0, 8)
        self.assertEqual(h, "s0000000")
        lat_min, lon_min, lat_max, lon_max = decode(h)
        self.assertLessEqual(lat_min, 0.0)
        self.assertGreaterEqual(lat_max, 0.0)
        self.assertLessEqual(lon_min, 0.0)
        self.assertGreaterEqual(lon_max, 0.0)

    def test_north_pole_bucket(self):
        # Latitude 90 must clamp rather than reject.
        h = encode(90.0, 0.0, 6)
        lat_min, lon_min, lat_max, _ = decode(h)
        self.assertGreater(lat_max, 89.0)
        self.assertLessEqual(lat_min, 90.0)

    def test_south_pole_bucket(self):
        h = encode(-90.0, 0.0, 6)
        lat_min, _, lat_max, _ = decode(h)
        self.assertLessEqual(lat_min, -89.0)
        self.assertGreaterEqual(lat_max, -90.0)

    def test_antimeridian_clamp(self):
        h_low = encode(0.0, 179.999999999, 8)
        h_high = encode(0.0, 180.0, 8)
        self.assertEqual(h_low, h_high)


class TestBitsApi(unittest.TestCase):
    def test_zero_precision(self):
        self.assertEqual(encode_bits(10.0, 20.0, 0), 0)
        self.assertEqual(decode_bits(0, 0), (-90.0, -180.0, 90.0, 180.0))

    def test_one_char_bits(self):
        # (0, 0) lies in the positive half of both axes, so with 5 bits
        # (3 lon, 2 lat) the interleaved value is 0b11000 = 24.
        b = encode_bits(0.0, 0.0, 1)
        self.assertEqual(b, 24)
        lat_min, lon_min, lat_max, lon_max = decode_bits(b, 1)
        self.assertEqual(lat_min, 0.0)
        self.assertEqual(lat_max, 45.0)
        self.assertEqual(lon_min, 0.0)
        self.assertEqual(lon_max, 45.0)

    def test_bits_round_trip(self):
        for precision in (1, 5, 8, 12):
            lat, lon = 48.137, 11.575
            b = encode_bits(lat, lon, precision)
            lat_min, lon_min, lat_max, lon_max = decode_bits(b, precision)
            self.assertGreater(lat_max, lat_min)
            self.assertGreater(lon_max, lon_min)
            self.assertGreaterEqual(lat, lat_min - 1e-9)
            self.assertLessEqual(lat, lat_max + 1e-9)
            self.assertGreaterEqual(lon, lon_min - 1e-9)
            self.assertLessEqual(lon, lon_max + 1e-9)

    def test_decode_bits_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            decode_bits(1 << 5, 1)  # 5 bits max value is 31


class TestDecodeValidation(unittest.TestCase):
    def test_empty_string_is_whole_globe(self):
        self.assertEqual(decode(""), (-90.0, -180.0, 90.0, 180.0))

    def test_uppercase_rejected(self):
        with self.assertRaises(ValueError):
            decode("S0000000")

    def test_ambiguous_lowercase_accepted(self):
        # 'a' is not in the alphabet but should map to 'b'.
        h = encode(0.0, 0.0, 8)
        # Replace the first 's'-equivalent char path: construct a hash that
        # uses 'a' where 'b' would be valid and confirm decode accepts it.
        # "b" decodes to bits 11; "a" should decode to the same.
        self.assertEqual(decode("b"), decode("a"))
        self.assertEqual(decode("j"), decode("i"))
        self.assertEqual(decode("m"), decode("l"))
        self.assertEqual(decode("p"), decode("o"))

    def test_non_string_rejected(self):
        with self.assertRaises(TypeError):
            decode(123)
        with self.assertRaises(TypeError):
            decode(None)

    def test_invalid_char_rejected(self):
        with self.assertRaises(ValueError):
            decode("s00!0000")


class TestEncodePrecision(unittest.TestCase):
    def test_negative_precision_rejected(self):
        with self.assertRaises(ValueError):
            encode(0.0, 0.0, -1)
        with self.assertRaises(ValueError):
            encode_bits(0.0, 0.0, -1)

    def test_zero_precision_empty_string(self):
        self.assertEqual(encode(0.0, 0.0, 0), "")

    def test_precision_affects_length(self):
        for p in (1, 2, 6, 10, 12):
            h = encode(10.0, 20.0, p)
            self.assertEqual(len(h), p)

    def test_truncation_increases_box(self):
        lat, lon = 40.7128, -74.0060
        full = encode(lat, lon, 10)
        short = full[:6]
        lat_min_f, lon_min_f, lat_max_f, lon_max_f = decode(full)
        lat_min_s, lon_min_s, lat_max_s, lon_max_s = decode(short)
        self.assertGreater(lat_max_s - lat_min_s, lat_max_f - lat_min_f)
        self.assertGreater(lon_max_s - lon_min_s, lon_max_f - lon_min_f)


class TestBitInterleaving(unittest.TestCase):
    def test_longitude_gets_extra_bit_on_odd_total(self):
        # 1 character -> 5 bits -> 3 lon, 2 lat. Longitude should be split
        # into 8 cells, latitude into 4.
        lat_min, lon_min, lat_max, lon_max = decode_bits(0, 1)
        self.assertAlmostEqual(lon_max - lon_min, 360.0 / 8)
        self.assertAlmostEqual(lat_max - lat_min, 180.0 / 4)

    def test_interleave_split_consistency(self):
        # A value with only the most-significant bit set, precision 2
        # (10 bits), should place the point in the high-longitude half.
        b = 1 << 9  # bit index 0 (MSB) -> longitude
        lat_min, lon_min, lat_max, lon_max = decode_bits(b, 2)
        self.assertGreaterEqual(lon_min, 0.0)
        self.assertLessEqual(lat_min, 0.0)
        self.assertLessEqual(lat_max, 0.0)


if __name__ == "__main__":
    unittest.main()
