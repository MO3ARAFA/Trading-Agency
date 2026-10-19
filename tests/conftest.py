import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from quant_agency.config import AgencyConfig
from quant_agency.inefficiency_hunter import Signal
from quant_agency.market_watchers import MarketBook, MarketMeta


def make_book(n_alt=2, tick=0.01, step=0.001, min_notional=5.0):
    metas = [MarketMeta("BTCUSDT", "binance", "BTCUSDT", "BTC", tick=0.01, step=1e-5, min_notional=5.0)]
    for k in range(n_alt):
        metas.append(MarketMeta(f"ALT{k+1}USDT", "binance", f"ALT{k+1}USDT", f"ALT{k+1}", tick=tick, step=step,
                                min_notional=min_notional))
    return MarketBook(metas)


def mk_signal(**kw) -> Signal:
    base = dict(sid=1, t=100.0, t_recv=100.0, market="ALT1USDT", idx=1, side=1, horizon_s=3.0, btc_delta_bps=10.0,
                btc_z=5.0, btc_obi=0.1, btc_flow_1s=0.2, vol_ratio=1.0, beta=1.0, rho=0.8, lag_s=0.8, window_s=2.0,
                age_s=0.2, fair_bps=10.0, actual_bps=0.0, gap_bps=10.0, gap_z=4.0, sigma_res_bps=2.0, spread_bps=2.0,
                bid=99.99, ask=100.01, bq=5000.0, aq=5000.0, mid=100.0, impulse_id=1)
    base.update(kw)
    return Signal(**base)


@pytest.fixture
def cfg():
    return AgencyConfig()


@pytest.fixture
def book2():
    b = make_book()
    for t in (1.0, 2.0, 3.0):                       # a little history so as-of lookups work
        b.on_quote(0, t, 80000.0, 80000.01, 3.0, 3.0)
        b.on_quote(1, t, 99.99, 100.01, 5000.0, 5000.0)
        b.on_quote(2, t, 49.99, 50.01, 5000.0, 5000.0)
    return b
