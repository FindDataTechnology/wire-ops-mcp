"""鉴权门的 token 缓存必须是有界的——现在它只增不减。

四个 MCP 门（`wire-ops-mcp` / `wire-build-mcp` / `wanxing-ops-mcp` / `facet-ops-mcp`）
都把「这个 bearer 见过没有」缓存在进程内 `dict[str, tuple[float, bool]]`，TTL 60s，
目的是避免每个 `initialize` 都打一次上游。

**问题**：这个 dict 没有任何淘汰。门对**任意**非空 bearer 都会写一条记录
（门语义是"无 Bearer 拒 / 有 Bearer 放行"，有效性由上游权威判定），所以：

* 一个坏客户端每次带随机 bearer 重试 → 每条一个新键；
* 负载均衡后面一批 agent 各自轮换 token → 同样每条一个新键；
* 这些请求**不需要任何有效凭据**，只要能路由到本服务。

键是 `sha256(token)`（64 字符），加 tuple，每条约 150-200 字节。长跑进程的 RSS
随时间单调上升，最终 OOM 重启；重启后又走一遍启动退避。这类"只在并发高时出现"
的泄漏最难在测试里撞见，所以用单元测试直接量缓存规模。

本文件对着 `wire-ops-mcp` 写；四个门的实现同形，修法一致。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "wire-ops-mcp"))

from wire_ops_mcp.auth_gate import AuthGate  # noqa: E402


def test_cache_is_bounded_under_many_distinct_bearers():
    """灌 5000 个不同 bearer，缓存条目必须停在某个上界内。"""
    gate = AuthGate()
    n = 5000

    async def run():
        for i in range(n):
            assert await gate.check(f"token-{i}") is True

    asyncio.run(run())
    size = len(gate._cache)
    assert size <= 1024, (
        f"缓存被灌了 {n} 个不同 bearer 后仍留 {size} 条 —— 无上界，"
        "长跑进程会单调增长到 OOM"
    )


def test_valid_calls_still_pass_and_empty_is_rejected():
    """有界化不许改变门的语义：有 bearer 放行、无 bearer 拒绝。"""
    gate = AuthGate()

    async def run():
        assert await gate.check("any-token") is True
        assert await gate.check("") is False
        assert await gate.check(None) is False
        # 重复同一 token 仍应放行（命中缓存或重算都行）
        assert await gate.check("any-token") is True

    asyncio.run(run())


def test_expired_entries_are_dropped():
    """过期项要被清掉，否则上界只是把泄漏变慢。"""
    gate = AuthGate(ttl_seconds=0.0)

    async def run():
        for i in range(50):
            await gate.check(f"tok-{i}")
        # TTL=0 → 下一次写入时应当把过期的清走
        await gate.check("trigger")

    asyncio.run(run())
    assert len(gate._cache) <= 8, f"TTL 已过期但缓存仍留 {len(gate._cache)} 条"
