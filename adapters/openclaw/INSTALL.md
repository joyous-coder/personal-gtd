# OpenClaw adapter

OpenClaw 的 workspace skills 通常是 `workspace/skills/<name>/`。把核心目录复制或软链进去：

```sh
cp -R "<SKILL_DIR>" <openclaw-workspace>/skills/personal-gtd
# 或
ln -s "<SKILL_DIR>" <openclaw-workspace>/skills/personal-gtd
```

核心 `SKILL.md` 不依赖 Claude Code 的斜杠命令；OpenClaw 用自然语言触发。若 OpenClaw 需要 `skill-card.md` 或 `metadata.clawdbot`，在 adapter 里提供模板，不要改核心。

环境变量同 `adapters/README.md`。不要把 token 写进 skill 目录或 workspace 的公开文件。

## 装完自检

```bash
scripts/gtd selfcheck
```

源码 `8/8` 齐全才算装好。跨机器用 `scripts/gtd pack` 打的源码包，别直接同步目录（`__pycache__` 里的字节码绑定 Python 版本，还可能只同步过去一部分文件）。
