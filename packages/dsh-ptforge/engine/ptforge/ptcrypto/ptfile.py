"""Codec for the Cisco Packet Tracer ``.pkt`` / ``.pka`` container.

Pipeline (observed on Packet Tracer 8.1.1):

    bytes
      -> stage-1 deobfuscation  (reverse byte order, XOR mask (L - i*L) & 0xFF)
      -> Twofish-128 (key = 16 * 0x89) in EAX mode (nonce = 16 * 0x10, 16-byte tag)
      -> stage-2 deobfuscation  (XOR mask (L - i) & 0xFF)
      -> Qt qCompress payload   (big-endian u32 raw size + zlib stream)
      -> UTF-8 XML document

``encode`` is the exact inverse, so a decoded file re-encodes byte-identically
for the same plaintext, which lets us round-trip safely.
"""

from __future__ import annotations

import struct
import zlib

from .eax import EAX
from .twofish import Twofish

# Packet Tracer 8.x fixed parameters.
_KEY = bytes([0x89]) * 16
_NONCE = bytes([0x10]) * 16
_TAG_SIZE = 16

__all__ = [
    "PacketTracerFormatError",
    "deobfuscate_stage1",
    "deobfuscate_stage2",
    "obfuscate_stage2",
    "obfuscate_stage1",
    "uncompress_qt",
    "compress_qt",
    "decode_container",
    "encode_container",
    "looks_like_pkt",
]


class PacketTracerFormatError(ValueError):
    """Raised when a container cannot be decoded with the known PT format."""


def _mask_stage1(size: int, index: int) -> int:
    return (size - index * size) & 0xFF


def deobfuscate_stage1(data: bytes) -> bytes:
    """Undo the outer byte shuffle/XOR layer."""
    size = len(data)
    return bytes(data[size - 1 - i] ^ _mask_stage1(size, i) for i in range(size))


def obfuscate_stage1(data: bytes) -> bytes:
    """Inverse of :func:`deobfuscate_stage1`."""
    size = len(data)
    out = bytearray(size)
    for i in range(size):
        out[size - 1 - i] = data[i] ^ _mask_stage1(size, i)
    return bytes(out)


def _mask_stage2(size: int, index: int) -> int:
    return (size - index) & 0xFF


def deobfuscate_stage2(data: bytes) -> bytes:
    """Undo the inner XOR layer applied after decryption."""
    size = len(data)
    return bytes(b ^ _mask_stage2(size, i) for i, b in enumerate(data))


obfuscate_stage2 = deobfuscate_stage2  # XOR layer is its own inverse


def uncompress_qt(blob: bytes) -> bytes:
    """Decode a Qt ``qCompress`` payload (u32 BE size prefix + zlib stream)."""
    if len(blob) < 5:
        raise PacketTracerFormatError("compressed payload too short")
    (size,) = struct.unpack(">I", blob[:4])
    try:
        raw = zlib.decompress(blob[4:])
    except zlib.error as exc:  # pragma: no cover - surfaced as format error
        raise PacketTracerFormatError(f"zlib stream invalid: {exc}") from exc
    if size > len(raw):
        raise PacketTracerFormatError(
            f"declared size {size} exceeds decompressed size {len(raw)}"
        )
    return raw[:size]


def compress_qt(raw: bytes) -> bytes:
    """Encode a Qt ``qCompress`` payload.

    Packet Tracer compresses with Qt's default zlib level (6); using level 9
    produces a smaller but *foreign* stream that Packet Tracer 8.1 rejects as
    an invalid file, so the level is pinned to reproduce PT's own output.
    """
    return struct.pack(">I", len(raw)) + zlib.compress(raw, 6)


def _twofish() -> Twofish:
    return Twofish(_KEY)


def decode_container(data: bytes) -> bytes:
    """Decrypt and decompress a ``.pkt`` payload, returning the XML bytes."""
    if len(data) <= _TAG_SIZE:
        raise PacketTracerFormatError("file too short to be a Packet Tracer save")

    stage1 = deobfuscate_stage1(data)
    ciphertext, tag = stage1[:-_TAG_SIZE], stage1[-_TAG_SIZE:]

    eax = EAX(_twofish().encrypt)
    try:
        plaintext = eax.decrypt(nonce=_NONCE, ciphertext=ciphertext, tag=tag)
    except ValueError as exc:
        raise PacketTracerFormatError(
            "EAX authentication failed - not a PT 7.x/8.x container, "
            "or the fixed key/nonce has changed"
        ) from exc

    return uncompress_qt(deobfuscate_stage2(plaintext))


def encode_container(xml: bytes) -> bytes:
    """Compress and encrypt an XML document into ``.pkt`` container bytes."""
    payload = compress_qt(xml)
    eax = EAX(_twofish().encrypt)
    ciphertext, tag = eax.encrypt(nonce=_NONCE, plaintext=deobfuscate_stage2(payload))
    return obfuscate_stage1(ciphertext + tag)


def looks_like_pkt(data: bytes) -> bool:
    """Cheap structural probe (no decryption attempt)."""
    if not 32 < len(data) < 64 * 1024 * 1024:
        return False
    # A valid container is always a multiple of... nothing in particular, so we
    # only rule out obvious non-containers: ZIP ('PK'), XML ('<?'/'<PA') and
    # plain text.
    head = data[:2]
    if head in (b"PK", b"\x1f\x8b", b"<?"):
        return False
    if all(32 <= b < 127 for b in data[:16]):
        return False
    return True


def decode(path: "str | Path") -> "ET.Element":
    """Read a ``.pkt`` file and return its parsed XML root element."""
    import xml.etree.ElementTree as ET
    from pathlib import Path

    return ET.fromstring(decode_container(Path(path).read_bytes()))


def encode(root: "ET.Element", path: "str | Path") -> "Path":
    """Serialise *root* into a ``.pkt`` file at *path*."""
    import xml.etree.ElementTree as ET
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_container(ET.tostring(root, encoding="utf-8")))
    return path
