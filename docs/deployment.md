# Deploy the staff workspace

The release serves the React app, the PDF viewer and the FastAPI API from one origin. Each hospital gets a dedicated PostgreSQL database. Staff in that installation can access its cases. A clean staff installation starts with empty queues. Local rehearsal uses a private loopback instance and synthetic examples.

## Build and verify

From the repository root, with Docker, OpenSSL and uv installed, run the following. The smoke test starts its own temporary PostgreSQL container. It generates an ephemeral local TLS certificate and checks login, both empty worklists, an actual synthetic discharge upload, all four embedded originals in the reviewed export, health and logout, then removes its containers and network.

```sh
docker build -t zeroupfront:release .
uv run --locked python bench/container_release.py --image zeroupfront:release
```

## Configure the service

Supply a dedicated persistent PostgreSQL connection as the server-side secret `DATABASE_URL`. The database role needs schema creation and read/write privileges in that database. The service initializes its tables on startup. Use the managed provider's TLS settings and configure backups with a tested restore. Source PDFs, document revisions, decisions and session records live in the database. Browser files are served from the image.

```sh
docker run -d --name zeroupfront --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=128m \
  -p 127.0.0.1:8080:8080 -e DATABASE_URL zeroupfront:release
docker exec -it zeroupfront python -m app.staff_access add coordinator --name "Case coordinator"
```

The account manager prompts for a passphrase. Use `reset` with `--name` to rotate it and revoke sessions, or `disable USERNAME` to disable access. Pass a staff member's own account at enrollment so the review ledger records the authenticated username. A session expires after eight hours.

Expose the service behind a TLS reverse proxy that preserves the original host and forwards the https scheme. Set `FORWARDED_ALLOW_IPS` to the trusted proxy address before starting the service. Restrict direct access to the app port to the proxy. Configure a request-body limit appropriate to the supported number of 24 MiB PDFs per packet, a bound on concurrent uploads, memory limits and request timeouts. Set the load balancer liveness path to `/healthz` and its database readiness path to `/readyz`. Both return 204 when healthy.

The image defaults to staff authentication. The local launcher selects rehearsal only for its loopback-only private database. `WORKSPACE_SEED_DEMO=1` opts into the earlier three synthetic admission cases. Independent new-case examples are available in rehearsal. Use a separate database for a demo.

## Optional OCR

Digital PDFs can be screened without an API key. On a service authorized to send document pages to OpenAI, set `OPENAI_API_KEY`, `OPENAI_OCR_MODEL` and `WORKSPACE_ENABLE_OCR=1` on the server, then select OCR on a supported upload. Private credentials never belong in the web build or a Git commit. Document review can proceed with a legible replacement when OCR is unavailable. The large-policy retrieval benchmarks run separately.

## Release boundary

Hospital and payer staff currently use their own channels for transmission and supply the original written reply. Provisioning a host, signing the provider's data agreements, validating payer-specific templates, testing backup recovery in the target environment and connecting to the hospital billing and insurer systems require a deployment owner and partner access. Use synthetic records to evaluate this release until those controls are in place.
