# SPDX-License-Identifier: AGPL-3.0-only
import json

from ps5remote import config


def test_load_missing_config_is_empty():
    assert config.load() == {}


def test_update_and_remove_keys_round_trip():
    config.update(ps5_host="10.0.0.2", psn_user="me", other=1)
    assert config.load() == {"ps5_host": "10.0.0.2", "psn_user": "me", "other": 1}
    config.remove_keys("ps5_host", "psn_user", "not-there")
    assert config.load() == {"other": 1}


def test_save_leaves_no_temp_file(data_dir):
    config.save({"a": 1})
    assert sorted(p.name for p in data_dir.iterdir()) == ["config.json"]


def test_set_data_dir_moves_every_path(tmp_path):
    config.set_data_dir(tmp_path / "elsewhere")
    assert config.DATA_DIR == (tmp_path / "elsewhere").resolve()
    assert config.CONFIG_FILE.parent == config.DATA_DIR
    assert config.PROFILES_FILE.parent == config.DATA_DIR
    assert config.LOG_DIR == config.DATA_DIR / "logs"
    assert config.CUSTOM_DATA_DIR


def test_is_paired_needs_host_user_and_keys(paired):
    assert config.is_paired()


def test_is_paired_false_without_host(paired):
    config.remove_keys("ps5_host")
    assert not config.is_paired()


def test_is_paired_false_without_keys_for_user(paired):
    config.PROFILES_FILE.write_text(json.dumps({"tester": {"id": "x", "hosts": {}}}))
    assert not config.is_paired()


def test_is_paired_false_with_corrupt_profiles(paired):
    config.PROFILES_FILE.write_text("{not json")
    assert not config.is_paired()


def test_profiles_saved_to_data_folder_not_home(data_dir, monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    profiles = config.profiles()
    config.save_profiles(profiles)
    assert config.PROFILES_FILE.is_file()
    assert not (tmp_path / "home").exists()


def test_no_migration_when_running_from_source(monkeypatch):
    monkeypatch.setattr(config, "FROZEN", False)
    assert config.migration_source() is None


def test_migration_found_next_to_exe(monkeypatch, tmp_path):
    exe_dir = tmp_path / "dist"
    old = exe_dir / "data"
    old.mkdir(parents=True)
    (old / "profiles.json").write_text("{}")
    (old / "config.json").write_text('{"ps5_host": "1.2.3.4"}')
    monkeypatch.setattr(config, "FROZEN", True)
    monkeypatch.setattr(config, "ROOT", exe_dir)
    config.set_data_dir(tmp_path / "appdata")
    monkeypatch.setattr(config, "CUSTOM_DATA_DIR", False)
    assert config.migration_source() == old

    copied = config.migrate_from(old)
    assert sorted(copied) == ["config.json", "profiles.json"]
    assert (old / "profiles.json").exists()  # copied, not moved
    assert config.migration_source() is None  # profiles.json now exists


def _frozen_exe(monkeypatch, tmp_path, exe_dir_name="dist"):
    exe_dir = tmp_path / exe_dir_name
    exe_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "FROZEN", True)
    monkeypatch.setattr(config, "ROOT", exe_dir)
    config.set_data_dir(tmp_path / "appdata" / "KeyboardDS5" / "data")
    monkeypatch.setattr(config, "CUSTOM_DATA_DIR", False)
    return exe_dir


def _old_data(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "profiles.json").write_text("{}")
    (folder / "config.json").write_text('{"ps5_host": "1.2.3.4"}')
    return folder


def test_pre_rename_appdata_folder_is_offered_first(monkeypatch, tmp_path):
    exe_dir = _frozen_exe(monkeypatch, tmp_path)
    _old_data(exe_dir / "data")
    legacy = _old_data(config.LEGACY_USER_DIR / "data")
    assert config.migration_source() == legacy
    assert config.migrate_from(legacy) == ["config.json", "profiles.json"]
    assert (legacy / "profiles.json").exists()   # copied, never moved
    assert config.migration_source() is None


def test_nothing_to_offer_without_old_data(monkeypatch, tmp_path):
    _frozen_exe(monkeypatch, tmp_path)
    assert config.migration_source() is None


def test_new_appdata_folder_name(monkeypatch):
    assert config.LEGACY_USER_DIR.name == "legacy-appdata"   # patched in conftest
    import importlib, sys as _sys
    monkeypatch.setattr(_sys, "frozen", True, raising=False)
    monkeypatch.setattr(_sys, "_MEIPASS", "C:/bundle", raising=False)
    fresh = importlib.reload(config)
    try:
        assert fresh.USER_DIR.name == "KeyboardDS5"
        assert fresh.LEGACY_USER_DIR.name == "PS5Remote"
        assert fresh.SOURCE_DATA_DIR is None   # no psn_client.json lookup next to the .exe
    finally:
        monkeypatch.delattr(_sys, "frozen")
        importlib.reload(config)


def test_declined_migration_is_not_offered_again(monkeypatch, tmp_path):
    exe_dir = tmp_path / "dist"
    (exe_dir / "data").mkdir(parents=True)
    (exe_dir / "data" / "profiles.json").write_text("{}")
    monkeypatch.setattr(config, "FROZEN", True)
    monkeypatch.setattr(config, "ROOT", exe_dir)
    config.set_data_dir(tmp_path / "appdata")
    monkeypatch.setattr(config, "CUSTOM_DATA_DIR", False)
    config.decline_migration()
    assert config.migration_source() is None
