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
from pathlib import Path

import httpx
import pytest

import wire_ops_mcp.server as server

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "line-manifest.json"


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
