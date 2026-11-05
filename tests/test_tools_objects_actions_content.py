"""objects/actions/content 九工具接线测试：薄转发 + 谓词正确 + 上游错误原样透传。

tool-surface.json 22 工具中此前零用例的 9 个（tests/test_tools.py 只覆盖 v1 十
+ packs 三）：
- 对象浏览三（wire_object_search/get/relations——只读，wire-entity-v2）
- 客户域动作三（wire_action_list/propose/status——提议面，结构性无 execute）
- 星研内容三（wire_content_browse/search + wire_claim_resolve——只读快照）

沿用 tests/test_tools.py 的风格：FakeClient mock client.request 记录
(method, path, bearer, params, json_body)，上游错误以 WireError 注入。
"""

from __future__ import annotations

import pytest
from fastmcp import Client, FastMCP

import wire_ops_mcp.tools_console as tc
from wire_ops_mcp.client import WireError


class FakeClient:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result
        self.error = error

    async def request(self, method, path, *, bearer, params=None, json_body=None):
        self.calls.append({"method": method, "path": path, "bearer": bearer,
                           "params": params, "json_body": json_body})
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def bearer(monkeypatch):
    monkeypatch.setattr(tc, "_current_bearer", lambda: "tok-abc")
    return "tok-abc"


async def _mk(fake):
    mcp = FastMCP("t-wire")
    tc.register(mcp, fake)
    return mcp


def _data(out):
    return out.data if hasattr(out, "data") else out


# ── 上游错误原样透传（9 工具 × 401/404/5xx）──────────────────────────────────

_UPSTREAM_ERRORS = [
    pytest.param(WireError("unauthorized", 401, "token 无效或过期（上游原文）"), id="401"),
    pytest.param(WireError("not_found", 404, "他企实体不可见（上游原文）"), id="404"),
    pytest.param(WireError("unreachable", 503, "柏讯服务错误：gateway timeout"), id="5xx"),
]

_TOOL_ARGS = {
    "wire_object_search": {"entity_id": 7, "q": "北京"},
    "wire_object_get": {"entity_id": 7, "key": "C1001"},
    "wire_object_relations": {"entity_id": 7, "key": "C1001", "relationship_id": 3,
                              "page": 4},
    "wire_action_list": {},
    "wire_action_propose": {"action_type_id": 11, "values": {"对象ID": "C1001"}},
    "wire_action_status": {"instance_id": 88},
    "wire_content_browse": {"zone": "briefings"},
    "wire_content_search": {"q": "GDP"},
    "wire_claim_resolve": {"slug": "law-bench-evaluation-loop", "claim_id": "c0001"},
}


@pytest.mark.parametrize("tool", list(_TOOL_ARGS))
@pytest.mark.parametrize("err", _UPSTREAM_ERRORS)
async def test_upstream_error_passthrough(bearer, tool, err):
    """上游 401/404/5xx 原样透传：kind 标记、上游 detail 原文、HTTP 状态码全保留。"""
    fake = FakeClient(error=err)
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        with pytest.raises(Exception) as ei:
            await c.call_tool(tool, _TOOL_ARGS[tool])
    msg = str(ei.value)
    assert f"[{err.kind}]" in msg        # kind 标记不丢
    assert err.detail in msg             # 上游 detail 原文不丢
    assert f"HTTP {err.status}" in msg   # 状态码不丢


# ── 对象浏览（3）─────────────────────────────────────────────────────────────

async def test_object_search_forwards_get_and_params(bearer):
    fake = FakeClient(result={"rows": [{"对象ID": "C1001"}], "total": 1})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("wire_object_search",
                                {"entity_id": 7, "q": "北京", "page": 2, "page_size": 5})
        await c.call_tool("wire_object_search", {"entity_id": 7})
    assert fake.calls[0]["method"] == "GET"
    assert fake.calls[0]["path"] == "/api/v1/entities/7/objects"
    assert fake.calls[0]["params"] == {"page": 2, "page_size": 5, "q": "北京"}
    assert fake.calls[0]["bearer"] == "tok-abc"          # Bearer 原样转发
    assert fake.calls[1]["params"] == {"page": 1, "page_size": 20}  # q 缺省不进 query
    assert _data(out)["total"] == 1                      # 上游结果原样


async def test_object_get_key_in_path(bearer):
    fake = FakeClient(result={"found": True, "row": {"对象ID": "C1001"}})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wire_object_get", {"entity_id": 7, "key": "C1001"})
    call = fake.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/api/v1/entities/7/objects/C1001"
    assert call["params"] is None                        # 主键走路径不进 query


async def test_object_relations_path_and_page(bearer):
    fake = FakeClient(result={"rows": [], "total": 0})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wire_object_relations",
                          {"entity_id": 7, "key": "C1001", "relationship_id": 3, "page": 4})
    call = fake.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/api/v1/entities/7/objects/C1001/relations/3"
    assert call["params"] == {"page": 4}


# ── 客户域动作（3）───────────────────────────────────────────────────────────

async def test_action_list_get(bearer):
    fake = FakeClient(result={"actions": [{"id": 11, "name": "标记重点对象", "risk": "write"}]})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("wire_action_list", {})
    call = fake.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/api/v1/domain-actions"
    assert call["params"] is None
    assert _data(out)["actions"][0]["id"] == 11          # 动作类型清单原样


async def test_action_propose_body_shape_and_source_ref(bearer):
    fake = FakeClient(result={"proposal_id": "pa_1", "status": "awaiting_confirmation"})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wire_action_propose", {
            "action_type_id": 11, "values": {"对象ID": "C1001", "标签": "重点"},
            "source_ref": "fleet=测试队/post=分析岗",
        })
        await c.call_tool("wire_action_propose",
                          {"action_type_id": 11, "values": {"对象ID": "C1001"}})
    first, second = fake.calls
    assert first["method"] == "POST" and first["path"] == "/api/v1/domain-actions/propose"
    assert first["bearer"] == "tok-abc"
    assert first["json_body"] == {
        "action_type_id": 11,
        "values": {"对象ID": "C1001", "标签": "重点"},
        "source_ref": "fleet=测试队/post=分析岗",        # source_ref 原样透传
    }
    assert second["json_body"] == {                      # 缺省不带 source_ref
        "action_type_id": 11, "values": {"对象ID": "C1001"},
    }


async def test_action_propose_returns_pending_without_executing(bearer):
    """即时返回 pending 提议标识，不等待确认：仅 propose 一次上游调用、
    结构性无 execute/confirm。"""
    pending = {"proposal_id": "pa_20261106_0001", "status": "awaiting_confirmation",
               "action_type_id": 11}
    fake = FakeClient(result=pending)
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("wire_action_propose",
                                {"action_type_id": 11, "values": {"对象ID": "C1001"}})
    data = _data(out)
    assert data["proposal_id"] == "pa_20261106_0001"     # pending 标识原样透传
    assert data["status"] == "awaiting_confirmation"     # 不冒充已执行
    assert len(fake.calls) == 1                          # 无第二次（execute/confirm）调用
    assert fake.calls[0]["path"] == "/api/v1/domain-actions/propose"


async def test_action_status_path(bearer):
    fake = FakeClient(result={"status": "executed", "correction_id": 42})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("wire_action_status", {"instance_id": 88})
    call = fake.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/api/v1/domain-actions/instances/88"
    assert _data(out)["status"] == "executed"            # 台账状态原样（不推送不轮询）


# ── 星研内容（3）─────────────────────────────────────────────────────────────

async def test_content_browse_zone_and_snapshot_passthrough(bearer):
    fake = FakeClient(result={"items": [{"slug": "macro-cpi"}],
                              "snapshot": {"source_sha": "abc123", "stale": True}})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("wire_content_browse",
                                {"zone": "briefings", "page": 3, "page_size": 10})
        await c.call_tool("wire_content_browse", {})
    call = fake.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/api/v1/xingyan/items"
    assert call["params"] == {"page": 3, "page_size": 10, "zone": "briefings"}
    assert fake.calls[1]["params"] == {"page": 1, "page_size": 20}  # 不传 zone 三区合并
    data = _data(out)
    assert data["snapshot"]["source_sha"] == "abc123"    # 快照指纹原样
    assert data["snapshot"]["stale"] is True             # 陈旧标记原样（不冒充最新）


async def test_content_search_q_forwarded(bearer):
    fake = FakeClient(result={"items": [], "snapshot": {"source_sha": "def456", "stale": False}})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("wire_content_search",
                                {"q": "GDP 平减指数", "zone": "research"})
        await c.call_tool("wire_content_search", {"q": "CPI"})
    call = fake.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/api/v1/xingyan/items"
    assert call["params"] == {"q": "GDP 平减指数", "page": 1, "page_size": 20,
                              "zone": "research"}
    assert fake.calls[1]["params"]["q"] == "CPI"
    assert "zone" not in fake.calls[1]["params"]         # zone 缺省不进 query
    assert _data(out)["items"] == []                     # 空结果如实为空


async def test_claim_resolve_path_and_locale(bearer):
    fake = FakeClient(result={"status": "active", "section_text": "……",
                              "section_found": True})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("wire_claim_resolve",
                                {"slug": "law-bench-evaluation-loop", "claim_id": "c0001"})
        await c.call_tool("wire_claim_resolve",
                          {"slug": "law-bench-evaluation-loop", "claim_id": "c0001",
                           "locale": "en"})
    call = fake.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/api/v1/xingyan/claims/law-bench-evaluation-loop/c0001"
    assert call["params"] == {"locale": "zh"}            # 缺省中文正文
    assert fake.calls[1]["params"] == {"locale": "en"}   # locale 转发
    assert _data(out)["section_text"] == "……"            # 锚小节正文原样
