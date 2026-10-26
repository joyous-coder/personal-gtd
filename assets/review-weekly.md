---
from: {{from}}
to: {{to}}
days: {{days}}
earned_total: {{earned_total}}
planned_total: {{planned_total}}
rate: {{rate}}
weekday_rate: {{weekday_rate}}
weekend_rate: {{weekend_rate}}
rule_version: v1
---
# 周回顾 {{from}} ~ {{to}}

## 趋势

- 积分：收入 {{earned_total}} 分，计划合计 {{planned_total}} 分
- 完成率：{{rate}}（工作日 {{weekday_rate}} / 双休 {{weekend_rate}}；各自按日算完成率再合并，空的一侧不按 0 算）
- 消费：日账 {{spent_daily}} 分 / 周账 {{spent_weekly}} 分
- 有日回顾 {{days}} 天

### 每日

| 日期 | 星期 | 类型 | 收入 | 计划 | 完成率 |
| --- | --- | --- | --- | --- | --- |
{{daily_rows}}

## 四类对象

- 过期未处理：
- 项目：
- 将来也许：
- 日程表：

## 卡住的项目

- [ ] 有没有下一步：

## 下周三个结果

1.
2.
3.

## 一个实验

（只改一个变量，下周看数据）

## 容量检查

（不要把空闲时间填满）
