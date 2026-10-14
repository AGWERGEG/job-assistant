"""Version and fixed extension identity read from the shipped manifest."""

import base64
import hashlib
import json
from pathlib import Path


_MANIFEST = json.loads((Path(__file__).resolve().parents[1] / "extension" / "manifest.json")
                       .read_text(encoding="utf-8"))
VERSION = str(_MANIFEST.get("version_name") or _MANIFEST["version"])
EXTENSION_VERSION = str(_MANIFEST["version"])
EXTENSION_NAME = str(_MANIFEST["name"])


def _extension_id(public_key):
    if not isinstance(public_key, str) or not public_key:
        raise ValueError("extension manifest must include a public key")
    try:
        der = base64.b64decode(public_key, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("extension manifest public key is invalid") from exc
    # Chrome derives a stable extension ID from the first 16 bytes of the
    # SHA-256 digest of the manifest's DER-encoded public key.
    digest = hashlib.sha256(der).digest()[:16]
    return "".join(chr(ord("a") + nibble)
                   for byte in digest for nibble in (byte >> 4, byte & 15))


EXTENSION_ID = _extension_id(_MANIFEST.get("key"))


def is_extension_origin(origin):
    """Match only the exact Chrome extension origin shipped by this project."""
    return isinstance(origin, str) and origin == f"chrome-extension://{EXTENSION_ID}"
