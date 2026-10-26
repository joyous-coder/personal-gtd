---
name: personal-gtd
description: Use when the user wants to run their own 时间管理/GTD loop — capture, screen, plan, execute, review, score, or query points with 滴答清单 and Obsidian.
---

# personal-gtd：个人时间管理闭环

把 `时间管理` 这套理论跑在日常：**执行在滴答清单，产出落在 Obsidian**。AI 负责判断、计算、提醒；人只负责两件事——这件事值不值得做、结果对不对。

工作区：本 skill 所在目录（复制/软链到任意 agent 的 skills 目录即可）。

## 跨 agent / 跨机器

- 核心不依赖 Claude Code：任何能读 Markdown、能跑 Python 3.10+ 的 agent 都可以用。
- 把整个目录复制或软链到该 agent 的 skills 目录；Claude Code 的斜杠命令、Hermes/OpenClaw 的安装方式见 `adapters/`，不要在核心文档里假定某个 agent。
- **不写死机器路径**：vault 用 `PERSONAL_GTD_VAULT_DIR`；Python 用 `PERSONAL_GTD_PYTHON` 或 PATH 里的 `python3`/`python`；滴答 token 用 `PERSONAL_GTD_DIDA_CONFIG`（默认 `~/.config/dida-cli/config.json`）；配置文件用 `PERSONAL_GTD_CONFIG`（默认 `~/.config/personal-gtd/config.json`）。
- 命令统一走 `scripts/gtd`（POSIX）或 `scripts\gtd.cmd`（Windows），它们会自动找 Python。
- **装完先自检**：`scripts/gtd selfcheck`。源码缺一个就退出 1（`.pyc` 不算数：字节码绑定 Python 版本，换机器就废）。跨机器安装的正规途径是 `scripts/gtd pack` 打源码包，解压覆盖后再 `selfcheck`。

## 铁律（违反任何一条就停下重来）

1. **理论以原文为准**：`<THEORY_DIR>/时间管理.md` **及该目录下全部子笔记**（`THEORY_DIR` = `PERSONAL_GTD_THEORY_DIR`，默认 `<vault-root>/我的方法论`）。做判断前先读相关子笔记；本 skill 只做执行化，规则冲突时回原文，不自行发明方法论。索引见 `references/theory.md`。
2. **四段闭环不跳段**：欲望（产生 → 筛选 → 询问确认 → 记录）→ 计划 → 执行 → 回顾。用户只问一段就只做一段，别顺手把后面几段全做掉。
3. **每次写入前给确认卡**：写滴答任务、改标题、写笔记、扣分之前，都先给紧凑确认卡，用户回「过 / 改 / 拒」。没有「过」不写。
4. **不接管番茄计时**：计时由用户在滴答 App 手动开；AI 只读 `focus` 记录，不起计时器、不催、不代打。
5. **删除必须点名**：只有用户明确说出任务名或笔记名才删；先预览再删。不批量删、不自动删、不"顺手清理"。
6. **token 只从环境变量或外部文件读**：`PERSONAL_GTD_FNS_URL` / `PERSONAL_GTD_FNS_TOKEN`；滴答 token 从 `PERSONAL_GTD_DIDA_CONFIG`（默认 `~/.config/dida-cli/config.json`）读。不写进 config、笔记、日志、对话或提交；需要展示时掩码。
7. **做完一段，提示下一阶段**：每段收尾时用**一句话**说明闭环走到哪了、下一步自然是什么（收集完 → 排今天；计划完 → 开始执行；日结完 → 看周账；周结完 → 月结）。**只提示，不自动执行**——不接着把下一阶段做了，用户回「过」才进下一阶段。

## 模式分流

**总入口**：本 skill 本身就是一个入口（Claude Code 里 `/personal-gtd`，Claude Code 命令与 Hermes bundle 里还有 `/gtd` 总入口）——先读下面这张表分流，再进对应模式；分模式入口 `/gtd-capture`、`/gtd-plan`、`/gtd-execute`、`/gtd-review`、`/gtd-settle`、`/gtd-report` 是快捷方式。

| 模式 | 触发词 | 先读 | 动作 |
| --- | --- | --- | --- |
| 收集 | 记一下 / 提醒我 / 我想 / 帮我收 / 别忘了 | `references/capture.md` | 产生 → 筛选 → 确认卡 → 按三层记录 |
| 计划 | 排一下今天 / 明天 / 这周 / 这个项目 | `references/plan.md` | 日程五步（巡检→估算→选择→排序→触发+积分）或项目分解 |
| 执行 | 开始 / 卡住了 / 拖延 / 做不下去 | `references/execute.md` | 30 秒准备 / 干扰标签 / 卡住诊断树 |
| 日结 | 结算 / 日结 / 今天怎么样 | `references/review.md` | `settle` + 读回日回顾，补总结/确认/谋划/一个实验 |
| 周结 | 复盘 / 周结 / 这周怎么样 | `references/review.md` | `report` 出数据 → 周回顾四类对象 + 三个结果 + 一个实验 |
| 月结 | 月结 / 这个月怎么样 | `references/review.md` | `monthly` 出完成率与金额 → 规则审计 + PDCA |
| 查询 | 我还剩多少分 / 这个任务值多少分 | `references/scoring.md` | `balance` / `score` |
| 对账 | 对账 / 审计 | `references/scoring.md` | `audit`（滴答重算 vs 日回顾 frontmatter） |
| 初始化 | 初始化 GTD / 配置 | `references/writing.md` | `init`（配置、writer 模式、回顾目录、版本） |

不确定属于哪一段时，先问；不要靠猜把两段合并执行。

## 命令

在本 skill 根目录运行：

```bash
scripts/gtd <subcommand> ...        # POSIX；自动用 python3/python 或 $PERSONAL_GTD_PYTHON
scripts\gtd.cmd <subcommand> ...    # Windows
```

| 命令 | 作用 | 是否写文件 |
| --- | --- | --- |
| `scripts/gtd init` | 初始化配置、报告 writer 模式、补齐回顾目录、检查 python/dida 版本 | 可能建配置与目录 |
| `scripts/gtd score --title '写周报' --priority 5 --size L` | 单任务算分，输出 JSON（`explicit_points` / `effective_points` / `final_points` / `late`） | 否 |
| `scripts/gtd settle --date 2026-10-25 [--dry-run] [--late-subjective ID1,ID2] [--force]` | 结算一天、写日回顾（已存在时默认拒绝，`--force` 才覆盖） | 是（`--dry-run` 只打印 JSON） |
| `scripts/gtd balance --date 2026-10-25` | 打印 `spendable` / `weekly_balance` / `spent_daily` / `spent_weekly` | 否 |
| `scripts/gtd backfill --from 2026-10-19 --to 2026-10-25 [--dry-run] [--force]` | 按日期升序补齐**缺失**的日回顾（已存在则跳过；`--force` 覆盖） | 是（`--dry-run` 否） |
| `scripts/gtd audit --date 2026-10-25 [--late-subjective ID1,ID2]` 或 `--from ... --to ...` | 用滴答重算与 frontmatter 对账（含周账三项），不一致退出码 1 | 否 |
| `scripts/gtd report --from 2026-10-19 --to 2026-10-25` | 打印周/区间回顾 Markdown | 否（要落盘时按确认卡另写） |
| `scripts/gtd monthly --month 2026-10` | 打印月完成率与金额 | 否（同上） |
| `scripts/gtd selfcheck [--json]` | 检查安装完整性：源码齐不齐、滴答在不在、写入后端配没配；缺源码退出 1 | 否 |
| `scripts/gtd pack [--out FILE] [--name NAME] [--list]` | 打出跨机器安装用的源码包（zip，不含 `__pycache__`/`.pyc`） | 是（写 zip 到 `--out`） |

约定：

- 日期一律 `YYYY-MM-DD`；月份 `YYYY-MM`。
- `--size` 只影响 `score` 的**预填**：`S`=1（默认）、`M`=1.5、`L`=2，乘优先级底分；标题已有 `$N` 时 `$N` 胜出。结算不乘规模（没写 `$` 就按优先级底分），见 `references/scoring.md`。
- `settle` / `balance` / `backfill` / `audit` / `report` / `monthly` 接受 `--vault-dir DIR`，临时覆盖 `PERSONAL_GTD_VAULT_DIR`（只对本次生效）。`init` 不接这个参数，目录取自 `PERSONAL_GTD_VAULT_DIR`。
- 退出码：0 成功；1 配置/数据/对账错误；2 参数错误。
- **数字只从命令输出取**。不手算、不凭记忆报余额，也不在没跑命令时猜分。
- `settle` 写之前先跑 `--dry-run` 把数字给用户看；用户确认后才真写。
- **`settle` 默认拒绝覆盖已存在的日回顾**：打印 `已存在 <path>；如需覆盖请加 --force` 并退出 1，不写任何东西。正文里有人写的总结/确认/谋划/身份反馈只有 `--force` 才会被整篇替换——更正账本时先读旧内容，再在确认卡里说明「将覆盖正文」。
- **`--dry-run` 不读前一天账本**：`weekly_earned` / `weekly_spent` / `weekly_balance` / `weekly_penalty_pending` / `spent_daily` / `spent_weekly` / `unmet_minutes` / `unmet_points` 都从 0 起算，只能当参考；`earned_*` / `planned_total` / `denominator` / `rate` / `spendable` / `late_*` 与真实结算一致。要看准余额，先确认后真跑再用 `balance` 读回。
- **前一天没有日回顾时**，真实结算会提示「前一天没有日回顾，周账从 0 起算」；**读前一天笔记失败**（后端/HTTP 故障）则直接退出 1、不写入——不能把故障当成「没有」。
- **`backfill` 默认只补缺失日期**：已存在的日回顾一律跳过（正文里有人写的总结/确认/谋划/身份反馈，重算会冲掉）。只有用户明确要求覆盖时才加 `--force`；配置了写入后端时，`--dry-run` 也会先检查存在性并打印「跳过」。

## 数据落点

只有两个地方，**不建独立积分目录、不维护逐任务账本**：

1. **滴答清单**（唯一事实源）：任务标题末尾 `$N`、习惯名里的 `$N`、`积分消费` 标签、专注记录、完成状态。
2. **Obsidian 回顾笔记**：

```
<VAULT>/
└── 7-规划回顾/
    ├── 71-规划/                 # 计划（714 周 / 713 月 / 712 年 / 716 项目）
    └── 73-回顾/                 # 活目录
        ├── 721-日维度/review-YYYY-MM-DD-星期X.md   # 每天一篇，唯一日汇总
        ├── 722-周维度/review-YYYY-Www.md
        └── 723-月维度/review-YYYY-MM.md
```

- 日回顾 frontmatter 是当天唯一的机器可读账本；正文写明细摘要。月/周视图从日回顾 frontmatter 聚合，不另存账本。
- 只有带 `date` + `earned_total` 的 frontmatter 才算账本；`721-日维度` 里老的自适应日总结（无 frontmatter）会被 `balance` / `report` / `monthly` / `audit` 判为「不是账本笔记，已跳过」，**不会**被当成完成率 0 的一天。
- 幂等：同一天重跑覆盖同一篇，不追加第二份；但**默认拒绝**覆盖已存在的日回顾，`--force` 才重写（见上）。
- **不写**废弃目录：`72-回顾`、`72-维度`、`74-项目`、`71-规划/715-项目`、`71-分类`。

## 写入后端（必须先配一个）

按固定顺序选，**不做别的假设**：

1. `PERSONAL_GTD_FNS_URL` 与 `PERSONAL_GTD_FNS_TOKEN` 都有值 → **FNS**（服务端 vault；失败时若配了 `PERSONAL_GTD_VAULT_DIR` 自动回退文件夹）。
2. 否则 `PERSONAL_GTD_VAULT_DIR` 有值 → **folder**（直接写本地 vault）。
3. 都没有 → **报错**，列出三个变量名，不写任何东西。

**没有后端时只有 `score`、`settle --dry-run`、`init` 可用**；`settle`（非 `--dry-run`）、`balance`、`backfill`、`audit`、`report`、`monthly` 六条命令都会以退出码 1 失败（它们要读/写笔记）。`init` 在这种情况会打印「未配置：现在还不能写入」。

一次性设置（二选一，设置后重启你的 agent）：

```bash
# Windows
setx PERSONAL_GTD_VAULT_DIR "<vault-root>"
# macOS / Linux
export PERSONAL_GTD_VAULT_DIR="<vault-root>"
```

或写进你的 agent 的 env 设置（例如 Claude Code 的 `~/.claude/settings.json`，见 `adapters/claude-code/INSTALL.md`）：

```json
{ "env": { "PERSONAL_GTD_VAULT_DIR": "<vault-root>" } }
```

只给单次命令临时指定（不动全局设置，测试/补账用）：

```bash
PERSONAL_GTD_VAULT_DIR="<vault-root>" scripts/gtd settle --date 2026-10-25 --dry-run
# 或
scripts/gtd settle --date 2026-10-25 --vault-dir "<vault-root>"
```

**不静默套用默认 vault 路径**：环境变量缺失就报错，绝不猜。细节（FNS 端点、DELETE body 坑、路径穿越防护、环境变量设在哪）见 `references/writing.md`。config 只放非敏感项（vault、工资、预留分等），token 永不入 config。

## 验证清单（每次答复前自查）

- [ ] 所有写操作都出过确认卡，且用户回过「过」。
- [ ] 报出的每个数字都来自 `gtd.py` 输出（或用户原话），没有手算/猜测。
- [ ] 没有猜 token、任务 ID、清单 ID；缺就查配置或问用户。
- [ ] 没有写进废弃目录；日回顾只在 `721-日维度`。
- [ ] 没有在未确认时用 `backfill` / `settle --force` 覆盖已存在的日回顾；`settle` 被拒绝（退出 1）时没硬加 `--force`，需要覆盖时才加，且先读一遍旧内容。
- [ ] 用 `score` 预填新任务时带了 `--size`（S/M/L），没有手算「优先级底分 × 规模」。
- [ ] 结算过主观超时的日子，`audit` 带了同一份 `--late-subjective IDS`。
- [ ] 删除是用户点名的，且先预览过。
- [ ] 写完读过一遍（`balance` / 读回笔记），确认落点和内容正确。
- [ ] token 没有出现在输出、笔记或命令回显里。

## 参考资料

| 文件 | 内容 |
| --- | --- |
| `references/theory.md` | 四段闭环摘要、原文与子笔记索引 |
| `references/capture.md` | 产生 → 筛选 → 确认卡 → 三层记录；五块关注点 |
| `references/plan.md` | 日程五步、路线聚类、缓冲、WBS 补充项、0.1.8 字段限制 |
| `references/execute.md` | 30 秒准备、干扰标签、时刻了解、卡住诊断树 |
| `references/review.md` | 日/周/月三动作、一个实验、规则审计、语气 |
| `references/scoring.md` | 公式、示例、边界（习惯比例、无 `$`、去重、重复任务、消费、惩罚、封顶） |
| `references/data-map.md` | 清单 ID、分组、标签、习惯、目录、frontmatter 字段 |
| `references/writing.md` | FNS 端点（含 DELETE body 坑）、文件夹模式、环境变量、回退顺序 |
