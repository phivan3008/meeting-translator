# Bug-Fix Prompt Template

Investigate and fix the following issue without weakening existing behavior or tests:

## Observed behavior

[Paste exact behavior]

## Expected behavior

[Paste expected behavior]

## Reproduction

[Paste exact steps, inputs, logs and environment]

## Constraints

- Read `CLAUDE.md` and relevant documents first.
- Reproduce the bug before editing when possible.
- Identify the root cause, not only the symptom.
- Add a failing regression test before or with the fix.
- Keep protocol compatibility unless a versioned change is necessary.
- Do not log sensitive meeting content.
- Run affected and full quality checks.
- Update `IMPLEMENTATION_STATUS.md` with the verified result.
