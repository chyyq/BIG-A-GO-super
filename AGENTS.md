# BIG A GO Learning Workflow

When the user says `开始学习`, treat it as an explicit request to run the local evidence-learning workflow.

1. Run `python scripts/learning_store.py scan --year <current year>`.
2. Read `learning/catalog.json` and inspect only newly discovered evidence files plus the related buy/sell dates for the same stocks. Web trade JSON exports may supply explicit outcomes but never replace chart evidence.
3. Associate each trade with its buy chart, sell chart, five-day chart, frozen night review, buy-day market chart, and sell-day market chart.
4. Update `learning/samples.json` with exact ISO `buyDate` and `sellDate`. Never infer a take-profit or stop-loss outcome when the user has not marked it.
5. Records whose planned T+1 date has passed but have no outcome remain `unknown`; exclude them from realized win-rate statistics.
6. Record diagnoses and candidate-rule evidence. Do not promote a rule from one stock or one trading date.
7. Run `python scripts/learning_store.py rebuild` and `python scripts/learning_store.py export`, read `learning/reports/latest.md`, and report new samples, missing evidence, accuracy changes, and rule candidates to the user.
8. Change the production strategy only when the evidence gate is met across at least three buy dates and the change passes the existing regression tests. Log promoted changes in the learning history.

The source images and web trade JSON exports remain in `reference/`. Do not rename, move, or delete the user's evidence files.
