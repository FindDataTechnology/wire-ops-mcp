"""FastMCP 组装 + ASGI 布线（鉴权门 + /health + /.well-known/line-manifest.json）。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fd_open_data_protocol import surface_report

from . import SERVER_NAME, tools_console
from .auth_gate import AuthGate, AuthGateMiddleware
from .client import WireClient
from .config import Settings

#: 线自描述端点（converge-line-identity-and-keys 1.4 的家族实现）：公开、免鉴权、零网络。
WELL_KNOWN_PATH = "/.well-known/line-manifest.json"
LINE_MANIFEST_ENV = "LINE_MANIFEST_PATH"
#: 清单是运行期契约：改一次要生效，但不能让边缘缓存长期撒谎。
_MANIFEST_CACHE_CONTROL = "public, max-age=300"

INSTRUCTIONS = (
    "柏讯客户面操作助手：提交/查询需求单、查本企业数据集并做只读查询/聚合/行读、"
    "浏览数据市场并订阅/退订。每个调用以你的柏讯凭据执行（Logto ID token 或 wdk_ "
    "数据面 key，上游双轨判定）；viewer 角色只读（写操作上游会 403 并如实转述）。"
    "需求单合规门（公开数据源 URL+公开数据声明）必须由用户真实意图驱动——绝不代勾。"
    "错误如实透传（401=未登录/未映射客户、403=无权限、404=无此条目、422=校验逐字段）；"
    "空结果如实为空，绝不编造数据集或数据行。"
)

_HEALTH_OK = b'{"status":"ok"}'
_HEALTH_OK_REPORTED = b'{"status":"ok","last_surface_report":"ok"}'
_HEALTH_FAILED_REPORTED = b'{"status":"ok","last_surface_report":"failed"}'


def manifest_candidates() -> list[Path]:
    """按优先级列出可能放清单的位置（`LINE_MANIFEST_PATH` 一项即封顶）。

    为什么要链而不是一条：**pip 装进去的包与源码树的 `__file__` 不同**。镜像是
    console script 起的，`__file__` 落在 site-packages，`parents[1]` 根本不是仓根——
    清单就在 `/app/line-manifest.json` 却读不到（lex 线 2026-11-11 真机 404，
    源码运行验不出来）。所以源码树、CWD（镜像 WORKDIR）、与包同级三处依次找。
    """
    override = os.environ.get(LINE_MANIFEST_ENV)
    if override:
        return [Path(override)]
    here = Path(__file__).resolve()
    return [
        here.parents[1] / "line-manifest.json",  # 源码树 / 镜像里包与清单同根
        Path.cwd() / "line-manifest.json",       # pip 装的包：CWD 才是仓根
        here.parent / "line-manifest.json",      # 清单与包同级（兜底）
    ]


def manifest_path() -> Path:
    """实际取用的清单路径；都不存在时返回首选位置（让 404 能点名期望路径）。"""
    candidates = manifest_candidates()
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def manifest_response() -> tuple[int, bytes, list[tuple[bytes, bytes]]]:
    """(status, body, extra_headers) —— 不读网络、不建会话。

    缺失=404（该线未发布清单，属配置事实）；存在但不可解析=500（属缺陷，不能
    伪装成 404 让调用方以为"本来就没有"）。
    """
    json_headers = [(b"content-type", b"application/json; charset=utf-8")]
    path = manifest_path()
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return 404, b'{"detail":"line-manifest not published"}', json_headers
    except OSError as exc:
        return 500, json.dumps(
            {"detail": f"line-manifest unreadable: {type(exc).__name__}"}).encode(), json_headers
    try:
        json.loads(raw)
    except ValueError:
        return 500, b'{"detail":"line-manifest is not valid JSON"}', json_headers
    return 200, raw, json_headers + [
        (b"cache-control", _MANIFEST_CACHE_CONTROL.encode()),
    ]


def create_server(settings: Settings | None = None) -> "FastMCP":
    from fastmcp import FastMCP

    settings = settings or Settings.from_env()
    mcp = FastMCP(SERVER_NAME, instructions=INSTRUCTIONS)
    client = WireClient(settings.base_url, timeout_seconds=settings.timeout_seconds)
    tools_console.register(mcp, client)
    mcp._wire_ops_client = client
    mcp._wire_ops_settings = settings
    mcp._surface_report = "not_configured"
    return mcp


def build_app(settings: Settings | None = None):
    """完整 ASGI 应用：/health 与线自描述免门；其余（/mcp）走鉴权门（无 Bearer 拒）。"""
    mcp = create_server(settings)
    settings_: Settings = mcp._wire_ops_settings
    mcp_app = mcp.http_app(path="/mcp")
    gate = AuthGateMiddleware(mcp_app, AuthGate(settings_.auth_cache_ttl_seconds))

    async def app(scope, receive, send):
        if scope.get("type") == "http":
            surface_report.ensure_started(mcp)  # 首请求触发：loop 已在跑
            path = (scope.get("path") or "").rstrip("/")
            if path == "/health":
                state = getattr(mcp, "_surface_report", "not_configured")
                body = {
                    "not_configured": _HEALTH_OK,
                    "ok": _HEALTH_OK_REPORTED,
                    "failed": _HEALTH_FAILED_REPORTED,
                }.get(state, _HEALTH_OK)
                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": body})
                return
            # 线自描述：公开元数据，必须在鉴权门**之前**应答（与 /health 同理），
            # 否则平台/客户在未持有本线凭据时连"这条线认哪些钥匙"都读不到。
            if path == WELL_KNOWN_PATH.rstrip("/"):
                status, body, headers = manifest_response()
                await send({"type": "http.response.start", "status": status,
                            "headers": headers + [(b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await gate(scope, receive, send)

    return app
