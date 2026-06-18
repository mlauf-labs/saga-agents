"""Tests for Debouncer timing logic."""

from __future__ import annotations

from saga_agents.triggers.redis_listener import Debouncer


def test_not_due_before_delay() -> None:
    """Debouncer is not due before the quiet window elapses."""
    now = [0.0]
    d = Debouncer(15 * 60, clock=lambda: now[0])
    d.mark()
    now[0] = 10 * 60
    assert d.due() is False


def test_due_after_quiet_window() -> None:
    """Debouncer becomes due once the quiet window has elapsed."""
    now = [0.0]
    d = Debouncer(15 * 60, clock=lambda: now[0])
    d.mark()
    now[0] = 16 * 60
    assert d.due() is True


def test_burst_resets_quiet_window() -> None:
    """Each new signal resets the quiet-window clock (spec §6.2).

    Timeline (delay = 15 min):
      t= 0 min  first mark
      t= 5 min  second mark  → clock resets to t=5
      t=19 min  only 14 min since last mark → NOT due
      t=21 min  16 min since last mark → due
      reset()   consumed; no new signal → not due
    """
    now = [0.0]
    d = Debouncer(15 * 60, clock=lambda: now[0])
    d.mark()
    now[0] = 5 * 60
    d.mark()  # second signal RESETS the window to t=5 min
    now[0] = 19 * 60
    assert d.due() is False  # only 14 min since last mark — still quiet-pending
    now[0] = 21 * 60
    assert d.due() is True   # 16 min since last mark — quiet window elapsed
    d.reset()
    assert d.due() is False  # consumed; no new signal since reset


def test_not_due_without_mark() -> None:
    """A fresh debouncer with no marks is never due."""
    now = [0.0]
    d = Debouncer(1.0, clock=lambda: now[0])
    now[0] = 999.0
    assert d.due() is False


def test_re_armed_after_reset_and_new_mark() -> None:
    """After reset(), a new mark re-arms the debouncer."""
    now = [0.0]
    d = Debouncer(10.0, clock=lambda: now[0])
    d.mark()
    now[0] = 15.0
    assert d.due() is True
    d.reset()
    assert d.due() is False
    # Re-arm
    now[0] = 20.0
    d.mark()
    now[0] = 31.0
    assert d.due() is True


def test_due_exact_boundary() -> None:
    """At exactly delay_seconds the debouncer is due (>= semantics)."""
    now = [0.0]
    d = Debouncer(10.0, clock=lambda: now[0])
    d.mark()
    now[0] = 9.999
    assert d.due() is False
    now[0] = 10.0
    assert d.due() is True
