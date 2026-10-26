# Adapters

`personal-gtd` 的核心是一个 agent 无关的目录：

```
SKILL.md + references/ + scripts/ + assets/
```

任何能读 Markdown、能跑 Python 3.10+ 的 agent 都可以把整个目录复制或软链到自己的 skills 目录。核心不依赖 Claude Code 的斜杠命令，也不依赖某个 agent 的多 skill 路由。

适配器只放“这个 agent 特有”的安装方式和入口：

- `claude-code/` — 目录 junction/软链 + 可选的 `/gtd-*` 斜杠命令
- `hermes/` — Hermes skills 目录安装说明
- `openclaw/` — OpenClaw workspace skills 安装说明

入口分三层，各 adapter 都一样：

| 层级 | 入口 | 说明 |
|---|---|---|
| 总入口 | skill 本身（`/personal-gtd`）+ `/gtd`（命令 / bundle） | 读 `SKILL.md` 的模式分流表判断意图，再进对应模式 |
| 分模式 | `/gtd-capture` `/gtd-plan` `/gtd-execute` `/gtd-review` `/gtd-settle` `/gtd-report` | 直接进某个模式 |
| 自然语言 | 「记一下…」「排一下明天」 | 靠 skill 描述自动匹配 |

收尾一律按 `SKILL.md` 铁律 7 **提示下一阶段**（只提示，不自动执行）。

核心路径约定（所有 agent 通用）：

| 变量 | 作用 | 默认 |
|---|---|---|
| `PERSONAL_GTD_VAULT_DIR` | 固定文件夹写入的 vault 根 | 无；不设置则只用 FNS 或不可写 |
| `PERSONAL_GTD_FNS_URL` / `PERSONAL_GTD_FNS_TOKEN` | FNS REST 写入 | 无 |
| `PERSONAL_GTD_DIR` | GTD 输出的根目录（相对 vault 根） | `7-规划回顾`；子目录由 `init` 自动建 |
| `PERSONAL_GTD_CONFIG` | 配置文件路径 | `~/.config/personal-gtd/config.json` |
| `PERSONAL_GTD_DIDA_CONFIG` | 滴答 token 文件 | `~/.config/dida-cli/config.json` |
| `PERSONAL_GTD_PYTHON` | Python 解释器 | `python3`，否则 `python` |

不要在核心文档里写死某台机器的绝对路径；如果某个 agent 需要，写在该 agent 的 adapter 里。

## 装完必须自检

```bash
scripts/gtd selfcheck
```

源码缺一个就退出 1。跨机器安装别直接同步目录——目录里可能有 `__pycache__` 里的字节码（绑定 Python 版本），还可能只同步过去一部分文件。走源码包：

```bash
scripts/gtd pack --out personal-gtd.zip     # 源机器
# 目标机器：解压到该 agent 的 skills 目录 → chmod +x scripts/gtd → selfcheck
```

