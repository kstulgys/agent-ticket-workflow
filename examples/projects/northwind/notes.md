# Northwind, Contoso migration

Fictional example. Every name, path, and command here is made up. Replace all of
it with your own project.

## Repo layout

One solution, three apps. `src/Contoso.Web` serves the public site.
`src/Contoso.Admin` serves the back office. `src/Contoso.Jobs` runs the nightly
imports. A ticket about a form on the public site is almost always
`Contoso.Web`.

## The verify gate

Run these in order from the repository root. Both must pass before you push.

```bash
dotnet format --verify-no-changes
dotnet test
```

A clean run prints `Passed!` with a failed count of 0 for each test project.
`dotnet format` prints nothing when the formatting is already correct.

## Conventions that bite

Never edit a file under `src/*/Migrations/`. Those are generated. Add a new
migration instead. The repository lints trailing whitespace, so save with your
editor's trim setting on.

## Code areas by name

Forms live in `src/Contoso.Web/Pages`. Shared validation lives in
`src/Contoso.Core/Rules`. The import flows live in `src/Contoso.Jobs/Flows`, one
file per feed.

## Project traps

Two brands share one deployment. `NORTHWIND_BYPASS_BROOKFIELD` and
`NORTHWIND_BYPASS_HILLCREST` each hold the preview bypass for one brand, so a
protected preview needs the variable for the brand in the ticket. The deploy
gate opens when the user says the build reached the test environment.

## Deep references

- `docs/imports.md` for the feed formats.
- `docs/brands.md` for which brand serves which domain.
