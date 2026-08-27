from __future__ import annotations

import base64
import binascii
import re
import struct
import zlib
from typing import Never

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}
PNG_HEADER_LENGTH = 13
PNG_BIT_DEPTH = 8
PNG_MAX_FILTER = 4


def _fail(kind: str, detail: str) -> Never:
    message = f"invalid {kind}: {detail}"
    raise ValueError(message)


def _png_chunks(data: bytes) -> tuple[bytes, bytes]:
    if not data.startswith(PNG_SIGNATURE):
        _fail("PNG", "missing signature")
    position = len(PNG_SIGNATURE)
    header = None
    compressed = bytearray()
    ended = False
    while position < len(data):
        if position + 12 > len(data):
            _fail("PNG", "truncated chunk header")
        length = struct.unpack(">I", data[position : position + 4])[0]
        kind = data[position + 4 : position + 8]
        end = position + 12 + length
        if end > len(data):
            _fail("PNG", f"truncated {kind.decode(errors='replace')} chunk")
        payload = data[position + 8 : position + 8 + length]
        expected_crc = struct.unpack(">I", data[position + 8 + length : end])[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected_crc:
            _fail("PNG", f"bad {kind.decode(errors='replace')} checksum")
        if kind == b"IHDR":
            if position != len(PNG_SIGNATURE) or length != PNG_HEADER_LENGTH:
                _fail("PNG", "invalid IHDR")
            header = payload
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            if length != 0 or end != len(data):
                _fail("PNG", "invalid IEND")
            ended = True
        position = end
    if header is None or not compressed or not ended:
        _fail("PNG", "missing required chunk")
    return header, bytes(compressed)


def _validate_png(data: bytes) -> None:
    header, compressed = _png_chunks(data)
    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", header)
    channels = PNG_CHANNELS.get(color_type)
    if width < 1 or height < 1 or bit_depth != PNG_BIT_DEPTH or channels is None or compression != 0 or filtering != 0 or interlace != 0:
        _fail("PNG", "fixture must use non-interlaced 8-bit grayscale, RGB, grayscale-alpha, or RGBA pixels")
    try:
        pixels = zlib.decompress(compressed)
    except zlib.error as error:
        message = "invalid PNG: invalid compressed pixels"
        raise ValueError(message) from error
    row_size = width * channels + 1
    if len(pixels) != height * row_size:
        _fail("PNG", "pixel data does not match dimensions")
    if any(pixels[offset] > PNG_MAX_FILTER for offset in range(0, len(pixels), row_size)):
        _fail("PNG", "invalid scanline filter")


def _validate_pdf(data: bytes) -> None:
    if not data.startswith(b"%PDF-"):
        _fail("PDF", "missing header")
    match = re.search(rb"startxref\s+(\d+)\s+%%EOF\s*$", data)
    if match is None:
        _fail("PDF", "missing final cross-reference pointer")
    xref = int(match.group(1))
    if xref >= len(data) or not data[xref:].startswith(b"xref"):
        _fail("PDF", "invalid cross-reference pointer")
    for required in (b"/Type /Catalog", b"/Type /Page", b"trailer"):
        if required not in data:
            _fail("PDF", f"missing {required.decode()}")


def validate_inline_media(media_type: str, encoded: str) -> None:
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        message = "invalid base64 media data"
        raise ValueError(message) from error
    if media_type == "image/png":
        _validate_png(data)
    elif media_type == "application/pdf":
        _validate_pdf(data)
    else:
        message = f"no fixture validator for {media_type}"
        raise ValueError(message)
