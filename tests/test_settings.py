# SPDX-License-Identifier: AGPL-3.0-only
import pytest

from ps5remote import config
from ps5remote.settings import AppSettings


def test_defaults_when_nothing_saved():
    assert AppSettings.load() == AppSettings()


def test_save_and_load_round_trip():
    s = AppSettings(press_ms=120, idle_timeout_min=0, safe_connect=True, profile_hotkey="F4")
    s.save()
    assert AppSettings.load() == s
    assert config.load()["app"]["press_ms"] == 120


def test_from_dict_ignores_unknown_fields():
    assert AppSettings.from_dict({"nope": 1}) == AppSettings()


def test_from_dict_converts_numbers():
    s = AppSettings.from_dict({"press_ms": 90.0, "idle_timeout_min": 1})
    assert s.press_ms == 90 and isinstance(s.press_ms, int)
    assert s.idle_timeout_min == 1.0 and isinstance(s.idle_timeout_min, float)


@pytest.mark.parametrize("data, message", [
    ({"press_ms": 5}, "between"),
    ({"press_ms": 5000}, "between"),
    ({"press_ms": "80"}, "number"),
    ({"press_ms": True}, "number"),
    ({"idle_timeout_min": -1}, "between"),
    ({"repeat_interval_ms": 10}, "between"),
    ({"safe_connect": 1}, "true or false"),
    ({"profile_hotkey": ""}, "key name"),
    ({"profile_hotkey": "x" * 33}, "key name"),
    ({"profile_hotkey": 5}, "key name"),
])
def test_from_dict_rejects_bad_values(data, message):
    with pytest.raises(ValueError, match=message):
        AppSettings.from_dict(data)


@pytest.mark.parametrize("data, message", [
    ({"mouse_curve": "cubic"}, "one of"),
    ({"mouse_sens_x": 0}, "between"),
    ({"mouse_sens_y": 50}, "between"),
    ({"stick_hz": 200}, "between"),
    ({"stick_hz": 10}, "between"),
    ({"mouse_outer_limit": 0.1}, "between"),
    ({"mouse_anti_deadzone": 0.7}, "between"),
    ({"mouse_anti_deadzone": 0.5, "mouse_outer_limit": 0.4}, "smaller than"),
    ({"mouse_smoothing_ms": 5}, "between"),
    ({"mouse_return_ms": -1}, "between"),
    ({"walk_tilt": 0}, "between"),
    ({"light_trigger": 1.5}, "between"),
    ({"mouse_invert_y": "yes"}, "true or false"),
    ({"mouse_toggle_key": "F2"}, "different keys"),
    ({"mouse_toggle_key": "F 1"}, "key name"),
])
def test_gaming_settings_rejected(data, message):
    with pytest.raises(ValueError, match=message):
        AppSettings.from_dict(data)


def test_gaming_settings_defaults_and_mouse_settings():
    s = AppSettings.from_dict({"mouse_sens_x": 2, "mouse_curve": "exponential",
                               "mouse_invert_y": True, "mouse_anti_deadzone": 0.15})
    assert s.stick_hz == 120 and s.mouse_toggle_key == "F1"
    m = s.mouse()
    assert m.sens_x == 2.0 and m.sens_y == 1.0 and m.curve == "exponential"
    assert m.invert_y is True and m.anti_deadzone == 0.15
    assert s.hotkeys() == {"F1", "F2"}


def test_load_falls_back_to_defaults_on_bad_saved_values():
    config.update(app={"press_ms": -1})
    assert AppSettings.load() == AppSettings()
