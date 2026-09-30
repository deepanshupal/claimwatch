# Watch My Handle web

Next.js app for Vercel. The free checker runs in the visitor's browser and calls public endpoints directly. There is no checker backend, database, or paid service. Browser CORS restrictions are reported as `unknown`; social results are `taken` or `unknown`, never `available`. Domains distinguish matching registry records (`taken`), authoritative no-record answers (`not_registered`) and `unknown`. No-record answers are not a registrar offer.

## Local

```bash
npm install
npm run dev
```

## Waitlist capture

Formspree is the selected $0 route. Create a free form at https://formspree.io/, then replace `REPLACE_WITH_FORM_ID` in `app/page.tsx`. This ID is public routing metadata, not a secret. Until that one-time setup, the site links to the CLI instead of displaying a broken signup form.

## Deploy on GitHub Pages

`.github/workflows/pages.yml` builds and deploys `web/out` on every push to `main`. The workflow sets `GITHUB_PAGES=true`, so Next.js uses `/claimwatch` as `basePath` and `assetPrefix` for the default project URL at `https://deepanshupal.github.io/claimwatch/`.

After `watchmyhandle.com` is attached in the repository's Pages settings, remove the `GITHUB_PAGES` environment variable from the workflow. The same static export then builds at the domain root. The canonical production hostname is already `https://watchmyhandle.com` in metadata, sitemap, and robots.

The site has no runtime server dependency. The checker calls public endpoints from the visitor's browser, and CORS-blocked checks stay `unknown`. The waitlist posts directly to Formspree after its form ID is configured.
