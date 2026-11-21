# Try two hospital workspaces

Choose Canal Bridge or Lakeside, sign in, and follow a synthetic inpatient claim through review. The directory is public. Each hospital has its own accounts, sessions, documents and event history in a dedicated PostgreSQL database.

## On this computer

With Python 3.12, Node 24, npm, uv and the PostgreSQL command-line tools installed, run the following from the repository root as a regular user.

```sh
npm --prefix web ci
npm --prefix web run build
uv run --locked python -m app.hospital_demo
```

For the optional digital guarantee reader in the fictional Canal Bridge workspace, add `--approve-openai-use canal-bridge/guarantee_fees` to the local serve command. This also requires the deployment AI switch and provider key. Both hospitals otherwise start with cloud document processing disabled.

On the first interactive launch, choose a separate password for the username `judge` in each hospital. The prompts hide typed input. The app stores only salted password verifiers. On subsequent launches, the same accounts, original exhibits and saved revisions are available. Open the [hospital directory](http://127.0.0.1:8040/).

To choose a new password, including after an unattended launch, leave the demo running and use a second terminal. A reset signs that hospital's judge account out on every device.

```sh
uv run --locked python -m app.hospital_demo password canal-bridge
uv run --locked python -m app.hospital_demo password lakeside
```

| Encounter | What to try |
| --- | --- |
| VISIT-CB-FX or VISIT-LS-FX | Compare the dated FX reference with simulated bank funding, inspect the bilingual fee reader and reconcile a THB 300 short receipt. [Pattaya walkthrough](demo.md#pattaya-fx-rehearsal) |
| VISIT-CB-001 or VISIT-LS-001 | Open the duplicate pharmacy charge and inspect page 2. Preview the corrected bill, confirm the encounter and save. Review the new revision, preview the attachments and open the reviewed export. The first bill remains in version history. |
| VISIT-CB-002 or VISIT-LS-002 | Review a complete packet directly. Record the external submission and the payer’s response as separate events. |
| VISIT-CB-003 or VISIT-LS-003 | Compare the final bill with the lower authorization ceiling in the payer letter. The hold calls for evidence or payer follow-up. |

Each hospital also has a pre-arrival case. Canal Bridge has a documented fracture repair. Lakeside has an elective procedure with a possible exclusion. Open **Switch hospital** to sign out of the current workspace and choose another. Separate authenticated tabs can coexist. Coordinators share the hospital case queue. Finance staff can read balances only for assigned discharge cases, with clinical documents and write actions restricted at the API. [Finance account and assignment commands](deployment.md#configure-the-service). Clinical-team assignments, SSO and MFA remain pilot work.

## Configure a shared release

One release can serve multiple hospitals. Add each stable slug and public label to `WORKSPACE_HOSPITALS` and keep the connection strings in server-side secrets. For example:

```json
{
  "canal-bridge": {
    "hospital_name": "Canal Bridge Demo Hospital",
    "database_url_env": "CANAL_DATABASE_URL",
    "approved_openai_uses": ["guarantee_fees"]
  },
  "lakeside": {"hospital_name":"Lakeside Demo Hospital","database_url_env":"LAKESIDE_DATABASE_URL"}
}
```

Provision a distinct PostgreSQL database and narrowly privileged role per hospital. Set the corresponding variables in the service. The database remembers its slug and startup rejects a connection mapped to another hospital’s existing binding. Publish the container through HTTPS and check `/readyz`. Readiness depends on **all** configured databases. Separate releases can limit the impact of a database outage or meet different residency requirements. The configuration applies on restart. [Container deployment](deployment.md) · [Privacy by jurisdiction](privacy-by-jurisdiction.md)

### Hospital approval for external document processing

A hospital in the directory starts with all external document processing disabled. In the example, Canal Bridge permits review of the current original payer guarantee. Lakeside permits no document transfers. A coordinator must still choose the cloud action for that particular request. Public directory responses contain only display names and slugs.

| Hospital setting in `approved_openai_uses` | Data sent when a coordinator chooses the action | Deployment switch |
| --- | --- | --- |
| `hosted_ocr` | Selected scanned pages for transcription during pre-arrival intake, estimate correction, discharge intake or document correction | `WORKSPACE_ENABLE_OCR=1` |
| `payer_second_read` | The bounded discharge packet’s original PDFs and specified encounter metadata | `WORKSPACE_ENABLE_AI_REVIEW=1` |
| `guarantee_fees` | The latest confirmed or partial payer decision PDF for fee review. A scanned letter also needs the hospital and deployment permissions for OCR. | `WORKSPACE_ENABLE_AI_REVIEW=1` |

Each operation also needs the server-side provider key. The hospital’s `approved_openai_base_url` defaults to `https://api.openai.com/v1`. If the service sets `OPENAI_BASE_URL`, explicitly approve the same HTTPS base URL for each participating hospital. Document requests are bound to the matching endpoint and decline redirects. Restart the deployment to apply registry changes. The single-workspace launcher retains its deployment-wide opt-in controls.

Before enabling a purpose for identifiable records, the hospital’s privacy lead should record the authorized recipient and purpose, permitted fields/pages, legal basis, transfer arrangements, retention and provider terms. The switches enforce the configured purpose and receiver. They do not verify a contract, consent document, physical processing location or retention period. Staff can read the local originals when cloud processing is unavailable.

For these **fictional hospitals only**, run `python -m app.hospital_demo seed-configured` in the configured container to populate the examples. In an interactive administrative shell with the same secrets, provision a separate staff login in each database. Both commands prompt for the password.

```sh
DATABASE_URL="$CANAL_DATABASE_URL" python -m app.staff_access add judge --name "Canal Bridge coordinator"
DATABASE_URL="$LAKESIDE_DATABASE_URL" python -m app.staff_access add judge --name "Lakeside coordinator"
```

Give each judge their own account for an individual audit trail. Deliver credentials privately. Configure provider secrets, web HTTPS and database certificate verification before issuing the link. [Staff access and encryption](security-and-encryption.md)

## One day of judging

For a judge link usable while the team’s laptop is offline, an always-on Singapore service is a reasonable first deployment for a Bangkok event. A 1 CPU / 2 GB Render web service and a 0.5 CPU / 1 GB managed PostgreSQL service at monthly rates of $25 and $19 amount to roughly **$1.47 for 24 hours**, assuming a 30-day month, one instance of each and usage-based compute billing. Budget separately for storage, network usage, API calls and any paid workspace subscription. Render supports two logical databases on the same PostgreSQL instance. Confirm current prices at checkout. Its internal database TLS uses self-signed certificates. To retain this release’s hostname verification, use the external database hostname with a trusted root, restrict database ingress to the service egress ranges and measure the resulting latency. [Pricing](https://render.com/pricing) · [Plans](https://render.com/docs/compute-plans) · [Database connections and multiple databases](https://render.com/docs/postgresql-creating-connecting) · [Regions](https://render.com/docs/regions)

Free Render web instances sleep after 15 idle minutes and can take about a minute to wake. For an on-stage demonstration the local staffed app avoids that delay. A tunnel to this computer depends on its power, network and running processes. Cloudflare describes Quick Tunnels as a testing service with no uptime guarantee. Share only a dedicated staffed synthetic instance with HTTPS, a trusted proxy and restricted judge access. The local rehearsal on port 8038 is for this computer. [Render free instances](https://render.com/docs/free) · [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

No public-host timing has been measured. Before distributing a hosted link, time a first sign-in, page-2 preview and export from the judge network and repeat with several simultaneous browsers. Keep the local demo available for the presentation. After judging, revoke judge logins, retain any needed synthetic results and remove the billable resources.
