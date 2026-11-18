"""Was Windows started since RigLab last ran? (Logged at start-up; the lighting check itself is in lightwatch.py
and now runs on every start, because with Windows' Fast Startup a shutdown -> power on doesn't change the boot
time.)"""
from __future__ import annotations

TOLERANCE_S = 120          # boot time read twice can differ by a second or two; a restart moves it by much more


def boot_time() -> float | None:
    try:
        import psutil
        return float(psutil.boot_time())
    except Exception:  # noqa: BLE001
        return None


def first_start_since_boot(saved: float | None, current: float | None, tol: float = TOLERANCE_S) -> bool:
    """True when RigLab hasn't run since Windows last started (or we can't tell - then a rescan is the safe choice)."""
    if current is None:
        return False                       # can't read the boot time: behave like a normal start
    if saved is None:
        return True
    try:
        return abs(float(current) - float(saved)) > tol
    except (TypeError, ValueError):
        return True


def missing_notice(missing: list[str]) -> str | None:
    if not missing:
        return None
    if len(missing) == 1:
        return f"After the restart, RigLab couldn't find this lighting device: {missing[0]}. Check it's plugged in, then press Rescan on the Lights page."
    return (f"After the restart, RigLab couldn't find {len(missing)} lighting devices: {', '.join(missing)}. "
            "Check they're plugged in, then press Rescan on the Lights page.")

