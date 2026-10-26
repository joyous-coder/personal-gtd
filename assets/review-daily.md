---
date: {{date}}
kind: {{kind}}
earned_task: {{earned_task}}
earned_habit: {{earned_habit}}
earned_total: {{earned_total}}
planned_total: {{planned_total}}
denominator: {{denominator}}
rate: {{rate}}
late_discount: {{late_discount}}
late_pending: {{late_pending}}
reserve: {{reserve}}
spendable: {{spendable}}
spent_daily: {{spent_daily}}
spent_weekly: {{spent_weekly}}
unmet_minutes: {{unmet_minutes}}
unmet_points: {{unmet_points}}
daily_balance: {{daily_balance}}
weekly_earned: {{weekly_earned}}
weekly_spent: {{weekly_spent}}
weekly_balance: {{weekly_balance}}
weekly_penalty_pending: {{weekly_penalty_pending}}
penalty_applied: {{penalty_applied}}
rule_version: {{rule_version}}
---
# 日回顾 {{date}} {{weekday}}

## 总结

- 类型：{{kind}}
- 得分：{{earned_total}}（任务 {{earned_task}} + 习惯 {{earned_habit}}）
- 分母：{{denominator}}（计划合计 {{planned_total}}）
- 完成率：{{rate}}
- 超时待确认：{{late_pending}}

## 确认

- 待确认折扣额度：{{late_discount}} 分

## 谋划

- [ ]

## 积分

### 今日明细

{{items}}

### 消费

{{consumption}}

今日消费 {{spent_daily}} 分，本周消费 {{spent_weekly}} 分。

### 明日可花

明日可花 **{{spendable}}** 分（已扣预留 {{reserve}} 分）。

### 余额

- 日余额：{{daily_balance}} 分
- 周余额：{{weekly_balance}} 分（本周赚 {{weekly_earned}}、花 {{weekly_spent}}）

## 身份反馈

（一句话：你今天是什么样的人）

## 一个实验

（只改一个变量，明天看数据）
