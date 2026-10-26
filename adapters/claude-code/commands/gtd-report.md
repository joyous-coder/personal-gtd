---
description: 用 personal-gtd 查看周报/月报数据
argument-hint: <from-to 或 YYYY-MM>
---
使用 `personal-gtd` skill 的「周结/月结」模式，查看：$ARGUMENTS

运行 `scripts/gtd report --from ... --to ...` 或 `scripts/gtd monthly --month ...`，把 Markdown 输出解释给用户。`report`/`monthly` 只打印，不写文件；要落盘时先给确认卡。

收尾时按 SKILL.md 铁律提示下一阶段（只提示，不自动执行）。
