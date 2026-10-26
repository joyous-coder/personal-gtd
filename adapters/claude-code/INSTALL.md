# Claude Code adapter

核心目录可以直接作为 Claude Code skill 使用。二选一安装：

## Windows（junction，单一源）

```powershell
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\personal-gtd" -Target "<SKILL_DIR>"
```

## macOS / Linux（symlink）

```sh
ln -s "<SKILL_DIR>" ~/.claude/skills/personal-gtd
```

`<SKILL_DIR>` 是这个仓库中 `1-收集箱/时间管理Skill` 的路径。安装后重启 Claude Code；`/skills` 或技能列表里应出现 `personal-gtd`。

## 可选：斜杠命令

Claude Code 的自定义命令是 `~/.claude/commands/*.md` 的提示模板，不是可执行程序。把 `commands/` 里的文件复制到 `~/.claude/commands/`（或把整个目录软链为 `~/.claude/commands/personal-gtd/`；如果当前版本支持子目录命名空间，命令名会是 `/personal-gtd:capture`，否则直接用 `gtd-capture.md` 这样的文件名）。

命令只是**确定入口**：它让 Claude 读 `personal-gtd` 的对应 reference，并按该模式执行。核心规则仍然只在 `SKILL.md` / `references/` 里，不在命令里重复。

装上后有两个层级：

| 入口 | 作用 |
|---|---|
| `/gtd` | **总入口**：读 `SKILL.md` 的模式分流表，判断意图后进对应模式 |
| `/gtd-capture` `/gtd-plan` `/gtd-execute` `/gtd-review` `/gtd-settle` `/gtd-report` | 分模式快捷入口 |
| `/personal-gtd`（skill 本身） | 也能直接调起，走同一套分流 |

## 环境变量

按 `adapters/README.md` 设置。Claude Code 可以把它们写进 `~/.claude/settings.json` 的 `env` 字段：

```json
{
  "env": {
    "PERSONAL_GTD_VAULT_DIR": "<vault-root>"
  }
}
```

不要把 token 写进命令文件或仓库。

## 装完自检

```bash
scripts/gtd selfcheck
```

源码 `8/8` 齐全才算装好。跨机器用 `scripts/gtd pack` 打的源码包，别直接同步目录（`__pycache__` 里的字节码绑定 Python 版本，还可能只同步过去一部分文件）。
