# SPDX-License-Identifier: AGPL-3.0-only
import math

import pytest

from ps5remote.gameinput import (FULL_TILT_SPEED, GameInput, MouseSettings, MouseStick,
                                 key_stick)

D = 1 / math.sqrt(2)


def approx(stick, expected, tol=1e-6):
    return stick[0] == pytest.approx(expected[0], abs=tol) and \
        stick[1] == pytest.approx(expected[1], abs=tol)


@pytest.mark.parametrize("dirs, expected", [
    (set(), (0, 0)),
    ({(0, -1)}, (0, -1)),
    ({(1, 0)}, (1, 0)),
    ({(0, -1), (1, 0)}, (D, -D)),        # W+D: normalised diagonal
    ({(0, 1), (-1, 0)}, (-D, D)),
    ({(1, 0), (-1, 0)}, (0, 0)),          # opposite keys cancel
    ({(1, 0), (-1, 0), (0, -1)}, (0, -1)),
])
def test_key_stick(dirs, expected):
    assert approx(key_stick(dirs), expected)


def test_key_stick_scale():
    assert approx(key_stick({(0, -1), (1, 0)}, 0.5), (0.5 * D, -0.5 * D))


# GameInput ---------------------------------------------------------------------------

def test_wasd_moves_the_left_stick():
    g = GameInput()
    g.set("ls_up", True)
    g.set("ls_right", True)
    left, right = g.sticks()
    assert approx(left, (D, -D)) and right == (0, 0)
    assert math.hypot(*left) == pytest.approx(1.0)


def test_walk_modifier_half_tilts():
    g = GameInput(walk_tilt=0.5)
    g.set("ls_up", True)
    g.set("walk", True)
    assert approx(g.sticks()[0], (0, -0.5))
    g.set("walk", False)
    assert approx(g.sticks()[0], (0, -1))


def test_keys_can_drive_the_right_stick():
    g = GameInput()
    g.set("rs_left", True)
    assert approx(g.sticks()[1], (-1, 0))


def test_buttons_and_triggers():
    g = GameInput(light_trigger=0.4)
    g.set("cross", True)
    g.set("r2", True)
    assert g.buttons() == {"cross": 255, "r2": 255}
    g.set("light_trigger", True)
    assert g.buttons() == {"cross": 255, "r2": 102}
    assert "light_trigger" not in g.buttons() and "walk" not in g.buttons()


def test_two_inputs_on_one_action_need_both_released():
    g = GameInput()
    g.set("l1", True)     # Q
    g.set("l1", True)     # wheel step
    g.set("l1", False)
    assert "l1" in g.buttons()
    g.set("l1", False)
    assert g.buttons() == {}
    g.set("l1", False)    # extra release doesn't go negative
    g.set("l1", True)
    assert "l1" in g.buttons()


def test_unknown_action():
    with pytest.raises(ValueError):
        GameInput().set("jump", True)


def test_neutral_releases_everything():
    g = GameInput()
    g.set_captured(True)
    for action in ("ls_up", "cross", "r2", "walk"):
        g.set(action, True)
    g.add_mouse(500, 0, now=0.0)
    g.tick(0.01)
    assert not g.is_neutral
    g.neutral()
    assert g.is_neutral and g.buttons() == {} and g.sticks() == ((0, 0), (0, 0))


def test_mouse_ignored_unless_captured():
    g = GameInput()
    g.add_mouse(500, 0, now=0.0)
    g.tick(0.01)
    assert g.sticks()[1] == (0, 0)


def test_releasing_capture_centres_the_right_stick():
    g = GameInput()
    g.set_captured(True)
    g.add_mouse(500, 0, now=0.0)
    g.tick(0.01)
    assert g.sticks()[1] != (0, 0)
    g.set_captured(False)
    assert g.sticks()[1] == (0, 0)


def test_right_stick_keys_override_mouse():
    g = GameInput()
    g.set_captured(True)
    g.add_mouse(500, 0, now=0.0)
    g.tick(0.01)
    g.set("rs_up", True)
    assert approx(g.sticks()[1], (0, -1))


# MouseStick --------------------------------------------------------------------------

def stick(**kw):
    return MouseStick(MouseSettings(**{"smoothing_ms": 20, **kw}))


def speed_move(m: MouseStick, vx: float, vy: float, now=1.0) -> tuple:
    """Feed a steady speed (counts/s) for 40 ms of 60 Hz reports and read the tilt."""
    for i in range(3, -1, -1):
        t = now - i / 60 * 0.6
        m.add(vx / 60 * 0.6, vy / 60 * 0.6, t)
    return m.tick(now)


def test_speed_sets_tilt_linear():
    m = stick()
    assert approx(speed_move(m, FULL_TILT_SPEED / 2, 0), (0.5, 0))


def test_full_speed_and_beyond_is_full_tilt():
    assert approx(speed_move(stick(), FULL_TILT_SPEED * 3, 0), (1, 0))


def test_direction_is_kept_when_clamped():
    x, y = speed_move(stick(), FULL_TILT_SPEED * 3, FULL_TILT_SPEED * 3)
    assert x == pytest.approx(D) and y == pytest.approx(D)


def test_separate_sensitivities():
    assert approx(speed_move(stick(sens_x=2.0), FULL_TILT_SPEED / 4, 0), (0.5, 0))
    assert approx(speed_move(stick(sens_y=0.5), 0, FULL_TILT_SPEED / 2), (0, 0.25))


def test_mouse_down_is_stick_down_unless_inverted():
    assert speed_move(stick(), 0, 1000)[1] > 0
    assert speed_move(stick(invert_y=True), 0, 1000)[1] < 0


def test_exponential_curve():
    assert approx(speed_move(stick(curve="exponential"), FULL_TILT_SPEED / 2, 0), (0.25, 0))


def test_outer_limit_and_anti_deadzone():
    m = stick(outer_limit=0.8, anti_deadzone=0.2)
    assert approx(speed_move(m, FULL_TILT_SPEED * 5, 0), (0.8, 0))
    assert approx(speed_move(stick(outer_limit=0.8, anti_deadzone=0.2), 1, 0), (0.2, 0), tol=1e-3)
    half = speed_move(stick(outer_limit=0.8, anti_deadzone=0.2), FULL_TILT_SPEED / 2, 0)
    assert approx(half, (0.5, 0))   # 0.2 + 0.6 * 0.5


def test_no_movement_no_tilt():
    m = stick(anti_deadzone=0.3)
    assert m.tick(1.0) == (0, 0)


def test_returns_to_centre_over_return_ms():
    m = stick(return_ms=100)
    assert speed_move(m, FULL_TILT_SPEED, 0, now=1.0)[0] == pytest.approx(1.0)
    assert m.tick(1.015)[0] == pytest.approx(1.0)    # within the 20 ms window: still moving
    # Reports stopped more than 20 ms ago: falls 1.0 per 100 ms from the last tick.
    assert m.tick(1.035)[0] == pytest.approx(0.8)
    assert m.tick(1.085)[0] == pytest.approx(0.3)
    assert m.tick(1.2) == (0, 0)


def test_instant_return():
    m = stick(return_ms=0)
    speed_move(m, FULL_TILT_SPEED, 0, now=1.0)
    m.tick(1.025)
    assert m.value == (0, 0)


def test_smoothing_averages_over_the_window():
    m = stick(smoothing_ms=100)
    m.add(FULL_TILT_SPEED * 0.1, 0, 1.0)   # one burst: a full-tilt amount for 100 ms
    assert approx(m.tick(1.0), (1, 0))
    assert approx(m.tick(1.05), (1, 0))     # still averaging the same movement
    assert m.tick(1.11)[0] < 1


def test_movement_gaps_shorter_than_the_window_do_not_drop_the_stick():
    """Browsers report movement ~60 times a second; the stick is sent ~120 times."""
    m = stick(smoothing_ms=35, return_ms=60)
    t, seen = 1.0, []
    for i in range(30):
        if i % 2 == 0:
            m.add(FULL_TILT_SPEED / 2 / 60, 0, t)   # half speed, at 60 Hz
        seen.append(m.tick(t)[0])
        t += 1 / 120
    steady = seen[10:]
    assert min(steady) > 0.4 and max(steady) < 0.6


def test_reset():
    m = stick()
    speed_move(m, 1000, 0)
    m.reset()
    assert m.value == (0, 0) and m.tick(2.0) == (0, 0)
