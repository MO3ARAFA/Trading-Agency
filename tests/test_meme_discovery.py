import base64
import struct

import pytest

from quant_agency import meme_discovery as md

MINT = bytes(range(32))
USER = bytes(range(32, 64))


def _trade_bytes(sol=1.0, tok=30e6, buy=True, vsol=40.0, vtok=800e6, rsol=10.0, fbps=95, cbps=30):
    b = md.TRADE_EVENT + MINT + struct.pack("<QQ", int(sol * 1e9), int(tok * 1e6)) + bytes([1 if buy else 0]) + USER
    b += struct.pack("<qQQQQ", 1_800_000_000, int(vsol * 1e9), int(vtok * 1e6), int(rsol * 1e9), 0) + bytes(32) + struct.pack("<QQ", fbps, 0)
    b += bytes(32) + struct.pack("<QQ", cbps, 0)
    return b


def _consistent_trade(buy=True):
    """A trade whose executed price lies between the pre- and post-trade curve price."""
    vs0, vt0, sol = 40.0, 800e6, 1.0
    tok, _, vs1 = md.curve_buy(vs0, vt0, sol, 0.0)
    if buy:
        return dict(sol=sol, tok=tok, buy=True, vsol=vs1, vtok=vt0 - tok)
    got, _, vs1 = md.curve_sell(vs0, vt0, 30e6, 0.0)
    return dict(sol=got, tok=30e6, buy=False, vsol=vs1, vtok=vt0 + 30e6)


def test_b58encode_known_vectors():
    assert md.b58encode(bytes(32)) == "1" * 32
    assert md.b58encode(b"\x00\x01") == "12"
    assert md.b58encode(bytes([255] * 4)) == "7YXq9G"


def test_decode_trade_fields_and_plausibility():
    kw = _consistent_trade()
    d = md._decode_trade(_trade_bytes(**kw))
    assert d["mint"] == md.b58encode(MINT) and d["user"] == md.b58encode(USER)
    assert d["is_buy"] and d["sol"] == pytest.approx(1.0) and d["fee_bps"] == 125
    assert md.plausible_trade(d)
    assert md.plausible_trade(md._decode_trade(_trade_bytes(**_consistent_trade(buy=False))))
    bad = md._decode_trade(_trade_bytes(sol=1.0, tok=1.0))                 # executed at 1 SOL per token on a 5e-8 curve
    assert not md.plausible_trade(bad)
    assert md._decode_trade(b"\x00" * 300) is None


def test_parse_pump_logs_attributes_data_to_the_emitting_program():
    good = "Program data: " + base64.b64encode(_trade_bytes(**_consistent_trade())).decode()
    logs = [f"Program {md.PUMP_PROGRAM} invoke [1]", good,
            "Program Evil1111111111111111111111111111111111 invoke [2]", good,          # another program prints the same bytes
            "Program Evil1111111111111111111111111111111111 success",
            f"Program {md.PUMP_PROGRAM} success", good]                                  # outside any invocation
    prints, creates, completes = md.parse_pump_logs(logs, "sig", 123.0)
    assert len(prints) == 1 and prints[0].side == 1 and prints[0].fee_bps == 125 and prints[0].t == 123.0
    assert prints[0].post_price == pytest.approx(prints[0].v_quote / prints[0].v_base)


def test_create_event_decoding():
    def s(x):
        return struct.pack("<I", len(x)) + x.encode()
    b = md.CREATE_EVENT + s("Doge Two") + s("DOGE2") + s("https://u") + MINT + bytes(32) + USER
    logs = [f"Program {md.PUMP_PROGRAM} invoke [1]", "Program data: " + base64.b64encode(b).decode(), f"Program {md.PUMP_PROGRAM} success"]
    _, creates, _ = md.parse_pump_logs(logs, "s", 1.0)
    assert creates[0].symbol == "DOGE2" and creates[0].mint == md.b58encode(MINT) and creates[0].creator == md.b58encode(USER)


def test_curve_round_trip_costs_two_fees():
    vs, vt = 30.0, 1_073_000_000.0
    tok, fee_b, vs1 = md.curve_buy(vs, vt, 1.0, 125)
    assert fee_b == pytest.approx(1.0 - 1.0 / 1.0125)
    got, fee_s, vs2 = md.curve_sell(vs1, vt - tok, tok, 125)
    assert vs2 == pytest.approx(vs)                                            # the curve returns to where it started
    assert got == pytest.approx((1.0 / 1.0125) * (1 - 0.0125))                 # lost: the fee on each side
    assert md.curve_buy(vs, vt, 1.0, 0)[0] > tok


def test_window_stats_and_ring_wraparound():
    st = md.TokenState("k", "pump")
    for i in range(700):
        st.push(1000 + i, 1 if i % 4 else -1, 1.0, 1.0 + i / 1000, f"u{i % 5}")
    w = st.window(1699, 9.5)                                                     # the last 10 prints
    assert w["n"] == 10 and w["unique"] == 5 and w["buys"] + w["sells"] == 10
    assert w["ret"] == pytest.approx((1 + 699 / 1000) / (1 + 690 / 1000) - 1)
    assert st.window(1699, 1e9)["n"] == md.RING                                  # never more than the ring holds
    assert st.window(5000, 10)["n"] == 0


def test_universe_lru_pin_ttl_and_creator_dump():
    u = md.Universe(max_tokens=3, ttl_s=100)
    for i in range(3):
        u.get(f"k{i}", "pump", 0.0)
    u.pinned.add("k0")
    u.get("k3", "pump", 1.0)
    assert "k0" in u.tokens and "k1" not in u.tokens and len(u.tokens) == 3
    u.on_create(md.TokenCreated(1.0, "m", "N", "SYM", "dev"))
    u.on_print(md.TradePrint(2.0, "pump", "m", 1, 1e6, 0.1, 1e-7, user="dev"))
    u.on_print(md.TradePrint(3.0, "pump", "m", -1, 8e5, 0.08, 1e-7, user="dev"))
    st = u.tokens["m"]
    assert st.creator_bought == 1e6 and st.creator_sold == 8e5
    u.expire(200.0)
    assert set(u.tokens) == {"k0"}


def _pump_state(**kw):
    st = md.TokenState("m", "pump", created_t=0.0, real_quote=10.0, fee_bps=125.0)
    for k, v in kw.items():
        setattr(st, k, v)
    return st


def test_safety_gate_rules():
    g = md.SafetyGate()
    clean = {"mint_authority": None, "freeze_authority": None, "top10_share": 0.2}
    assert g.evaluate(_pump_state(), dict(clean), 120.0).ok
    r = g.evaluate(_pump_state(), {}, 120.0)                                      # nothing verified -> fail, never pass
    assert not r.ok and any("unknown" in x for x in r.reasons)
    assert not g.evaluate(_pump_state(), {**clean, "mint_authority": "Auth"}, 120.0).ok
    assert not g.evaluate(_pump_state(), {**clean, "top10_share": 0.6}, 120.0).ok
    assert not g.evaluate(_pump_state(real_quote=1.0), dict(clean), 120.0).ok
    assert not g.evaluate(_pump_state(), dict(clean), 30.0).ok                   # younger than a minute
    assert not g.evaluate(_pump_state(creator="d", creator_bought=10.0, creator_sold=9.0), dict(clean), 120.0).ok
    assert not g.evaluate(_pump_state(fee_bps=500.0), dict(clean), 120.0).ok
    assert "bonding curve" in g.evaluate(_pump_state(), dict(clean), 120.0).facts["lp_lock"]
    gate = md.TokenState("P_USDT", "gate", bid=1.0, ask=1.001)
    assert g.evaluate(gate, {}, 0.0).ok
    assert not g.evaluate(md.TokenState("P_USDT", "gate", bid=1.0, ask=1.05), {}, 0.0).ok
    assert not g.evaluate(gate, {"tax_sell": 12.0}, 0.0).ok
    assert not g.evaluate(gate, {"is_honeypot": True}, 0.0).ok


def test_holder_concentration_excludes_pools_and_lockers():
    rep = {"topHolders": [{"owner": "POOL", "address": "a1", "pct": 60.0}, {"owner": "dev", "address": "a2", "pct": 8.0},
                          {"owner": "LOCK", "address": "a3", "pct": 20.0}, {"owner": "w1", "address": "a4", "pct": 5.0},
                          {"owner": "w2", "address": "MKTACC", "pct": 4.0}],
           "knownAccounts": {"POOL": {"type": "AMM"}, "LOCK": {"type": "LOCKER"}, "dev": {"type": "CREATOR"}},
           "markets": [{"pubkey": "M", "liquidityAAccount": {"pubkey": "MKTACC"}, "liquidityB": "x"}]}
    assert md.holder_concentration(rep) == pytest.approx(0.13)            # creator 8 % + wallet 5 %
    assert md.holder_concentration({}) is None


def test_rugcheck_danger_and_rugged_fail_the_gate():
    g = md.SafetyGate()
    clean = {"mint_authority": None, "freeze_authority": None, "top10_share": 0.2}
    st = _pump_state()
    assert not g.evaluate(st, {**clean, "rugcheck_danger": ["Low Liquidity"]}, 120.0).ok
    assert not g.evaluate(st, {**clean, "rugged": True}, 120.0).ok
