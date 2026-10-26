# personal-gtd

> 把「时间管理 / GTD」四段闭环跑在日常：**执行在滴答清单（TickTick），产出落在 Obsidian**。
> AI 负责判断、计算、提醒；人只负责两件事——这件事值不值得做、结果对不对。

一个 agent 无关的 skill：核心是 `SKILL.md` + `references/` + `scripts/` + `assets/`，
任何能读 Markdown、能跑 Python 3.10+ 的 agent 都可以直接用（Claude Code / Hermes / OpenClaw / 其它）。

## 它做什么

```
①欲望  产生 → 筛选 → 询问确认 → 记录
②计划  巡检 → 估算 → 选择 → 排序（路线聚类）→ 指定触发 + 分配积分
③执行  30 秒准备 → 干扰打标签 → 卡住诊断树 → 收尾
④回顾  日结 / 周结 / 月结 → 完成率、积分、PDCA
```

积分不是手算的：任务标题末尾 `$N`、习惯名里的 `$N` 会被脚本解析，
日/周/月账由 `scripts/gtd` 统一结算并写进 Obsidian 的回顾笔记。
规则细节见 `references/scoring.md`，方法论原文见 `references/theory.md`。

## 装

```bash
# 1. 拷到你的 agent 的 skills 目录
cp -R <此目录> ~/.claude/skills/personal-gtd        # Claude Code
cp -R <此目录> ~/.hermes/skills/personal-gtd        # Hermes

# 2. 自检（源码必须 8/8 齐全；缺源码退出 1）
scripts/gtd selfcheck
```

Windows 用 `scripts\gtd.cmd`。各 agent 的详细安装（含斜杠命令 / bundle）见 `adapters/`。

跨机器传这个 skill 时**用源码包**，别直接同步目录：

```bash
scripts/gtd pack --out personal-gtd.zip   # 只含源码，不含 __pycache__/*.pyc
```

> 目录里如果混进了 `__pycache__` 里的字节码，它会绑定某个 Python 版本，
> 换台机器就 `import` 不了——`selfcheck` 会把这种情况报出来。

## 环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `PERSONAL_GTD_VAULT_DIR` | 固定文件夹写入的 vault 根 | 无 |
| `PERSONAL_GTD_FNS_URL` / `PERSONAL_GTD_FNS_TOKEN` | FNS REST 写入（服务端 vault） | 无 |
| `PERSONAL_GTD_CONFIG` | 配置文件 | `~/.config/personal-gtd/config.json` |
| `PERSONAL_GTD_DIDA_CONFIG` | 滴答 token 文件 | `~/.config/dida-cli/config.json` |
| `PERSONAL_GTD_PYTHON` | Python 解释器 | `python3`，否则 `python` |
| `PERSONAL_GTD_DIR` | GTD 输出的根目录（相对 vault 根） | `7-规划回顾`；`init` 在它下面建 `1-规划/` 与 `2-回顾/{1-日维度,2-周维度,3-月维度}/` |

写入后端二选一（FNS 优先，folder 兜底）：`PERSONAL_GTD_FNS_URL` + `PERSONAL_GTD_FNS_TOKEN`
或 `PERSONAL_GTD_VAULT_DIR`。**都没配时**，只有 `score` / `settle --dry-run` / `init` /
`selfcheck` / `pack` 能跑，其余六条命令会以退出码 1 失败（它们要读写笔记）。

token 只从环境变量或外部文件读，**永不写进 config、笔记、日志或提交**。

## 依赖

- Python 3.10+（只用标准库，无第三方依赖）
- 滴答 CLI `dida`（Node ≥ 20）：`npm i -g @suibiji/dida-cli`
- 滴答 Open API token：放在 `~/.config/dida-cli/config.json` 的 `access_token`
- 一个 Obsidian vault（写回顾用）

## 命令

| 命令 | 作用 | 写文件 |
|---|---|---|
| `scripts/gtd init` | 初始化配置、报告写入后端、补齐回顾目录、检查 python/dida 版本 | 可能建配置与目录 |
| `scripts/gtd score --title '写周报' --priority 5 --size L` | 单任务算分，输出 JSON | 否 |
| `scripts/gtd settle --date 2026-10-25 [--dry-run] [--force]` | 结算一天、写日回顾（已存在时默认拒绝） | 是 |
| `scripts/gtd balance --date 2026-10-26` | 「今日可花」（取前一天账本，今天没结算也能答）/「明日可花」/ 周余额 / 消费 | 否 |
| `scripts/gtd backfill --from 2026-10-19 --to 2026-10-25` | 按日期升序补齐缺失的日回顾 | 是 |
| `scripts/gtd audit --date 2026-10-25` | 用滴答重算，与日回顾 frontmatter 对账 | 否 |
| `scripts/gtd report --from ... --to ...` / `scripts/gtd monthly --month 2026-10` | 打印周/月回顾 Markdown | 否 |
| `scripts/gtd selfcheck [--json]` | 检查安装完整性（源码、依赖、写入后端） | 否 |
| `scripts/gtd pack [--out FILE] [--list]` | 打出跨机器安装用的源码包 | 是 |

退出码：`0` 成功 / `1` 配置、数据或对账错误 / `2` 参数错误。

## 你的方法论放哪

这个 skill 只做**执行化**，不发明方法论。它读你笔记目录里的原文来判分和排程：

```
<theory_dir>/时间管理.md   ← 主笔记
<theory_dir>/…             ← 它的子笔记
```

`theory_dir` 是配置文件里的一个字段（相对 vault 根，默认 `我的方法论`），
`gtd init` / `gtd selfcheck` 会把它打印出来。把它指到你自己写方法论的那个目录即可；
`references/theory.md` 是导航与摘要，规则冲突时**以你的原文为准**。

## 目录

```
SKILL.md          入口：铁律、模式分流、命令、数据落点、验证清单
references/       theory / capture / plan / execute / review / scoring / data-map / writing
scripts/          gtd.py + lib/（纯标准库）+ gtd / gtd.cmd 启动器
assets/           回顾模板、配置示例
adapters/         Claude Code / Hermes / OpenClaw 的安装方式
tests/            130 个单测
```

## 隐私

- 仓库里**不含任何密钥**：token 只从环境变量或外部文件读。
- 也不含任何账号相关数据：滴答清单 ID、你的项目名、习惯名都要自己填
  （`references/data-map.md` 里有说明，运行 `dida project list` 取你的清单 ID）。
- 你的方法论原文**不会**被这个仓库包含——它只在你自己的 vault 里。

## License

MIT
