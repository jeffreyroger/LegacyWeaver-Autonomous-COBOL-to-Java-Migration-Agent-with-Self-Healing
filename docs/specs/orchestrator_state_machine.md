# Orchestrator state machine — Step P1

Reviewed against `AGENT_LAYER_PLAN.md`'s diagram; matches exactly (P1
acceptance test: divergence between this and any architecture-deck diagram
is a presentation bug, not a states/transitions bug).

```
perceive -> plan -> [next unit] -> synthesise -> compile
                          ^                          |
                          |                    fail  |  ok
                          |                     v     v
                          |                classify <- verify
                          |                     |      |
                          |                     v      | pass
                          |              memory lookup |
                          |                     |       v
                          |               hit / miss  commit
                          |                     |       |
                          |                     v       |
                          |                  repair     |
                          |                     |        |
                          |             [attempts<3]     |
                          |                     |         |
                          |                     +---------+
                          |                               |
                          +-------------------------------+
                                          |
                              [attempts=3] v
                                      escalate
```

## Node -> implementation mapping

| Node | Implementation |
|---|---|
| perceive | `weaver.agent.segment.segment` + `weaver.agent.data_context.build_context` (Phase L, precomputed once per unit) |
| plan | `Orchestrator._next_unit` -- pop the next unit from the dependency-ordered queue |
| synthesise | `weaver.agent.synthesize.synthesize_paragraph` (Phase M) |
| compile | `weaver.agent.attribution.verify_unit`'s `javac` step |
| verify | `weaver.agent.attribution.verify_unit`'s differential-comparison step (against golden, per unit attribution N1) |
| classify | `weaver.classification.classify`, already invoked inside `verify_unit` |
| memory lookup | `weaver.agent.memory_repair.try_memory_repair` (Phase O) |
| repair | `weaver.agent.repair_loop.repair_unit` (N2 deterministic / N3 model-assisted, N4 bounded) |
| commit | unit's verified body is recorded in `Orchestrator.results` and its verified body becomes the input for the next unit's reference assembly |
| escalate | `weaver.agent.escalation.build_diagnostic_record` (Phase Q) |

## Persistence and events

`Orchestrator.run()` persists one JSON object per unit to
`generated/orchestrator_state.json` after each unit finishes (resumability:
a rerun skips units already present with `status: committed`). Every state
transition emits a structured event (timestamp, unit, node, action,
duration, model_calls, tokens, memory_hit, outcome) appended as one line of
newline-delimited JSON to `generated/trace.ndjson` -- this stream is both
the audit trail and the source for Phase R's metrics.

## Never halt on one failure

Per the plan's explicit instruction, an escalated unit does not stop the
run: `Orchestrator.run()` continues to the next unit in the queue and
reports a partial result. This fixture has one synthesizable unit
(PROCESS-RECORD); Phase S's FEECALC gives the orchestrator a second,
independent unit to demonstrate this on for real.
