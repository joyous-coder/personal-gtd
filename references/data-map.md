# 数据地图

唯一事实源是滴答清单；Obsidian 只存回顾。**不建独立积分目录，不维护逐任务账本**。

## 滴答清单与分组

| 清单 | ID | 分组 |
| --- | --- | --- |
| 📌 长期计划 | `<list-id-1>` | 长期 / 风险 / 替代 |
| 📌 执行计划 | `<list-id-2>` | 执行 / 收集 / 计划 / 回顾 |
| 📌 健康计划 | `<list-id-3>` | 身体 / 情绪 |
| 📌 成长计划 | `<list-id-4>` | 短期目标 / 中期目标 / 长期目标 |
| 求职阶段 | `<list-id-5>` | — |
| 收集箱 | `<inbox-id>` | — |

ID 只是导航；**不要猜 ID**，要用时从 `dida project list` 或配置里读，读不到就问用户。

## 标签（config `tags`，可在配置里改名）

| 键 | 默认值 | 用途 |
| --- | --- | --- |
| `consumption` | `积分消费` | 支出任务；不计收入，按专注分钟扣 |
| `breakthrough` | `突破` | 突破类，超时不打折 |
| `interrupt_in` | `内在干扰` | 执行时的内部干扰 |
| `interrupt_out` | `外在干扰` | 执行时的外部干扰 |
| `u_event` | `U事件` | 计划外事件 |
| — | `下一步`、`精力好` 等 | 情景/状态标签，按用户既有用法 |

标签只能挂在任务上；0.1.8 没有 `tag list/create`，需要新标签时让用户在 App 里建。

## 习惯

- 共 27 个，名字里已带分值，如 `阅读 $3`、`学习$4 %60`、`运动 $1`。
- 约定：`$N` 是单次全额（任意位置，取第一个），`%N` 是目标 `goal`。
- 罚分触发习惯：`惩罚习惯`（config `penalty_habit`）。
- 名字以实时滴答数据为准（`dida habit list` / Open API）；本文件不复制完整清单，避免过期。

## 专注记录

- 只读。`focus` 接口单次查询 ≤30 天，跨月分段查。
- 时间用 `+0800`；`endTime − startTime` 即分钟数。
- 任务侧 `completedTime` / `dueDate` 是 UTC，读入后统一转 `+0800` 再取 `.date()`。

## frontmatter（日回顾，机器可读的唯一日汇总）

文件：`7-规划回顾/73-回顾/721-日维度/review-YYYY-MM-DD-星期X.md`

| 字段 | 含义 |
| --- | --- |
| `date` | 日期 `YYYY-MM-DD` |
| `kind` | `workday` / `weekend` |
| `earned_task` | 任务得分 |
| `earned_habit` | 习惯得分 |
| `earned_total` | 当日收入 |
| `planned_total` | 计划任务有效分合计 |
| `denominator` | `min(60, max(30, planned_total))` |
| `rate` | 完成率，3 位小数，封顶 1 |
| `late_discount` | 已确认折扣额度 |
| `late_pending` | 还有逾期待确认原因 |
| `reserve` | 每日预留分 |
| `spendable` | 次日可花分 |
| `spent_daily` | 当日扣的日账 |
| `spent_weekly` | 当日扣的周账 |
| `unmet_minutes` | 没扣下的消费分钟 |
| `unmet_points` | 没扣下的消费分 |
| `daily_balance` | 日余额 |
| `weekly_earned` | 本周累计收入 |
| `weekly_spent` | 本周累计消费 |
| `weekly_balance` | 周余额 |
| `weekly_penalty_pending` | 周账待罚 |
| `penalty_applied` | 当日触发触发惩罚 |
| `rule_version` | 规则版本，当前 `v1` |

数值写 `:g`（22 不写 22.0）；布尔写小写 `true` / `false`。

## 目录

| 路径 | 用途 | 写？ |
| --- | --- | --- |
| `7-规划回顾/71-规划/` | 计划（714 周 / 713 月 / 712 年 / 716 项目） | 按确认卡 |
| `7-规划回顾/73-回顾/721-日维度/` | 日回顾，每天一篇 | 是 |
| `7-规划回顾/73-回顾/722-周维度/` | 周回顾 `review-YYYY-Www.md` | 按确认卡 |
| `7-规划回顾/73-回顾/723-月维度/` | 月回顾 `review-YYYY-MM.md` | 按确认卡 |
| `72-回顾`、`72-维度`、`74-项目`、`71-规划/715-项目`、`71-分类` | 空/废弃 | **不写** |

## 配置文件与环境（非敏感项才进 config）

- config：`PERSONAL_GTD_CONFIG`（默认 `~/.config/personal-gtd/config.json`；`init` 生成；示例见 `assets/config.example.json`）。
- 字段：`vault`、`salary`、`reserve`、`daily_cap`、`weekly_cap`、`day_rate`、`week_rate`、`month_budget_rate`、`month_threshold`、`dida_base_url`、`dida_token_path`、`reviews_dir`、`plans_dir`、`penalty_habit`、`tags`。
- 滴答 token：`PERSONAL_GTD_DIDA_CONFIG`（默认 `~/.config/dida-cli/config.json`）的 `access_token`（只读，不打印）。
- FNS 凭据与 vault 目录：只从环境变量读，见 `writing.md`。
- 清单 ID 是**账号相关**的；换账号或换机器后若 ID 不同，运行 `dida project list` 重新取，不要硬编码旧 ID。
