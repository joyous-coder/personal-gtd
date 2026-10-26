---
description: 用 personal-gtd 结算某一天（先 dry-run）
argument-hint: <YYYY-MM-DD>
---
使用 `personal-gtd` skill 的「日结」模式，结算日期：$ARGUMENTS

先运行：

```sh
scripts/gtd settle --date <YYYY-MM-DD> --dry-run
```

把 DayScore 的数字给用户看。只有用户确认后才真写；如果当天日回顾已存在，不要覆盖，除非用户明确要求 `--force`。写入后再用 `balance` 读回余额。

收尾时按 SKILL.md 铁律提示下一阶段（只提示，不自动执行）。
