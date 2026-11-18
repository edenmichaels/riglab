"""First start after the PC boots: rescan lighting (USB RGB devices can be slow to appear) and reapply the
last effect. Pure logic here, tested with fake clocks and fake scanners."""
from __future__ import annotations

import time

TOLERANCE_S = 120          # boot time read twice can differ by a second or two; a restart moves it by much more
RETRY_DELAYS = (0, 5, 8, 12, 15, 20)     # seconds to wait before each scan: about 60 s in total


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


class Rescan:
    """Scan for lighting devices until every device seen last time is back, or the retries run out.
    scan() -> list of device keys found now."""

    def __init__(self, scan, expected, delays=RETRY_DELAYS, sleep=time.sleep, cancelled=lambda: False):
        self.scan, self.expected = scan, list(dict.fromkeys(expected or []))
        self.delays, self.sleep, self.cancelled = delays, sleep, cancelled
        self.tries = 0
        self.found: list[str] = []

    def run(self) -> dict:
        for d in self.delays:
            if self.cancelled():
                break
            if d:
                self.sleep(d)
            self.tries += 1
            try:
                self.found = list(self.scan() or [])
            except Exception:  # noqa: BLE001 - the service may still be starting; try again
                continue
            if self.expected and all(k in self.found for k in self.expected):
                break
            if not self.expected and self.found:
                break
        missing = [k for k in self.expected if k not in self.found]
        return {"found": self.found, "missing": missing, "tries": self.tries, "ok": not missing}


def missing_notice(missing: list[str]) -> str | None:
    if not missing:
        return None
    if len(missing) == 1:
        return f"After the restart, RigLab couldn't find this lighting device: {missing[0]}. Check it's plugged in, then press Rescan on the Lights page."
    return (f"After the restart, RigLab couldn't find {len(missing)} lighting devices: {', '.join(missing)}. "
            "Check they're plugged in, then press Rescan on the Lights page.")


def rescan_and_reapply(light, quitting=lambda: False, sleep=time.sleep, delays=None) -> dict:
    """The after-boot routine for the lighting engine: rescan until the devices seen last time are back (or about a
    minute passes), then reapply the saved effect on every device found. Returns the Rescan result plus 'notice'."""
    expected = list(light.L.get("known_devices") or [])

    def scan():
        if not light.client:                      # lighting service still starting: wait for it (counts as one try)
            for _ in range(20):
                if light.client or quitting():
                    break
                sleep(0.5)
            if not light.client:
                raise RuntimeError("lighting service not ready")
        try:
            if hasattr(light.client, "rescan_devices"):
                light.client.rescan_devices()
                sleep(1.5)
        except Exception:  # noqa: BLE001
            pass
        light.discover()
        return list(light.keys)
    res = Rescan(scan, expected, delays=delays or RETRY_DELAYS, sleep=sleep, cancelled=quitting).run()
    try:
        light.set_state(**dict(light.L["state"]))      # reapply the last effect
        res["reapplied"] = True
    except Exception:  # noqa: BLE001
        res["reapplied"] = False
    res["notice"] = missing_notice(res["missing"])
    return res
