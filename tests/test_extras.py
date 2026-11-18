"""Explain my PC, storage clean-up, startup impact, the weekly task, and appearance settings validation."""
import os
import time
from datetime import date

import pytest

from riglab.core import pcinfo, schedule, storage

INV = {
    "Processor": [{"Model": "AMD Ryzen 7 7800X3D 8-Core Processor", "Cores / Threads": "8 / 16"}],
    "Graphics": [{"Model": "NVIDIA GeForce RTX 4070 SUPER", "Display": "2560x1440 @ 165 Hz"}, {"Model": "AMD Radeon(TM) Graphics", "Display": "—"}],
    "Motherboard": [{"Manufacturer": "ASUSTeK COMPUTER INC.", "Model": "TUF GAMING B650-PLUS WIFI"}, {"BIOS": "AMI 3222", "BIOS date": "2021-03-14"}],
    "Memory": [{"Total": "32.0 GB", "Type": "DDR5", "Rated speed": "6000 MT/s", "Running speed": "4800 MT/s"}],
    "Storage": [{"Drive": "Samsung SSD 990 PRO 2TB", "Type": "SSD (NVMe)"}, {"Volume": "C:\\", "Used": "1.7 TB of 1.8 TB (93%)"}],
    "Displays": [{"Monitor": "LG ULTRAGEAR"}],
    "Network": [{"Adapter": "Intel Wi-Fi 6E AX210", "Link": "1201 Mbps"}],
    "System": [{"OS": "Microsoft Windows 11 Home"}],
}


def by_id(items):
    return {i["id"]: i for i in items}


def test_explain_my_pc_in_plain_words():
    it = by_id(pcinfo.explain(INV, today=date(2026, 11, 17)))
    assert set(it) == {"cpu", "gpu", "memory", "storage", "display", "windows", "board", "network"}
    assert "8 cores" in it["cpu"]["say"] and "plenty" in it["cpu"]["say"]
    assert "RTX 4070 SUPER" in it["gpu"]["say"] and "1 other graphics chip" in it["gpu"]["say"]
    assert it["memory"]["state"] == "warn" and "XMP/EXPO" in it["memory"]["say"] and "32 GB" in it["memory"]["say"]
    assert it["storage"]["state"] == "warn" and "93% full" in it["storage"]["say"]
    assert "165 times a second" in it["display"]["say"] and "smooth" in it["display"]["say"]
    assert it["board"]["state"] == "warn" and "2021" in it["board"]["say"] and "ASUS TUF" in it["board"]["say"]
    assert "Wi-Fi" in it["network"]["say"] and it["windows"]["say"] == "You're running Windows 11 Home."
    for i in it.values():
        assert i["details"] and "Model" not in i["say"]


def test_explain_handles_small_and_missing_hardware():
    small = {"Processor": [{"Model": "Intel Celeron N4020", "Cores / Threads": "2 / 2"}],
             "Graphics": [{"Model": "Intel(R) UHD Graphics 600"}], "Memory": [{"Total": "4.0 GB"}],
             "Storage": [{"Drive": "WDC WD10", "Type": "HDD (SATA)"}]}
    it = by_id(pcinfo.explain(small))
    assert "built into the processor" in it["gpu"]["say"] and it["memory"]["state"] == "warn" and it["storage"]["state"] == "warn"
    assert "simple tasks" in it["cpu"]["say"]
    assert pcinfo.explain({}) == []


def test_largest_files_finds_the_biggest(tmp_path):
    for name, size in (("a.mp4", 500), ("b.iso", 900), ("c.txt", 50), ("sub/d.zip", 700)):
        p = tmp_path / name
        p.parent.mkdir(exist_ok=True)
        with open(p, "wb") as f:
            f.truncate(size)
    (tmp_path / "node_modules").mkdir()
    with open(tmp_path / "node_modules" / "huge.bin", "wb") as f:
        f.truncate(5000)
    files, done = storage.largest_files([tmp_path], limit=2, min_size=100)
    assert done and [f["name"] for f in files] == ["b.iso", "d.zip"]
    assert files[0]["kind"] == "Disk image" and files[1]["kind"] == "Archive"


def test_largest_files_stops_on_cancel(tmp_path):
    files, done = storage.largest_files([tmp_path], cancelled=lambda: True)
    assert not done and files == []
    files, done = storage.largest_files([tmp_path], deadline=time.monotonic() - 1)
    assert not done


def test_only_files_inside_your_folders_can_be_removed(tmp_path):
    root = tmp_path / "Downloads"
    root.mkdir()
    (root / "x.bin").write_bytes(b"1")
    assert storage.inside(root / "x.bin", [root])
    assert not storage.inside(root / ".." / "x.bin", [root])
    assert not storage.inside(root, [root])
    assert not storage.inside(tmp_path / "other.bin", [root])


def test_folder_size_and_clean_only_old_files(tmp_path):
    old, new = tmp_path / "old.cab", tmp_path / "new.cab"
    old.write_bytes(b"x" * 100)
    new.write_bytes(b"y" * 50)
    t = time.time() - 30 * 86400
    os.utime(old, (t, t))
    assert storage.folder_size(tmp_path) == (150, 2)
    assert storage.folder_size(tmp_path, older_than_days=10) == (100, 1)
    assert storage.clean_folder(tmp_path, older_than_days=10) == (100, 1)
    assert new.exists() and not old.exists()


def test_user_roots(tmp_path):
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Videos").mkdir()
    assert [p.name for p in storage.user_roots(tmp_path)] == ["Downloads", "Videos"]


@pytest.mark.parametrize("name, cmd, size, impact", [
    ("Steam", r'"C:\Program Files (x86)\Steam\steam.exe" -silent', None, "High"),
    ("Discord", r"C:\Users\you\AppData\Local\Discord\Update.exe --processStart Discord.exe", None, "High"),
    ("SecurityHealth", r"%windir%\system32\SecurityHealthSystray.exe", None, "Low"),
    ("Mystery", r"C:\tools\big.exe", 200 * 1024 * 1024, "High"),
    ("Mystery", r"C:\tools\tiny.exe", 100_000, "Low"),
    ("Mystery", r"C:\tools\mid.exe", 20 * 1024 * 1024, "Medium"),
])
def test_startup_impact(name, cmd, size, impact):
    level, why = storage.startup_impact(name, cmd, size)
    assert level == impact and why


def test_exe_path():
    assert storage.exe_path(r'"C:\Program Files\App\app.exe" --x') == r"C:\Program Files\App\app.exe"
    assert storage.exe_path(r"C:\tools\a.exe -q") == r"C:\tools\a.exe"
    assert storage.exe_path("") is None


def test_weekly_task_command():
    args = schedule.create_args([r"C:\Program Files\RigLab\RigLab.exe"])
    assert args[:4] == ["schtasks", "/Create", "/TN", schedule.TASK]
    assert args[5] == '"C:\\Program Files\\RigLab\\RigLab.exe" --weekly-check'
    assert "/RL" in args and "HIGHEST" in args and "WEEKLY" in args and args[args.index("/D") + 1] == "SUN"
    assert schedule.create_args(["x"], day="BAD")[args.index("/D") + 1] == "SUN"
    with pytest.raises(ValueError):
        schedule.create_args(["C:\\" + "a" * 300])
    assert schedule.delete_args()[-1] == "/F"


def test_appearance_settings_are_validated():
    from riglab.api import ui_values
    assert ui_values({"theme": "nord", "accent": "theme", "text_scale": 1.5, "view": "advanced"}) == \
        {"theme": "nord", "accent": "theme", "text_scale": 1.5, "view": "advanced"}
    assert ui_values({"theme": "hotdog", "accent": "pink", "view": "expert"}) == {}
    assert ui_values({"text_scale": 1.31})["text_scale"] == 1.25          # nearest allowed size
    assert ui_values({"text_scale": 9})["text_scale"] == 1.5 and ui_values({"text_scale": 0.1})["text_scale"] == 0.8
    assert ui_values({"text_scale": True}) == {} and ui_values({"text_scale": "big"}) == {}
    assert ui_values({"tour_done": True, "tips_hidden": ["home", "tweaks"]}) == {"tour_done": True, "tips_hidden": ["home", "tweaks"]}
    assert ui_values({"tour_done": "yes"}) == {}
