# Independent Local Review Prompt

Perform a strict review against `CLAUDE.md`, `LOCAL_WORKFLOW.md`, `GPU_MANUAL_WORKFLOW.md`, all documents under `docs/`, and the status files.

1. Inspect all local source and configuration files.
2. Run only safe local formatting, lint, type and CPU/mock tests.
3. Map acceptance criteria to code and tests.
4. Identify correctness, concurrency, protocol, privacy, Windows and GPU-integration risks.
5. Distinguish locally verified defects from hardware questions.
6. Fix blocker and high local defects and add regression tests.
7. Do not connect to the GPU server.
8. Convert hardware questions into manual actions and stop for user results.
9. Update status truthfully.
