# Deploy the staff workspace

The release serves the React app, the PDF viewer and the FastAPI API from one origin. Each hospital gets a dedicated PostgreSQL database. Staff in that installation can access its cases. A clean staff installation starts with empty queues. The published hackathon walkthrough uses a private loopback instance with synthetic examples. A container is available to build for a separately provisioned host. [Local demo](../README.md#run-the-demo)

## Build and verify

From the repository root, with Docker, OpenSSL and uv installed, run the following. The smoke test starts its own temporary PostgreSQL container. It generates an ephemeral local TLS certificate and checks login, both empty worklists, an actual synthetic discharge upload, all four embedded originals in the reviewed export, health and logout, then removes its containers and network.

```sh
docker build -t zeroupfront:release .
uv run --locked python bench/container_release.py --image zeroupfront:release
```

## Configure the service

Set the optional `WORKSPACE_HOSPITAL_NAME` to the public-facing hospital name, for example `Canal Demo Hospital`. Staff see it on sign-in and in the workspace header. Restart the service after changing it. The facility on an individual encounter is entered from the source documents.

Supply a dedicated persistent PostgreSQL connection as the server-side secret `DATABASE_URL`. The database role needs schema creation and read/write privileges in that database. The service initializes its tables on startup. Use the managed provider's TLS settings and configure backups with a tested restore. Source PDFs, document revisions, decisions and session records live in the database. Browser files are served from the image.

```sh
docker run -d --name zeroupfront --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=128m \
  -p 127.0.0.1:8080:8080 -e DATABASE_URL -e WORKSPACE_HOSPITAL_NAME -e FORWARDED_ALLOW_IPS zeroupfront:release
docker exec -it zeroupfront python -m app.staff_access add coordinator --name "Case coordinator"
```

The account manager prompts for a passphrase. Use `reset` with `--name` to rotate it and revoke sessions, or `disable USERNAME` to disable access. Pass a staff member's own account at enrollment so the review ledger records the authenticated username. A session expires after eight hours.

Expose the service behind a TLS reverse proxy that preserves the original host and forwards the https scheme. Set `FORWARDED_ALLOW_IPS` to the trusted proxy address before starting the service. Restrict direct access to the app port to the proxy. Configure a request-body limit appropriate to the supported number of 24 MiB PDFs per packet, a bound on concurrent uploads, memory limits and request timeouts. Set the load balancer liveness path to `/healthz` and its database readiness path to `/readyz`. Both return 204 when healthy.

The image defaults to staff authentication. The local launcher selects rehearsal only for its loopback-only private database. `WORKSPACE_SEED_DEMO=1` opts into the earlier three synthetic admission cases. Independent new-case examples are available in rehearsal. Use a separate database for a demo.

## Optional OCR

Digital PDFs can be screened without an API key. On a service authorized to send document pages to OpenAI, set `OPENAI_API_KEY`, `OPENAI_OCR_MODEL` and `WORKSPACE_ENABLE_OCR=1` on the server, then select OCR on a supported upload. Private credentials never belong in the web build or a Git commit. Document review can proceed with a legible replacement when OCR is unavailable. The large-policy retrieval benchmarks run separately.

## Optional AI second read

Set `WORKSPACE_ENABLE_AI_REVIEW=1`, `OPENAI_API_KEY` and, if needed, `OPENAI_OCR_MODEL` on the server, and restart. Opening the second-read control requires a further confirmation for the specific revision. It sends the available PDFs across up to four document roles and scoped encounter metadata to OpenAI in one request with `store=False`. The supported form families are AIA Thailand IPD, CMS-1450, and FEP overseas medical. The combined limit is 40 physical pages and 24 MiB. The response supplies provisional observations and page links. Staff can compare them against the originals; approval, export and settlement continue to use the existing signed workflow. A changed head revision invalidates an in-flight request. Review the organization's applicable hosted-processing arrangements before enabling the feature on non-synthetic records. [Benchmarks and research](payer-review-design.md)

## Release boundary

Hospital and payer staff currently use their own channels for transmission and supply the original written reply. Provisioning a host, signing the provider's data agreements, validating payer-specific templates, testing backup recovery in the target environment and connecting to the hospital billing and insurer systems require a deployment owner and partner access. Use synthetic records to evaluate this release until those controls are in place.

## One product, a workspace for each hospital

For the hackathon, deploy the same release for each participating hospital and give each installation its own database, staff accounts, uploaded files and audit history. Use separate databases for the live team demo and for any hospital pilot. A hospital name on an intake form identifies the facility on an exhibit. The configured server and database determine which workspace a signed-in user can access. Running two hospitals in one existing database would give staff access to both hospitals’ records. The release has no in-app hospital switcher.

Keep evidence preservation, revision checks, staff approval and payment recording consistent across installations. For a pilot, add reviewed, versioned payer profiles scoped to the hospital's contract. Each profile should name its form edition, claim route, required evidence, signatures, currency and rules for corrections. Save the profile version on the reviewed revision. The AIA consent, FEP assignment and CMS replacement trials are acceptance cases for this future work. The hackathon release still uses its documented supported layouts. [Thai results](thai-payer-forms.md) · [US results](us-payer-forms.md) · [Microsoft’s dedicated deployment pattern](https://learn.microsoft.com/en-us/azure/architecture/guide/multitenant/approaches/overview)

For an on-stage demo, open the local synthetic workspace before presenting and start on the claim queue. For a shared team or judge instance, use the existing staff sign-in and individually provisioned accounts over HTTPS. A later hospital pilot can integrate the hospital’s identity provider and MFA. All staff in a given installation currently share case access.
