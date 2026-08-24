# Implementation plans

Written by the `improve` skill on 2026-08-23, against commit `00d0bb2`. Every
plan stamps that commit and carries its own drift check.

Execute in the order below unless the dependency notes say otherwise. Each
executor: read the plan fully before starting, honour its STOP conditions, and
update your row when done.

Every plan verifies with the same command, run from the repository root:

```bash
python3 -m unittest discover -s tests -t tests
```

At `00d0bb2` that reports 388 tests and ends `OK` in about 0.04 seconds, with no
network. A plan that adds tests raises the number, so a later plan's count check
is "the previous count plus mine".

## Execution order and status

All thirteen executed on branch `advisor/plans`, one commit each, nothing
pushed. The suite went from 388 tests to 447, and it ends `OK`.

| Plan | Title | Priority | Effort | Depends on | Status | Commit |
|------|-------|----------|--------|------------|--------|--------|
| 001 | Run the test suite on every push and pull request | P1 | S | none | DONE | `be9ba9f` |
| 002 | Keep a link target when rendered HTML becomes text | P1 | S | none | DONE | `fb14f58` |
| 003 | Give every request a deadline, name every transport failure | P1 | S | none | DONE | `9dda22f` |
| 004 | Stop a credential crossing hosts, never write an unchecked download | P1 | M | 003 | DONE | `5a1a811` |
| 005 | Make the first wizard run work | P1 | S | 001 | DONE | `2d33c6c` |
| 006 | Refuse a malformed profile with the documented error | P2 | S | 003 | DONE | `83eaaf3` |
| 007 | Pin the exit code of every verb that changes a ticket | P2 | M | 003 | DONE | `50397c8` |
| 008 | Write the Jira session file where only its owner can read it | P2 | S | none | DONE | `1b9b8da` |
| 009 | Mask the credential in the form it travels in | P2 | S | 003, 004 | DONE | `8bcbdbe` |
| 010 | Make the documentation match what the code does | P2 | S | 005, 008, 009 | DONE | `b0a1af1` |
| 011 | Read every assigned ticket, or say the read is not complete | P3 | M | 004 | DONE | `61704f8` |
| 012 | Make `tk doctor` fail a placeholder profile | P3 | M | 006 | DONE | `6860934` |
| 013 | Delete the one dead function, mark the three that wait | P3 | S | none | DONE | `ff698ef` |

## Where a plan was not followed to the letter

Three plans asked for something the code then argued against. Each departure is
recorded here with the evidence, because a reviewer needs to see it.

- **004 dropped one of the two header spellings.** The plan stripped both
  `name.capitalize()` and `name.title()`. Only `capitalize()` is reachable:
  `Request.add_header` and the redirect constructor both store a header under
  `key.capitalize()`, so `title()` never matches a stored key. A probe against
  `following.headers` confirms all three credential headers leave on a cross
  host hop with `capitalize()` alone.
- **004 also changed `free_path`, which its scope called out of bounds.** The new
  `write_new` could not work without it. `os.path.exists` follows a symlink and
  answers False for a dangling one, so `free_path` returned the same taken name
  on every try while `O_EXCL` kept raising `FileExistsError`. The loop spun 50
  times and then reported "no free name", which is the wrong reason. One word,
  `lexists`, makes the two functions agree on what taken means. The download now
  lands beside the link and the link target is never written.
- **009 skipped step 3, the stderr warning for a short secret.** It hits the
  plan's own STOP condition. Two fixtures hold short values on purpose
  (`tests/test_secrets.py` writes `SHORT=ab` and `A=""abc""`), and both exist to
  prove a short value is not masked, so the warning fires in a normal run. On the
  path the warning was written for it can never fire: `basic()` output is at
  least 10 characters for any input. An unreachable warning that only produces
  false positives trains a reader to ignore stderr.
- **012 dropped rule 5, the `host.local_path` directory check, and adds its row
  only when it finds a gap.** The directory check makes `doctor`'s verdict depend
  on the machine rather than the file, it fails on a profile whose repository is
  not cloned yet, and a wrong path already fails at `tk git` with an error that
  names the directory, so it lacks the confusing late failure that justifies this
  plan. Adding a row unconditionally would also have rewritten six assertions
  that pin the exact `projects` list, purely to carry a row saying nothing is
  wrong.

Status values: TODO, IN PROGRESS, DONE, BLOCKED (with a one line reason),
REJECTED (with a one line rationale).

## Dependency notes

Most dependencies here are file collisions, not logic. Two plans editing the same
function in parallel produce a merge no reviewer wants to read.

- **004 needs 003.** Both change the `Http` constructor. 003 adds the `timeout`
  keyword that 004's opener must keep.
- **005 needs 001.** Step 5 of 005 adds a `shellcheck` step to the workflow file
  that 001 creates. 001 deliberately leaves that step out, because the dead
  functions 005 deletes are what `shellcheck` would report on the first run.
- **006 needs 003.** Both read `cli.error_codes`. 006 also argues against adding
  two classes to it, so it should be written after 003 settles what the table
  holds.
- **007 needs 003.** Both add tests to `tests/test_verbs.py`.
- **009 needs 003 and 004.** It edits `http.py` and it describes, in the README,
  the behaviour those two leave behind.
- **010 needs 005, 008 and 009.** It documents the wizard prompts from 005, the
  new session file path from 008, and it edits a different README paragraph from
  009.
- **011 needs 004.** Both edit `azure.py` and `jira.py`.
- **012 needs 006.** 006 guarantees every profile block is an object, so 012 can
  read a block without guarding its type.
- **013 last.** It asserts the test count does not change, so it wants a quiet
  tree.

Plans 002 and 008 touch files nothing else touches. Either can run at any time.

## What each plan fixes

Ordered by leverage, which is impact divided by effort, discounted by confidence
and by the risk of the fix itself.

- **002** is the highest user value. A Figma link inside a hyperlink is dropped
  before `figma_urls` ever sees it, so the agent skips a design read the routine
  calls mandatory. Reproduced before the plan was written.
- **003** gives the CLI a bounded wall clock. It has none today, and it runs as a
  subprocess under an agent.
- **005** fixes the first thing a new user runs. The wizard verifies tokens
  against this repository's own example organisations, so a correct token reports
  as broken.
- **004** stops a provider credential following a redirect to another host, and
  stops an unchecked download landing on disk under an attachment's name.
- **001** is the gate the other twelve rely on.

## Findings considered and rejected

Recorded so nobody audits them again.

- **Consolidate the three provider adapters.** Not worth doing. `azure.py`,
  `github.py` and `jira.py` are three correct implementations, not one logic
  copied three times. `state()` is the clearest case: an Azure field patch with a
  type to state map, a Jira transition graph resolved by name, and a GitHub label
  operation share a signature and nothing else. Merging them would couple three
  files whose whole design is that they may diverge.
- **`secrets.env` written to the wrong path.** Not a defect. The wizard library
  default at `scripts/setup.sh:26` is `.env`, and `setup.sh:209` overrides it with
  the real path before any stage runs.
- **`pr create` exits 0 when a work item link is dropped or a reviewer is
  refused.** By design. `SKILL.md` names all six answer keys and states that a
  refused reviewer does not fail the pull request.
- **`util.free_path` is subject to a race between two concurrent runs.** Real and
  unreachable. The routine works one ticket at a time in one process. Plan 004
  closes the symlink half of it anyway, because that fix is one helper.
- **README claims 388 tests.** Accurate at `00d0bb2`. The suite was run while
  auditing. No fix needed.
- **Move the profile model out of `cli.py`.** Deferred, not rejected. About 115
  lines of `cli.py` are the identity and bucket model rather than CLI plumbing,
  and five deferred imports work around one real cycle between `cli` and
  `config`. The refactor is M effort at MED risk on the subtlest logic in the
  repository, which is a bad trade while there is no CI. Revisit after plan 001
  lands. One piece of it is free and worth doing inside any other `cli.py` edit:
  the comment at `cli.py:124-125` says an adapter imports `cli` for its verb
  table, and no adapter imports `cli` at all, so two of those five deferrals
  guard a cycle that does not exist.
- **Add a linter, formatter or type checker.** Not worth doing. The code is
  standard library only and consistently formatted, and a checker would find
  close to nothing. `compileall` in CI covers the one class that matters, a name
  error in an untested branch.
- **A unit test for `scripts/jira-cookies.py`.** Not worth writing. It drives
  Chrome's cookie database, DBus and the login keyring. A test would assert
  against mocks of all three and defend nothing.
- **An https floor on the profile base URL.** Low value, folded away. A profile
  with an `http://` organisation would send the token in the clear, but the
  profile is the user's own file and every example uses https. Plan 004's host
  comparison keeps the scheme, which covers the reachable case.

## Open decisions

- **Wire or delete the three unreached functions.** `util.slugify`,
  `util.expand` and `Azure.identity` have no caller and carry 17 tests. Two
  verbs would use them: `tk names`, which would expand `branch_pattern` and
  `commit_subject` in code rather than in prose, and `tk whois`, which would
  find the raw identity a profile's `people` block needs. Both were offered
  during the audit and deferred. Plan 013 marks the functions and deletes
  nothing, so the decision stays cheap either way.

## Direction options, deferred

Grounded in the repository, offered during the audit, and not planned. Kept here
so the evidence is not lost.

- **`tk names <ticket>`.** `SKILL.md:107-108` hands branch and commit pattern
  expansion to the model, and a wrong branch name is the one write no read back
  catches. `util.expand` and `util.slugify` already do the work, tested. Against
  it: `{area}` and `{summary}` are judgement calls, so the verb removes the
  mechanical error only.
- **`tk whois`.** Profile authoring is the only onboarding step with no tooling
  and the worst failure mode. `cli.py:186-190` records what goes wrong: a Jira
  account id used as a GitHub login matched none of the operator's own threads
  and returned them all. `Azure.identity` exists; Jira `/myself` and GitHub
  `/user` are already called every `doctor` run.
- **Editable ticket comments.** `references/writing-comments.md` says to correct
  a stale comment, then admits `tk` has no edit verb, while both pull request
  hosts can already rewrite a body. The blocker is that `show` does not surface
  comment ids, and adding them changes the normalised shape that
  `tests/test_azure_read.py` pins exactly.

## What the audit did not cover

- **Performance.** Audited and empty, correctly. No hot loop, no database, no
  bundle. `figma._walk` recurses over provider data, and a real file nests
  nowhere near the recursion limit.
- **Live provider behaviour.** Two claims were checked against vendor
  documentation while planning: the Jira attachment route answers 303 to a media
  host, and the Azure work items batch route accepts at most 200 ids. Everything
  else about provider behaviour comes from the code and its fixtures.
- **The operator's live data** under `~/.claude/ticket-workflow/`. Never read.
  Every profile claim is checked against `examples/projects/` and
  `references/profiles.md`.
- **`scripts/setup.sh` line by line.** The library helpers, the provider stages
  and the tail were read. The colour and layout helpers were not.
