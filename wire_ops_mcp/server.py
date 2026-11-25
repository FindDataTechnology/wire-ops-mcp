"""FastMCP 组装 + ASGI 布线（鉴权门 + /health + /.well-known/line-manifest.json）。

ASGI 布线已收敛到 `fd_open_data_protocol.line_ops.assemble`（openspec:
enforce-mcp-supply-contract / line-ops-runtime-core）；本仓只提供「建 FastMCP 并注册
本线工具」这一步。
"""

from __future__ import annotations

from fd_open_data_protocol.line_ops import assemble as _assemble
from fd_open_data_protocol.line_ops.auth_gate import (  # noqa: F401  (tests monkeypatch server.AuthGateMiddleware)
    AuthGateMiddleware,
)
from fd_open_data_protocol.line_ops.wellknown import (
    LINE_MANIFEST_ENV,
    WELL_KNOWN_PATH,
)

#: 清单定位必须锚在本仓 `server.py`，不能锚在 protocol 包里——共享实现的
#: `__file__` 指向 fd_open_data_protocol 的目录，算出来的仓根是错的
#: （2026-11-25 实测：五个消费仓的 manifest_path() 全指到 protocol 包里）。
#: **每次调用读本模块的 `__file__`（不缓存成常量）**：测试会 monkeypatch
#: `server.__file__` 模拟「pip 装的包在 site-packages」，缓存常量会让它打不中。
def _anchor():
    return globals()["__file__"]


def manifest_candidates() -> list:
    from fd_open_data_protocol.line_ops.wellknown import manifest_candidates as _f
    return _f(_anchor())


def manifest_path():
    from fd_open_data_protocol.line_ops.wellknown import manifest_path as _f
    return _f(_anchor())


def manifest_response():
    from fd_open_data_protocol.line_ops.wellknown import manifest_response as _f
    return _f(_anchor())

from . import SERVER_NAME, tools_console
from .client import WireClient
from .config import Settings

INSTRUCTIONS = (
    "柏讯客户面操作助手：提交/查询需求单、查本企业数据集并做只读查询/聚合/行读、"
    "浏览数据市场并订阅/退订。每个调用以你的柏讯凭据执行（Logto ID token 或 wdk_ "
    "数据面 key，上游双轨判定）；viewer 角色只读（写操作上游会 403 并如实转述）。"
    "需求单合规门（公开数据源 URL+公开数据声明）必须由用户真实意图驱动——绝不代勾。"
    "错误如实透传（401=未登录/未映射客户、403=无权限、404=无此条目、422=校验逐字段）；"
    "空结果如实为空，绝不编造数据集或数据行。"
)


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
    settings_ = settings or Settings.from_env()
    return _assemble(
        lambda: create_server(settings_),
        auth_cache_ttl_seconds=settings_.auth_cache_ttl_seconds,
        gate_cls=AuthGateMiddleware,
        manifest_anchor=_anchor(),
    )
