"""线自描述端点：`/.well-known/line-manifest.json`（公开、免鉴权、零网络）。

判据源=change converge-line-identity-and-keys 的 specs/line-manifest：清单是运行期
契约——缺失=404（配置事实），不可解析=500（缺陷，不伪装 404），响应体 SHALL 与仓内
源逐字段一致（不内联第二份，避免漂移）。端点必须在**鉴权门之前**应答：平台/客户在
未持有本线凭据时也要能读到「这条线认哪些钥匙」。

照 lex-ops-mcp 的家族实现移植（含候选链：镜像里 `__file__` 落在 site-packages，
`parents[1]` 不是仓根，只有装成包才会暴露——lex 线 2026-11-11 真机 404 的教训）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

import wire_ops_mcp.server as server

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "line-manifest.json"

#: 允许出现在清单里的**字符串**键路径（闭集）。清单随 `/.well-known` 匿名公开，
#: 自由文本（`note` 一族）不是「写短点」就安全——它压根不该在公开契约里。
#: 2026-11-15 实测：本仓曾有 5 段 note 约 1.4KB，写着内部代码路径
#: （`api/fd_wire_api/data_plane/auth.py`、`billing/sub2api.py`、`web/src/admin`）、
#: ClusterIP 重复、以及「车道地址为什么只能写字面 IP」的完整推演。
#: 证据已移到 `docs/line-auth-evidence.md`。
_SANCTIONED_TEXT_PATHS = {
    "schema", "line", "public_base_url", "internal_base_url",
    "identity.issuer", "identity.jwks_uri", "identity.jit_policy",
    "billing.plane", "billing.evidence_url", "billing.evidence_path",
    "auth_tracks[].name", "auth_tracks[].kind", "auth_tracks[].accepts",
    "auth_tracks[].migration_task", "scopes[]",
}

#: 落在 sanction 字段里也照样不许出现的东西。
_INTERNAL_PATTERNS = (
    (r"fd-[a-z0-9][a-z0-9-]*-(?:token|key)\b", "Secret 名"),
    (r"\b[A-Z][A-Z0-9_]{2,}(?:TOKEN|SECRET|PASSWORD|PEM)\b", "凭据类环境变量"),
    (r"(?<![\w/.-])(?:[\w.-]+/)+[\w.-]+\.(?:py|js|ts|sh|ya?ml)(?::\d+(?:-\d+)?)?", "内部代码路径"),
)


def _walk_strings(node, path: str = ""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for v in node:
            yield from _walk_strings(v, path + "[]")
    elif isinstance(node, str):
        yield path, node


def test_source_manifest_has_no_free_text() -> None:
    """清单的每个字符串都会匿名公开 ⇒ 只许产品语义，不许内部细节。

    判据是**键的闭集**而不是长度（一段 20 字符的 note 一样能写出 Secret 名），
    外加内容侧扫描（Secret 名 / 凭据类 ENV / 内部代码路径）。
    """
    doc = json.loads(SOURCE.read_text(encoding="utf-8"))
    strings = list(_walk_strings(doc))

    stray = [p for p, _ in strings if p not in _SANCTIONED_TEXT_PATHS]
    assert not stray, f"清单里出现自由文本键（会随投影公开）: {stray}；证据请写进 docs/"

    # `internal_base_url` 是规格允许写集群内地址的唯一字段，排除在内容扫描外。
    body = json.dumps({k: v for k, v in doc.items() if k != "internal_base_url"},
                      ensure_ascii=False)
    for pattern, what in _INTERNAL_PATTERNS:
        hit = re.search(pattern, body)
        assert hit is None, f"清单里出现{what}: {hit.group(0)!r}"


def _get(app, path: str) -> httpx.Response:
    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            return await c.get(path)

    return _run()


@pytest.mark.asyncio
async def test_well_known_served_without_auth_and_equals_source() -> None:
    app = server.build_app()
    resp = await _get(app, "/.well-known/line-manifest.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "max-age=" in resp.headers.get("cache-control", "")
    # 逐字段等于仓内源（唯一事实源，不另存一份）
    assert resp.json() == json.loads(SOURCE.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_well_known_bypasses_the_auth_gate() -> None:
    """不带 Bearer 也必须是 200——若走了鉴权门就是 401（这正是要防的回退）。"""
    app = server.build_app()
    resp = await _get(app, "/.well-known/line-manifest.json")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_well_known_missing_is_404(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(server.LINE_MANIFEST_ENV, str(tmp_path / "absent.json"))
    app = server.build_app()
    resp = await _get(app, "/.well-known/line-manifest.json")
    assert resp.status_code == 404
    assert "not published" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_well_known_corrupt_is_500_not_404(monkeypatch, tmp_path: Path) -> None:
    corrupt = tmp_path / "line-manifest.json"
    corrupt.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv(server.LINE_MANIFEST_ENV, str(corrupt))
    app = server.build_app()
    resp = await _get(app, "/.well-known/line-manifest.json")
    assert resp.status_code == 500
    assert "not valid JSON" in resp.json()["detail"]


def test_manifest_path_defaults_to_repo_root(monkeypatch) -> None:
    monkeypatch.delenv(server.LINE_MANIFEST_ENV, raising=False)
    assert server.manifest_path() == SOURCE


def test_manifest_path_falls_back_to_cwd_when_package_is_installed(monkeypatch, tmp_path):
    """pip 装的包在 site-packages 时，`__file__` 祖先里没有清单——必须退到 CWD。"""
    monkeypatch.delenv(server.LINE_MANIFEST_ENV, raising=False)
    fake_pkg = tmp_path / "site-packages" / "wire_ops_mcp"
    fake_pkg.mkdir(parents=True)
    monkeypatch.setattr(server, "__file__", str(fake_pkg / "server.py"))
    cwd = tmp_path / "app"
    cwd.mkdir()
    (cwd / "line-manifest.json").write_text('{"schema": "line-manifest/v1", "line": "wire"}')
    monkeypatch.chdir(cwd)

    assert server.manifest_path() == cwd / "line-manifest.json"
    assert server.manifest_response()[0] == 200


def test_manifest_path_prefers_env_override(monkeypatch, tmp_path):
    """显式给了 LINE_MANIFEST_PATH 就只认它——配置比搜索链更可信。"""
    target = tmp_path / "explicit.json"
    target.write_text('{"schema": "line-manifest/v1", "line": "wire"}')
    monkeypatch.setenv(server.LINE_MANIFEST_ENV, str(target))
    assert server.manifest_candidates() == [target]
    assert server.manifest_path() == target


def test_missing_manifest_is_404_not_500(monkeypatch, tmp_path):
    """三个候选全不存在 = 404（配置事实），不许伪装成 5xx 让运维以为服务坏了。"""
    monkeypatch.delenv(server.LINE_MANIFEST_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server, "__file__", str(tmp_path / "pkg" / "server.py"))
    assert server.manifest_response()[0] == 404
