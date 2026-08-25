---
name: agent-ticket-workflow
description: >
  Work an Azure Boards, Jira, or GitHub ticket end to end: read it, classify it,
  ship the fix, open the pull request, then comment and route it. Use when given
  a ticket id, a ticket key, a tracker url, "same drill" with ticket numbers, a
  named project, "work on the tickets assigned to me", a brand site bug, a Figma
  link in a ticket, review comments to address on an open pull request, a tester
  saying a fix does not work, "the tickets are on TST" or another way of saying a
  build reached the test environment, or first-run token setup for Azure, Jira,
  GitHub, or Figma.
---

# Ticket workflow

One routine for every tracker. `scripts/tk` makes every API call, so the
endpoints, the body formats, and the provider traps stay out of this file.
Project facts live in the profile.

Done means every ticket in the batch has a bucket, a comment, and its routing
applied. A bucket is one of four names for the work that remains, and it decides
the state, the owner, and what the comment says. A half-processed batch is the
failure this routine prevents.

## Method

This routine is the Superpowers workflow applied to tickets. Invoke
`using-superpowers` first, before you read the ticket or open a file.

That skill sets the one rule the rest of this file leans on: a process skill
chooses the approach, then an implementation skill carries it out. Skip it and a
ticket run slides into the shape this routine exists to prevent, which is read
the ticket, guess a fix, open a pull request, and learn in review that the cause
was somewhere else.

A subagent that this routine dispatches skips that bootstrap. Superpowers says
so itself, and a subagent already holds one narrow task.

Each phase below has a skill that governs it. Invoke that skill when you reach
the phase, not all of them at the start.

| Phase | Skill | What it buys |
|---|---|---|
| 3, when you cannot state the wanted behaviour | `brainstorming` | Turns a vague ticket into a spec before any code |
| 3, when the bucket is a bug | `systematic-debugging` | Finds the cause, so the fix is not a guess at the symptom |
| Before 4, unless the change is one line | `using-git-worktrees` | Keeps the ticket off your working tree |
| 4, when the ticket spans many files | `writing-plans`, then `subagent-driven-development` | Splits the work and reviews each part |
| 4 | `test-driven-development` | A failing test first, so the fix is proven and not assumed |
| 5 | `verification-before-completion` | Evidence before you call it done |
| 6, before the pull request | `requesting-code-review` | Catches what you stopped seeing |
| Resume mode | `receiving-code-review` | Answers a reviewer without relitigating |
| After the merge | `finishing-a-development-branch` | Closes the branch and clears the worktree |
| Batch mode, independent tickets | `dispatching-parallel-agents` | Runs tickets at once instead of one after another |

Your own skill list tells you whether those skills are loaded, so no command
asks. A Claude Code plugin install names them `superpowers:using-superpowers`
and so on, and a shared skills directory install names them with no prefix.
Either name is the same skill, so take whichever your list shows. When neither
form is there, `scripts/setup.sh superpowers` installs them, and a restart of
your agent loads them. Say that once and carry on, because the phases below
still describe the work.

## 0. Start where the user is

There is no setup gate. The first command is the one that answers the question
the user asked, and a gap answers for itself.

```bash
T=~/.claude/skills/agent-ticket-workflow/scripts/tk
$T resolve 5438
```

On Windows the runnable names are `scripts/tk.cmd` and `scripts/setup.cmd`. Set
`T` to the first in Git Bash, and from PowerShell or `cmd` run them with
backslashes: `scripts\tk.cmd`. Those two shells read no shebang, and a stock
Windows install has no `python3` for one to name, so each shim finds the
interpreter itself. Wherever this file says `scripts/tk` or `scripts/setup.sh`,
read the `.cmd` beside it. Nothing else changes.

Every failure prints a fixed code under `error` and a sentence under `message`,
so switch on the code, not the prose.

| `error` | What it means | Your next step |
|---|---|---|
| none | a profile owns this ticket | step 2 |
| `ambiguous` | two profiles match, exit 2 | ask the user which slug, then pass `--slug` on every verb that follows |
| `unresolved` | no profile owns it | the bootstrap in step 1 |
| `secrets` | a token variable is not set. The message names the variable and the one stage that writes it | run that stage, then repeat the command |
| `http` with 401 or 403 | the token is set and the provider refused it | run that stage again, then repeat the command |
| `profile` | a `config.json` on disk is unreadable. The message names the file | fix that one file |

Every answer is JSON on stdout. Exit 2 means one thing: a ticket matched more
than one project and a human must choose. Everything else is exit 1, a bad
command line included.

Ask for nothing you have not been refused. A run that asks for four tokens
before it reads the ticket spends the user's attention on three providers this
ticket does not touch.

`$T doctor` reads every profile and every provider at once. Run it when a call
fails for a reason no code above explains, or when the user asks what is
configured. It is a diagnostic, and never a first step: on a machine with no
profile yet its answer is a failure, and that failure is not about this ticket.

`tk` reads the tokens itself. Leave `secrets.env` closed.

Every ticket read, every ticket write, and every Figma read goes through `tk`,
with a token from `secrets.env`. Never drive a browser to reach a ticket or a
design, and never read a browser session, a cookie store, or a keyring for a
credential. A session cookie is a full account credential, and no token scope
limits it. When a provider refuses to issue API tokens, say so and stop,
because that is the user's to settle with their administrator.

Three entry points fork here.

- "The tickets assigned to me" goes to batch mode below.
- A ticket that already has an open pull request goes to resume mode below.
- Word that a build reached the test environment goes to Gates below.

## 1. Resolve the project

```bash
$T resolve 59644          # id, key, tracker url, or nothing for the current directory
```

The answer holds `slug`, `tracker`, `ticket`, and `notes_path`. Read that
`notes.md` before you touch code. It holds the repo layout, the verify gate, and
the traps for that project.

`config.json` sits beside it in the same directory. Read three fields from it,
`host.base_branch`, `host.branch_pattern`, and `host.commit_subject`, and
expand the patterns yourself. The rest of that file is for `tk`, apart from
`preview.bypass_env`, which step 5 reads on a protected deployment.

Exit 2 answers `slugs` with the candidates. Ask the user which project, then
pass `--slug <slug>` on every verb that follows. `tk resolve` takes no `--slug`,
and it ignores one in silence.

### No profile owns this ticket

This is a new project, and the machine already holds most of what a profile
needs. Read first, ask second.

```bash
$T detect
```

`detect` reads the git remote and the git config in the working directory. It
answers `provider`, `owner`, `repo`, `org`, `project`, `base_branch`, and the
commit identity. A null is a field it could not read, and a null is the only
thing worth a question. It makes no network call and needs no token.

1. The tracker. `detect` names it when the remote is GitHub or Azure DevOps. A
   Jira tracker never appears in a git remote, and neither does a tracker that
   lives apart from the code. So when `provider` is null, or when the id the
   user typed does not look like that provider's ids, ask the user once, with a
   select of three options: GitHub, Azure Boards, Jira. One question, three
   options, no free text.
2. The token, and only when it is missing. Run `scripts/setup.sh <provider>`
   from `~/.claude/skills/agent-ticket-workflow`. On Windows outside Git Bash,
   run `scripts\setup.cmd <provider>` instead. That stage opens the provider's
   token page, names the scopes to select, writes the value to `secrets.env`
   itself, and verifies it. You never see the value. Never ask the user to
   paste a token into the chat, and never read one from a browser session, a
   cookie store, or a keyring.
3. The values `detect` left null and the provider needs: the Azure organization
   and project, the Jira site and project key, or the GitHub owner and
   repository. Ask for these together, in one message.
4. Write the profile.

```bash
$T init --slug northwind --tracker azure --ticket 5438 \
    --org https://dev.azure.com/northwind --project "Contoso migration"
```

`init` fills the rest: the id pattern from the ticket you passed, the repo path
and the host block from `detect`, `people.self` from the provider's own account,
and the four buckets. It writes `notes.md` as a stub. It refuses to overwrite a
profile that is already there, and it writes nothing at all when a call fails,
so a missing token means you mint it and run the same command again.

Read the `next` list in its answer. Those are the fields no machine can fill,
and two of them cost a run when they stay empty.

- `notes.md` has no verify gate yet. Ask the user for the commands that prove a
  change in this repo, and write them into the stub before step 4.
- The four buckets hold no states. The first time a ticket needs one, ask the
  user which column their board uses for it, then write it into `config.json`.
  Until then the routing travels in the comment, which is already how this
  routine works on Azure and Jira.
- There is no `deploy_gate`. Ask for the state a tested build reaches the first
  time a ticket gets there.

`references/profiles.md` documents every key, for the fields you add by hand.

## 2. Read the ticket in full

```bash
$T show 59644 --attachments /tmp/tk-59644
```

- `description_text` keeps tables intact. A requirement written as a table is
  still readable, and that is where exact values live.
- Read every entry in `comments`. A product owner reply often carries the answer,
  including the answer to a question you asked last time.
- Read every downloaded file in `attachments`. A screenshot that decides the fix
  gets opened, not guessed at. Azure and Jira carry attachments. GitHub does
  not, so on GitHub read the issue body for inline images instead.
- Every url in `figma_urls` is an instruction. Pull the frame with
  `$T figma <url> --render /tmp/frame.png --specs` and read `references/figma.md`.
  `--specs` prints resolved values: hex, pixels, font sizes. Mapping a value back
  to a brand design token is your own step, because the Figma variables endpoint
  is Enterprise only.
  A ticket with no Figma url needs no Figma token, so this is the first place
  that asks for one. When the call answers `secrets`, run
  `scripts/setup.sh figma`, then repeat it. When it answers `http` with 403, the
  token is real and the file is not shared with the account that minted it, so
  ask the user to share the file or to mint a token on an account that can read
  it. Never open the design in a browser instead.
- `parent` and `children` matter. A bug states the loose what, and its child task
  names the how: the exact function, the config entry, the env var. Run `$T show`
  on the child too, and treat the child's description as the spec. Azure fills
  `parent`, `children`, and `links`. Jira fills `parent` only. GitHub fills
  none of the three.
- An empty list can mean the tracker carries no such key, because the shape
  fills every missing list with `[]`. So an empty `children` on Jira or GitHub
  is not evidence that no child spec exists. Read the description and the
  comments for a ticket id, run `$T show` on the id you find, and when the
  ticket names none, ask the user for the child id. Do not open the tracker in
  a browser to look.

Done when you can state the wanted behaviour in one sentence and name the file
that must change.

## 3. Classify by remaining work

First, can you state the wanted behaviour? When step 2 left you unable to, the
bucket is `needs-clarification` and this step ends there. Ask one specific
question: what wording, which field, which screen. A behaviour the ticket does
not state is the product owner's to supply, and user-facing copy in another
language always is.

Otherwise trace the code to the root cause. Then answer one question: what work
remains, and whose repo holds it?

| Remaining work | Bucket |
|---|---|
| all of it is in this repo | `fixable-here` |
| none of it is in this repo | `owned-elsewhere`, and name the concrete fix its owner must make |
| a real part ships here now, and this repo is blocked on the rest | `split` |

The profile maps each bucket to that project's state and owner, which `tk state`
writes. On a GitHub tracker that state is a label operation, so the bucket
shows as a tag there. Nothing writes a tag on Azure or Jira, so the routing
there travels in the comment.

A `fixable-here` or `split` ticket goes on to step 4. An `owned-elsewhere` or
`needs-clarification` ticket goes straight to step 7.

Three traps sit in that question:

- A contract that already exists downstream keeps the work here. When the API
  declares the field and only this repo fails to send it, the remaining work is
  here.
- Work already finished here counts as finished. A value that renders but the
  service never sends leaves this repo nothing to do. Route it, and say "already
  done here" in the comment.
- `split` needs proof this repo is blocked. Check what signal it already
  receives. It is often enough for the whole job, which makes it `fixable-here`.

A Bug drives through `systematic-debugging`, with the rigour scaled to the bug.
A label, sort, or copy fix earns a quick repro and a root-cause trace. A data or
mapping bug earns the full loop. A Story or a Task skips that skill.

Code you cannot localise goes to a read-only `scout` subagent, which keeps your
context lean. Verify its verdict before you edit. Scouts have named the wrong app
and called a service-rooted bug a local one.

## 4. Implement

Make the smallest change that solves it, and reuse the patterns already in the
repo. Follow the mechanism the ticket names. When a value already has a home, an
existing hidden field, a config entry, a computed default, fill that one, and
leave no parallel copy beside it.

Prefer editing a file over adding one. Obey the repo's own rules from `notes.md`,
and route a cross-file rename through the language server.

Done when every changed line traces to the ticket.

## 5. Verify

Run the gate from `notes.md`, then prove the behaviour. Both, not either.

The proof is running the thing. Read `references/verification.md` for how to
prove each kind of change, and for what counts as proof of a visual change.

State only what you ran. Keep internal caveats out of the ticket.

## 6. Ship

`BASE` is the profile's `base_branch`. `BRANCH` is its `branch_pattern`
expanded, and the commit subject is its `commit_subject` expanded.

```bash
BASE=master
BRANCH=feature/59644-gtm-fields
$T git --slug northwind -- fetch origin $BASE
$T git --slug northwind -- checkout -b $BRANCH
$T git --slug northwind -- commit -m "$(cat /tmp/subject.txt)"
$T git --slug northwind -- push origin HEAD:refs/heads/$BRANCH
$T pr create --slug northwind --head $BRANCH \
    --title "[59644] Hillcrest | fill the tracking fields" \
    --body-file /tmp/pr.md --link 59644:Task --reviewer reviewer
```

`tk git` runs in the project's repo path, injects the credential, and commits as
the project identity. Write the pull request body with
`references/writing-comments.md`.

`--link` takes `<id>:<type>`, with the type spelled the way the profile's
`link_rules` spells it. Without that suffix the CLI reads the type over the
network, one call per link. `--reviewer` takes a role the profile's host block
names, or a name the host reads already, such as a GitHub login.

`tk pr create` answers `id`, `url`, `linked`, `unlinked`, `refused`, and
`reviewer_ok`. Read all six.

- `refused` is what `never_link_types` blocked. A merge completes every linked
  work item, and a bug must reach its test pass instead. Leave a refused item to
  its parent relation.
- `unlinked` is what the call asked to link and the server did not confirm. Link
  it in the web UI, or say so in the comment.
- `reviewer_ok` is `null` when the call named no reviewer, and `false` when the
  server refused the one it named. A refused reviewer does not fail the pull
  request, so add that person by hand and carry on.

A visual change carries its proof through `$T pr attach` and `$T pr describe`.

Merge is the user's action. Open the pull request, report its url, and stop
there.

## 7. Bookkeep

```bash
$T comment 59644 --body-file /tmp/comment.md
$T state 59644 --bucket fixable-here --type Task
```

`tk state` applies the bucket's state and assignee together. It takes
`--bucket <name>` or `--gate`, never both. `--type` is optional and saves one
read. Use `$T assign <ticket> --owner <role>` only to override the owner the
bucket names.

Write the comment with `references/writing-comments.md`. On an Azure project the
comment is the whole routing a reader sees, so name the bucket and the owner in
it.

Every write reads back what the server stored and exits non-zero on a mismatch.
Read the stored text, and report what landed.

Done when this ticket has a bucket, a comment, and its state and owner applied.

## Resume mode: the ticket already has a PR

A ticket that comes back with an open pull request came back because somebody
answered it.

```bash
$T pr threads --slug northwind --pr 6453
```

Those threads, plus any ticket comment newer than your last update, are the whole
spec for this pass. The description is already implemented on that branch, so
re-deriving scope from it concludes "already done" and wastes the run.

A resumed run keeps steps 1, 4, 5, and 7. The threads replace steps 2 and 3, and
step 6 loses its branch and its pull request, so commit and push onto the branch
that is already there.

When your change is in, reply in each thread with `$T pr comment --slug northwind
--pr 6453 --reply-to <threadId> --body-file <file>`. Leave a reviewer's thread
for the reviewer to resolve, because closing it hides the ask from their queue.

When your change renamed or dropped something the description names, fix the
description in the same pass with `$T pr describe --slug northwind --pr 6453
--body-file <file>`.

Reviewer feedback often arrives in chat rather than on the pull request. Reply
where the feedback lives. Answering on the pull request makes a thread where
every comment is yours.

## Gates

- The deploy-gated state is the one state you set on a word, not on a bucket.
  The project's `notes.md` names the word: on most projects it is the user
  saying the build is on the test environment. Then run
  `$T state <ticket> --gate`. `tk` tests no trigger, so a run that guesses one
  writes the state early.
- Merged is not deployed. When a tester says a fix does not work, check that the
  pull request merged and that the environment holds that build, before you read
  the code again.
- An `owned-elsewhere` or `split` ticket stays with the other owner until their
  part lands.

## Batch mode

```bash
$T mine
```

One answer across every configured project: `tickets` and `failed`. `--slug`
narrows it, and repeats. Exit 1 means at least one project did not answer, and
the tickets it did read are still in `tickets`. Work those, and tell the user
which project failed and why.

Each row carries its own `slug`, so work the tickets one at a time through steps
2 to 7. Print the pull request list at the end, one block per pull request, url
then title, with a blank line between blocks and nothing around it. That block is
what the user pastes into chat.
