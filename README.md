# Watch My Handle

**Know when a name moves.** Watch My Handle is powered by the open-source `claimwatch` CLI that watches domains and handles for availability, ownership changes, and activity changes, then emits webhook or email alerts.

It is for the awkward window between “we want that identity” and “someone remembered to check”: a founder waiting on a domain, a team protecting a brand, or an individual tracking the same handle across platforms.

Watch My Handle is self-hostable and has no required server component. Run it from cron, a $0 GitHub Actions schedule, or any machine that can keep a small JSON state file.

> **Alpha software.** Platform checks are evidence, not a claim guarantee. Confirm availability in the platform or registrar before making decisions.

## What works

| Target | Signal source | Quality | Availability | Ownership/activity |
| --- | --- | --- | --- | --- |
| Domain | IANA-bootstrapped registry RDAP | Matching registry records | Taken / not registered / unknown; no promise of registrability | Registry event dates; no registrant identity |
| GitHub | Public REST API | Strong | Taken / unknown | Numeric account ID, `updated_at` |
| Instagram | Optional Apify actor; unknown public-page fallback | Matching profile records only | Unknown on absence/throttle | Profile ID/activity when Apify exposes it |
| npm, PyPI, Docker Hub | Public registry APIs | Strong | Taken / unknown | Package/user identity; versions where exposed |
| Mastodon | Instance account lookup | Strong when `handle@instance` is supplied | Taken / unknown | Instance account ID, last status date |
| YouTube, Reddit, Twitch, Pinterest, Bluesky, Product Hunt, Substack, Medium, dev.to | Public profile endpoints | Best effort | Unknown; public pages cannot verify claimability | Handle only unless source exposes more |
| X, LinkedIn, Threads, Snapchat, Telegram, TikTok | Public profile pages | Weak / frequently challenged | Conservative `unknown` on ambiguous 404 or throttle | Handle only |

No social handle is labeled available. A missing account can be deleted, reserved or restricted. Generic HTML pages stay `unknown`, including HTTP 200 login pages and soft 404s. Matching public API records are `taken`.

Domains use `taken` for a matching registry RDAP record, `not_registered` only for an authoritative registry HTTP 404 with an empty body or RDAP errorCode 404 ([RFC 7480 section 5.3](https://www.rfc-editor.org/rfc/rfc7480.html#section-5.3)), and `unknown` for unsupported TLDs, malformed records, redirects, timeouts or rate limits. `not_registered` does not mean available to buy: registry reservation, premium pricing and policy restrictions require registrar confirmation. DNS and website content are not registration evidence.

### Instagram: optional Apify backend

Set `APIFY_TOKEN` to use Apify's Instagram Profile Scraper (`apify/instagram-profile-scraper`) for Instagram checks. The actor uses a paid provider with pricing and credit policies that can change; check current Apify pricing. The token is read only from the environment and must never be committed. Configuring it authorizes the CLI to use that paid source; do not set it unless you intend to consume the provider's credits. Without it, the claimwatch CLI uses the public profile fallback and reports `unknown` without issuing unverifiable HTML requests.

## Quickstart

```bash
git clone https://github.com/DeepanshuPal/claimwatch.git
cd claimwatch
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp claimwatch.example.yml claimwatch.yml
claimwatch --config claimwatch.yml --no-alerts
```

The first conclusive run emits `first_seen` events and writes `.claimwatch/state.json`. Later runs emit only field changes:

- `availability_changed`
- `owner_changed`
- `last_activity_changed`

Remove `--no-alerts` after configuring a transport.

## Configure targets

```yaml
targets:
  - platform: domain
    domain: your-brand.com
  - platform: github
    handle: your-brand
  - platform: x
    handle: your_brand
  - platform: instagram
    handle: your_brand
  - platform: tiktok
    handle: your_brand
```

JSON configs are supported too. The committed example contains **sample data only**.

## Alerts

### Webhook

```yaml
alerts:
  webhook:
    url: "${CLAIMWATCH_WEBHOOK_URL}"
```

The claimwatch CLI sends a JSON body with `source` and an `events` array. Point it at your own service, n8n, or another self-hosted webhook consumer.

### SMTP email

```yaml
alerts:
  smtp:
    host: smtp.example.com
    port: 587
    username: "${SMTP_USERNAME}"
    password: "${SMTP_PASSWORD}"
    from: alerts@example.com
    to: you@example.com
```

Secrets are read from environment variables at runtime. Never commit a filled config or `.env` file.

## Run it for nearly $0

### GitHub Actions (recommended)

Copy the committed `.github/workflows/claimwatch.yml`, add your `claimwatch.yml`, and configure any optional repository secrets. It runs daily at 06:17 UTC and commits the state file back so change detection survives ephemeral runners. Change the cron to `17 * * * *` for hourly checks. A copy also lives at `docs/claimwatch-workflow.yml` for installations where the GitHub token used to publish the claimwatch CLI cannot create workflow files.

The workflow uses only GitHub-hosted Actions and the public repository. Normal public-repo usage fits GitHub's free model; platform quotas and policies can change.

### Cron


Cron is enough:

```cron
17 */6 * * * cd /opt/claimwatch && .venv/bin/claimwatch -c claimwatch.yml >> claimwatch.log 2>&1
```

A sensible starting cadence is:

- Domains: every 6-24 hours. RDAP data does not need minute-level polling.
- GitHub: every 1-6 hours. Set `GITHUB_TOKEN` for a higher API limit; the checker also works unauthenticated.
- X, Instagram, TikTok: every 12-24 hours with jitter. Faster scraping is brittle and more likely to trigger blocks.

If you run in ephemeral CI, persist `.claimwatch/state.json` between runs. Keep permissions read-only by default, pin third-party Actions, and store config secrets in the CI secret store.

## Platform reality, without hand-waving

### Domains

RDAP is free and standardized, but coverage and semantics vary by registry. Missing DNS is not used to infer registration. A valid no-record answer from the IANA-selected registry is `not_registered`, never a claim that a name can be purchased. Watch My Handle does not buy or reserve names.

### GitHub

The public REST endpoint is reliable for whether a profile exists. Unauthenticated requests have a lower rate limit. A token is optional and should be scoped as narrowly as possible; no token is ever stored by the claimwatch CLI.

### X

X's official API access and pricing can change. V1 does not require it. The adapter links the public profile URL but returns `unknown`: generic pages cannot prove identity, claimability or dormancy. A future official-API adapter belongs behind the same checker interface.

### Instagram and TikTok

Neither offers a dependable, free, general-purpose username availability API for this use case. Public pages frequently challenge automation. These adapters are best-effort discovery signals. They do not bypass login, CAPTCHA, or platform controls.

## Exit behavior

- `0`: checks completed (individual targets may still be `unknown`)
- `2`: at least one checker returned `error`

Every run prints structured JSON to stdout, so it composes with `jq`, log pipelines, and CI.

## Development

```bash
pip install -e '.[dev]'
ruff check .
pytest -q
cd web && npm ci && node --test lib/checks.test.mjs && npm run build
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for adapter and transport boundaries.

## Hosted site

The `web/` directory contains a static-export Next.js site for GitHub Pages with a client-side free checker, pricing copy only (no billing backend), clean metadata, robots.txt, and sitemap. Direct browser probes can be blocked by CORS; those results stay `unknown` and point users to the CLI. The waitlist uses a Formspree free form after the owner creates one ID; see `web/README.md`.

## Roadmap

- Fixture-backed adapters for more registries and networks
- Optional SQLite state for long histories
- Alert deduplication and retry policy
- Signed event payloads
- A maintained Docker image
- Managed hosted watches, history, and team workflows (the current site is a product preview)

## License

MIT. See [`LICENSE`](LICENSE).

## Alert delivery and old state

Old `available` records and unversioned `taken` records are downgraded to `unknown` on load, so old HTML and DNS guesses are not retained as proof. Inconclusive probes preserve the last verified record and do not emit change alerts. Missing activity fields are not treated as activity changes. Registry handles identify records, not registrant identities; domain checks do not emit owner-change alerts.

The CLI saves state after configured alert sends succeed. A failed send leaves changes retryable. With multiple transports, a retry can repeat a send that already succeeded; delivery is at least once, not exactly once. `--no-alerts` intentionally consumes the current changes without sending.

The browser checker rejects invalid input rather than silently renaming it. Each network request times out after 12 seconds. Browser CORS limits and unsupported registries remain `unknown`; the CLI is the broader evidence source.
