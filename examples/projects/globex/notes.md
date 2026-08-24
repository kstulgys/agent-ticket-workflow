# Globex, Dist web platform

Fictional example. Every name, path, and command here is made up. Replace all of
it with your own project.

## Repo layout

A pnpm workspace. `apps/storefront` serves the customer site. `apps/portal`
serves the dealer portal. `packages/ui` holds the shared components. A ticket
about a checkout step is `apps/storefront`.

## The verify gate

Run these in order from the repository root. All three must pass before you
push.

```bash
pnpm lint
pnpm test
pnpm build
```

A clean run prints `0 problems` from lint, a passing suite with no failures, and
`build succeeded` for each app.

## Conventions that bite

`packages/ui` is consumed by both apps, so a change there needs both builds
green. Use the language server to find every consumer before you rename an
exported component. The repository refuses a commit that adds a `console.log`.

## Code areas by name

Checkout lives in `apps/storefront/src/checkout`. Feature flags live in
`packages/config/flags.ts`. The dealer pricing rules live in
`packages/pricing`, which both apps import.

## Project traps

The tracker is Jira and the pull request host is GitHub, so a reviewer is a
GitHub login, not a Jira account id. The deploy gate opens on the word
"promoted": when the user says the build was promoted to test, move the ticket
to `Ready for Test`. Nothing else releases that gate.

## Deep references

- `docs/flags.md` for how a flag reaches an app.
- `docs/pricing.md` for the dealer tier rules.
