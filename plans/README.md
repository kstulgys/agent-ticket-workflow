# Implementation plans

Written by the improve skill on 2026-08-24 against commit `50239f0`, from a
request to change how the skill asks for credentials.

The request, in the owner's words:

- No presetup phase. Install the skill, open a project, type "work on 5438".
  Ask only when something is missing.
- Only when the tracker cannot be worked out, ask which one it is, with a
  select of GitHub, Azure, or Jira, then guide the user to that one token.
- Ask for a Figma token only when a ticket links a Figma frame and the read
  fails.
- Reading a ticket or a Figma frame through a browser is forbidden. The user
  supplies a token, the tool stores it locally, and the tool reads it when
  needed.
- Update the README and add an install prompt a user can paste into an agent.

Execute in the order below. Each executor: read the plan fully before starting,
honor its STOP conditions, and update your row when done.

## Execution order and status

| Plan | Title | Priority | Effort | Risk | Depends on | Status |
|------|-------|----------|--------|------|------------|--------|
| 001 | Remove the browser session path for reading tickets and designs | P1 | S | LOW | — | DONE |
| 002 | Make a missing token one provider's question, not a wizard gate | P1 | M | MED | — | DONE |
| 003 | Build a project profile from what the machine already knows | P1 | L | MED | 002 | DONE |
| 004 | Ask at the moment of need, and say so in the docs | P1 | M | LOW | 001, 002, 003 | DONE |

Status values: TODO | IN PROGRESS | DONE | BLOCKED (with one-line reason) |
REJECTED (with one-line rationale)

All four landed on branch `advisor/lazy-first-run`, seven commits, `50239f0..`.
One branch rather than four, because the plans run in sequence and 003 depends
on 002, so stacking them avoids a merge.

Three checks in the plans were wrong and the execution found them. Each one is
corrected in its plan file:

- 001 and 004 checked a phrase that the replacement text wraps across a line
  break, so the grep could never match. `a browser to look` replaced
  `in a browser to look`, and the SKILL.md Figma paragraph was reflowed to keep
  `scripts/setup.sh figma` on one line, because a command a reader copies must
  not wrap.
- 004's em dash check used `grep '^+'`. In this environment that pattern
  matches every line, so it counted a line plan 001 removed. The check now
  reads `grep -c '^[+].*—'`, and the real answer is 0.
- 003 gave `bootstrap.init` no runner seam, so a test of the Azure host path
  would have had to shell out to git. `init` now takes `runner=None` beside
  `client=None`, and both are injected by the tests.

## Dependency notes

- 001 and 002 are independent. Both edit `scripts/setup.sh`, in different
  hunks: 001 the Jira stage at lines 297-301, 002 the argument default at
  156-172 and the closing stage at 343-363. Run them in either order, or on one
  branch to avoid a merge.
- 003 depends on 002 because the bootstrap it adds leans on a missing token
  naming its own wizard stage. Without 002, `tk init` on a fresh machine fails
  with "no secrets file" and names the whole wizard.
- 004 depends on all three because it documents them. Documenting first would
  promise verbs that do not exist. Its line numbers shift by about six lines
  once 001 lands, so every replace instruction in it names a text anchor too.

## Test counts, so no plan argues with the next

| After | Suite | How |
|---|---|---|
| `50239f0` | 447 | baseline, measured |
| 001 | 447 | prose and deletions only |
| 002 | 451 | replaces 1 test, adds 4 |
| 003 | 483 | adds the 32 cases in `tests/test_bootstrap.py` |
| 004 | 483 | prose only |

`README.md:258` says "388 tests". That number is stale at `50239f0` already,
and plan 004 step 6 replaces it with the real one.

## What the four plans do together

The user's flow, after all four land:

1. Clone the skill. Nothing else.
2. Open a project, type "work on 5438".
3. `tk resolve 5438` answers `unresolved`, because no profile exists yet.
4. `tk detect` reads the git remote. When it names GitHub or Azure DevOps, that
   is the tracker and no question is asked. When it names nothing, the agent
   asks once, with three options.
5. `scripts/setup.sh <provider>` mints that one token. The wizard writes it to
   `secrets.env` itself, so the value never reaches the chat.
6. `tk init` writes the profile from the remote, the git config, the provider's
   own account, and the id the user typed.
7. The ticket is read. A Figma url in it asks for a Figma token, and only then.

Split across four plans because the parts fail differently. 001 is deletion.
002 changes one guard that every verb passes through. 003 is new code with a
new test file. 004 is prose. One plan holding all four could not be verified
step by step.

## Decisions taken while planning

Each of these was decided from the code rather than asked, and each is
reversible.

- **`tk detect` and `tk init` are code, not prose in `SKILL.md`.** The repo's
  own rule (`README.md:139-142`) is that a provider trap belongs in code with a
  test, because prose gets skipped. Reading a git remote has six forms and real
  edge cases, so it is a guard, not a note.
- **A bare `scripts/setup.sh` runs the Superpowers stage only.** Asking for four
  tokens is the setup phase this work removes. Naming several stages still
  works: `scripts/setup.sh azure github`. Flip this by changing one line in the
  wizard if you want the old default back.
- **`tk init` invents no tracker state name, no assignee beyond `self`, and no
  deploy gate.** It writes the four bucket names with null states. A wrong guess
  there writes to a real ticket, which is the one failure worth a question.
- **`tk init` writes the profile last.** A missing token then leaves no profile
  at all, so the retry is the same command. A profile written first would leave
  a broken one that `doctor` reports for ever.
- **The browser ban covers reading, not proving.**
  `references/verification.md` still drives a browser to prove a visual change.
  Reading a ticket or a design goes through the API with a token.

## Findings considered and rejected

- **Rewrite `references/profiles.md` around `tk init`.** Not worth doing now.
  The page is the full schema reference and stays correct. `tk init` writes a
  subset, and plan 004 says which fields the page is still for.
- **Delete `tk doctor`, or fold it into the first run.** Rejected. It is a good
  diagnostic and three tests depend on its fix lines. The problem was running it
  as a gate, which plan 004 fixes in one paragraph.
- **Have `tk init` ask the questions itself, in the terminal.** Rejected. The
  agent already has a select-option question tool, and a prompting CLI cannot be
  driven by an agent without a pseudo-terminal. `init` takes flags and stays
  testable.
- **Add GitLab and Bitbucket to `tk detect`.** Rejected as speculative. Nothing
  in the request needs it, and a remote pattern without a matching host kind in
  `gitcmd.TOKEN_ENV` would write a profile that cannot push.
