"""Six witness-search algorithms -- Phase X8
(docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md), migration-framework-spec.md
Section 5.2 Step 2.

Generic over any list of `FieldDomain`s -- never hardcoded to a specific
`.cob` file. A caller derives one `FieldDomain` per numeric COBOL field it
cares about (a subprogram's LINKAGE parameters via
`weaver.cobol.subprogram.SubprogramModel`, or a full program's input
record fields via `weaver.agent.scaffold.ScaffoldSpec.input_layout`) and
hands the list here; this module knows nothing about program shape, file
names, or fixture identity.

A *witness* is `dict[str, Decimal]` -- one value per field name. This lets
the same six algorithms serve a single-field subprogram (a 1-key dict) and
a multi-field program or subprogram (an N-key dict) without special-casing
either.

Disclosed scope adaptation: the spec (Section 5.2) describes these
algorithms in terms of compound `IF` branch coverage. This harness's real
oracle-execution feedback signal (used by MAP-Elites and UCB1) is the
*output shape* of a real GnuCOBOL run -- sign, zero-ness, and width
saturation of each output field -- rather than an instrumented branch
trace, since no paragraph-level coverage instrumentation exists in this
codebase. This is real, distinct, execution-driven work over the actual
verification surface this project has, not a fabrication of coverage
numbers.

All randomness is seeded (`random.Random(seed)`) -- deterministic, no
unseeded randomness anywhere (consistent with `RunSpec.seed`, CLAUDE.md
rule 13).
"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from weaver.layout import Field

Witness = dict[str, Decimal]
OracleFn = Callable[[Witness], Witness]


@dataclass(frozen=True)
class FieldDomain:
    name: str
    width: int
    scale: int
    signed: bool
    trailing_separate_sign: bool = False

    @classmethod
    def from_field(cls, name: str, field: Field) -> "FieldDomain":
        return cls(name=name, width=field.width, scale=field.decimal_scale, signed=field.signed,
                    trailing_separate_sign=getattr(field, "trailing_separate_sign", False))

    @property
    def digit_width(self) -> int:
        """Digit count of PIC 9(n)V9(m) -- excludes a trailing separate
        sign byte, which is not a digit position."""
        return self.width - (1 if self.trailing_separate_sign else 0)

    @property
    def integer_digits(self) -> int:
        return self.digit_width - self.scale

    @property
    def max_value(self) -> Decimal:
        magnitude = Decimal(10) ** self.integer_digits - Decimal(1) / (Decimal(10) ** self.scale)
        return magnitude

    @property
    def min_value(self) -> Decimal:
        return -self.max_value if self.signed else Decimal(0)

    def clamp(self, value: Decimal) -> Decimal:
        quantum = Decimal(1).scaleb(-self.scale)
        value = value.quantize(quantum)
        if value > self.max_value:
            value = self.max_value
        if value < self.min_value:
            value = self.min_value
        return value


def _factor_values(domain: FieldDomain) -> list[Decimal]:
    """Candidate values for one field: boundary flags (zero, min, max) plus
    magnitude-decade and fraction-bucket representatives."""
    values = {domain.clamp(Decimal(0)), domain.clamp(domain.max_value), domain.clamp(domain.min_value)}
    for decade in range(domain.integer_digits + 1):
        candidate = Decimal(10) ** decade
        values.add(domain.clamp(candidate))
        if domain.signed:
            values.add(domain.clamp(-candidate))
    if domain.scale > 0:
        quantum = Decimal(1).scaleb(-domain.scale)
        values.add(domain.clamp(quantum))
        values.add(domain.clamp(domain.max_value / 2))
    return sorted(values)


def _factors(domains: list[FieldDomain]) -> list[list[tuple[str, Decimal]]]:
    return [[(d.name, v) for v in _factor_values(d)] for d in domains]


def _pad_records(combo: tuple, domains: list[FieldDomain], rng: random.Random) -> Witness:
    """A covering-array combo may cover fewer fields than len(domains) when
    building lower-order interactions; fill any untouched field with a
    random in-domain value so every returned witness is a full record."""
    record: Witness = dict(combo)
    for d in domains:
        if d.name not in record:
            record[d.name] = d.clamp(Decimal(rng.uniform(float(d.min_value), float(d.max_value))))
    return record


def generate_pairwise(domains: list[FieldDomain], seed: int, budget: int, oracle_fn: OracleFn | None = None) -> list[Witness]:
    rng = random.Random(seed)
    factors = _factors(domains)
    if len(factors) == 1:
        return [_pad_records((pair,), domains, rng) for pair in factors[0][:budget]]

    # Greedy pairwise covering array: track which (field_i, field_j,
    # value_i, value_j) tuples are still uncovered, and each round add the
    # witness whose randomly-assembled values cover the most new pairs.
    field_index_pairs = list(itertools.combinations(range(len(factors)), 2))
    pairs_needed = {
        (i, j, vi, vj) for i, j in field_index_pairs for vi in factors[i] for vj in factors[j]
    }
    witnesses: list[Witness] = []
    attempts = 0
    while pairs_needed and len(witnesses) < budget and attempts < budget * 20:
        attempts += 1
        picks = [rng.choice(factors[i]) for i in range(len(factors))]
        record = _pad_records(tuple(picks), domains, rng)
        newly_covered = {
            (i, j, picks[i], picks[j]) for i, j in field_index_pairs if (i, j, picks[i], picks[j]) in pairs_needed
        }
        if not newly_covered and witnesses:
            continue
        pairs_needed -= newly_covered
        witnesses.append(record)
    return witnesses


def generate_three_way(domains: list[FieldDomain], seed: int, budget: int, oracle_fn: OracleFn | None = None) -> list[Witness]:
    rng = random.Random(seed)
    factors = _factors(domains)
    if len(factors) < 3:
        return generate_pairwise(domains, seed, budget, oracle_fn)
    triples_needed = list(
        (i, j, k, vi, vj, vk)
        for i, j, k in itertools.combinations(range(len(factors)), 3)
        for vi in factors[i]
        for vj in factors[j]
        for vk in factors[k]
    )
    rng.shuffle(triples_needed)
    witnesses: list[Witness] = []
    seen: set[tuple] = set()
    for i, j, k, vi, vj, vk in triples_needed:
        if len(witnesses) >= budget:
            break
        key = (vi, vj, vk)
        if key in seen:
            continue
        seen.add(key)
        witnesses.append(_pad_records((vi, vj, vk), domains, rng))
    return witnesses


def generate_latin_hypercube(domains: list[FieldDomain], seed: int, budget: int, oracle_fn: OracleFn | None = None) -> list[Witness]:
    rng = random.Random(seed)
    budget = max(budget, 1)
    per_field_strata: list[list[Decimal]] = []
    for d in domains:
        lo, hi = float(d.min_value), float(d.max_value)
        step = (hi - lo) / budget if budget else 0.0
        strata = []
        for b in range(budget):
            low, high = lo + b * step, lo + (b + 1) * step
            strata.append(d.clamp(Decimal(rng.uniform(low, high))))
        rng.shuffle(strata)
        per_field_strata.append(strata)
    witnesses = []
    for row in range(budget):
        witnesses.append({d.name: per_field_strata[i][row] for i, d in enumerate(domains)})
    return witnesses


def _distance(a: Witness, b: Witness, domains: list[FieldDomain]) -> float:
    total = 0.0
    for d in domains:
        span = float(d.max_value - d.min_value) or 1.0
        total += ((float(a[d.name]) - float(b[d.name])) / span) ** 2
    return math.sqrt(total)


def generate_adaptive_random(domains: list[FieldDomain], seed: int, budget: int, oracle_fn: OracleFn | None = None) -> list[Witness]:
    rng = random.Random(seed)
    pool_size = max(budget * 10, 20)
    pool = [
        {d.name: d.clamp(Decimal(rng.uniform(float(d.min_value), float(d.max_value)))) for d in domains}
        for _ in range(pool_size)
    ]
    if not pool:
        return []
    chosen = [pool.pop(0)]
    while len(chosen) < budget and pool:
        best_idx, best_dist = 0, -1.0
        for idx, candidate in enumerate(pool):
            min_dist = min(_distance(candidate, c, domains) for c in chosen)
            if min_dist > best_dist:
                best_idx, best_dist = idx, min_dist
        chosen.append(pool.pop(best_idx))
    return chosen


def _outcome_shape(record: Witness, output: Witness, output_domains: list[FieldDomain]) -> tuple:
    shape = []
    for d in output_domains:
        value = output.get(d.name, Decimal(0))
        sign = -1 if value < 0 else (0 if value == 0 else 1)
        saturated = value in (d.max_value, d.min_value)
        shape.append((d.name, sign, saturated))
    return tuple(shape)


def generate_map_elites(
    domains: list[FieldDomain], seed: int, budget: int, oracle_fn: OracleFn,
    output_domains: list[FieldDomain] | None = None,
) -> list[Witness]:
    if oracle_fn is None:
        return []
    rng = random.Random(seed)
    output_domains = output_domains or domains
    candidates = generate_latin_hypercube(domains, seed, max(budget * 4, 12))
    elites: dict[tuple, Witness] = {}
    for candidate in candidates:
        output = oracle_fn(candidate)
        shape = _outcome_shape(candidate, output, output_domains)
        if shape not in elites:
            elites[shape] = candidate
        if len(elites) >= budget:
            break
    return list(elites.values())[:budget]


def generate_ucb1_bandit(
    domains: list[FieldDomain], seed: int, budget: int, oracle_fn: OracleFn,
    output_domains: list[FieldDomain] | None = None,
) -> list[Witness]:
    if oracle_fn is None:
        return []
    rng = random.Random(seed)
    output_domains = output_domains or domains
    # Arms: magnitude-decade bucket per field, capped so the cross-product
    # stays tractable for many fields.
    per_field_buckets = []
    for d in domains:
        decades = min(d.integer_digits + 1, 4)
        per_field_buckets.append(list(range(decades)))
    arms = list(itertools.product(*per_field_buckets)) if domains else [()]
    counts = {arm: 0 for arm in arms}
    rewards = {arm: 0.0 for arm in arms}
    seen_shapes: set[tuple] = set()
    witnesses: list[Witness] = []
    t = 0
    for arm in arms:
        if len(witnesses) >= budget:
            break
        t += 1
        record = {}
        for d, bucket in zip(domains, arm):
            lo = Decimal(10) ** bucket if bucket > 0 else Decimal(0)
            hi = Decimal(10) ** (bucket + 1) - Decimal(1) / (Decimal(10) ** d.scale)
            hi = min(hi, d.max_value)
            value = d.clamp(Decimal(rng.uniform(float(lo), float(min(hi, d.max_value) or lo))))
            record[d.name] = value
        output = oracle_fn(record)
        shape = _outcome_shape(record, output, output_domains)
        reward = 1.0 if shape not in seen_shapes else 0.0
        seen_shapes.add(shape)
        counts[arm] += 1
        rewards[arm] += reward
        witnesses.append(record)

    while len(witnesses) < budget and arms:
        t += 1
        scores = {}
        for arm in arms:
            n = counts[arm] or 1
            mean = rewards[arm] / n
            bonus = math.sqrt(2 * math.log(max(t, 2)) / n)
            scores[arm] = mean + bonus
        best_arm = max(scores, key=scores.get)
        record = {}
        for d, bucket in zip(domains, best_arm):
            lo = Decimal(10) ** bucket if bucket > 0 else Decimal(0)
            hi = Decimal(10) ** (bucket + 1) - Decimal(1) / (Decimal(10) ** d.scale)
            hi = min(hi, d.max_value)
            value = d.clamp(Decimal(rng.uniform(float(lo), float(min(hi, d.max_value) or lo))))
            record[d.name] = value
        output = oracle_fn(record)
        shape = _outcome_shape(record, output, output_domains)
        reward = 1.0 if shape not in seen_shapes else 0.0
        seen_shapes.add(shape)
        counts[best_arm] += 1
        rewards[best_arm] += reward
        witnesses.append(record)
    return witnesses[:budget]


def generate_witnesses(
    domains: list[FieldDomain], oracle_fn: OracleFn | None = None, seed: int = 0,
    per_algorithm_budget: int = 6, output_domains: list[FieldDomain] | None = None,
) -> list[Witness]:
    """Runs all six algorithms, dedups (first-seen order), returns the
    union. MAP-Elites and UCB1 are skipped when no `oracle_fn` is given."""
    all_witnesses: list[Witness] = []
    all_witnesses += generate_pairwise(domains, seed, per_algorithm_budget)
    all_witnesses += generate_three_way(domains, seed, per_algorithm_budget)
    all_witnesses += generate_latin_hypercube(domains, seed, per_algorithm_budget)
    all_witnesses += generate_adaptive_random(domains, seed, per_algorithm_budget)
    if oracle_fn is not None:
        all_witnesses += generate_map_elites(domains, seed, per_algorithm_budget, oracle_fn, output_domains)
        all_witnesses += generate_ucb1_bandit(domains, seed, per_algorithm_budget, oracle_fn, output_domains)

    seen_keys: set[tuple] = set()
    deduped: list[Witness] = []
    for w in all_witnesses:
        key = tuple(sorted(w.items()))
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(w)
    return deduped


def witnesses_for_subprogram(model, oracle_fn: OracleFn | None = None, seed: int = 0,
                              per_algorithm_budget: int = 6) -> list:
    """Adapter for any `weaver.cobol.subprogram.SubprogramModel` -- works
    for LEAF-A/LEAF-B's 1-input shape and any N-input subprogram alike,
    never hardcoded to a specific program. Returns `list[Decimal]` for the
    N=1 back-compat shape (matching `verify_subprogram`'s existing API),
    or `list[Witness]` (dicts) for N>1 (consumed by `verify_subprogram_multi`)."""
    domains = [FieldDomain.from_field(p.name, p) for p in model.input_params]
    output_domains = [FieldDomain.from_field(p.name, p) for p in model.output_params]
    witnesses = generate_witnesses(domains, oracle_fn, seed, per_algorithm_budget, output_domains)
    if len(model.input_params) == 1:
        name = model.input_params[0].name
        return [w[name] for w in witnesses]
    return witnesses


def witnesses_for_program(spec, oracle_fn: OracleFn | None = None, seed: int = 0,
                           per_algorithm_budget: int = 6) -> list[Witness]:
    """Adapter for any `weaver.agent.scaffold.ScaffoldSpec` -- generates
    synthetic input records over every numeric field in `spec.input_layout`,
    for any full file-based program the frontend can parse (not tied to
    any one fixture)."""
    domains = [FieldDomain.from_field(f.name, f) for f in spec.input_layout if f.numeric]
    return generate_witnesses(domains, oracle_fn, seed, per_algorithm_budget)


__all__ = [
    "FieldDomain",
    "Witness",
    "OracleFn",
    "generate_pairwise",
    "generate_three_way",
    "generate_latin_hypercube",
    "generate_adaptive_random",
    "generate_map_elites",
    "generate_ucb1_bandit",
    "generate_witnesses",
    "witnesses_for_subprogram",
    "witnesses_for_program",
]
