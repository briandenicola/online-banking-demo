# Cross-language contract seam

**Use when** two artifacts in different languages must agree, neither owns the other, and every
existing check lives inside one artifact's own language. Symptom: both files review as correct and
the system fails anyway.

Real instance: `config/authority-policy.yaml` (`requiredFields`, consumed by C#) and
`config/copilot-tools.yaml` (`evidenceProjection`, consumed by Python) were mutually unsatisfiable
for an entire phase. Six of six actions refused at propose. The first thing that noticed was a
human running a demo.

## The trap

The obvious fix — assert the expected shape in the language you happen to be working in — creates a
**third document that can drift from both**. It keeps passing on the day someone strengthens the
real check, because it never called the real check.

## The pattern

**Two tests, each running one real component, joined by one checked-in artifact. Neither
re-implements the other.**

```
fixture.json = { input, arguments, output }
                  ^                    ^
   producer test (lang A)        consumer test (lang B)
   "output is what the SHIPPED   "the REAL consumer accepts
    producer actually emits"      this output"
```

- **Producer test** regenerates `output` from `input` with the shipped code and asserts equality.
  This is what stops the fixture being hand-edited into agreement with a reality that does not
  exist. It must assert **nothing** about the consumer's rules — that would be the third document.
- **Consumer test** calls the **real** predicate/validator, not a restatement. If it is private,
  reach it through the public entry point and assert on its reported output.
- Generate the fixture with a script that reads both sides and restates neither.

## Non-negotiable companions

1. **A negative control per held key.** The RAW input must FAIL the check its transformed form
   passes, and the requirement list must be non-empty. Without this, emptying the contract makes
   every assertion pass for the wrong reason.
2. **`held.Should().BeGreaterThan(0)`.** A loop over a contract that has been rewritten to hold
   nothing must fail, not report success.
3. **Assert the declaration, not just the artifact.** Read the producer's *source declaration* in
   the consumer test too. Otherwise deleting the declaration leaves the fixture as its only
   witness, still attesting to something that no longer exists. (Found by tampering; it was green.)
4. **Test the wiring separately from the mechanism.** Every test calling the component directly
   proves nothing about whether production calls it. Deleting the one line that invoked a new
   engine left a 285-test suite fully green and the feature inert.
5. **Quarantine by name, with the reason, in the test.** Never by omission. Fixing the upstream
   deletes the entry and the test starts holding that case automatically. An invisible quarantine
   becomes permanent.
6. **State what the test does NOT prove, in the test.** A fixture built from source types proves
   two documents are mutually satisfiable; it does not prove the live service still returns that
   shape. Say so where the next reader will be tempted to over-trust it.

## Tamper checklist

Break each, confirm a *specific* named test fails, revert, confirm green:

- move the consumer's requirement; delete the producer's declaration; hand-edit the artifact's
  output; doctor the artifact's input so the raw form already passes; drop the call site;
  add a declaration for a deliberately quarantined case.

If a tamper is caught by a *different* test than you intended, you have found a coincidence, not a
guard.
