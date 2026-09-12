# BIG A GO Learning Workflow

When the user says `开始学习`, treat it as an explicit request to run the local evidence-learning workflow.

1. Run `python scripts/learning_store.py scan --year <current year>`.
2. Read `learning/catalog.json` and inspect only newly discovered evidence files plus the related buy/sell dates for the same stocks. Web trade JSON exports may supply explicit outcomes but never replace chart evidence.
3. For newly discovered trades, run `python scripts/learning_market.py` with the applicable `--since` date. Use its public Eastmoney daily K-line and Yahoo Finance 5-minute K-line evidence to verify the buy day, T+1 before 10:00, MA5, and both trading days' Shanghai/Shenzhen market conditions. Preserve the fetched evidence under `learning/market_evidence/`.
4. Associate each trade with its buy chart, sell chart, five-day chart, frozen night review, buy-day market chart, and sell-day market chart.
5. Update `learning/samples.json` with exact ISO `buyDate` and `sellDate`. Treat the user's outcome button as the authoritative categorical result for a T+1 sale before 10:00; `resultMarkedAt` is only the later recording time. Never treat the mark-time quote as an exact execution price, and never infer an unmarked outcome.
6. Records whose planned T+1 date has passed but have no outcome remain `unknown`; exclude them from realized win-rate statistics.
7. Record diagnoses and candidate-rule evidence. Do not promote a rule from one stock or one trading date.
8. Run `python scripts/learning_store.py rebuild` and `python scripts/learning_store.py export`, read `learning/reports/latest.md`, and report new samples, missing evidence, accuracy changes, and rule candidates to the user.
9. Change the production strategy only when the evidence gate is met across at least three buy dates and the change passes the existing regression tests. Log promoted changes in the learning history.

The source images and web trade JSON exports remain in `reference/`. Do not rename, move, or delete the user's evidence files.
