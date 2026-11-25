"""HTTP 层鉴权门（ASGI 中间件）——「无 Bearer 拒 / 有 Bearer 放行」变体。

运行时实现已收敛到 `fd_open_data_protocol.line_ops.auth_gate`（openspec:
enforce-mcp-supply-contract / line-ops-runtime-core）。有界缓存（`_MAX_ENTRIES` +
`_evict()`）现在由全部五个消费仓共享——此前只有本仓打过这个补丁，另外四仓的
`_cache` 无上界（灌 5000 个不同 bearer 后缓存留 5000 条，2026-11-09 实测）。

wire API 对无 Bearer 一律 401（实测），且凭据双轨（Logto ID token / wdk_ key）
没有单一轻校验端点——门语义收窄在 spec 已声明；上游对坏凭据的 401 在工具层
原样透传（上游权威）。凭据永不落日志（缓存键 = sha256(token)）。
"""

from __future__ import annotations

from fd_open_data_protocol.line_ops.auth_gate import (
    DEFAULT_MAX_ENTRIES,
    AuthGate,
    AuthGateMiddleware,
    bearer_from_scope,
)

#: 兼容别名：本仓测试与潜在内部调用曾用私有名 `_bearer_from_scope`。
_bearer_from_scope = bearer_from_scope

__all__ = ["AuthGate", "AuthGateMiddleware", "bearer_from_scope", "_bearer_from_scope",
           "DEFAULT_MAX_ENTRIES"]
