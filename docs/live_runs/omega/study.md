### Every momentum signal on the recorded live tapes

`omega_signal_study.py` on 4 recorded live tapes (1.75 h; the first three are the sessions restarted after the bug fixes noted in §5, the fourth is the 60-min session above): **192 signals on 135 tokens**, at most one per token per 60 s, same conditions as the engine. Entry at the curve price as of +0.8 s, exit as of +h; round-trip cost of a 5 USD trade = 2.93 % (SOL 101.98 USD). Standard errors clustered by token.

| horizon | n | tokens | gross mean | ± s.e. | median | p10 / p90 | net mean | t (net) | share beating the cost |
|---|---|---|---|---|---|---|---|---|---|
| 10 s | 191 | 135 | -3.14 % | 1.14 % | +0.00 % | -21.1 % / +8.7 % | -6.07 % | -5.32 | 24 % |
| 30 s | 187 | 131 | -5.30 % | 2.05 % | -1.55 % | -35.5 % / +15.5 % | -8.23 % | -4.01 | 28 % |
| 60 s | 184 | 129 | -7.72 % | 2.18 % | -4.81 % | -39.0 % / +15.6 % | -10.65 % | -4.89 | 24 % |
| 120 s | 176 | 121 | -8.34 % | 3.23 % | -10.99 % | -42.5 % / +19.8 % | -11.27 % | -3.49 | 23 % |
| 300 s | 149 | 97 | -1.68 % | 6.34 % | -13.10 % | -44.6 % / +26.8 % | -4.61 % | -0.73 | 28 % |

The gross move is negative at every horizon up to 2 minutes. About a quarter of the signals beat the cost, which is what lets a few trades look good, but the typical signal loses. At 300 s the mean recovers because of a few very large winners (p90 +27 %); the median is −13 %. That is the lottery-ticket shape of meme tokens, not an edge a 2-5 USD account can harvest reliably.
