"""All tunables in one place. The CEO mutates a *subset* at runtime through directives."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Tuple


@dataclass
class OracleConfig:
    horizons_s: Tuple[float, ...] = (1.0, 3.0, 5.0, 10.0)
    grid_s: float = 0.1                  # sub-second grid
    tick_cap: int = 131072               # tick ring (~5 min of BTC top-of-book at 400/s)
    grid_cap: int = 6000                 # 10 min of 100 ms bins
    sec_cap: int = 3600                  # 1 h of 1 s samples
    vol_halflife_s: float = 120.0        # EW half-life for impulse variance
    slow_vol_halflife_s: float = 900.0   # regime baseline
    warmup_s: float = 20.0
    sigma_floor_bps_per_sqrt_s: float = 0.2
    flow_bucket_s: float = 0.1
    gap_s: float = 1.5                   # silence longer than this = feed gap


@dataclass
class WatcherConfig:
    ring_cap: int = 8192
    n_markets: int = 60                  # Binance USDT alts (BTC is always market 0)
    rate_tau_ticks: float = 20.0         # EW window (in ticks) for inter-arrival time
    spread_fast_alpha: float = 0.05
    spread_slow_alpha: float = 0.002
    cross_venue: bool = True             # also watch BTC/ETH/SOL on Gate + Kraken
    exclude_bases: Tuple[str, ...] = ("USDC", "FDUSD", "TUSD", "USDP", "DAI", "EUR", "AEUR", "USD1",
                                      "XUSD", "BFUSD", "USDE", "PAXG", "XAUT", "RLUSD", "EURI", "USDT")
    exclude_regex: str = r"^[A-Z0-9]{4,}B$"   # Binance tokenized equities/ETFs (SPCXB, TQQQB, CRCLB, ...)


@dataclass
class HunterConfig:
    z_thr: float = 3.0                   # BTC impulse Z threshold (CEO-tunable)
    z_release: float = 1.5
    min_impulse_bps: float = 1.5
    min_gap_bps: float = 1.0
    gap_z_thr: float = 1.5               # gap / idiosyncratic noise
    rho_min: float = 0.30                # OLS correlation (3 s windows) at the lead-lag peak
    beta_tmin: float = 3.0               # regression t-stat of beta: decoupled markets can't fire gaps
    max_repriced: float = 0.6            # market already did >60% of expected move => not stale
    window_mult: float = 2.0             # opportunity window = mult*lag + base (CEO-tunable)
    window_base_s: float = 0.5
    window_min_s: float = 0.5
    window_max_s: float = 6.0
    max_spread_bps: float = 15.0
    min_tick_rate: float = 0.05          # ticks/s; below this the quote is unobservable
    max_quote_age_s: float = 30.0        # hard liveness guard: older quote => market considered dead
    cooldown_s: float = 5.0
    scan_min_interval_s: float = 0.002
    # calibration
    calib_window_s: float = 180.0
    calib_interval_s: float = 15.0
    first_calib_after_s: float = 45.0
    lag_grid_s: Tuple[float, float, float] = (-0.5, 3.0, 0.1)   # (start, stop_inclusive, step)
    min_calib_ticks: int = 60
    # dynamic beta (Kalman)
    h_cal_s: float = 3.0
    kalman_period_s: float = 1.0
    kalman_q: float = 1e-4
    beta_prior: float = 1.0
    beta_max: float = 4.0
    resid_period_s: float = 0.25
    resid_halflife_s: float = 90.0
    shadow_all: bool = True


@dataclass
class CFOConfig:
    capital_usd: float = 10_000.0
    fee_taker_bps: float = 7.5           # Binance spot VIP0 w/ BNB
    fee_maker_bps: float = 7.5
    safety_hurdle_bps: float = 1.0       # CEO-tunable
    edge_credit: float = 1.0             # fraction of |gap| we expect to capture (CEO-tunable)
    mode_policy: str = "auto"            # auto | maker_only | taker_only  (CEO-tunable)
    size_mult: float = 1.0               # CEO-tunable
    max_spread_bps: float = 15.0
    slip_depth_coeff: float = 0.5
    slip_vol_coeff: float = 0.25
    latency_s: float = 0.15              # assumed order-entry round trip from this gateway
    p_fill_maker: float = 0.2            # prior: a resting bid is rarely hit while price is rising; learned online
    kelly_fraction: float = 0.25
    risk_per_trade_frac: float = 0.002   # of equity at the adverse stop
    max_notional_frac: float = 0.05
    max_gross_frac: float = 0.5
    max_market_frac: float = 0.10
    max_beta_net_frac: float = 0.30
    liquidity_frac: float = 0.25         # share of top-of-book size we may take
    min_notional: float = 10.0
    tp_capture: float = 0.7              # convergence take-profit = 70% of credited gap
    stop_mult: float = 2.0               # adverse stop = max(mult*sigma_res, min_stop)
    min_stop_bps: float = 4.0
    time_stop_min_s: float = 10.0
    time_stop_max_s: float = 30.0
    maker_ttl_s: float = 3.0
    urgent_window_s: float = 2.5         # opportunity windows shorter than this => taker
    allow_short: bool = True             # paper/perp-style; spot would be long-only
    market_loss_frac: float = 0.004      # per-market rolling loss breaker (of equity)
    portfolio_dd_frac: float = 0.02
    daily_loss_frac: float = 0.03
    breaker_cooldown_s: float = 600.0
    markout_horizons_s: Tuple[float, ...] = (1.0, 3.0, 5.0, 10.0, 30.0)
    # ---- Phase 5 maker sniper (CFO's queue-aware cost model)
    snipe_enabled: bool = True
    snipe_gate_bps: float = 8.0          # spread gate for maker entries (a maker *captures* spread; PM spreads are in the 100s of bps)
    snipe_p_fill: float = 0.3            # prior P(fill) for a joined order (learned online from account attempts)
    snipe_p_exit_maker: float = 0.5      # prior P(passive exit fills before the work window ends)
    snipe_adverse_bps: dict = field(default_factory=lambda: {"hyperliquid": 0.3, "polymarket": 60.0})
    snipe_min_ev_bps: float = 0.2
    snipe_adverse_hs_frac: float = 0.75  # prior: a passive fill gives back ~75 % of the half-spread to adverse selection
    snipe_penny: bool = True
    max_snipe_open: int = 6
    snipe_blocked: tuple = ()            # venues the CEO has switched off
    # ---- Phase 6 Architecture A (pre-positioned quote maker)
    mm_enabled: bool = True
    mm_adverse_bps: dict = field(default_factory=lambda: {"hyperliquid": 0.3, "polymarket": 60.0})
    mm_min_ev_bps: float = 0.5           # minimum modelled round-trip net (bps of price) to quote a market at all
    mm_stop_bps: dict = field(default_factory=lambda: {"hyperliquid": 6.0, "polymarket": 300.0})
    max_mm_open: int = 6                 # concurrent inventory-holding quoters in the account
    mm_blocked: tuple = ()
    # ---- Phase 6 Architecture B (high-conviction taker sniper)
    b_enabled: bool = True
    b_floor_mult: float = 1.5            # hard absolute floor: |predicted move| >= mult x (spread + taker-in + maker-out fee)  (CEO-tunable)
    b_min_ev_bps: float = 0.5
    max_b_open: int = 4
    b_blocked: tuple = ()


@dataclass
class CEOConfig:
    review_interval_s: float = 30.0
    window_s: float = 600.0              # KPI look-back
    primary_horizon_s: float = 5.0
    n_min_market: int = 6
    n_min_global: int = 12
    market_net_bad_bps: float = -3.0
    market_hit_bad: float = 0.35
    toxic_gross1_bps: float = -0.5
    quarantine_s: float = 600.0
    quarantine_max_s: float = 7200.0
    false_gap_bad: float = 0.55
    fee_bleed_ratio: float = 0.6
    net_bad_bps: float = -1.0
    net_good_bps: float = 1.0
    realization_bad: float = 0.5
    hurdle_step_bps: float = 0.5
    hurdle_max_bps: float = 8.0
    hurdle_min_bps: float = 0.5
    z_step: float = 0.25
    z_min: float = 2.0
    z_max: float = 5.0
    size_floor: float = 0.1
    halt_pause_s: float = 300.0
    vol_ratio_hi: float = 1.5
    vol_ratio_lo: float = 0.7
    missed_opportunity_bps: float = 1.0


@dataclass
class ExecConfig:
    latency_s: float = 0.15
    max_open: int = 20


@dataclass
class ArbConfig:
    record_gap_bps: float = 0.3          # shadow-track every basis-adjusted locked gap above this
    max_quote_age_s: float = 3.0         # both quotes must be live
    scan_min_interval_s: float = 0.01
    basis_halflife_s: float = 300.0
    basis_update_s: float = 1.0
    basis_min_samples: int = 60


@dataclass
class PolyConfig:
    enabled: bool = True
    z_thr: float = 2.0                   # BTC impulse Z that triggers a prediction-market scan
    min_impulse_bps: float = 1.0
    min_gap_prob: float = 0.01           # |fair move - market move| >= 1 cent
    max_repriced: float = 0.6
    window_s: float = 20.0               # how long after the impulse the lag is assumed to last
    cooldown_s: float = 5.0
    max_spread_prob: float = 0.06
    mid_lo: float = 0.05
    mid_hi: float = 0.95
    vol_floor_ann: float = 0.35
    max_markets: int = 90
    n_updown_windows: int = 3
    rediscover_s: float = 120.0
    min_ttl_s: float = 60.0              # no entries in the last minute before expiry (resolution gap risk)


@dataclass
class SnipeConfig:
    enabled: bool = True
    venues: Tuple[str, ...] = ("hyperliquid", "polymarket")
    order_latency_s: float = 0.15
    cancel_latency_s: float = 0.15
    taker_slack_bps: float = 1.0
    ttl_s: dict = field(default_factory=lambda: {"hyperliquid": 6.0, "polymarket": 12.0})
    work_s: dict = field(default_factory=lambda: {"hyperliquid": 8.0, "polymarket": 10.0})
    max_hold_s: float = 30.0
    hold_frac: float = 0.4               # shield: cancel when < 40 % of the impulse is still intact (CEO-tunable)
    rev_bps: float = 0.3                 # shield: cancel on BTC reversal beyond this since the signal
    converge_frac: float = 0.8           # shield: cancel when the venue already did >= 80 % of the gap
    hl_notional: float = 200.0           # shadow-variant paper size (identical across variants)
    pm_notional: float = 50.0
    shadow_models: Tuple[str, ...] = ("strict", "depletion")
    account_model: str = "strict"        # fill model for the CFO-accounted attempt ('trades' when a trade tape exists)


@dataclass
class MMConfig:
    enabled: bool = True
    venues: Tuple[str, ...] = ("hyperliquid", "polymarket")
    order_latency_s: float = 0.15
    cancel_latency_s: float = 0.15
    calm_z: float = 1.0                  # quote only while every fast-horizon |BTC Z| is below this
    impulse_z: float = 2.0               # cancel the vulnerable side at this Z (any fast horizon)
    min_abs_bps: float = 0.3             # ... and at least this many bps of actual BTC move
    fast_horizons_s: Tuple[float, ...] = (0.25, 1.0, 3.0)
    fast_halflife_s: float = 120.0
    requote_hold_s: dict = field(default_factory=lambda: {"hyperliquid": 3.0, "polymarket": 6.0})   # stay off the vulnerable side this long (CEO-tunable)
    min_rest_s: float = 1.0              # min age before a mispriced resting quote is re-pegged (no churn)
    quote_notional: dict = field(default_factory=lambda: {"hyperliquid": 200.0, "polymarket": 25.0})
    hold_s: dict = field(default_factory=lambda: {"hyperliquid": 20.0, "polymarket": 30.0})        # inventory time stop (taker flatten)
    stop_bps: dict = field(default_factory=lambda: {"hyperliquid": 6.0, "polymarket": 300.0})      # adverse stop on inventory
    stop_ticks: float = 3.0              # prediction markets: adverse stop in price ticks (a % stop is sub-tick at low prices)
    taker_slack_bps: float = 1.0
    pm_mid_lo: float = 0.10
    pm_mid_hi: float = 0.90
    expiry_pull_s: float = 180.0         # no new quotes inside this window before expiry
    expiry_flat_s: float = 90.0          # inventory is flattened before this (CFO entry guard is 60 s)
    shadow_models: Tuple[str, ...] = ("strict", "depletion", "trades")
    account_model: str = "strict"


@dataclass
class BConfig:
    enabled: bool = True
    venues: Tuple[str, ...] = ("hyperliquid", "polymarket")
    stall_after_s: dict = field(default_factory=lambda: {"hyperliquid": 1.5, "polymarket": 3.0})   # earliest a stall is declared after entry
    stall_frac: float = 0.3              # venue has done < 30 % of the credited gap ...
    hold_frac: float = 0.4               # ... AND < 40 % of the BTC impulse is still intact  => scratch
    scratch_work_s: float = 3.0          # passive scratch at the touch before the taker fallback
    rev_stop_bps: float = 1.0            # genuine reversal: BTC back through the pre-impulse level by this much (and position adverse)
    ref_floor_mult: float = 1.5          # fixed floor used to *tag* shadow rows (the CEO moves only the ACCOUNT's live floor)
    shadow_models: Tuple[str, ...] = ("strict", "depletion", "trades")
    account_model: str = "strict"
    hl_notional: float = 200.0
    pm_notional: float = 50.0


@dataclass
class AgencyConfig:
    oracle: OracleConfig = field(default_factory=OracleConfig)
    watchers: WatcherConfig = field(default_factory=WatcherConfig)
    hunter: HunterConfig = field(default_factory=HunterConfig)
    cfo: CFOConfig = field(default_factory=CFOConfig)
    ceo: CEOConfig = field(default_factory=CEOConfig)
    exec: ExecConfig = field(default_factory=ExecConfig)
    arb: ArbConfig = field(default_factory=ArbConfig)
    poly: PolyConfig = field(default_factory=PolyConfig)
    snipe: SnipeConfig = field(default_factory=SnipeConfig)
    mm: MMConfig = field(default_factory=MMConfig)
    hc: BConfig = field(default_factory=BConfig)

    def to_dict(self):
        return asdict(self)
