# Record the hospital-to-insurer handoff

The silent demo uses Chromium to submit a real, revision-bound synthetic Amelia Morgan request to the Meridian Assist inbox. The recorder starts the app with a disposable PostgreSQL cluster; closing it leaves the judge’s workspaces intact.

From the repository root, install Node 24+, uv, Python 3.12, PostgreSQL command-line tools and FFmpeg with libass and ffprobe. Then run:

```sh
npm ci
npx playwright install chromium
npm --prefix web ci
npm --prefix web run build
npm run demo:record
```

The recorder binds the release to `http://127.0.0.1:18092/`. To use a different free loopback port set `DEMO_PORT`. It creates separate, transient hospital and insurer accounts, signs in through the ordinary UI, and cuts authentication from the film. The benchmark runs against disposable synthetic records in a real terminal. The only presentation screens are the title and closing cards. The ten storyboard scenes cover one pre-arrival request through insurer receipt. A close-up shows the highlighted words on the original policy. Separate clicks show staff marking the draft reviewed and then submitting it to the insurer. The separate [discharge follow-up rehearsal](../docs/demo.md#human-review-after-a-payer-reply) starts after a payer has already replied. Captions are burned in and also written as SRT. The local MP4 is ignored by Git.

For a persistent, interactive demonstration use `uv run --locked python -m app.hospital_demo` and open the [judge directory](http://127.0.0.1:8040/). [Hospital setup and access](../docs/hospital-workspaces.md)
