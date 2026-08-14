# GPU Result Analysis Prompt

I have manually executed the requested GPU action. Analyze the result without connecting to the server yourself.

First read `CLAUDE.md`, `GPU_MANUAL_WORKFLOW.md`, `MANUAL_ACTIONS.md`, `USER_RESULTS.md` and `IMPLEMENTATION_STATUS.md`.

User result:

```text
Action ID: [ID]
Environment: [description]
Command executed: [command]
Exit status: [status]
Full output: [redacted stdout/stderr]
Notes: [observations]
```

Required response:

1. Determine `PASSED`, `FAILED`, `INCONCLUSIVE` or `NEEDS_MORE_INFO`.
2. Explain the evidence.
3. Update the action and non-sensitive result files.
4. If failed, diagnose the most likely cause and create one safe next manual action.
5. If passed, create only the next dependency action, if any.
6. Never execute remote commands yourself.
7. Stop whenever the next action requires my manual execution.
