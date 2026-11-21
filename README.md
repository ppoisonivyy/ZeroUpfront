# ZeroFront

Hackathon project by a team of three.

## Repository layout

```text
ZeroFront/
├── app/          Application code and tests
├── docs/demo.md  Demo script and submission prep
└── README.md     Project overview and team workflow
```

Keep application code and its tests together in `app/`. Once the first runnable version lands, add the prerequisites and the exact setup and run commands here. List any required environment variables in a committed `.env.example` with placeholder values.

## Team ownership

| Role | First responsibility |
| --- | --- |
| Tech lead | Choose the stack, define shared interfaces, and own integration and the release build. |
| Teammate 1 | Own the main user experience and the on-screen demo flow. |
| Teammate 2 | Own the data, integrations, and demo fixtures. |

Agree on the one flow you want judges to see. Build a minimal version that runs end to end, then polish it. Use GitHub Issues for work that needs coordination and assign each issue one owner.

## Git workflow

1. Branch from `main` for each task, using a short name such as `feat/demo-flow`.
2. Open a small pull request with a summary and a quick way to verify it. Request review from the tech lead for changes to shared interfaces, setup, or deployment. For other changes, any teammate can review.
3. Squash-merge once the change is verified. Keep `main` in a state the team can demo.

Before submission, run through the demo from a fresh clone and tag the commit you submit.
