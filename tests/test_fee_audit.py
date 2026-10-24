import pytest

from quant_agency import fee_audit as fa


def _word(x):
    return f"{x:064x}"


def test_decode_fills_and_implied_rate():
    # 10 shares bought for 4.00 USDC (p = 0.4) with a 0.07 crypto fee: 10 x 0.07 x 0.4 x 0.6 = 0.168
    data = "0x" + "".join(_word(x) for x in (0, 123, 4_000_000, 10_000_000, 168_000, 0, 0))
    rc = {"logs": [{"topics": [fa.FILL_TOPIC, "0x" + "ab" * 32, "0x" + "0" * 24 + "11" * 20, "0x" + "0" * 24 + "22" * 20], "data": data},
                   {"topics": ["0xdeadbeef"], "data": "0x"}]}
    fills = fa.decode_fills(rc)
    assert len(fills) == 1 and fills[0]["token"] == "123" and fills[0]["maker"] == "0x" + "11" * 20
    assert fills[0]["usdc"] == pytest.approx(4.0) and fills[0]["fee"] == pytest.approx(0.168)
    assert fa.implied_rate(fills[0]) == pytest.approx(0.07)
    assert fa.implied_rate({"usdc": 0, "shares": 0, "fee": 0}) is None
