# Authority reason-template rendering

Use this when editing signer-facing authority/escalator reason templates.

## Pattern

1. Treat reason templates as signer-facing evidence, not debug strings.
2. Resolve semantic placeholders (`actual`, `threshold`) from evaluator-owned state, not from ad hoc caller input.
3. Trim YAML block-scalar whitespace before persisting/API response.
4. Never emit unresolved `{placeholder}` text. Drop the affected sentence; if no safe prose remains, use a neutral non-templated fallback.
5. Add regression tests for:
   - threshold-based reasons (`actual` + `threshold`),
   - categorical reasons (`actual` with no threshold),
   - unresolved placeholder suppression,
   - no trailing newline.
6. Do not put explanatory assessment fields into the payload hash without an authority-design ruling.
