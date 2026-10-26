import io, json, tempfile, unittest, sys
import urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.notes import FolderWriter, FnsWriter, NotesError, WriterConfigError, writer_chain, write_with_fallback

class TestFolderWriter(unittest.TestCase):
    def test_roundtrip_and_parents(self):
        with tempfile.TemporaryDirectory() as d:
            w = FolderWriter(Path(d))
            w.write("a/b/c.md", "hello")
            self.assertEqual(w.read("a/b/c.md"), "hello")
            self.assertTrue((Path(d) / "a/b/c.md").exists())

    def test_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            w = FolderWriter(Path(d))
            with self.assertRaises(ValueError):
                w.write("../escape.md", "x")

    def test_delete_moves_to_trash(self):
        with tempfile.TemporaryDirectory() as d:
            w = FolderWriter(Path(d))
            w.write("a.md", "x")
            w.delete("a.md")
            self.assertIsNone(w.read("a.md"))
            self.assertTrue((Path(d) / ".trash/a.md").exists())

class TestWriterSelection(unittest.TestCase):
    def test_fns_priority(self):
        env = {"PERSONAL_GTD_FNS_URL": "https://x", "PERSONAL_GTD_FNS_TOKEN": "t",
               "PERSONAL_GTD_VAULT_DIR": "D:/v"}
        chain = writer_chain("Obsidian_Vault", env)
        self.assertIsInstance(chain[0], FnsWriter)
        self.assertIsInstance(chain[1], FolderWriter)

    def test_folder_only(self):
        env = {"PERSONAL_GTD_VAULT_DIR": "D:/v"}
        chain = writer_chain("Obsidian_Vault", env)
        self.assertEqual(len(chain), 1)
        self.assertIsInstance(chain[0], FolderWriter)

    def test_missing_env_raises(self):
        with self.assertRaises(WriterConfigError) as cm:
            writer_chain("Obsidian_Vault", {})
        msg = str(cm.exception)
        for name in ("PERSONAL_GTD_FNS_URL", "PERSONAL_GTD_FNS_TOKEN", "PERSONAL_GTD_VAULT_DIR"):
            self.assertIn(name, msg)

class TestFnsWriter(unittest.TestCase):
    def test_write_sends_post(self):
        w = FnsWriter("https://x/", "t", "V")
        with patch.object(w, "_request", return_value={"code": 1}) as m:
            w.write("a.md", "hi", create_only=True)
            method, path, body = m.call_args.args
            self.assertEqual(method, "POST")
            self.assertEqual(path, "/note")
            self.assertEqual(body["path"], "a.md")
            self.assertTrue(body["createOnly"])

    def test_read_unknown_non_success_code_raises(self):
        """只有 430（笔记不存在）算 None；其它业务码是故障，不能当「没有」。"""
        w = FnsWriter("https://x", "t", "V")
        with patch.object(w, "_request", return_value={"code": 404, "message": "no"}):
            with self.assertRaises(NotesError):
                w.read("a.md")

    def test_delete_uses_body_with_path_hash(self):
        w = FnsWriter("https://x", "t", "V")
        responses = [{"code": 1, "data": {"pathHash": "ph"}}, {"code": 1}]
        with patch.object(w, "_request", side_effect=responses) as m:
            w.delete("a.md")
            self.assertEqual(m.call_args_list[1].args[0], "DELETE")
            self.assertEqual(m.call_args_list[1].args[2]["pathHash"], "ph")

    def test_url_normalized(self):
        w = FnsWriter("https://x/", "t", "V")
        self.assertEqual(w.base_url, "https://x/api")

class TestFallback(unittest.TestCase):
    def test_fallback_to_folder(self):
        with tempfile.TemporaryDirectory() as d:
            folder = FolderWriter(Path(d))
            class Boom:
                def write(self, *a, **k): raise RuntimeError("down")
            used = write_with_fallback([Boom(), folder], "a.md", "x")
            self.assertEqual(used, "folder")
            self.assertEqual(folder.read("a.md"), "x")

class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body

class TestFnsTransport(unittest.TestCase):
    """urlopen 层：URL 拼装、Bearer 头、JSON 编解码与错误映射（不 mock `_request`）。"""

    def _capture(self, body):
        calls = []
        def fake_urlopen(request, timeout=None):
            calls.append((request, timeout))
            return _FakeResponse(body)
        return calls, fake_urlopen

    @staticmethod
    def _headers(request):
        return {k.lower(): v for k, v in request.headers.items()}

    def test_read_builds_url_query_and_bearer_header(self):
        calls, fake = self._capture(b'{"code": 1, "data": {"content": "hi"}}')
        with patch("urllib.request.urlopen", side_effect=fake):
            content = FnsWriter("https://x/", "tok", "V").read("a b.md")
        self.assertEqual(content, "hi")
        request, timeout = calls[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, "https://x/api/note?vault=V&path=a+b.md")
        self.assertEqual(self._headers(request)["authorization"], "Bearer tok")
        self.assertEqual(timeout, 30.0)

    def test_write_encodes_json_body(self):
        calls, fake = self._capture(b'{"code": 1}')
        with patch("urllib.request.urlopen", side_effect=fake):
            FnsWriter("https://x", "tok", "V").write("a/b.md", "hi\n", create_only=True)
        request, _ = calls[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "https://x/api/note")
        self.assertEqual(self._headers(request)["authorization"], "Bearer tok")
        self.assertEqual(self._headers(request)["content-type"], "application/json")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body, {"vault": "V", "path": "a/b.md",
                                "content": "hi\n", "createOnly": True})

    def test_http_error_maps_to_notes_error_with_status(self):
        def fake(request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url, 500, "boom", None, io.BytesIO(b"bad gateway")
            )
        with patch("urllib.request.urlopen", side_effect=fake):
            with self.assertRaises(NotesError) as cm:
                FnsWriter("https://x", "tok", "V").read("a.md")
        self.assertEqual(cm.exception.status, 500)
        self.assertIn("HTTP 500", str(cm.exception))
        self.assertIn("bad gateway", str(cm.exception))

    def test_invalid_json_maps_to_notes_error(self):
        _, fake = self._capture(b"<html>not json</html>")
        with patch("urllib.request.urlopen", side_effect=fake):
            with self.assertRaises(NotesError) as cm:
                FnsWriter("https://x", "tok", "V").read("a.md")
        self.assertIn("invalid JSON", str(cm.exception))
        self.assertIsInstance(cm.exception.__cause__, json.JSONDecodeError)


class TestFnsReadDistinguishesMissingFromFailure(unittest.TestCase):
    """FNS 用 HTTP 200 传错误 code：只有「笔记不存在」才算 None。

    实测服务端：会话过期返回 `{"code": 308, ...}` + HTTP 200。若把这类响应也当成
    「不存在」，`settle` 会把周账从 0 起算并写进账本——故障被当成「没有」。
    """

    def _read_with(self, payload):
        _, fake = TestFnsTransport()._capture(json.dumps(payload).encode("utf-8"))
        with patch("urllib.request.urlopen", side_effect=fake):
            return FnsWriter("https://x", "tok", "V").read("a.md")

    def test_note_does_not_exist_is_none(self):
        self.assertIsNone(self._read_with({"code": 430, "message": "Note does not exist"}))

    def test_session_expired_raises(self):
        with self.assertRaises(NotesError) as cm:
            self._read_with({"code": 308, "message": "Session expired, please log in again."})
        self.assertIn("308", str(cm.exception))

    def test_server_error_code_raises(self):
        with self.assertRaises(NotesError):
            self._read_with({"code": 500, "message": "Internal error"})

    def test_success_but_no_content_is_none(self):
        """code=1 但没有内容：确实是空笔记，不算故障。"""
        self.assertIsNone(self._read_with({"code": 1, "data": None}))
