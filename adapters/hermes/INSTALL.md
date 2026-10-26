# Hermes adapter

Hermes 没有 Claude Code 那种“`~/.claude/commands/*.md` 自定义提示命令”。它的对应机制是 **skill bundles**：一个 bundle 是一个 `/slash` 命令，加载一个或多个 skill，并可以带一段 `instruction` 预置到 skill 内容前。

所以 Hermes 上可以做到 `/gtd-capture`、`/gtd-plan`、`/gtd-review`、`/gtd-settle` 等确定入口——用 bundle，而不是 command 文件。

## 1. 安装核心 skill

把核心目录复制或软链到 Hermes 的 skills 目录（`<HERMES_HOME>/skills`；本机是 `~/AppData/Local/hermes/skills`，其他机器以 `hermes status` / 配置为准）：

```powershell
# Windows（junction，单一源）
New-Item -ItemType Junction -Path "<HERMES_HOME>\skills\personal-gtd" -Target "<SKILL_DIR>"
```

```sh
# macOS / Linux
ln -s "<SKILL_DIR>" "<HERMES_HOME>/skills/personal-gtd"
```

确认：

```bash
hermes skills list | grep personal-gtd
```

### 1b. 跨机器安装：走源码包（推荐）

直接从另一台机器同步 vault 目录过来，容易出两件事：目录里的 `__pycache__/*.pyc`（绑定 Python 版本，换机器就 import 不了）跟着跑过去；以及只同步过去一部分文件（见过 `scoring.py`、`report.py`、`review_note.py` 只剩 `.pyc`，源码没跟上）。所以跨机器用源码包：

```bash
# 源机器（skill 所在目录）
scripts/gtd pack --out personal-gtd.zip

# 目标机器
unzip personal-gtd.zip -d "<HERMES_HOME>/skills"    # 得到 <HERMES_HOME>/skills/personal-gtd/
chmod +x "<HERMES_HOME>/skills/personal-gtd/scripts/gtd"
"<HERMES_HOME>/skills/personal-gtd/scripts/gtd" selfcheck
```

`selfcheck` 输出「源码模块：8/8 齐全」才算装好；缺源码它退出 1，`scripts/gtd` 也会直接退出 2 并点名缺哪个模块。

如果这台机器的 skill 是跟着笔记同步（fast-note-sync 之类）来的，把 `__pycache__` 和 `*.pyc` 排除出同步范围，否则字节码会反复跑回来。

## 2. 安装 bundles

把本目录 `bundles/*.yaml` 复制到 `<HERMES_HOME>/skill-bundles/`：

```bash
mkdir -p "<HERMES_HOME>/skill-bundles"
cp bundles/*.yaml "<HERMES_HOME>/skill-bundles/"
hermes bundles reload
hermes bundles list
```

或者用命令逐个创建（`--instruction` 就是 bundle 里那段模式说明）：

```bash
# 总入口：判断意图后进对应模式（推荐先建这个）
hermes bundles create gtd --skill personal-gtd \
  --description "personal-gtd 总入口：判断意图后进入对应模式" \
  --instruction "使用 personal-gtd 的总入口。先读 SKILL.md 的模式分流表，把用户输入归到某一模式（收集/计划/执行/日结/周结/月结/查询/对账/初始化）；判断不了就问用户是哪一段，不要猜。再读该模式的 reference 执行。写入前给确认卡；收尾时按 SKILL.md 铁律提示下一阶段，只提示不自动执行。"

hermes bundles create gtd-capture --skill personal-gtd \
  --description "用 personal-gtd 收集、筛选并记录一个欲望" \
  --instruction "使用收集模式；读 references/capture.md；写入前给确认卡。"

hermes bundles create gtd-plan --skill personal-gtd \
  --description "用 personal-gtd 排今天/明天/这周或拆项目" \
  --instruction "使用计划模式；读 references/plan.md；排序考虑路线聚类。"

hermes bundles create gtd-execute --skill personal-gtd \
  --description "用 personal-gtd 处理开始/卡住/拖延" \
  --instruction "使用执行模式；读 references/execute.md；不接管番茄计时。"

hermes bundles create gtd-review --skill personal-gtd \
  --description "用 personal-gtd 做日结/周结/月结" \
  --instruction "使用回顾模式；读 references/review.md；先跑 scripts/gtd 取数。"

hermes bundles create gtd-settle --skill personal-gtd \
  --description "用 personal-gtd 结算某一天（先 dry-run）" \
  --instruction "使用日结模式；先 settle --dry-run；确认后才写；不要覆盖已有日回顾。"

hermes bundles create gtd-report --skill personal-gtd \
  --description "用 personal-gtd 查看周报/月报数据" \
  --instruction "运行 report/monthly；只打印，不写文件。"
```

之后在 Hermes CLI 或 gateway 里：

```
/gtd 记一下明天下午去医院        # 总入口：自动分流到收集模式
/gtd-capture 记一下明天下午去医院
/gtd-plan 排一下明天
/gtd-review 这周怎么样
/gtd-settle 2026-10-25
/gtd-report 2026-10
```

`/<bundle>` 会把 `personal-gtd` 和该模式的 instruction 一起加载；bundle 与 skill 同名时 bundle 优先。

## 3. 环境变量

同 `adapters/README.md`。Hermes 的进程环境里要有 `PERSONAL_GTD_VAULT_DIR`（或 FNS 两个变量），否则六条读写命令会退出 1；`score`、`settle --dry-run`、`init` 不需要后端。

Hermes 若用 cron/automation 定时调用，仍要遵守 `SKILL.md` 的确认卡规则：自动任务只跑 `--dry-run`/报告，不自动覆盖人工回顾。

## 4. 装完自检

```bash
scripts/gtd selfcheck          # 人类可读
scripts/gtd selfcheck --json   # 机器可读
```

看三件事：**源码模块 8/8 齐全**（`.pyc` 不算数）、滴答 CLI 与 token 在不在、写入后端（FNS 或文件夹）配没配。后端没配时 `settle`/`balance`/`backfill`/`audit`/`report`/`monthly` 会退出 1，只有 `score`、`settle --dry-run`、`init`、`selfcheck`、`pack` 能跑。

## 5. 已有残安装怎么修

症状：`selfcheck` 报某模块缺源码，或 `scripts/gtd` 报「安装不完整：缺少源码 scoring」。

原因：那份 skill 是从同步里来的，源码没跟上，只剩 `__pycache__` 里的字节码。字节码绑定 Python 版本，所以「本机能跑、换台机器就不行」。

修法（任选其一）：

1. **重装（推荐）**：源机器 `scripts/gtd pack --out personal-gtd.zip`，拷过去解压覆盖整个 skill 目录，再 `selfcheck`。
2. **补源码**：源机器的 `scripts/lib/*.py` 是全的（服务端也有），把这几个文件拷到目标机器的同名位置：
   ```bash
   cp scripts/lib/scoring.py scripts/lib/report.py scripts/lib/review_note.py \
      "<HERMES_HOME>/skills/personal-gtd/scripts/lib/"
   ```
3. **清字节码**：删掉目标机器 skill 目录里的 `__pycache__`（源码齐了就不需要它们），并把 `__pycache__` / `*.pyc` 排除出同步范围，免得再被带回来。

不要靠"指定某个 Python 版本"绕过去——那是让残安装看起来能用，换个版本还会再炸一次；正确做法是让源码齐全。
