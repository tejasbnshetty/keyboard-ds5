# SPDX-License-Identifier: AGPL-3.0-only
import pytest

from ps5remote import appmaps, ps5


def test_bundled_app_maps_load_and_use_real_buttons():
    maps, default = appmaps.load_app_maps()
    assert default in maps
    assert maps["appletv"].name == "Apple TV"


@pytest.mark.parametrize("running, key", [
    ("Apple TV", "appletv"),
    ("NETFLIX", "netflix"),
    ("Prime Video", "primevideo"),
    ("Disney+", "disneyplus"),
    ("Stan", "stan"),
])
def test_find_streaming_app_by_name(running, key):
    found = appmaps.find_streaming_app({"running-app-name": running})
    assert found is not None and found.key == key


@pytest.mark.parametrize("running", ["Stanley's Parable", "Astro Bot", "", "   "])
def test_find_streaming_app_needs_a_whole_word(running):
    assert appmaps.find_streaming_app({"running-app-name": running}) is None


def test_find_streaming_app_by_title_id():
    m = appmaps.AppMap("x", "X", "cross", "left", "right", "ps", 10, title_ids=["PPSA01234"])
    assert m.matches("", "PPSA01234")
    assert not m.matches("", "PPSA99999")


@pytest.mark.parametrize("seconds, presses", [(10, 1), (20, 2), (30, 3), (5, 1), (0, 1), (11, 2)])
def test_seek_presses(seconds, presses):
    m = appmaps.AppMap("x", "X", "cross", "left", "right", "ps", 10)
    assert m.seek_presses(seconds) == presses


def test_pick_app_map_auto_and_fixed():
    m, why = appmaps.pick_app_map("auto", {"running-app-name": "Netflix"})
    assert m.key == "netflix" and "Netflix" in why
    m, why = appmaps.pick_app_map("auto", {"running-app-name": "Some Game"})
    assert m.key == "appletv" and "not recognised" in why
    m, why = appmaps.pick_app_map("auto", {})
    assert "no running app" in why
    m, why = appmaps.pick_app_map("youtube", {"running-app-name": "Netflix"})
    assert m.key == "youtube" and why == "set in settings"


def test_pick_app_map_unknown_name():
    with pytest.raises(ps5.PS5Error, match="No app map called"):
        appmaps.pick_app_map("nope", {})
