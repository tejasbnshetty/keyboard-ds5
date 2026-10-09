# SPDX-License-Identifier: AGPL-3.0-only
import copy
import json

import pytest

from ps5remote import keymaps
from ps5remote.gameinput import ACTIONS
from ps5remote.remote import BUTTONS

HOTKEYS = {"F1", "F2"}


def test_defaults_are_valid():
    assert keymaps.validate(keymaps.defaults(), HOTKEYS) == keymaps.DEFAULTS


def test_built_in_profiles():
    assert list(keymaps.DEFAULTS["profiles"]) == ["Menus", "Gaming"]


def test_menus_profile_covers_every_original_button():
    original = {"up", "down", "left", "right", "cross", "circle", "triangle", "square",
                "options", "ps", "l1", "r1", "l2", "r2"}
    profile = keymaps.DEFAULTS["profiles"]["Menus"]
    assert set(profile["bindings"].values()) == original
    assert profile["hold_buttons"] is False


def test_saved_custom_profiles_are_kept():
    """Profiles you made (including an old 'Games') stay; only the defaults changed."""
    data = keymaps.defaults()
    data["profiles"]["Games"] = {"hold_buttons": False, "bindings": {"KeyW": "up"}}
    data["profiles"]["My racer"] = {"hold_buttons": True, "bindings": {"KeyW": "r2", "KeyS": "l2"}}
    keymaps.save(data)
    assert list(keymaps.load({"F1", "F2"})["profiles"]) == ["Menus", "Gaming", "Games", "My racer"]


def test_old_mouse_stick_flag_is_dropped():
    """The captured mouse aims in every profile now; files saved with the old flag still load."""
    old = {"version": 2, "active": "P", "profiles": {"P": {
        "hold_buttons": True, "mouse_stick": False, "bindings": {"KeyW": "ls_up"}}}}
    keymaps.save(old)
    assert keymaps.load()["profiles"]["P"] == {"hold_buttons": True, "bindings": {"KeyW": "ls_up"}}


@pytest.mark.parametrize("name", ["My racer", "FPS (fast)", "Ünïcode-1", "a+b & c_d.e"])
def test_custom_profile_names_allowed(name):
    clean = keymaps.validate({"profiles": {name: {"bindings": {}}}}, set())
    assert name in clean["profiles"]


def test_gaming_profile_defaults():
    g = keymaps.DEFAULTS["profiles"]["Gaming"]
    assert g["hold_buttons"] and set(g) == {"hold_buttons", "bindings"}
    b = g["bindings"]
    assert [b[k] for k in ("KeyW", "KeyA", "KeyS", "KeyD")] == ["ls_up", "ls_left", "ls_down", "ls_right"]
    assert [b[k] for k in ("Space", "KeyC", "KeyE", "KeyR")] == ["cross", "circle", "square", "triangle"]
    assert [b[k] for k in ("ShiftLeft", "KeyV", "KeyQ", "KeyF", "Tab", "Enter")] == [
        "l3", "r3", "l1", "r1", "touchpad", "options"]
    assert [b[k] for k in ("Mouse0", "Mouse2", "WheelUp", "WheelDown")] == ["r2", "l2", "r1", "l1"]
    assert [b[k] for k in ("ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight")] == [
        "up", "down", "left", "right"]
    assert b["AltLeft"] == "walk"
    assert not set(b) & HOTKEYS  # F1 / F2 stay free


def test_one_action_can_have_several_inputs():
    b = keymaps.DEFAULTS["profiles"]["Gaming"]["bindings"]
    assert [k for k, a in b.items() if a == "l1"] == ["KeyQ", "WheelDown"]


def test_defaults_returns_a_copy():
    d = keymaps.defaults()
    d["profiles"]["Menus"]["bindings"]["ArrowUp"] = "down"
    assert keymaps.DEFAULTS["profiles"]["Menus"]["bindings"]["ArrowUp"] == "up"


def test_version_1_profile_is_converted():
    old = {"active": "Mine", "profiles": {"Mine": {"up": "KeyW", "down": "", "cross": "Space"}}}
    clean = keymaps.validate(old, HOTKEYS)
    assert clean["version"] == keymaps.VERSION
    assert clean["profiles"]["Mine"] == {
        "hold_buttons": False, "bindings": {"KeyW": "up", "Space": "cross"}}


def test_loading_a_version_1_file_adds_gaming(data_dir):
    data_dir.mkdir(parents=True)
    old = {"active": "Menus", "profiles": {"Menus": {"up": "ArrowUp", "ps": "KeyP"}}}
    keymaps.keymaps_file().write_text(json.dumps(old))
    loaded = keymaps.load(HOTKEYS)
    assert list(loaded["profiles"]) == ["Menus", "Gaming"]
    assert loaded["profiles"]["Menus"]["bindings"] == {"ArrowUp": "up", "KeyP": "ps"}
    assert loaded["active"] == "Menus"


def test_loading_a_version_2_file_does_not_re_add_gaming():
    data = keymaps.defaults()
    del data["profiles"]["Gaming"]
    keymaps.save(data)
    assert "Gaming" not in keymaps.load(HOTKEYS)["profiles"]


def test_missing_active_falls_back_to_first_profile():
    clean = keymaps.validate({"profiles": {"P": {"bindings": {"KeyW": "up"}}}}, set())
    assert clean["active"] == "P"


def test_every_action_is_bindable():
    bindings = {f"Key{chr(65 + i)}" if i < 26 else f"Digit{i - 26}": a for i, a in enumerate(ACTIONS)}
    clean = keymaps.validate({"profiles": {"P": {"bindings": bindings}}}, set())
    assert set(clean["profiles"]["P"]["bindings"].values()) == set(ACTIONS)


@pytest.mark.parametrize("data, message", [
    ([], "malformed"),
    ({"profiles": []}, "malformed"),
    ({"profiles": {}}, "between"),
    ({"profiles": {f"p{i}": {"bindings": {}} for i in range(keymaps.MAX_PROFILES + 1)}}, "between"),
    ({"profiles": {"<script>": {"bindings": {}}}}, "isn't allowed"),
    ({"profiles": {"x" * 25: {"bindings": {}}}}, "isn't allowed"),
    ({"profiles": {"P": []}}, "malformed"),
    ({"profiles": {"P": {"bindings": []}}}, "malformed"),
    ({"profiles": {"P": {"bindings": {f"Key{i}": "up" for i in range(65)}}}}, "malformed"),
    ({"profiles": {"P": {"bindings": {"Key W": "up"}}}}, "valid key"),
    ({"profiles": {"P": {"bindings": {"KeyW": "jump"}}}}, "can be bound"),
    ({"profiles": {"P": {"bindings": {"KeyW": 5}}}}, "can be bound"),
    ({"profiles": {"P": {"bindings": {"F2": "up"}}}}, "reserved"),
    ({"profiles": {"P": {"bindings": {"F1": "cross"}}}}, "reserved"),
    ({"profiles": {"P": {"bindings": {"WheelUp": "ls_up"}}}}, "wheel"),
    ({"profiles": {"P": {"bindings": {"WheelDown": "walk"}}}}, "wheel"),
    ({"profiles": {"P": {"bindings": {}, "hold_buttons": "yes"}}}, "true or false"),
    ({"profiles": {"P": {"up": "F2"}}}, "reserved"),  # version 1 is validated too
])
def test_validate_rejects(data, message):
    with pytest.raises(ValueError, match=message):
        keymaps.validate(data, HOTKEYS)


def test_mouse_buttons_can_do_anything():
    clean = keymaps.validate({"profiles": {"P": {"bindings": {
        "Mouse1": "walk", "Mouse3": "ls_up", "Mouse4": "ps"}}}}, HOTKEYS)
    assert clean["profiles"]["P"]["bindings"]["Mouse3"] == "ls_up"


def test_new_buttons_are_actions():
    for button in ("l3", "r3", "touchpad"):
        assert button in BUTTONS and button in ACTIONS


def test_save_and_load_round_trip():
    data = keymaps.defaults()
    data["active"] = "Gaming"
    keymaps.save(data)
    assert keymaps.load(HOTKEYS) == data


def test_load_falls_back_to_defaults_when_file_is_bad(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    keymaps.keymaps_file().write_text("{broken")
    assert keymaps.load() == keymaps.DEFAULTS


def test_load_falls_back_when_saved_map_uses_a_hotkey():
    data = copy.deepcopy(keymaps.DEFAULTS)
    data["profiles"]["Menus"]["bindings"]["F2"] = "ps"
    keymaps.save(data)
    assert keymaps.load(HOTKEYS) == keymaps.DEFAULTS
