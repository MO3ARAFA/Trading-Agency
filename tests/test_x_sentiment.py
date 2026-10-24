import asyncio
import random

import pytest

from quant_agency import x_sentiment_crawler as xs

CA = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"


def test_text_tools():
    assert xs.normalize_text(f"$WIF 100x gem https://t.co/abc {CA} 0xdAC17F958D2ee523a2206206994597C13D831ec7") == "gem"
    assert xs.text_key("$AAA to the moon 123") == xs.text_key("$BBB to the moon 999")
    assert xs.sentiment("$PEPE to the moon 🚀 bullish") > 0.5
    assert xs.sentiment("rug pull scam, avoid") < -0.5
    assert xs.sentiment("not bullish") < 0 and xs.sentiment("hello world") == 0.0
    assert set(xs.extract_symbols(f"buy $wif now {CA}", ["$WIF", CA, "$BONK"])) == {"$WIF", CA}


def _feed(book, key, now, n, bot, rng, span=300.0):
    for i in range(n):
        t = now - span + span * (i + rng.random()) / n
        if bot:
            tw = xs.Tweet(f"{key}b{i}", t, f"bot{i % 5}", rng.randrange(0, 30), t - rng.uniform(1, 10) * 86400, f"{key} 100x gem sending now 🚀 {CA}", [key])
        else:
            words = ["chart", "strong", "community", "legit", "holders", "growing", "volume", "early", "nice", "memes", "careful", "breakout", "team"]
            text = f"{key} " + " ".join(rng.sample(words, 4))
            tw = xs.Tweet(f"{key}o{i}", t, f"user{rng.randrange(10 ** 6)}", int(10 ** rng.uniform(2, 5)), t - rng.uniform(100, 3000) * 86400, text, [key])
        book.on_tweet(tw)


def test_bot_farm_is_capped_and_organic_ranks_higher():
    rng = random.Random(1)
    b = xs.SocialBook()
    now = 10_000.0
    _feed(b, "$BOT", now, 400, True, rng)
    _feed(b, "$ORG", now, 400, False, rng)
    mb, mo = b.trackers["$BOT"].metrics(now), b.trackers["$ORG"].metrics(now)
    assert mb.dup_share > 0.9 and mb.bot_score > 0.6 and mb.unique_5m <= 5
    assert mo.dup_share < 0.2 and mo.bot_score < 0.3
    sb, so = b.score("$BOT", now, 4.0), b.score("$ORG", now, 4.0)
    assert sb["bot_capped"] and sb["score"] <= 20.0
    assert not so["bot_capped"] and so["score"] > sb["score"] + 20
    assert b.score("$NONE", now, 4.0) is None                                     # unknown is None, never 0


def test_regular_posting_raises_regularity():
    tr = xs.SocialTracker("$X")
    for i in range(60):
        tr.add(xs.Tweet(str(i), 1000.0 + 10 * i, "a", 10, float("nan"), "same"))
    assert tr.metrics(1600.0).regularity > 0.95


def test_score_renormalizes_without_onchain_and_dedups():
    b = xs.SocialBook()
    tw = xs.Tweet("1", 100.0, "a", 1000, 0.0, "$K moon", ["$K"])
    b.on_tweet(tw)
    b.on_tweet(tw)
    assert b.tweets == 1 and b.duplicates == 1
    s = b.score("$K", 100.0, None)
    assert s["onchain_known"] is False and s["parts"]["onchain"] is None


def test_tracker_bounds_and_expiry():
    b = xs.SocialBook(max_symbols=3)
    for i in range(5):
        b.on_tweet(xs.Tweet(str(i), 100.0, "a", 1, 0.0, "x", [f"$S{i}"]))
    assert list(b.trackers) == ["$S2", "$S3", "$S4"]
    tr = xs.SocialTracker("$Y", horizon_s=60.0, maxlen=50)
    for i in range(200):
        tr.add(xs.Tweet(str(i), float(i), "a", 1, 0.0, "x"))
    assert len(tr.ring) == 50 and tr.ring[0][0] >= 199 - 60
    assert b.expire(100.0 + 3601.0) == 3 and not b.trackers


def test_x_api_source_without_token_is_unavailable(monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    src = xs.XApiV2Source(session=None)
    assert not src.status.available and "not set" in src.status.reason
    assert asyncio.run(src.poll(["$WIF"])) == []


def test_x_api_queries_and_parse():
    keys = [f"$TOKEN{i}" for i in range(80)] + [CA]
    qs = xs.XApiV2Source.build_queries(keys, max_len=200)
    assert all(len(q) <= 200 for q in qs) and sum(q.count(" OR ") + 1 for q in qs) == len(keys)
    payload = {"data": [{"id": "9", "text": f"$TOKEN3 looks good {CA}", "author_id": "u1", "created_at": "2026-10-24T12:00:00.000Z"}],
               "includes": {"users": [{"id": "u1", "created_at": "2020-01-01T00:00:00.000Z", "public_metrics": {"followers_count": 1234}}]},
               "meta": {"newest_id": "9"}}
    tw = xs.XApiV2Source.parse(payload, keys)[0]
    assert tw.followers == 1234 and set(tw.symbols) == {"$TOKEN3", CA} and tw.t > tw.author_created_t
