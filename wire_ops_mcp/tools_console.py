"""十工具面（design D3）：需求单 3 + 数据面 4 + 市场 3，写显式，Bearer 原样转发。

Bearer 从进站 MCP 请求取（get_http_request 原始头——fastmcp 4.1.0 的
get_http_headers 过滤 Authorization，家族坑）。上游权威鉴权：双轨（Logto ID
token / wdk_ key）由 wire 判定，本层不解析凭据。
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .client import MISSING_CREDENTIAL_HINT, WireClient, WireError


def _current_bearer() -> str | None:
    try:
        from fastmcp.server.dependencies import get_http_request
    except ImportError:
        return None
    req = get_http_request()
    if req is None:
        return None
    auth = (req.headers.get("Authorization") or req.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def _bearer_or_raise() -> str:
    bearer = _current_bearer()
    if not bearer:
        raise WireError("missing_credential", 401, MISSING_CREDENTIAL_HINT)
    return bearer


def register(mcp: FastMCP, client: WireClient) -> None:
    # ── 需求单（3）────────────────────────────────────────────────────────────

    @mcp.tool
    async def wire_demand_submit(
        description: str,
        contact_email: str,
        source_urls: list[str],
        public_data_asserted: bool,
        company: str | None = None,
        indicator_code: str | None = None,
    ) -> dict[str, Any]:
        """提交柏讯意向单（POST /api/v1/demands）——显式写操作。

        必填：需求描述（自由文本）、联系邮箱、≥1 个公开数据源 URL（http/https）、
        公开数据声明（所求数据为公开可获取——false 会被合规门拒绝）。选填：公司名、
        目录锚点 indicator code。初始状态 submitted，运营异步跟进；422 逐字段错误
        如实转述（绝不代勾声明或放宽校验）。
        """
        body: dict[str, Any] = {
            "description": description,
            "contact_email": contact_email,
            "source_urls": source_urls,
            "public_data_asserted": public_data_asserted,
        }
        if company is not None:
            body["company"] = company
        if indicator_code is not None:
            body["indicator_code"] = indicator_code
        result = await client.request(
            "POST", "/api/v1/demands", bearer=_bearer_or_raise(), json_body=body
        )
        return {"submitted": True, "demand": result}

    @mcp.tool
    async def wire_demands_list(status: str | None = None) -> Any:
        """本企业需求单列表（GET /api/v1/demands）——含当前状态与完整时间线。

        status 可选过滤（submitted/scoping/quoting/…以柏讯控制台口径为准）；
        他企需求单不可见（上游映射客户隔离）。
        """
        params = {"status": status} if status else None
        return await client.request(
            "GET", "/api/v1/demands", bearer=_bearer_or_raise(), params=params
        )

    @mcp.tool
    async def wire_demand_read(demand_id: int) -> Any:
        """需求单详情（GET /api/v1/demands/{id}）——他企或不存在一律 404（上游语义）。"""
        return await client.request(
            "GET", f"/api/v1/demands/{demand_id}", bearer=_bearer_or_raise()
        )

    # ── 数据面读（4）──────────────────────────────────────────────────────────

    @mcp.tool
    async def wire_datasets_list() -> Any:
        """本企业数据集列表（GET /api/v1/datasets）。双轨凭据（ID token 或 wdk_ key）。"""
        return await client.request(
            "GET", "/api/v1/datasets", bearer=_bearer_or_raise()
        )

    @mcp.tool
    async def wire_dataset_query(
        dataset_id: str,
        filters: dict[str, Any] | None = None,
        sort: list[dict[str, Any]] | None = None,
        limit: int = 50,
        offset: int = 0,
        count_only: bool = False,
    ) -> Any:
        """数据集查询（POST /api/v1/datasets/{id}/query）——只读。

        filters/sort 形状按柏讯数据面契约；limit 默认 50（大量数据用分页，
        别一次拉全量）；count_only=true 只回计数。
        """
        body: dict[str, Any] = {"limit": limit, "offset": offset, "count_only": count_only}
        if filters:
            body["filters"] = filters
        if sort:
            body["sort"] = sort
        return await client.request(
            "POST", f"/api/v1/datasets/{dataset_id}/query",
            bearer=_bearer_or_raise(), json_body=body,
        )

    @mcp.tool
    async def wire_dataset_aggregate(dataset_id: str, body: dict[str, Any]) -> Any:
        """数据集聚合（POST /api/v1/datasets/{id}/aggregate）——只读。

        body 按柏讯数据面 AggregateIn 契约（group/aggregates 等）薄转发。
        """
        return await client.request(
            "POST", f"/api/v1/datasets/{dataset_id}/aggregate",
            bearer=_bearer_or_raise(), json_body=body,
        )

    @mcp.tool
    async def wire_dataset_rows(
        dataset_id: str, limit: int = 50, offset: int = 0
    ) -> Any:
        """数据集行读（GET /api/v1/datasets/{id}/rows）——只读分页。"""
        return await client.request(
            "GET", f"/api/v1/datasets/{dataset_id}/rows",
            bearer=_bearer_or_raise(), params={"limit": limit, "offset": offset},
        )

    # ── 市场（3）──────────────────────────────────────────────────────────────

    @mcp.tool
    async def wire_market_browse() -> Any:
        """浏览柏讯数据市场目录（GET /api/v1/market/datasets）——公开/客户可见集。"""
        return await client.request(
            "GET", "/api/v1/market/datasets", bearer=_bearer_or_raise()
        )

    @mcp.tool
    async def wire_market_subscribe(dataset_id: str) -> dict[str, Any]:
        """订阅市场数据集（POST /api/v1/market/datasets/{id}/subscribe）——显式写操作。

        approval 档不会直接订阅：上游自动转为访问申请（返回
        {subscribed: false, access_request: …}——如实转述，不冒充订阅成功）。
        """
        result = await client.request(
            "POST", f"/api/v1/market/datasets/{dataset_id}/subscribe",
            bearer=_bearer_or_raise(), json_body={},
        )
        return {"result": result}

    @mcp.tool
    async def wire_market_unsubscribe(dataset_id: str) -> dict[str, Any]:
        """退订市场数据集（DELETE /api/v1/market/datasets/{id}/unsubscribe）——显式写操作。"""
        result = await client.request(
            "DELETE", f"/api/v1/market/datasets/{dataset_id}/unsubscribe",
            bearer=_bearer_or_raise(),
        )
        return {"result": result}

    # ── 源包（3）──────────────────────────────────────────────────────────────

    @mcp.tool
    async def wire_packs_list() -> dict[str, Any]:
        """源包目录 + 我的订阅（GET /api/v1/packs + /subscriptions）——只读。

        包卡片含双语名称/描述与实时指标数；subscribed 为本企业已订包 id 列表。
        """
        packs = await client.request("GET", "/api/v1/packs", bearer=_bearer_or_raise())
        subscribed = await client.request(
            "GET", "/api/v1/packs/subscriptions", bearer=_bearer_or_raise()
        )
        return {"packs": packs, "subscribed": subscribed}

    @mcp.tool
    async def wire_pack_subscribe(pack_id: str) -> dict[str, Any]:
        """订阅源包（POST /api/v1/packs/{id}/subscribe）——显式写操作。

        订阅免费、幂等；未知包上游 404 原文透传。订阅后目录更新即跟踪。
        """
        result = await client.request(
            "POST", f"/api/v1/packs/{pack_id}/subscribe",
            bearer=_bearer_or_raise(), json_body={},
        )
        return {"result": result}

    @mcp.tool
    async def wire_pack_unsubscribe(pack_id: str) -> dict[str, Any]:
        """退订源包（POST /api/v1/packs/{id}/unsubscribe）——显式写操作；幂等。"""
        result = await client.request(
            "POST", f"/api/v1/packs/{pack_id}/unsubscribe",
            bearer=_bearer_or_raise(), json_body={},
        )
        return {"result": result}

    # ── 对象浏览（wire-entity-v2；只读——对象修改沿修正层与动作闸，不在本面）──

    @mcp.tool
    async def wire_object_search(
        entity_id: int,
        q: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Any:
        """按实体搜索对象实例（GET /api/v1/entities/{id}/objects）——只读。

        实体=客户在柏讯声明的业务对象类型（绑定数据集+主键）；q 按实体显示列
        （缺省主键列）contains 检索。cell 档专属（免费档 403 如实）；他企实体
        404 不泄露。返回行按声明列呈现，limit 钳制。
        """
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if q:
            params["q"] = q
        return await client.request(
            "GET",
            f"/api/v1/entities/{entity_id}/objects",
            bearer=_bearer_or_raise(),
            params=params,
        )

    @mcp.tool
    async def wire_object_get(entity_id: int, key: str) -> Any:
        """按主键取单个对象（GET /api/v1/entities/{id}/objects/{key}）——只读。

        零行命中返回结构化「无此对象」态（found=false，不泄露历史存在性）；
        v0 仅支持单列主键实体。
        """
        return await client.request(
            "GET",
            f"/api/v1/entities/{entity_id}/objects/{key}",
            bearer=_bearer_or_raise(),
        )

    @mcp.tool
    async def wire_object_relations(
        entity_id: int, key: str, relationship_id: int, page: int = 1
    ) -> Any:
        """沿关系遍历关联对象（GET …/objects/{key}/relations/{rid}）——只读。

        按关系声明方向遍历：n:1 反查目标行 / 1:n 正查引用行 / m:n 经中间
        数据集两段查询。只执行声明查询（读边界纪律），分页钳制。
        """
        return await client.request(
            "GET",
            f"/api/v1/entities/{entity_id}/objects/{key}/relations/{relationship_id}",
            bearer=_bearer_or_raise(),
            params={"page": page},
        )

    # ── 客户域动作（wire-domain-actions；提议面——执行走柏讯闸确认链，
    #    工具面结构性无 execute；不镜像壹座拍板面）──

    @mcp.tool
    async def wire_action_list() -> Any:
        """本企业已启用的域动作类型清单（GET /api/v1/domain-actions）——只读。

        返回动作类型（挂实体、风险档、表单字段 schema）——供构造
        wire_action_propose 提议。viewer 只读不受影响（list 无写语义）。
        """
        return await client.request(
            "GET", "/api/v1/domain-actions", bearer=_bearer_or_raise()
        )

    @mcp.tool
    async def wire_action_propose(
        action_type_id: int,
        values: dict[str, Any],
        source_ref: str | None = None,
    ) -> dict[str, Any]:
        """提议一个域动作（POST /api/v1/domain-actions/propose）——写提议面。

        **即时返回 pending 提议标识，不等待人工确认**（对偶义务：阻塞实现
        会被壹座回合归因 stalled）；执行由人（owner）在柏讯控制台确认后经
        闸管线落库——本工具面结构性无 execute。source_ref 为调用方原样透传
        的岗位来源标注（≤256 字符，柏讯台账不解析）——壹座身份行 key 名
        fleet=/post=/title=/target=，turn= 字段位预留。

        viewer 角色不可提议（403）；未注册/停用/他企类型一律「未注册」拒绝；
        表单值校验 422 逐字段。
        """
        body: dict[str, Any] = {
            "action_type_id": action_type_id,
            "values": values,
        }
        if source_ref:
            body["source_ref"] = source_ref
        return await client.request(
            "POST", "/api/v1/domain-actions/propose",
            bearer=_bearer_or_raise(), json_body=body,
        )

    @mcp.tool
    async def wire_action_status(instance_id: int) -> Any:
        """查域动作实例状态（GET /api/v1/domain-actions/instances/{id}）——只读。

        返回实例台账行（status: awaiting_confirmation/executed/rejected/
        failed/disabled；executed 含 correction_id 与 error 文本）。下轮巡检
        读状态即可达意——柏讯侧不推送、壹座侧不轮询建徽标（评审 R2 口径）。
        """
        return await client.request(
            "GET",
            f"/api/v1/domain-actions/instances/{instance_id}",
            bearer=_bearer_or_raise(),
        )

    # ── 自理动作闸面（add-esignature-selfaction-gate 组 1；ai/actions.py REGISTRY
    #    形态=action_id 字符串，wire.esignature.* 等自理写动作的唯一壹座入口）──
    #    上游=/api/v1/ai/actions 五端点（面板直发入口，require_console_actor）。
    #    对偶义务同 domain 版：propose 即时 pending 不等待人工确认（阻塞实现
    #    会被壹座回合归因 stalled）；确认与执行在柏讯唯一确认面——本面结构性
    #    无 approve/execute 映射。

    @mcp.tool
    async def wire_self_action_list(page: int = 1, page_size: int = 50) -> Any:
        """列本企业自理动作提议台账（GET /api/v1/ai/actions）——只读。

        返回提议台账行（action_id、状态 pending_confirm/executed/rejected/
        failed、tier、impact 摘要），按创建时间倒序；电子签三动作
        （wire.esignature.initiate/nudge/archive，write→inline 档）的提议与
        结果都在此可查。可用动作以 REGISTRY 在册名为准——本面不提供
        approve/execute，任何动作的执行都在柏讯唯一确认面完成。
        """
        return await client.request(
            "GET", "/api/v1/ai/actions", bearer=_bearer_or_raise(),
            params={"page": page, "page_size": page_size},
        )

    @mcp.tool
    async def wire_self_action_propose(action_id: str, args: dict[str, Any]) -> dict[str, Any]:
        """提议一个自理动作（POST /api/v1/ai/actions/propose）——写提议面。

        即时返回 pending 提议标识（proposal_id/tier/impact 人类可读影响面），
        **不等待人工确认**；执行由 owner 在柏讯控制台确认后经闸管线进行——
        本面结构性无 execute。未注册/停用/他企 action_id 与 preflight 失败
        （如缺 title/signers）一律 4xx 如实文案且不落 pending。下轮巡检用
        wire_self_action_status 读结果，本轮即收。
        """
        return await client.request(
            "POST", "/api/v1/ai/actions/propose",
            bearer=_bearer_or_raise(),
            json_body={"action_id": action_id, "args": args},
        )

    @mcp.tool
    async def wire_self_action_status(proposal_id: int) -> Any:
        """查自理动作提议状态（GET /api/v1/ai/actions/{proposal_id}）——只读。

        返回单条提议台账行；executed 含结果摘要、failed 含错误原文。柏讯侧
        不推送、壹座侧不轮询建徽标（评审 R2 口径沿用）——岗位下轮巡检读
        状态即可达意。
        """
        return await client.request(
            "GET", f"/api/v1/ai/actions/{proposal_id}", bearer=_bearer_or_raise()
        )

    # ── 星研内容供给（3）──────────────────────────────────────────────────────
    # 三类窄工具（spec「工具面显式窄声明」）：目录列举 / 条目检索 / claim 取回。
    # 上游是官方公开件镜像，不读客户数据；但工具面仍拒绝未声明扩张——新增
    # 端点必须先改 tool-surface.json（暴露面清单是发布门的唯一真源）。

    @mcp.tool
    async def wire_content_browse(
        zone: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Any:
        """星研内容目录列举（GET /api/v1/xingyan/items）——只读。

        zone ∈ briefings（内参）/ academy（学院）/ research（研究）；不传则三区
        合并。返回条目摘要（slug、双语标题/摘要、日期、claim 计数、页面地址）
        并携带 snapshot 块：source_sha 是上游快照指纹，stale=true 表示内容
        落后于官网（此时仍返回上一版，绝不返回空集冒充）。
        """
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if zone:
            params["zone"] = zone
        return await client.request(
            "GET", "/api/v1/xingyan/items", bearer=_bearer_or_raise(), params=params
        )

    @mcp.tool
    async def wire_content_search(
        q: str,
        zone: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Any:
        """星研内容条目检索（GET /api/v1/xingyan/items?q=）——只读。

        关键词匹配双语标题/摘要与 slug；可与 zone 叠加。空结果如实为空——
        不编造条目。响应同样携带 snapshot 指纹与陈旧标记。
        """
        params: dict[str, Any] = {"q": q, "page": page, "page_size": page_size}
        if zone:
            params["zone"] = zone
        return await client.request(
            "GET", "/api/v1/xingyan/items", bearer=_bearer_or_raise(), params=params
        )

    @mcp.tool
    async def wire_claim_resolve(slug: str, claim_id: str, locale: str = "zh") -> Any:
        """按全局 ID 取回一条 claim（GET /api/v1/xingyan/claims/{slug}/{claim_id}）。

        全局 ID 形如 ``law-bench-evaluation-loop/c0001``（slug/claim-id，跨语言
        同一 ID）。返回 claim 骨架（类型、证据 key 集）、锚定小节的正文
        （section_text，按 locale 取对应语言正文；section_found=false 表示
        锚点标题在当前正文里找不到，此时不给空串冒充内容）、以及逐条可解析的
        证据来源（resolved=false 表示该 key 在当前条目来源里解不到）。

        已撤销的 claim 返回 200 + status="withdrawn"（保留登记供溯源），
        不是未找到；真正不存在才 404。
        """
        return await client.request(
            "GET",
            f"/api/v1/xingyan/claims/{slug}/{claim_id}",
            bearer=_bearer_or_raise(),
            params={"locale": locale},
        )

    # ── 追踪主体（wire-subject-tracking；单实体的多通道持续追踪 + 物化）──

    @mcp.tool
    async def wire_subject_create(
        kind: str,
        ref: dict,
        title: str,
        description: str | None = None,
        channels: list[dict] | None = None,
    ) -> Any:
        """声明一个追踪主体（POST /api/v1/subjects）。

        kind ∈ {company, industry, chain, country, region}；ref 形如
        {source: stock_code, code: "600519"} 或 {source: chain_spec, name, segments}。
        channels 每项 {type, spec}，type ∈ {indicators, announcements, registry,
        graph, context}。非法 kind/ref/通道 422 如实定位。
        """
        body: dict[str, Any] = {"kind": kind, "ref": ref, "title": title}
        if description is not None:
            body["description"] = description
        if channels:
            body["channels"] = channels
        return await client.request(
            "POST", "/api/v1/subjects", bearer=_bearer_or_raise(), json_body=body
        )

    @mcp.tool
    async def wire_subject_list(kind: str | None = None) -> Any:
        """列出本团队的全部追踪主体（GET /api/v1/subjects?kind=）——只读。"""
        params = {"kind": kind} if kind else None
        return await client.request(
            "GET", "/api/v1/subjects", bearer=_bearer_or_raise(), params=params
        )

    @mcp.tool
    async def wire_subject_get(subject_id: int) -> Any:
        """取一个追踪主体的声明与通道（GET /api/v1/subjects/{id}）——只读。"""
        return await client.request(
            "GET", f"/api/v1/subjects/{subject_id}", bearer=_bearer_or_raise()
        )

    @mcp.tool
    async def wire_subject_read(subject_id: int) -> Any:
        """扇出主体全部通道读一次（GET /api/v1/subjects/{id}/read）——只读零计量。

        返回 {subject, channels[], timeline[]}；每个通道带 coverage 三态
        （available/stale/unavailable），上游不可用如实标注、不渲染成 0 条。
        服务端不做统计推断——关系/传导交给 pack 层技能。
        """
        return await client.request(
            "GET", f"/api/v1/subjects/{subject_id}/read", bearer=_bearer_or_raise()
        )

    @mcp.tool
    async def wire_subject_snapshot(subject_id: int) -> Any:
        """把主体读结果物化成本团队数据集（POST /api/v1/subjects/{id}/snapshot）。

        幂等：同主体再次快照更新既有数据集。返回 {dataset_id, dataset_key,
        row_count}——该数据集可直接进 dashboard / alert_rule / 市场，走既有面。
        """
        return await client.request(
            "POST", f"/api/v1/subjects/{subject_id}/snapshot",
            bearer=_bearer_or_raise(), json_body={},
        )

    @mcp.tool
    async def wire_subject_archive(subject_id: int) -> Any:
        """归档一个追踪主体（DELETE /api/v1/subjects/{id}）——删主体并级联删通道。"""
        return await client.request(
            "DELETE", f"/api/v1/subjects/{subject_id}", bearer=_bearer_or_raise()
        )

    @mcp.tool
    async def wire_subject_add_channel(
        subject_id: int, ctype: str, spec: dict | None = None
    ) -> Any:
        """给主体加一个通道（POST /api/v1/subjects/{id}/channels）。"""
        return await client.request(
            "POST", f"/api/v1/subjects/{subject_id}/channels",
            bearer=_bearer_or_raise(),
            json_body={"type": ctype, "spec": spec or {}},
        )

    @mcp.tool
    async def wire_subject_remove_channel(subject_id: int, channel_id: int) -> Any:
        """删除主体的一个通道（DELETE /api/v1/subjects/{id}/channels/{cid}）。"""
        return await client.request(
            "DELETE", f"/api/v1/subjects/{subject_id}/channels/{channel_id}",
            bearer=_bearer_or_raise(),
        )
