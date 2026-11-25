"""环境配置（家族模式：Settings.from_env，测试可注入）。

运行时实现已收敛到 `fd_open_data_protocol.line_ops.config`（openspec:
enforce-mcp-supply-contract / line-ops-runtime-core）；本模块只保留线自己的前缀
与默认地址，对外类名与字段不变。
"""

from __future__ import annotations

from fd_open_data_protocol.line_ops.config import make_settings_class

Settings = make_settings_class("WIRE_OPS", "https://wire.finddatatech.cloud")
