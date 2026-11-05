"""十工具接线测试：薄转发+写显式+上游权威语义透传。"""

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


async def test_demand_submit_thin_forward_with_compliance(bearer):
    fake = FakeClient(result={"id": 1, "status": "submitted"})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("wire_demand_submit", {
            "description": "需要全国城市面板数据",
            "contact_email": "a@b.c",
            "source_urls": ["https://stats.gov.cn/x"],
            "public_data_asserted": True,
            "company": "测试公司",
        })
    call = fake.calls[0]
    assert call["method"] == "POST" and call["path"] == "/api/v1/demands"
    assert call["json_body"]["public_data_asserted"] is True
    assert len(call["json_body"]["source_urls"]) == 1


async def test_demands_list_status_filter(bearer):
    fake = FakeClient(result=[])
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wire_demands_list", {"status": "submitted"})
    assert fake.calls[0]["params"] == {"status": "submitted"}


async def test_dataset_query_readonly_shape(bearer):
    fake = FakeClient(result={"rows": []})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wire_dataset_query", {
            "dataset_id": "ds1", "filters": {"city": "北京"}, "limit": 10,
        })
    call = fake.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/api/v1/datasets/ds1/query"
    assert call["json_body"] == {"limit": 10, "offset": 0, "count_only": False,
                                 "filters": {"city": "北京"}}


async def test_market_subscribe_approval_semantics_pass_through(bearer):
    fake = FakeClient(result={"subscribed": False, "access_request": {"id": 9}, "created": True})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("wire_market_subscribe", {"dataset_id": "mkt1"})
    assert fake.calls[0]["path"] == "/api/v1/market/datasets/mkt1/subscribe"
    data = out.data if hasattr(out, "data") else out
    assert data["result"]["subscribed"] is False  # 不冒充订阅成功


async def test_unsubscribe_delete(bearer):
    fake = FakeClient(result={"ok": True})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wire_market_unsubscribe", {"dataset_id": "mkt1"})
    assert fake.calls[0]["method"] == "DELETE"


async def test_viewer_403_propagates(bearer):
    fake = FakeClient(error=WireError("forbidden", 403, "团队成员权限不足（viewer 只读）"))
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        with pytest.raises(Exception) as ei:
            await c.call_tool("wire_demand_submit", {
                "description": "x", "contact_email": "a@b.c",
                "source_urls": ["https://x"], "public_data_asserted": True,
            })
    assert "viewer 只读" in str(ei.value)


async def test_missing_credential_hints_dual_track(monkeypatch):
    monkeypatch.setattr(tc, "_current_bearer", lambda: None)
    fake = FakeClient()
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        with pytest.raises(Exception) as ei:
            await c.call_tool("wire_datasets_list", {})
    assert "wdk_" in str(ei.value)
    assert fake.calls == []


async def test_packs_list_reads_catalog_and_subscriptions(bearer):
    fake = FakeClient(result={"packs": [{"id": "macro-price", "name_zh": "宏观价格"}], "subscribed": ["macro-price"]})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("wire_packs_list", {})
    calls = [(x["method"], x["path"]) for x in fake.calls]
    assert ("GET", "/api/v1/packs") in calls
    assert ("GET", "/api/v1/packs/subscriptions") in calls


async def test_pack_subscribe_posts_and_reports(bearer):
    fake = FakeClient(result={"pack_id": "macro-price", "subscribed": True})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wire_pack_subscribe", {"pack_id": "macro-price"})
    call = fake.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/api/v1/packs/macro-price/subscribe"


async def test_pack_unsubscribe_posts_and_reports(bearer):
    fake = FakeClient(result={"pack_id": "macro-price", "subscribed": False})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wire_pack_unsubscribe", {"pack_id": "macro-price"})
    call = fake.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/api/v1/packs/macro-price/unsubscribe"


# ── 自理动作闸面（add-esignature-selfaction-gate 组 1）───────────────────────


async def test_self_action_list_thin_forward(bearer):
    fake = FakeClient(result=[{"proposal_id": 7, "action_id": "wire.esignature.initiate",
                               "state": "pending_confirm"}])
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wire_self_action_list", {"page": 1})
    call = fake.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/api/v1/ai/actions"
    assert call["params"] == {"page": 1, "page_size": 50}


async def test_self_action_propose_posts_action_id_args(bearer):
    fake = FakeClient(result={"proposal_id": 9, "action_id": "wire.esignature.initiate",
                              "state": "pending_confirm", "tier": "inline",
                              "impact": "发起电子签任务「x」"})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("wire_self_action_propose", {
            "action_id": "wire.esignature.initiate",
            "args": {"title": "x", "file_name": "c.txt", "file_b64": "QUJD",
                     "signers": [{"name": "A"}]},
        })
    call = fake.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/api/v1/ai/actions/propose"
    assert call["json_body"]["action_id"] == "wire.esignature.initiate"
    assert "signers" in call["json_body"]["args"]
    # 即时 pending：返回载荷含 tier/impact，无 execute 语义字段
    assert out.data["tier"] == "inline"
    assert "proposal_id" in out.data


async def test_self_action_status_reads_by_id(bearer):
    fake = FakeClient(result={"proposal_id": 9, "state": "executed",
                              "result_summary": "task_id=es_01"})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("wire_self_action_status", {"proposal_id": 9})
    call = fake.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/api/v1/ai/actions/9"


async def test_self_action_preflight_fail_no_pending_row(bearer):
    """preflight 失败：4xx 如实文案透传，上游未落 pending（薄转发不吞错）。"""
    fake = FakeClient(error=WireError("preflight_rejected", 422, "发起签署必须带 title。"))
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        # fastmcp 把工具内异常包成 ToolError——如实文案透传（不吞错、不代兜底）
        with pytest.raises(Exception) as exc:
            await c.call_tool("wire_self_action_propose", {
                "action_id": "wire.esignature.initiate", "args": {},
            })
    assert "title" in str(exc.value)
    assert "422" in str(exc.value)


def test_self_action_surface_declared_and_gated():
    """发布门：三工具在 manifest customer 组且 risk 映射正确（双向对拍）。"""
    import json
    from pathlib import Path

    m = json.loads((Path(__file__).resolve().parent.parent / "tool-surface.json").read_text())
    customer = m["tool_groups"][0]
    for t in ("wire_self_action_list", "wire_self_action_propose", "wire_self_action_status"):
        assert t in customer["tools"]
    assert m["tool_risk"]["wire_self_action_propose"] == "write"
    assert m["tool_risk"]["wire_self_action_list"] == "read"
    assert m["tool_risk"]["wire_self_action_status"] == "read"
