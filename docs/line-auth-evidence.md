# 身份、钥匙轨与结算面的生效证据

> 这份文档是**仓内证据**，不属于对外的 `line-manifest.json`。
> 清单的每个字段都会随 `https://wire.finddatatech.cloud/.well-known/line-manifest.json`
> 匿名公开、可被索引，所以清单里只留产品语义。内部代码路径、Secret 名、环境变量、
> 车道地址的代价说明一律写在这里。

## 身份与鉴权分工

工具面**只把进站 Bearer 原样转发**，权威鉴权在上游 `fd-wire`（两条原轨：Logto ID token、
`wdk-` 数据面 key）。本线没有断言兑换端点，所以 `identity.jit_policy = off`——
「平台代做」在 wire 侧一律不允许，不是留白。

## 钥匙轨

| 轨 | kind | 生效 | 说明 |
|---|---|---|---|
| `wdk-data-key` | line-native | 是（fallback） | 数据面 `Bearer wdk-…`，客户级凭据、不承载成员身份、per-key 限流与数据集 allowlist 生效。摘掉平台后照常工作。 |
| `ciyuan-sk` | customer-key | 是（2026-11-14 上产） | 网关把客户 `sk-` 换成 `aud`/`source`=wire、≤600s 的 ES256 票；本服务离线验签后解析到 `billing_customers.sub2api_user_id` 那一行，客户级身份直通 25 个工具。 |

词元票的边界：

- `scope` 决定读写（缺 `line:write` 则 viewer 只读）。
- **不做成员级动作**（`member_sub` 恒 None）。
- 密钥物面（铸/吊 `wdk-`）对词元票一律 403——短命票不能铸长命钥匙。
- 线内实测：真实客户钥匙 → 换票 → 线 200；跨线票 401；匿名 401。

内部实现位置（不进清单）：

- 数据面鉴权：`api/fd_wire_api/data_plane/auth.py`
- 结算聚合与扣减：`api/fd_wire_api/billing/settle.py` / `api/fd_wire_api/billing/sub2api.py`
- 内部运营后台：`web/src/admin`（**不**向平台服务主体开放，故 `surfaces.admin = false`）

## 结算面

客户余额与超额扣减都落在 sub2api（词元平面）：`settle()` 聚合 metering 行数 → 超额经
sub2api **幂等**扣减。本仓 `billing.db` 是账本投影，不是钱的真源 ⇒ `billing.plane = ciyuan`。

## 车道地址（`internal_base_url`）为什么要写字面 IP

`http://10.43.229.59` 是 `fd-prod/wire-ops-mcp` 的 ClusterIP:80，即车道
`/api/lines/<line>/proxy/*` 的转发目标。

平台 pod 是 `hostNetwork: true` + `dnsPolicy: Default`，走宿主解析器，所以
`wire-ops-mcp`、`wire-ops-mcp.fd-prod.svc`、`wire-ops-mcp.fd-prod.svc.cluster.local`
**三个名字全部 ENOTFOUND**，症状是车道 502 `upstream_error`。因此只能写字面 IP。

**代价**：Service 重建后 IP 会变，改 Service 必须同批改本字段并**重出本线镜像**
（清单是 `COPY` 进镜像的），车道侧没有任何东西能发现 IP 变了。

## 2026-11-15 线内实测

- `POST /mcp` 无票 → **401** `{"error":"Authentication required"}`
- 带平台现签的 ≤600s 票 → **200** + 真 MCP 握手（protocolVersion 2024-11-05）

## 相关

- 车道三件套与回滚：`openspec/changes/gateway-line-key-exchange/`
- 清单字段闭集：`openspec/changes/converge-line-identity-and-keys/specs/line-manifest/spec.md`
- 可达性闸：`fd-infra-deploy/tools/check_line_key_reach.py`（四档）
