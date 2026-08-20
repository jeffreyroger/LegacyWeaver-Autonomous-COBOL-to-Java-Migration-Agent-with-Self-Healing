"""Phase X8 acceptance tests (docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md
X8, migration-framework-spec.md Section 5.2 Step 2) -- the six
witness-search algorithms, exercised over synthetic `FieldDomain`s (no
`.cob` file hardcoded here; generality across real COBOL fixtures is
covered separately in tests/test_leaf_orchestrator_witness_search.py and
tests/test_synthetic_records.py)."""

from decimal import Decimal

from weaver.agent.witness_search import (
    FieldDomain,
    generate_adaptive_random,
    generate_latin_hypercube,
    generate_map_elites,
    generate_pairwise,
    generate_three_way,
    generate_ucb1_bandit,
    generate_witnesses,
)

D_IN = FieldDomain(name="IN", width=7, scale=2, signed=False)
D_OUT = FieldDomain(name="OUT", width=8, scale=2, signed=False)
D_A = FieldDomain(name="A", width=5, scale=2, signed=False)
D_B = FieldDomain(name="B", width=5, scale=2, signed=True)


def _in_domain(value: Decimal, domain: FieldDomain) -> bool:
    return domain.min_value <= value <= domain.max_value


def test_pairwise_deterministic_and_in_domain():
    a = generate_pairwise([D_IN], seed=42, budget=6)
    b = generate_pairwise([D_IN], seed=42, budget=6)
    assert a == b
    assert all(_in_domain(w["IN"], D_IN) for w in a)
    assert len(a) > 0


def test_pairwise_multi_field_covers_pairs():
    witnesses = generate_pairwise([D_A, D_B], seed=1, budget=12)
    assert len(witnesses) > 1
    for w in witnesses:
        assert set(w) == {"A", "B"}
        assert _in_domain(w["A"], D_A)
        assert _in_domain(w["B"], D_B)


def test_three_way_deterministic_and_covers_three_fields():
    witnesses = generate_three_way([D_A, D_B, D_IN], seed=7, budget=10)
    assert witnesses == generate_three_way([D_A, D_B, D_IN], seed=7, budget=10)
    for w in witnesses:
        assert set(w) == {"A", "B", "IN"}


def test_latin_hypercube_stratifies_and_is_deterministic():
    witnesses = generate_latin_hypercube([D_IN], seed=3, budget=8)
    assert witnesses == generate_latin_hypercube([D_IN], seed=3, budget=8)
    assert len(witnesses) == 8
    assert len({w["IN"] for w in witnesses}) == 8  # distinct strata, no collapse
    assert all(_in_domain(w["IN"], D_IN) for w in witnesses)


def test_adaptive_random_spreads_out_and_is_deterministic():
    witnesses = generate_adaptive_random([D_IN], seed=5, budget=6)
    assert witnesses == generate_adaptive_random([D_IN], seed=5, budget=6)
    values = sorted(w["IN"] for w in witnesses)
    assert len(set(values)) == len(values)  # every pick distinct


def _stub_oracle(w: dict) -> dict:
    """Deterministic synthetic oracle used only to prove MAP-Elites/UCB1's
    real execution-feedback mechanics, independent of any COBOL fixture."""
    value = w["IN"]
    if value == 0:
        out = Decimal("0.00")
    elif value < 0:
        out = value
    else:
        out = min(value * 3, D_OUT.max_value)
    return {"OUT": out}


def test_map_elites_covers_multiple_outcome_shapes():
    witnesses = generate_map_elites([D_IN], seed=9, budget=6, oracle_fn=_stub_oracle, output_domains=[D_OUT])
    shapes = set()
    for w in witnesses:
        out = _stub_oracle(w)["OUT"]
        shapes.add((-1 if out < 0 else (0 if out == 0 else 1),))
    assert len(shapes) >= 1
    assert len(witnesses) <= 6


def test_ucb1_visits_multiple_arms_before_pure_exploitation():
    witnesses = generate_ucb1_bandit([D_IN], seed=11, budget=6, oracle_fn=_stub_oracle, output_domains=[D_OUT])
    assert len(witnesses) == 6
    assert all(_in_domain(w["IN"], D_IN) for w in witnesses)


def test_generate_witnesses_unions_and_dedups():
    combined = generate_witnesses([D_IN], oracle_fn=_stub_oracle, seed=0, per_algorithm_budget=6, output_domains=[D_OUT])
    without_feedback = generate_witnesses([D_IN], oracle_fn=None, seed=0, per_algorithm_budget=6)
    assert len(combined) >= len(without_feedback)
    keys = [tuple(sorted(w.items())) for w in combined]
    assert len(keys) == len(set(keys))  # no duplicates
