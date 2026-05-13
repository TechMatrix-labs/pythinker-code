# Pythinker feedback worker

Cloudflare Worker for `POST https://api.pythinker.com/coding/v1/feedback`.

It accepts explicit user submissions from the Pythinker CLI `/feedback` and `/report-error`
commands, creates a GitHub issue, and optionally emails `support@pythinker.com` through Brevo,
Resend, or Postmark.

## Setup

```bash
cd examples/feedback-worker
npm install
npx wrangler secret put GITHUB_TOKEN
npx wrangler secret put BREVO_API_KEY         # recommended email provider
# Optional alternatives:
# npx wrangler secret put RESEND_API_KEY
# npx wrangler secret put POSTMARK_SERVER_TOKEN
npm run deploy
```

`GITHUB_TOKEN` should be a fine-grained token with access to the target repository and permission to
create issues. For Brevo, verify the sender domain for `FROM_EMAIL` first, including SPF/DKIM records.

## Optional shared secret

For public PyPI builds, prefer leaving `FEEDBACK_SHARED_SECRET` unset and rely on server-side
rate-limiting/WAF rules. A secret embedded in a PyPI package is not secret.

For private/dev builds, you can require a bearer token:

```bash
npx wrangler secret put FEEDBACK_SHARED_SECRET
```

Then configure local clients with:

```bash
export PYTHINKER_FEEDBACK_API_KEY='same-secret'
```

## Test

```bash
curl -i https://api.pythinker.com/coding/v1/feedback \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"test","content":"hello from curl","version":"dev","os":"linux","model":"test"}'
```
