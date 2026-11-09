"""AuthGate（家族变体）：无 Bearer 拒、有 Bearer 放行。"""

from __future__ import annotations

from wire_ops_mcp.auth_gate import _bearer_from_scope, AuthGate


async def test_anonymous_rejected():
    assert await AuthGate().check(None) is False


async def test_any_bearer_passes():
    assert await AuthGate().check("anything") is True


def test_gateway_header_is_accepted():
    """The gateway forwards the caller's token as `x-authorization`; reading only
    the standard header made every proxied call a 401 (live 2026-11-09)."""
    scope = {"headers": [(b"x-authorization", b"Bearer caller-token")]}
    assert _bearer_from_scope(scope) == "caller-token"


def test_bearer_extraction_ignores_empty_and_other_schemes():
    assert _bearer_from_scope({"headers": [(b"authorization", b"Bearer direct")]}) == "direct"
    assert _bearer_from_scope({"headers": [(b"x-authorization", b"Bearer  ")]}) is None
    assert _bearer_from_scope({"headers": [(b"x-authorization", b"Basic abc")]}) is None
