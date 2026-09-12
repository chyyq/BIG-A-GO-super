# 本地学习状态

- 更新时间：2026-09-12T16:12:57+08:00
- 已归档图片：36
- 已识别网页交易快照：5
- 结构化交易样本：42
- 已标注结果：29
- 待补结果：13
- 实际止盈率：55.17%
- 有确认成交价样本平均收益：--
- 有确认成交价样本正收益率：--
- 第一止盈区命中率：42.86%
- 次日最大涨幅达到3%：45.00%

## 开盘形态

| 形态 | 样本 | 已标注 | 止盈率 | 平均MFE |
| --- | ---: | ---: | ---: | ---: |
| flat_open_failed_followthrough | 2 | 1 | 0.00% | 0.98% |
| flat_open_followthrough | 5 | 5 | 80.00% | 3.59% |
| gap_down_recovery | 2 | 2 | 0.00% | 0.33% |
| gap_down_recovery_then_fade | 1 | 0 | -- | 2.91% |
| gap_down_weak | 2 | 2 | 0.00% | -0.83% |
| gap_up_failed_followthrough | 6 | 2 | 100.00% | 4.33% |
| gap_up_fast_recovery_limit | 1 | 0 | -- | 2.84% |
| strong_open_extension | 2 | 0 | -- | 5.53% |
| unknown | 21 | 17 | 58.82% | 0.00% |

## 规则候选

- `OPENING_CONFIRMATION_OVERRIDE`：阶段规则已部署，继续验证，证据 9 笔，其中真实结果 0 笔，覆盖 2 个买入日。
- `FREEZE_OVERNIGHT_TARGET`：阶段规则已部署，继续验证，证据 6 笔，其中真实结果 0 笔，覆盖 2 个买入日。
- `PRIOR_TREND_PERSISTENCE_VETO`：阶段规则已部署，继续验证，证据 4 笔，其中真实结果 0 笔，覆盖 1 个买入日。
- `EXECUTABLE_TARGET_BAND`：阶段规则已部署，继续验证，证据 4 笔，其中真实结果 2 笔，覆盖 2 个买入日。
- `WEAK_EXECUTION_MONOTONIC`：阶段规则已部署，继续验证，证据 4 笔，其中真实结果 0 笔，覆盖 2 个买入日。
- `NEUTRAL_EXIT_0945_STRONG_EXIT_1000`：继续积累，证据 9 笔，其中真实结果 0 笔，覆盖 2 个买入日。
- `AM_TOP_SAME_DAY_LIMIT_PRECISION`：阶段规则已部署，继续验证，证据 9 笔，其中真实结果 9 笔，覆盖 5 个买入日。
- `TAIL_T3_SAME_DAY_RANKING_CALIBRATION`：继续积累，证据 8 笔，其中真实结果 8 笔，覆盖 4 个买入日。
- `TAIL_RECOVERY_MA5_EXTENSION_VETO`：阶段规则已部署，继续验证，证据 5 笔，其中真实结果 5 笔，覆盖 3 个买入日。
- `T1_GAP_DOWN_ONE_PCT_DEFENSIVE_EXIT`：继续积累，证据 4 笔，其中真实结果 4 笔，覆盖 3 个买入日。

## 买入策略分组

| 策略 | 样本 | 已标注 | 止盈率 | 平均确认成交收益 | 买入日触板率 | 买入日封板率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AM_TOP | 9 | 9 | 55.56% | -- | -- | 0.00% |
| TAIL_MAIN | 24 | 20 | 55.00% | -- | -- | -- |
| unknown | 9 | 0 | -- | -- | -- | -- |

## 买入入口证据

| 买入入口 | 样本 | 已标注 | 买入日 | 止盈率 | 平均确认成交收益 | 买入日封板率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| [AM_TOP] early lift-off entry | 7 | 7 | 4 | 57.14% | -- | 0.00% |
| [AM_TOP] open-strength entry | 2 | 2 | 1 | 50.00% | -- | 0.00% |
| [TAIL_MAIN] T3 mid-trend breakout | 22 | 18 | 12 | 55.56% | -- | -- |
| [TAIL_MAIN] T5 first pullback reclaim | 2 | 2 | 2 | 50.00% | -- | -- |
| unknown | 9 | 0 | 2 | -- | -- | -- |

## 缺失证据

- `actual_outcome`：13 笔
- `buy`：21 笔
- `entry_strategy`：9 笔
- `five_day`：30 笔
- `market_buy`：21 笔
- `market_sell`：21 笔
- `night_review`：23 笔
- `sell`：21 笔
- `valid_frozen_night_plan`：6 笔
