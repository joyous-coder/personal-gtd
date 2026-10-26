# 笔记写入（FNS / 文件夹）

实现：`scripts/lib/notes.py`。所有路径都是**相对 vault 根**的路径，如
`7-规划回顾/2-回顾/1-日维度/review-2026-10-25-星期日.md`。

## 环境变量（只从环境读，永不落盘）

| 变量 | 作用 |
| --- | --- |
| `PERSONAL_GTD_FNS_URL` | FNS 服务根，如 `https://your-fns-host.example.com`（**不带 `/api`**，脚本自己拼） |
| `PERSONAL_GTD_FNS_TOKEN` | FNS 的 JWT（**不带 `Bearer `**，脚本自己加） |
| `PERSONAL_GTD_VAULT_DIR` | 固定文件夹模式的 vault 根，如 `<vault-root>` |

设置方式（二选一，设置后重启你的 agent）：Windows 用户环境变量（`setx PERSONAL_GTD_VAULT_DIR "<vault-root>"`）、POSIX（`export PERSONAL_GTD_VAULT_DIR="<vault-root>"`），或写进你的 agent 的 env 设置（Claude Code 见 `adapters/claude-code/INSTALL.md`）。

**必须先配一个**：没有后端时 `settle`（非 `--dry-run`）、`balance`、`backfill`、`audit`、`report`、`monthly` 六条命令都退出 1，只有 `score`、`settle --dry-run`、`init` 可用。脚本不会默认套用 vault 路径，缺变量就报错；单次命令可用 `--vault-dir DIR` 或内联环境变量（`PERSONAL_GTD_VAULT_DIR=<vault-root> scripts/gtd ...`）。

## 回退顺序（`writer_chain`）

1. `PERSONAL_GTD_FNS_URL` 与 `PERSONAL_GTD_FNS_TOKEN` 都非空 → 链首放 **FNS**。
2. `PERSONAL_GTD_VAULT_DIR` 非空 → 链上追加 **folder**。
3. 链为空 → `WriterConfigError`，列出三个变量名，**不写任何东西**。

写入（`write_with_fallback`）按链顺序尝试，第一个成功即返回，打印后端名（`fns` / `folder`）；全失败抛最后一个异常，**不静默丢内容**。读取按同一顺序；`settle` 的前一日账本读取失败会中止（不把故障当没有），`report`/`monthly` 只警告并跳过该日。

`init` 报的 writer 模式：两套都有 → `FNS（folder 兜底）`；只有 FNS → `FNS`；只有 folder → `folder`；都没有 → `未配置`。

## FNS 模式

已实测端点（base = `<URL>/api`）：

| 操作 | 请求 | 说明 |
| --- | --- | --- |
| 读 | `GET /note?vault=Obsidian_Vault&path=<urlencoded>` | 返回 JSON，内容在 `data`（字符串或 `{content, pathHash}`） |
| 建 | `POST /note`，body `{vault, path, content, createOnly: true}` | 已存在则失败 |
| 改 | `POST /note`，body `{vault, path, content}` | 覆盖 |
| 删 | `DELETE /note`，**body** `{vault, path, pathHash}` | 见下方坑 |
| 清回收站 | `DELETE /note/recycle-clear`，body `{vault, path}` | 非必要不用 |

两个坑：

1. **HTTP 200 不代表成功**：必须看 JSON 的 `code == 1`，否则按失败处理（读返回 None，写抛 `NotesError`）。
2. **DELETE 的参数必须放 JSON body**：放 query 会返回 `305 Invalid Params`；`pathHash` 要先 `GET /note` 拿。

错误信息里的 token 永远不打印；`NotesError.status` 是 HTTP 状态码（网络错误为 None），便于判断 401 后回退。

## 文件夹模式

- 写入：父目录不存在自动创建；先写临时文件再 `os.replace`，UTF-8、`\n` 换行，避免半截文件。
- 读取：不存在返回 `None`。
- 删除：移到 `<vault>/.trash/<原相对路径>`，不真删；不存在时静默返回。
- **路径穿越防护**：`../` 与绝对路径都会被拒绝（`ValueError`）；所有路径必须落在 vault 根内。
- 适合不想用 API 或 API 不可用时；Obsidian 的 fast-note 插件会自行同步本地改动。

## config 与 token 的边界

- config（`PERSONAL_GTD_CONFIG`，默认 `~/.config/personal-gtd/config.json`）只放非敏感项：vault、工资、预留分、上限、目录、标签名等。
- FNS URL/token 只从环境变量读；滴答 token 只从 `PERSONAL_GTD_DIDA_CONFIG`（默认 `~/.config/dida-cli/config.json`）读。
- 任何 token 都不写进 config、笔记、日志、对话或 git 提交；展示时掩码。

## 命令侧开关

`settle` / `balance` / `backfill` / `audit` / `report` / `monthly` 支持 `--vault-dir DIR` 临时覆盖 `PERSONAL_GTD_VAULT_DIR`（只对本次命令生效，进程退出即还原），用于补账、测试和指定别的 vault。`init` 不接该参数：它按 `PERSONAL_GTD_VAULT_DIR` 建回顾目录。**FNS 两个变量同时配置时，`--vault-dir` 只作为 folder 兜底，不会改变 FNS 优先级**；需要强制本地写时先清掉 FNS 变量。
