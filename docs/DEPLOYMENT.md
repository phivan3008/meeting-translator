# Deployment: TLS and Reverse Proxy

The application server (`server/app.py`, `deployment/Dockerfile`) speaks
plain WebSocket/HTTP on `SERVER_PORT` (default `8080`) and does not
terminate TLS itself. Every non-development deployment puts a reverse
proxy in front of it that terminates TLS and forwards WebSocket traffic
(the `Upgrade`/`Connection` headers) through to the application port. This
mirrors `docs/OPERATOR_RUNBOOK_SEED.md`'s "Expected deployment: a reverse
proxy terminates TLS and forwards WebSocket traffic."

## What the proxy must do

1. Terminate TLS (client connects via `wss://` and `https://`).
2. Forward `/ws/stream` as a WebSocket upgrade -- this requires explicitly
   passing through the `Upgrade` and `Connection` headers; most reverse
   proxies do **not** do this by default for a generic `proxy_pass`/
   reverse-proxy block.
3. Use a long (or no) proxy read/write idle timeout on the WebSocket route
   specifically -- a meeting session's WebSocket connection can legitimately
   sit open for the whole meeting. The application's own
   `WS_IDLE_TIMEOUT_MS` / `WS_HEARTBEAT_INTERVAL_MS` (`.env.example`)
   already close a genuinely idle connection from the application side;
   the proxy's timeout should be longer than that, not shorter, or it will
   kill live sessions.
4. Forward `/health/live` and `/health/ready` for the orchestrator's own
   health checks (Docker `HEALTHCHECK`, Kubernetes probes, load-balancer
   health checks).
5. Decide whether `/metrics` is reachable from outside the deployment's
   internal network at all -- it has no authentication of its own
   (`docs/SECURITY.md`'s checklist). Typically this route is only exposed
   to an internal Prometheus scraper, not the public listener.

## nginx example

```nginx
# /etc/nginx/sites-available/meeting-translator.conf
upstream meeting_translator {
    server 127.0.0.1:8080;
}

server {
    listen 443 ssl http2;
    server_name meeting-translator.example.internal;

    ssl_certificate     /etc/letsencrypt/live/meeting-translator.example.internal/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/meeting-translator.example.internal/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    # WebSocket audio/control stream.
    location /ws/stream {
        proxy_pass http://meeting_translator;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # A meeting session's socket is long-lived by design; keep this
        # comfortably above WS_IDLE_TIMEOUT_MS (default 15s) so the proxy
        # never cuts a live session before the application's own idle
        # timeout would.
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # Liveness/readiness for load-balancer/orchestrator health checks.
    location /health/ {
        proxy_pass http://meeting_translator;
        proxy_set_header Host $host;
    }

    # Internal-only: restrict by network, not exposed publicly.
    location /metrics {
        allow 10.0.0.0/8;
        deny all;
        proxy_pass http://meeting_translator;
        proxy_set_header Host $host;
    }
}

server {
    listen 80;
    server_name meeting-translator.example.internal;
    return 301 https://$host$request_uri;
}
```

## Caddy example

Caddy forwards WebSocket upgrade headers automatically for
`reverse_proxy` and manages the TLS certificate itself (ACME), so the
equivalent `Caddyfile` is shorter:

```caddyfile
meeting-translator.example.internal {
    handle /metrics* {
        @internal remote_ip 10.0.0.0/8
        reverse_proxy @internal 127.0.0.1:8080
        respond 403
    }

    handle {
        reverse_proxy 127.0.0.1:8080
    }
}
```

## Client configuration

The Windows client's `CLIENT_SERVER_URL` (`.env.example`, client-side
config) must point at the proxy's `wss://` endpoint in any deployment with
a reverse proxy in front (e.g.
`wss://meeting-translator.example.internal/ws/stream`), not directly at
the application server's plain `ws://` port.

## Docker Compose

`deployment/docker-compose.yml` runs the application server and Redis as
local containers; it intentionally does not include a reverse proxy or TLS
termination (this is a *local* skeleton -- see its header comment; GPU
services are explicitly excluded from the default profile too). Add the
proxy as a separate service or an external, already-managed load balancer
in front of the `server` container's published port when deploying beyond
a local/dev environment; do not remove the container's own `EXPOSE 8080`
plain-HTTP listener, since that is what the proxy connects to internally.

For a monitored, production-like example that also runs Prometheus and
Grafana alongside the server, see `deployment/docker-compose.prod.yml`.

## Windows client packaging

The Windows client (`client/ui/bootstrap.py` and everything it imports) is
packaged into a distributable executable with PyInstaller via
`scripts/build_windows_client.py`. This requires packages the default `dev`
extra deliberately excludes (real PySide6, real PyAudioWPatch, PyInstaller
itself) since the CPU test suite never needs them:

```powershell
pip install -e ".[client,windows-audio,packaging]"
python scripts/build_windows_client.py --clean
```

Produces `dist/MeetingTranslator-<version>/` (default, one-directory build)
or a single `dist/MeetingTranslator-<version>.exe` with `--onefile` (slower
startup -- it self-extracts to a temp directory first, but is easier to
hand to someone as one file). `packaging/entrypoint.py` is the actual entry
script PyInstaller builds from; it exists as a thin top-level wrapper
around `client/ui/bootstrap.py` so the repository root, not
`client/ui/`'s own location, is what gets added to `sys.path` for
`client`/`shared` imports to resolve inside the frozen build.
`pyaudiowpatch` is imported lazily inside functions
(`client/audio/windows_backend.py`), not at module scope, so the build
script passes `--hidden-import pyaudiowpatch` explicitly -- PyInstaller's
static import scan does not always catch function-local imports on its
own.

**What this verifies and what it does not.** A successful build proves
PyInstaller can resolve and bundle the full real dependency graph (PySide6
widgets/plugins, PyAudioWPatch, this project's own packages) into a
self-contained executable with no import errors at freeze time. It does
**not** prove the produced `.exe` actually launches, opens real audio
devices, or connects to a real server -- that requires running it on
Windows with real audio hardware, which is a separate, staged manual
action (see `MANUAL_ACTIONS.md`), consistent with `CLAUDE.md`'s "never
claim hardware verification from mocks."

## Version metadata and upgrade strategy

`shared/version.py`'s `__version__` is the single source of truth,
semantic-versioned (`MAJOR.MINOR.PATCH`) and kept in sync with
`pyproject.toml`'s `[project] version` field by convention --
`tests/test_version.py` is the enforcement (asserts they match on every
local check run). The server's `/health/live` response and FastAPI app
metadata, and the client window's title bar, both read this same constant,
so the running version is always visible without reading source.

- **PATCH** (`0.1.0` -> `0.1.1`): bug fixes and internal changes with no
  wire-protocol or settings-schema change. Safe to roll out to server and
  clients independently, in either order.
- **MINOR** (`0.1.0` -> `0.2.0`): backward-compatible additions (a new
  optional setting, a new optional protocol field). Roll the server out
  first; older clients that don't know about a new optional field keep
  working unchanged, per `shared/protocol/messages.py`'s
  `ProtocolModel(extra="forbid")` -- new *optional* fields with defaults
  are additive and safe, but note `extra="forbid"` means an old server
  talking to a client sending a genuinely new *required* field, or vice
  versa, is a MAJOR change, not a MINOR one (see below).
- **MAJOR** (`0.x` -> `1.0`, or any `PROTOCOL_VERSION` bump): a
  wire-incompatible change. `shared/protocol/enums.PROTOCOL_VERSION` is
  checked on every `session.start` (`server/transport/gateway.py`) and
  every binary packet header (`shared/protocol/binary.py`); a mismatch is
  rejected with `PROTOCOL_VERSION_UNSUPPORTED`/`MALFORMED_PACKET` rather
  than silently misinterpreted. **The server and every connected client
  must agree on `PROTOCOL_VERSION`** -- when it changes, roll out the
  server first (it can reject old clients cleanly via the typed error
  above), then upgrade clients; there is no dual-protocol-version bridge
  mode.
- **Client upgrade mechanism**: none built in (no auto-updater). A new
  packaged `.exe` is a full replacement of the old one; there is no
  in-place patching. `client/ui/settings_store.py`'s persisted settings
  file tolerates a partial/missing-field document (falls back to defaults
  per-field, per its own test coverage), so replacing an older client
  build with a newer one does not require the user to reconfigure device
  selection or language presets, as long as no field was *renamed*
  (renaming a persisted field name is itself a MAJOR-class change from the
  client's perspective, since old JSON keys would then be silently
  ignored).
- **Server upgrade mechanism**: standard container/process replacement
  (`deployment/docker-compose.yml`/`.prod.yml`), gated by this project's
  own graceful-shutdown drain (`docs/SECURITY.md`'s "Graceful shutdown")
  so in-flight sessions finish or disconnect cleanly rather than being cut
  off mid-utterance. No database schema/migration concerns exist today
  (no persistent store beyond Redis, used only as declared in
  `docker-compose.yml`, not yet for durable state).
