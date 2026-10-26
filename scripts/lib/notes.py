"""笔记写入后端：FNS REST API 与固定文件夹。

两种后端都实现 `NotesWriter`（`read` / `write` / `delete`），路径一律是
**相对 vault 根**的路径（如 `7-规划回顾/2-回顾/1-日维度/review-....md`）。
`writer_chain` 按环境变量决定用哪个后端，`write_with_fallback` 在链上依次尝试。

FNS 的两个坑：
- HTTP 200 不代表成功，必须看 JSON 里的 `code == 1`；例外：`code == 430`
  是「笔记不存在」（返回 None），其余非 1 的 code 都是故障，要抛异常。
- DELETE 的参数要放进 JSON body（query 参数会返回 305 Invalid Params），
  且 `pathHash` 得先 GET 一次 `/note` 拿到。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Protocol

ENV_FNS_URL = "PERSONAL_GTD_FNS_URL"
ENV_FNS_TOKEN = "PERSONAL_GTD_FNS_TOKEN"
ENV_VAULT_DIR = "PERSONAL_GTD_VAULT_DIR"

TRASH_DIR = ".trash"

#: FNS 的「笔记不存在」业务码（HTTP 仍是 200，看 body 里的 code）
_MISSING_CODES = frozenset({430})


class NotesError(RuntimeError):
    """笔记读写失败；HTTP 失败时 `status` 是状态码（网络/本地错误为 None）。"""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class WriterConfigError(NotesError):
    """没有可用的写入后端（环境变量没配）。"""


class NotesWriter(Protocol):
    """笔记后端接口；`rel_path` 相对 vault 根。"""

    def read(self, rel_path: str) -> str | None:
        """返回笔记内容；不存在返回 None。"""

    def write(self, rel_path: str, content: str, create_only: bool = False) -> None:
        """写入笔记；`create_only=True` 时已存在则失败。"""

    def delete(self, rel_path: str) -> None:
        """删除笔记；不存在时什么也不做。"""


def _posix(rel_path: str) -> str:
    """把 Windows 反斜杠统一成 FNS 认的 `/`。"""
    return str(rel_path).replace("\\", "/")


class FolderWriter:
    """直接读写 vault 目录里的文件。

    路径解析后必须仍在 `root` 内，`../` 与绝对路径都会被拒绝（ValueError）。
    写入走“临时文件 + `os.replace`”，避免半截文件；删除是移到 `<root>/.trash/`。
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._root_resolved = self.root.resolve()

    def _resolve(self, rel_path: str) -> Path:
        target = (self.root / rel_path).resolve()
        if not target.is_relative_to(self._root_resolved):
            raise ValueError(f"path escapes vault root: {rel_path!r}")
        return target

    def read(self, rel_path: str) -> str | None:
        path = self._resolve(rel_path)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def write(self, rel_path: str, content: str, create_only: bool = False) -> None:
        path = self._resolve(rel_path)
        if create_only and path.exists():
            raise NotesError(f"note already exists: {rel_path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            os.replace(tmp, path)
        except OSError as exc:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise NotesError(f"write failed: {rel_path}: {exc}") from exc

    def delete(self, rel_path: str) -> None:
        path = self._resolve(rel_path)
        if not path.is_file():
            return
        trash = self._resolve(f"{TRASH_DIR}/{_posix(rel_path)}")
        trash.parent.mkdir(parents=True, exist_ok=True)
        os.replace(path, trash)


class FnsWriter:
    """Fast Note Sync 的 REST API 后端。

    `read` 在 `code != 1` 时返回 None；`write` 在 `code != 1` 时抛 `NotesError`。
    `delete` 先 GET 拿 `pathHash`，再把它放进 DELETE 的 JSON body。
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        vault: str,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/api"
        self.token = token
        self.vault = vault
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        query: dict | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if query:
            clean = {k: v for k, v in query.items() if v is not None}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"
        data = (
            None
            if body is None
            else json.dumps(body, ensure_ascii=False).encode("utf-8")
        )
        request = urllib.request.Request(
            url,
            data=data,
            method=method.upper(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:300]
            except Exception:  # pragma: no cover - 读错误体失败不影响主错误
                detail = ""
            raise NotesError(
                f"{method.upper()} {path} failed: HTTP {exc.code} {detail}".strip(),
                status=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            raise NotesError(
                f"{method.upper()} {path} failed: {exc.reason}"
            ) from exc
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise NotesError(f"{method.upper()} {path} failed: invalid JSON") from exc

    @staticmethod
    def _ok(response: Any) -> bool:
        return isinstance(response, dict) and response.get("code") == 1

    @staticmethod
    def _is_missing(response: Any) -> bool:
        """`code == 430` = 笔记不存在；其余非 1 的 code 一律当故障。"""
        return isinstance(response, dict) and response.get("code") in _MISSING_CODES

    @staticmethod
    def _error_detail(response: Any) -> str:
        if isinstance(response, dict):
            code = response.get("code")
            message = response.get("message") or response.get("msg") or ""
            return f"code={code} {message}".strip()
        return f"unexpected response: {response!r}"

    @staticmethod
    def _content(response: Any) -> str | None:
        data = response.get("data") if isinstance(response, dict) else None
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            content = data.get("content")
            return None if content is None else str(content)
        return None

    def _read_raw(self, rel_path: str) -> Any:
        return self._request(
            "GET",
            "/note",
            query={"vault": self.vault, "path": _posix(rel_path)},
        )

    def read(self, rel_path: str) -> str | None:
        """读笔记：不存在返回 None；**其它失败（会话过期、服务端错误）抛 `NotesError`**。

        FNS 用 HTTP 200 传业务错误码，所以不能只看 HTTP 状态：
        `code == 430` 才是「笔记不存在」，其余非 1 的 code 都是故障。
        把它压成 None 会让上游把「读不到」当成「没有」——`settle` 就会把周账
        从 0 起算并写进账本。
        """
        response = self._read_raw(rel_path)
        if self._ok(response):
            return self._content(response)
        if self._is_missing(response):
            return None
        raise NotesError(
            f"GET /note failed for {rel_path}: {self._error_detail(response)}"
        )

    def write(self, rel_path: str, content: str, create_only: bool = False) -> None:
        body: dict[str, Any] = {
            "vault": self.vault,
            "path": _posix(rel_path),
            "content": content,
        }
        if create_only:
            body["createOnly"] = True
        response = self._request("POST", "/note", body)
        if not self._ok(response):
            raise NotesError(
                f"POST /note failed for {rel_path}: {self._error_detail(response)}"
            )

    def delete(self, rel_path: str) -> None:
        response = self._read_raw(rel_path)
        if self._is_missing(response):
            return  # 不存在：幂等
        if not self._ok(response):
            raise NotesError(
                f"GET /note failed for {rel_path}: {self._error_detail(response)}"
            )
        data = response.get("data") if isinstance(response, dict) else None
        path_hash = data.get("pathHash") if isinstance(data, dict) else None
        if not path_hash:
            raise NotesError(f"GET /note returned no pathHash for {rel_path}")
        body = {
            "vault": self.vault,
            "path": _posix(rel_path),
            "pathHash": path_hash,
        }
        result = self._request("DELETE", "/note", body)
        if not self._ok(result):
            raise NotesError(
                f"DELETE /note failed for {rel_path}: {self._error_detail(result)}"
            )


def writer_chain(
    vault: str,
    env: Mapping[str, str] | None = None,
) -> list[NotesWriter]:
    """按环境变量返回写入链：FNS 优先，文件夹兜底。

    `PERSONAL_GTD_FNS_URL` 与 `PERSONAL_GTD_FNS_TOKEN` 都非空 → FNS；
    `PERSONAL_GTD_VAULT_DIR` 非空 → 文件夹（FNS 之后追加）。都没有 → 报错。
    """
    source: Mapping[str, str] = os.environ if env is None else env
    url = (source.get(ENV_FNS_URL) or "").strip()
    token = (source.get(ENV_FNS_TOKEN) or "").strip()
    folder = (source.get(ENV_VAULT_DIR) or "").strip()

    writers: list[NotesWriter] = []
    if url and token:
        writers.append(FnsWriter(url, token, vault))
    if folder:
        writers.append(FolderWriter(Path(folder)))
    if not writers:
        raise WriterConfigError(
            "no note writer configured: set "
            f"{ENV_FNS_URL} + {ENV_FNS_TOKEN} (FNS), or {ENV_VAULT_DIR} (folder)"
        )
    return writers


def _writer_label(writer: NotesWriter) -> str:
    if isinstance(writer, FnsWriter):
        return "fns"
    if isinstance(writer, FolderWriter):
        return "folder"
    return type(writer).__name__.lower()


def write_with_fallback(
    writers: list[NotesWriter],
    rel_path: str,
    content: str,
    create_only: bool = False,
) -> str:
    """依次尝试每个后端，返回成功的那个（`"fns"` / `"folder"`）。

    全失败时抛出最后一个异常；链为空抛 `NotesError`。
    """
    last_error: Exception | None = None
    for writer in writers:
        try:
            writer.write(rel_path, content, create_only=create_only)
            return _writer_label(writer)
        except Exception as exc:  # noqa: BLE001 - 逐个后端降级，最后统一抛出
            last_error = exc
    if last_error is not None:
        raise last_error
    raise NotesError("no note writer configured")
