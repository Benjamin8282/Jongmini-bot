import hashlib


def get_passphrase() -> str:
    parts = [
        b"\x6a\x6f\x6e\x67",  # byte fragments
        b"\x6d\x69\x6e\x69",
        b"\x3a\x65\x78\x70",
        b"\x6f\x72\x74\x3a",
        b"\x65\x64\x32\x35",
        b"\x35\x31\x39\x3a",
        b"\x32\x30\x32\x36",
    ]
    seed = b"".join(parts)
    return hashlib.blake2s(seed, digest_size=16).hexdigest()
