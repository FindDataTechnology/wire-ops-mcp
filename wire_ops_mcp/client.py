"""wire 客户面 HTTP 客户端：Bearer 原样转发 + 诚实错误映射。

运行时实现已收敛到 `fd_open_data_protocol.line_ops.client`（openspec:
enforce-mcp-supply-contract / line-ops-runtime-core）。本模块保留线自己的错误类名
`WireError`（工具层与测试按名字捕获它）与上游文案，公共逻辑为共享实现。

wire 特有（spec：上游权威鉴权）——401（未映射客户/缺 token）、403（viewer 只读/
owner-only）、422（需求单合规门逐字段）全原样透传。凭据只经手不落盘；连接失败
/5xx=unreachable。
"""

from __future__ import annotations

from fd_open_data_protocol.line_ops.client import LineClient, LineError


class WireError(LineError):
    """结构化错误：kind + status + 上游 detail 原文。

    继承共享 `LineError`：签名与属性不变，只是名字是 wire 的已发布契约。
    """


MISSING_CREDENTIAL_HINT = (
    "缺少凭据：柏讯客户面需要 Bearer（Logto ID token——壹座同租户登录后获取；"
    "数据面工具也接受 wdk_ 数据面 key）"
)


class WireClient(LineClient):
    """Bearer 原样转发。错误类抛 `WireError`，不可达文案用「柏讯服务」。"""

    def __init__(self, base_url: str, timeout_seconds: float = 20.0, transport=None):
        super().__init__(
            base_url,
            timeout_seconds,
            transport,
            error_cls=WireError,
            service_label="柏讯",
            missing_hint=MISSING_CREDENTIAL_HINT,
        )
