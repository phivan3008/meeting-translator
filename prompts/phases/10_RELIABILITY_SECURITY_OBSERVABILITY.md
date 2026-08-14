# Phase 10: Reliability, Security and Observability

Harden the application.

Required outcomes:

- JWT verification interface and production configuration.
- TLS deployment guidance and reverse-proxy example.
- Request, packet, session and queue limits.
- Redaction tests proving no raw audio, transcript, prompt or translation is logged by default.
- Prometheus metrics described in the product documents.
- Structured correlation IDs across session, stream, utterance and model request.
- Readiness reflects dependency health without dumping sensitive details.
- Graceful shutdown flush policy.
- Translation and ASR circuit-breaker/backoff behavior where appropriate.
- Model overload and queue pressure behavior.
- Server restart and client reconnect tests.
- Security review checklist and dependency pinning strategy.

Run checks and update status.
