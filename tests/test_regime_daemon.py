import asyncio
import datetime as dt
import math
import types

import pytest

from quant_agency import regime_daemon as rd
from quant_agency.regime import RollingSigma60, sigma60_series

UTC = dt.timezone.utc


def T(h, m=0, s=0, day=20):                      # 2026-10-20 is a Tuesday
    return dt.datetime(2026, 10, day, h, m, s, tzinfo=UTC)


# ------------------------------------------------------------------ estimator
def test_sigma60_is_the_rms_of_one_second_bps_returns_and_needs_a_full_window():
    r = RollingSigma60()
    px = 80_000.0
    for k in range(0, 59):
        px *= 1.0001                                # +1 bp every second
        r.update(1000.0 + k + 0.5, px)
    assert math.isnan(r.value())                    # < 60 s of history
    for k in range(59, 80):
        px *= 1.0001
        r.update(1000.0 + k + 0.5, px)
    assert r.value() == pytest.approx(1.0, rel=1e-3)


def test_flat_market_reads_zero_and_missing_seconds_carry_the_price_forward():
    r = RollingSigma60()
    for k in range(0, 100, 7):                      # sparse ticks, constant price
        r.update(500.0 + k, 80_000.0)
    assert r.value() == pytest.approx(0.0, abs=1e-9)


def test_batch_and_streaming_estimators_agree():
    import numpy as np
    rng = np.random.default_rng(1)
    t = np.arange(0.0, 300.0, 0.1) + 5000.0
    mid = 80_000.0 * np.exp(np.cumsum(rng.normal(0, 0.2e-4, t.size)))
    at = np.array([5100.0, 5200.0, 5290.0])
    batch = sigma60_series(t, mid, at)
    r = RollingSigma60()
    k = 0
    for tq, b in zip(at, batch):
        while k < t.size and t[k] <= tq:
            r.update(float(t[k]), float(mid[k]))
            k += 1
        assert r.value(tq) == pytest.approx(b, rel=1e-12)


# ------------------------------------------------------------------ schedule
def test_scheduled_windows_are_utc_weekdays_only_with_half_open_bounds():
    c = rd.DaemonConfig()
    assert rd.in_window(T(7, 0), c) == "london" and rd.in_window(T(9, 59), c) == "london" and rd.in_window(T(10, 0), c) is None
    assert rd.in_window(T(13, 29), c) is None and rd.in_window(T(13, 30), c) == "us" and rd.in_window(T(16, 29), c) == "us" and rd.in_window(T(16, 30), c) is None
    assert rd.in_window(T(8, 0, day=24), c) is None and rd.in_window(T(14, 0, day=25), c) is None        # Sat / Sun
    assert rd.in_window(T(8, 0, day=19), c) == "london"                                                   # Monday
    with pytest.raises(ValueError):
        rd.in_window(dt.datetime(2026, 10, 20, 8), c)


# ------------------------------------------------------------------ decisions
def test_window_starts_capture_immediately_even_in_dead_chop():
    d = rd.Decider()
    assert d.step(T(13, 30, 0), 0.10) == ("start", "window:us")
    assert d.capturing


def test_volatility_must_persist_for_confirm_seconds_before_it_starts_capture():
    d = rd.Decider()
    t0 = T(3, 0).timestamp()
    clock = lambda s: dt.datetime.fromtimestamp(t0 + s, UTC)
    assert d.step(clock(0), 0.60) is None
    assert d.step(clock(20), 0.60) is None
    assert d.step(clock(25), 0.20) is None                         # a spike shorter than 30 s resets the timer
    assert d.step(clock(30), 0.60) is None
    assert d.step(clock(50), 0.60) is None
    act = d.step(clock(61), 0.60)
    assert act is not None and act[0] == "start" and act[1].startswith("vol:")


def test_between_thresholds_neither_starts_nor_stops():
    d = rd.Decider()
    t0 = T(3, 0).timestamp()
    clock = lambda s: dt.datetime.fromtimestamp(t0 + s, UTC)
    for s in range(0, 400, 10):
        assert d.step(clock(s), 0.40) is None                      # 0.35 <= sigma < 0.45 while idle: nothing
    d.capturing, d.started_at = True, t0
    for s in range(400, 1200, 10):
        assert d.step(clock(s), 0.40) is None                      # ... and while capturing: no stop (hysteresis)


def test_stop_needs_calm_for_calm_s_after_min_session_and_outside_windows():
    d = rd.Decider()
    t0 = T(3, 0).timestamp()
    clock = lambda s: dt.datetime.fromtimestamp(t0 + s, UTC)
    d.capturing, d.started_at = True, t0
    assert d.step(clock(0), 0.30) is None
    assert d.step(clock(100), 0.30) is None                        # calm but < calm_s and < min_session
    assert d.step(clock(250), 0.50) is None                        # a blip resets the calm timer
    assert d.step(clock(300), 0.30) is None
    assert d.step(clock(590), 0.30) is None                        # 290 s of calm
    act = d.step(clock(605), 0.30)                                 # >= 300 s of calm and >= 600 s since the start
    assert act is not None and act[0] == "stop" and not d.capturing


def test_a_scheduled_window_blocks_the_calm_stop_and_nan_holds_state():
    d = rd.Decider()
    d.capturing, d.started_at = True, T(13, 31).timestamp()
    for s in range(0, 2000, 10):
        assert d.step(T(13, 31) + dt.timedelta(seconds=s), 0.05) is None        # inside the US window until 16:30
    assert d.capturing
    d2 = rd.Decider()
    d2.capturing, d2.started_at = True, T(3).timestamp()
    for s in range(0, 2000, 10):
        assert d2.step(T(3) + dt.timedelta(seconds=s), float("nan")) is None    # unknown sigma never releases
    assert d2.capturing


def test_segment_end_returns_to_standby_and_the_next_tick_can_restart():
    d = rd.Decider()
    assert d.step(T(8, 0), 0.1)[0] == "start"
    d.segment_ended()
    assert not d.capturing and d.step(T(8, 0, 5), 0.1) == ("start", "window:london")


# ------------------------------------------------------------------ daemon wiring
def test_overrides_mark_the_run_as_validation_and_use_a_separate_prefix_and_log():
    a = rd.parse(["--n-star", "100", "--start-thr", "0.0"])
    cfg, plan = rd.build(a)
    assert plan.validation and plan.prefix == "p9v_seg" and "validation_log" in plan.log_path and cfg.start_thr == 0.0
    a = rd.parse(["--n-star", "100"])
    cfg, plan = rd.build(a)
    assert not plan.validation and plan.prefix == "p9_seg" and cfg.start_thr == 0.45 and cfg.stop_thr == 0.35 and cfg.calm_s == 300.0


def test_dry_run_daemon_logs_start_and_stop_without_launching_anything(tmp_path):
    cfg = rd.DaemonConfig(confirm_s=20.0, calm_s=30.0, min_session_s=30.0)
    plan = rd.Plan(n_star=50, log_path=str(tmp_path / "log.jsonl"), dry_run=True, out_dir=str(tmp_path), tape_dir=str(tmp_path))
    state = {"t": T(3, 0).timestamp(), "sigma": 0.8}

    def clock():
        state["t"] += 10.0
        return dt.datetime.fromtimestamp(state["t"], UTC)

    d = rd.Daemon(cfg, plan, clock=clock)
    d.tick_s = 0.001
    ticks = {"n": 0}

    async def no_feed():
        while not d.stop_requested:
            await asyncio.sleep(0.01)

    d.feed = no_feed
    d.current_sigma = lambda: (ticks.__setitem__("n", ticks["n"] + 1) or (0.8 if ticks["n"] < 12 else 0.1))
    d.proc = None

    async def go():
        task = asyncio.create_task(d.run())
        for _ in range(400):
            await asyncio.sleep(0.01)
            if sum(1 for _ in open(plan.log_path)) > 0 and ticks["n"] > 30:
                break
        d.stop_requested = True
        await task
    asyncio.run(go())
    kinds = [__import__("json").loads(l)["kind"] for l in open(plan.log_path)]
    assert "DRY_RUN_start" in kinds and "DRY_RUN_stop" in kinds and kinds.index("DRY_RUN_start") < kinds.index("DRY_RUN_stop") and kinds[-1] == "daemon_end"
