import zlib

from luminasnake_pc.protocol import cobs_decode, cobs_encode


def test_crc_matches_standard_vector():
    assert zlib.crc32(b"123456789") & 0xFFFFFFFF == 0xCBF43926


def test_cobs_254_nonzero_boundary():
    payload = bytes((index % 254) + 1 for index in range(254))
    assert cobs_decode(cobs_encode(payload)) == payload
