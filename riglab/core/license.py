"""Offline-first licence checks.

A licence is a small signed token issued by the RigLab licence server when a key is activated:

    <base64url(payload JSON)>.<base64url(Ed25519 signature of those payload bytes)>

It is verified here with a public key built into the app, so no internet is needed at startup.

Rules
  * Anything wrong with the token (missing, edited, wrong PC, expired) means the Free tier - never an error
    screen, never a locked app.
  * Subscription / trial: Pro until ``expires_at``; if the app can't reach the server to refresh, Pro keeps
    working until ``offline_grace_until`` (the server sets this 14 days after ``expires_at``).
  * Lifetime: ``expires_at`` is null - valid offline forever.
  * Safety features (monitoring, temperature alerts, reset to stock, emergency stops) are in ALWAYS_FREE and
    can never be gated; ``has()`` returns True for them whatever the licence says.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

try:  # the app still starts (as Free) if the crypto package is missing from a broken install
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError:  # pragma: no cover
    Ed25519PublicKey = None
    InvalidSignature = Exception

TOKEN_VERSION = 1
GRACE_DAYS = 14
DAY = 86400
CLOCK_SLACK = DAY            # how far the PC clock may go backwards before we stop trusting it

# Public keys of the licence server (base64, 32 bytes each). More than one so a key can be rotated.
# Empty until the server keypair is generated (tools/gen_license_keypair.py) - with no key, everyone is Free.
PUBLIC_KEYS: list[str] = []

PLAN_FREE, PLAN_TRIAL, PLAN_SUB, PLAN_LIFETIME = "free", "trial", "subscription", "lifetime"

# ----------------------------------------------------------------------------- features
# Never behind a paywall. has() is always True for these.
ALWAYS_FREE = frozenset({
    "monitor",            # live sensors + history
    "alerts",             # temperature alerts
    "sysinfo",            # hardware inventory
    "health",             # health check and its fixes
    "reset_stock",        # GPU / OC / fan / lighting reset to stock, RGB off
    "stop",               # stopping a stress test, benchmark or validation run
    "fans_manual",        # manual fan speed + handing fans back to the motherboard
    "restore_point",      # create a Windows restore point
})

# Included in Free, with limits enforced where the feature lives (see FREE_LIMITS).
FREE = frozenset({"fan_curves", "lighting_static", "stress", "bench", "crash_scan"})

# Pro (subscription, lifetime or trial).
PRO = frozenset({
    "gpu_tune",           # apply GPU tuning values + guided validation
    "oc_validate",        # overclock guide validation runs
    "stress_unlimited",   # stress tests longer than the free limit
    "bench_history",      # benchmark history and run-vs-run comparison
    "lighting_fx",        # animated effects, LED mapping, painting, per-game lighting
    "fan_curves_unlimited",
    "overlay",            # in-game overlay
    "logging",            # sensor logging to file + report export
    "crash_analyze",      # crash-dump analysis
    "tweaks",             # Windows tweaks, power plans, startup manager, clean-up
})

FREE_LIMITS = {"fan_curves": 1, "stress_minutes": 10}

assert not (ALWAYS_FREE & PRO) and not (FREE & PRO), "a safety/free feature must never be listed as Pro"


# ----------------------------------------------------------------------------- machine id
def _win_reg(root_path: str, name: str) -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root_path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return ""


def _raw_machine_parts() -> list[str]:
    if sys.platform == "win32":
        bios = r"HARDWARE\DESCRIPTION\System\BIOS"
        return [
            _win_reg(r"SOFTWARE\Microsoft\Cryptography", "MachineGuid"),
            _win_reg(bios, "SystemManufacturer"), _win_reg(bios, "SystemProductName"),
            _win_reg(bios, "BaseBoardManufacturer"), _win_reg(bios, "BaseBoardProduct"),
            _win_reg(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString"),
        ]
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            return [Path(p).read_text().strip()]
        except OSError:
            continue
    import platform
    return [platform.node()]


def machine_id(parts: list[str] | None = None) -> str:
    """Stable id for this PC. Only this one-way hash ever leaves the machine - no serial numbers."""
    parts = _raw_machine_parts() if parts is None else parts
    joined = "\x1f".join(p.strip().lower() for p in parts)
    return hashlib.sha256(b"riglab-machine-v1\x1f" + joined.encode("utf-8")).hexdigest()[:32]


def machine_name() -> str:
    return os.environ.get("COMPUTERNAME") or __import__("platform").node() or "PC"


# ----------------------------------------------------------------------------- token
class LicenseError(Exception):
    """Why a token was rejected (shown in the Account & License screen, never fatal)."""


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_token(token: str, public_keys: list[str] | None = None) -> dict:
    """Check the signature and shape of a token and return its payload. Raises LicenseError."""
    keys = PUBLIC_KEYS if public_keys is None else public_keys
    if Ed25519PublicKey is None or not keys:
        raise LicenseError("licence checking isn't set up in this build")
    try:
        body_b64, sig_b64 = token.strip().split(".")
        body, sig = _b64d(body_b64), _b64d(sig_b64)
    except (ValueError, AttributeError) as e:
        raise LicenseError("the licence file is damaged") from e
    for key in keys:
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(key)).verify(sig, body)
            break
        except (InvalidSignature, ValueError):
            continue
    else:
        raise LicenseError("the licence signature isn't valid")
    try:
        p = json.loads(body)
    except ValueError as e:
        raise LicenseError("the licence file is damaged") from e
    if not isinstance(p, dict) or p.get("v") != TOKEN_VERSION:
        raise LicenseError("this licence needs a newer RigLab")
    if p.get("plan") not in (PLAN_TRIAL, PLAN_SUB, PLAN_LIFETIME):
        raise LicenseError("unknown licence type")
    for k in ("license_id", "machine_id", "issued_at"):
        if not p.get(k):
            raise LicenseError("the licence file is incomplete")
    if p["plan"] != PLAN_LIFETIME and not isinstance(p.get("expires_at"), (int, float)):
        raise LicenseError("the licence file is incomplete")
    return p


@dataclass
class Entitlements:
    plan: str = PLAN_FREE                 # what the user effectively has right now
    status: str = "free"                  # free | active | grace | expired | invalid
    features: frozenset = field(default_factory=lambda: ALWAYS_FREE | FREE)
    license_id: str = ""
    expires_at: float | None = None
    grace_until: float | None = None
    days_left: int | None = None          # days of Pro left (None = no end date)
    message: str = ""

    def has(self, feature: str) -> bool:
        return feature in ALWAYS_FREE or feature in self.features

    def limit(self, name: str):
        """Free-tier limit, or None when the user has Pro."""
        return None if self.plan != PLAN_FREE else FREE_LIMITS.get(name)

    def to_dict(self) -> dict:
        return {"plan": self.plan, "status": self.status, "features": sorted(self.features),
                "license_id": self.license_id, "expires_at": self.expires_at, "grace_until": self.grace_until,
                "days_left": self.days_left, "message": self.message, "limits": dict(FREE_LIMITS) if self.plan == PLAN_FREE else {},
                "pro": self.plan != PLAN_FREE}


def _free(status="free", message="", **kw) -> Entitlements:
    return Entitlements(status=status, message=message, **kw)


def evaluate(token: str | None, *, now: float | None = None, this_machine: str | None = None,
             public_keys: list[str] | None = None, last_seen: float | None = None) -> Entitlements:
    """Turn a stored token into what the user may use right now. Never raises."""
    if not token:
        return _free()
    now = time.time() if now is None else now
    if last_seen and now < last_seen - CLOCK_SLACK:
        now = last_seen                      # clock was wound back: keep counting from the latest time we saw
    try:
        p = verify_token(token, public_keys)
    except LicenseError as e:
        return _free("invalid", str(e))
    lid = str(p["license_id"])
    if p["machine_id"] != (machine_id() if this_machine is None else this_machine):
        return _free("invalid", "this licence was activated on a different PC - activate it again here", license_id=lid)
    if p["issued_at"] > now + CLOCK_SLACK:
        return _free("invalid", "the PC clock looks wrong - check the date and time", license_id=lid)

    pro = ALWAYS_FREE | FREE | PRO
    extra = p.get("features")
    if isinstance(extra, list):              # server may narrow Pro features for a plan; never widens past PRO
        pro = ALWAYS_FREE | FREE | (PRO & set(extra))
    if p["plan"] == PLAN_LIFETIME:
        return Entitlements(PLAN_LIFETIME, "active", frozenset(pro), lid)

    exp = float(p["expires_at"])
    grace = float(p.get("offline_grace_until") or exp)
    grace = min(grace, exp + GRACE_DAYS * DAY)          # a token can't grant more grace than the policy
    if now <= exp:
        return Entitlements(p["plan"], "active", frozenset(pro), lid, exp, grace, int((exp - now) // DAY))
    if now <= grace:
        return Entitlements(p["plan"], "grace", frozenset(pro), lid, exp, grace, int((grace - now) // DAY),
                            "Couldn't confirm your subscription - connect to the internet to keep Pro features")
    what = "trial" if p["plan"] == PLAN_TRIAL else "subscription"
    return _free("expired", f"Your {what} has ended - Pro features are paused, everything else keeps working",
                 license_id=lid, expires_at=exp, grace_until=grace)


# ----------------------------------------------------------------------------- storage
class LicenseStore:
    """Keeps the signed token (and the latest time we've seen) in %APPDATA%\\RigLab\\license.json.
    The token is useless on another PC and can't be edited without breaking its signature."""

    def __init__(self, path: Path | None = None):
        if path is None:
            from .config import app_dir
            path = app_dir() / "license.json"
        self.path = Path(path)

    def _read(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, d: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, self.path)

    def save_token(self, token: str) -> None:
        d = self._read()
        d["token"] = token.strip()
        self._write(d)

    def clear(self) -> None:
        d = self._read()
        d.pop("token", None)
        self._write(d)

    def entitlements(self, *, now: float | None = None, **kw) -> Entitlements:
        d = self._read()
        now = time.time() if now is None else now
        ent = evaluate(d.get("token"), now=now, last_seen=d.get("last_seen"), **kw)
        if now > (d.get("last_seen") or 0) + 3600:      # remember the time at most hourly
            d["last_seen"] = max(now, d.get("last_seen") or 0)
            try:
                self._write(d)
            except OSError:
                pass
        return ent
