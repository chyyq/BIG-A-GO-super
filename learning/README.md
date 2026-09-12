# 本地自主学习库

这套目录只做本地实盘证据积累，不会在无人复核时直接改动正式选股参数。

## 触发方式

后续在项目对话中说 `开始学习`。系统会扫描 `reference/` 中的新图片和网页导出的交易 JSON，按哈希去重，补充结构化交易样本并重建统计报告。

手机端交易记录需要进入本地学习时，在网页点击“导出同步码”，再点“导出 JSON”，将生成的 `BIG-A-GO-trades-日期.json` 放入 `reference/`。系统只采纳你在网页明确点击的止盈/止损结果；未标记记录仍为 `unknown`。

建议每批资料放在独立日期目录，文件名使用：

- `股票名-买入盘MMDD.jpg`
- `股票名-卖出盘MMDD.jpg`
- `股票名-五日盘MMDD.jpg`
- `股票名-夜间复盘MMDD.jpg`
- `MMDD大盘.jpg`

买入日、卖出日必须写在文件名或目录中。网页里的止盈/止损结果是实际胜负标签；没有结果标签的过期记录只归档，不参与胜率计算。

## 数据文件

- `catalog.json`：图片路径、哈希、类型、日期和股票名索引。
- `samples.json`：每笔交易的结构化事实、夜间计划、次日表现和诊断。
- `model_state.json`：自动汇总的胜率、目标命中率、MFE/MAE和开盘形态统计。
- `reports/latest.md`：最近一次可读报告。
- `history/events.jsonl`：每次扫描和重建的时间线。
- `exports/latest.json`、`exports/trades.csv`：需要拉取或进一步分析时使用的完整导出。

## 手动查看

```powershell
python scripts/learning_store.py status
python scripts/learning_store.py run --year 2026
```

规则先作为候选积累证据。只有覆盖至少三个买入日、达到样本门槛且已有足够真实结果标签后，才允许进入正式策略。

除本说明文件外，`learning/` 的实盘数据已加入 `.gitignore`，默认只保留在当前电脑，不随公开网页上传。
