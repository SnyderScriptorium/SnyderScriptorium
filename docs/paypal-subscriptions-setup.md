# PayPal subscription rollout

The membership uses separate PayPal fixed-price plans so changing the price for new members does not silently change an existing subscriber's price.

## Planned plans

- `founding_3` — $3/month
- `standard_4` — $4/month
- `standard_5` — $5/month

The first launch uses `founding_3`. When the catalog grows, a new plan is activated for new subscribers. Existing subscribers remain attached to the PayPal plan they originally joined under.

## Sandbox first

Create and test the product and plans in PayPal Sandbox before using live credentials. PayPal's current subscription flow is: product -> billing plan -> JavaScript SDK subscription button -> buyer approval -> subscription status/webhooks.

## Render environment variables

Set these in Render when the Sandbox integration is ready:

- `PAYPAL_ENV=sandbox`
- `PAYPAL_CLIENT_ID=<sandbox client id>`
- `PAYPAL_CLIENT_SECRET=<sandbox secret>`
- `PAYPAL_WEBHOOK_ID=<sandbox webhook id>`
- `PAYPAL_PLAN_FOUNDING_3=<sandbox $3 plan id>`
- `PAYPAL_PLAN_STANDARD_4=<sandbox $4 plan id>`
- `PAYPAL_PLAN_STANDARD_5=<sandbox $5 plan id>`

Never commit the client secret, webhook secret, or other credentials to GitHub.

## Membership status mapping

- Activated / successful subscription payment -> `active`
- Payment failed -> `past_due`
- Suspended -> `paused`
- Cancelled -> `cancelled`
- Expired -> `expired`

The site's protected K. W. Snyder Writing area should only unlock for `active` status. A failed payment should not delete the member account.

## Go-live sequence

1. Create Sandbox product.
2. Create Sandbox $3 founding plan.
3. Connect Sandbox PayPal button to the logged-in member.
4. Add and verify subscription webhooks.
5. Test successful signup and member access.
6. Test failed payment and access pause.
7. Test cancellation and expiration.
8. Test admin disable/revocation.
9. Only then create/activate the live product and founding plan and switch `PAYPAL_ENV=live`.
