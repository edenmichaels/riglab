import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from riglab.core import license as lic

DAY = 86400
T0 = 1_800_000_000          # "issued" moment used by every test
ME = "a" * 32

KEY = Ed25519PrivateKey.generate()
PUB = [base64.b64encode(KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()]


def b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def make(key=KEY, **over):
    p = {"v": 1, "license_id": "lic_1", "plan": "subscription", "machine_id": ME, "issued_at": T0,
         "expires_at": T0 + 30 * DAY, "offline_grace_until": T0 + 44 * DAY}
    p.update(over)
    body = json.dumps(p).encode()
    return b64(body) + "." + b64(key.sign(body))


def ev(token, days=0, **kw):
    return lic.evaluate(token, now=T0 + days * DAY, this_machine=ME, public_keys=PUB, **kw)


# --- signature validation
def test_valid_signature_unlocks_pro():
    e = ev(make())
    assert (e.plan, e.status) == ("subscription", "active")
    assert e.has("gpu_tune") and e.days_left == 30 and e.limit("fan_curves") is None


def test_edited_payload_is_rejected():
    body, sig = make().split(".")
    forged = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    forged["plan"] = "lifetime"
    e = ev(b64(json.dumps(forged).encode()) + "." + sig)
    assert (e.plan, e.status) == ("free", "invalid") and not e.has("gpu_tune")


def test_token_signed_by_someone_else_is_rejected():
    assert ev(make(key=Ed25519PrivateKey.generate())).status == "invalid"


@pytest.mark.parametrize("junk", ["", "abc", "a.b.c", "!!!.???", "e30.e30", None])
def test_garbage_never_raises_and_is_free(junk):
    e = ev(junk)
    assert e.plan == "free" and not e.has("gpu_tune") and e.has("monitor")


def test_no_public_key_means_free():
    assert lic.evaluate(make(), now=T0, this_machine=ME, public_keys=[]).plan == "free"


def test_key_rotation_second_key_accepted():
    other = base64.b64encode(b"\x01" * 32).decode()
    assert lic.evaluate(make(), now=T0, this_machine=ME, public_keys=[other] + PUB).status == "active"


def test_other_machine_is_free():
    e = lic.evaluate(make(), now=T0, this_machine="b" * 32, public_keys=PUB)
    assert e.status == "invalid" and "different PC" in e.message


# --- subscription expiry, grace, fallback to Free
def test_subscription_inside_grace_keeps_pro():
    e = ev(make(), days=30 + 13)
    assert e.status == "grace" and e.has("gpu_tune") and e.days_left == 1


def test_subscription_last_second_of_grace():
    assert lic.evaluate(make(), now=T0 + 44 * DAY, this_machine=ME, public_keys=PUB).status == "grace"


def test_subscription_after_grace_falls_back_to_free():
    e = ev(make(), days=30 + 15)
    assert (e.plan, e.status) == ("free", "expired")
    assert not e.has("gpu_tune") and e.limit("fan_curves") == 1
    assert e.has("monitor") and e.has("reset_stock") and e.has("fan_curves")


def test_token_cannot_grant_more_than_14_days_grace():
    e = ev(make(offline_grace_until=T0 + 400 * DAY), days=30 + 15)
    assert e.status == "expired"


def test_missing_grace_field_means_no_grace():
    assert ev(make(offline_grace_until=None), days=31).status == "expired"


def test_trial_expires_to_free():
    t = make(plan="trial", expires_at=T0 + 14 * DAY, offline_grace_until=T0 + 14 * DAY)
    assert ev(t, days=13).has("lighting_fx")
    e = ev(t, days=15)
    assert e.plan == "free" and "trial" in e.message


# --- lifetime
def test_lifetime_valid_offline_forever():
    t = make(plan="lifetime", expires_at=None, offline_grace_until=None)
    e = ev(t, days=365 * 30)
    assert (e.plan, e.status) == ("lifetime", "active") and e.has("gpu_tune") and e.days_left is None


# --- clock tampering
def test_winding_clock_back_does_not_extend_subscription():
    e = ev(make(), days=5, last_seen=T0 + 60 * DAY)
    assert e.status == "expired"


def test_small_clock_drift_is_tolerated():
    assert ev(make(), days=5, last_seen=T0 + 5 * DAY + 3600).status == "active"


def test_token_issued_in_the_future_is_rejected():
    assert ev(make(), days=-3).status == "invalid"


# --- gating rules
def test_safety_features_are_never_gated():
    assert not (lic.ALWAYS_FREE & lic.PRO)
    for e in (ev(None), ev("junk"), ev(make(), days=100), ev(make(features=[]))):
        for f in lic.ALWAYS_FREE:
            assert e.has(f)


def test_server_feature_list_can_narrow_but_not_widen():
    e = ev(make(features=["gpu_tune", "made_up_feature"]))
    assert e.has("gpu_tune") and not e.has("overlay") and not e.has("made_up_feature")


# --- machine id + store
def test_machine_id_is_deterministic_and_hides_inputs():
    a = lic.machine_id(["GUID-1", "ASUS", "Board"])
    assert a == lic.machine_id(["guid-1 ", "asus", "board"]) and a != lic.machine_id(["GUID-2", "ASUS", "Board"])
    assert len(a) == 32 and "guid" not in a.lower()
    assert lic.machine_id() == lic.machine_id()


def test_store_roundtrip_and_clock_memory(tmp_path):
    s = lic.LicenseStore(tmp_path / "license.json")
    assert s.entitlements(now=T0, this_machine=ME, public_keys=PUB).plan == "free"
    s.save_token(make())
    assert s.entitlements(now=T0 + 50 * DAY, this_machine=ME, public_keys=PUB).status == "expired"
    assert s.entitlements(now=T0 + 1 * DAY, this_machine=ME, public_keys=PUB).status == "expired"   # wound back
    s.clear()
    assert s.entitlements(now=T0 + 51 * DAY, this_machine=ME, public_keys=PUB).status == "free"


def test_corrupt_store_file_is_free(tmp_path):
    p = tmp_path / "license.json"
    p.write_text("{not json")
    assert lic.LicenseStore(p).entitlements(now=T0, this_machine=ME, public_keys=PUB).plan == "free"
