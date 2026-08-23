"""Exit-gate tests for ProviderStrategy plan-aware chains (Step 18, RFC-002 §7).

``get_model_chain`` (role-only) must keep working; ``get_model_chain_for_plan``
must re-rank by capability weight for the plan's ``task_type`` and size the
chain by ``complexity``. Route-aware role aliases resolve onto generation/judge.
"""

from __future__ import annotations

from dataclasses import dataclass

from api_gateway.strategy import ProviderStrategy


@dataclass
class _Plan:
    task_type: str = "general"
    complexity: str = "medium"


# ── get_model_chain (compat) ─────────────────────────────────────────────


def test_get_model_chain_unchanged_for_base_roles() -> None:
    strat = ProviderStrategy("PAID")
    chain = strat.get_model_chain("generation")
    assert chain[0] == "openrouter/anthropic/claude-sonnet-5"
    assert len(chain) >= 2  # primary + fallback guarantee


def test_route_aware_role_aliases_resolve() -> None:
    strat = ProviderStrategy("PAID")
    # critical_judge aliases onto 'judge'.
    assert strat.get_model_chain("critical_judge") == strat.get_model_chain("judge")


def test_unknown_role_raises() -> None:
    strat = ProviderStrategy("FREE")
    try:
        strat.get_model_chain("nonsense_role")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for unknown role")


def test_exact_model_can_be_disabled_without_mutating_global_maps() -> None:
    first = ProviderStrategy("PAID")
    second = ProviderStrategy("PAID")
    model = first.get_model_chain("generation")[0]

    assert first.set_model_enabled(model, False) is True
    assert model not in first.get_model_chain("generation")
    assert model in first.get_configured_model_chain("generation")
    assert first.is_model_enabled(model) is False
    assert model in second.get_model_chain("generation")


def test_unknown_model_cannot_be_toggled() -> None:
    strategy = ProviderStrategy("HYBRID")
    assert strategy.set_model_enabled("missing/model", False) is False


# ── get_model_chain_for_plan ─────────────────────────────────────────────


def test_low_complexity_returns_single_primary() -> None:
    strat = ProviderStrategy("PAID")
    chain = strat.get_model_chain_for_plan(_Plan(task_type="coding", complexity="low"))
    assert len(chain) == 1


def test_critical_complexity_widens_chain() -> None:
    strat = ProviderStrategy("PAID")
    low = strat.get_model_chain_for_plan(_Plan(task_type="coding", complexity="low"))
    crit = strat.get_model_chain_for_plan(
        _Plan(task_type="coding", complexity="critical")
    )
    assert len(crit) > len(low)


def test_coding_plan_prefers_strongest_coding_model() -> None:
    # PAID generation chain: claude-sonnet-5(coding .92), gpt-4o(.83),
    # deepseek-chat(.82) → re-rank puts claude first at 'high' depth.
    strat = ProviderStrategy("PAID")
    chain = strat.get_model_chain_for_plan(_Plan(task_type="coding", complexity="high"))
    assert chain[0] == "openrouter/anthropic/claude-sonnet-5"


def test_unknown_task_type_degrades_to_generation() -> None:
    strat = ProviderStrategy("FREE")
    chain = strat.get_model_chain_for_plan(_Plan(task_type="astrology", complexity="medium"))
    # Falls back to the plain generation chain; never raises.
    assert chain
    assert chain[0] in strat.get_model_chain("generation")


def test_missing_plan_attrs_default_general_medium() -> None:
    strat = ProviderStrategy("HYBRID")

    class _Bare:
        pass

    chain = strat.get_model_chain_for_plan(_Bare())
    assert 1 <= len(chain) <= 2  # 'medium' depth
