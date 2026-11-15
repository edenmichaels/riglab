"""Make the licence-signing keypair. Run ONCE, on the machine that will hold the private key.

    python tools/gen_license_keypair.py

Prints the PUBLIC key (paste into PUBLIC_KEYS in riglab/core/license.py - safe to commit) and the PRIVATE key
(goes ONLY into the licence server's secret settings - never into the repo, a chat or Dropbox).
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key = Ed25519PrivateKey.generate()
raw = serialization.Encoding.Raw
priv = key.private_bytes(raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
pub = key.public_key().public_bytes(raw, serialization.PublicFormat.Raw)
print("PUBLIC  (commit this):      ", base64.b64encode(pub).decode())
print("PRIVATE (server secret only):", base64.b64encode(priv).decode())
