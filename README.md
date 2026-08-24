# agent-ticket-workflow

An agent skill that works a ticket end to end. It reads the ticket, classifies
the work that remains, ships the fix, opens the pull request, then comments on
the ticket and routes it.

One routine covers three trackers: Azure Boards, Jira, and GitHub Issues. The
pull request host can be a different provider from the tracker, so an Azure
Boards ticket can ship through GitHub.

Built on the [Superpowers](https://github.com/obra/superpowers) methodology.

## Why this exists

An agent that works a ticket without a routine tends to do the same thing every
time: read the ticket, guess a fix, open a pull request, then learn in review
that the cause was somewhere else. It also leaves a batch half done, because
nothing says what "done" means for a ticket it decided not to fix.

This skill answers both. Every ticket gets a bucket, a comment, and its routing
applied. A bucket is one of four names for the work that remains, and it decides
the state, the owner, and what the comment says.

## Use cases

Each case starts with what you type. The skill picks the mode and the phases
from there.

### One ticket, start to finish

> work 59644

The agent finds which project owns 59644, then reads the ticket whole:
description, every comment, the attachments, and any child task that names the
actual mechanism. It traces the cause, writes the failing test, makes the
change, runs that project's verify gate, and opens the pull request with the
ticket linked and the profile's reviewer added. Then it comments and applies the
routing for `fixable-here`, which on the northwind example is In Progress and
assigned to you.

You get a pull request url. Merging stays your call.

### The fix belongs to another team

> DIST-4471

The trace ends outside this repo. The API never sends the field, so there is
nothing here to change, and no branch and no pull request. The bucket is
`owned-elsewhere`, and the comment names the concrete fix: the mapper, the
field, or the flag. Routing follows the profile. Globex moves the ticket to To
Do and hands it to the backend owner. Northwind writes no state, so the comment
carries the whole handover. On a GitHub tracker a bucket state is a label, so
the routing shows on the ticket itself.

The investigation leaves your session with the ticket. An `owned-elsewhere`
ticket without that comment counts as unfinished.

### The ticket cannot be answered yet

> look at 61002

The ticket says the checkout wording is wrong and never says what it should be.
No comment supplies it either. The agent does not invent user-facing copy, and
copy in a language it cannot verify is always the product owner's to write. The
bucket is `needs-clarification`, and the comment asks one question: which
string, which screen, which language.

### Everything assigned to you

> work on the tickets assigned to me

`tk mine` answers once for every configured project, so an Azure Boards ticket
and a Jira ticket arrive in the same list. Each row carries its own project
slug, so each ticket uses its own branch pattern, states, and owners.
Independent tickets can run at the same time instead of one after another.

The run ends with one block per pull request, url then title, with nothing
around it. Paste that where you need it. A project that did not answer is named
with its reason, so you always know why a list is short.

### Review comments came back

> 59644 has comments

This is resume mode. The threads on the pull request, plus any ticket comment
newer than your last update, are the whole spec for the pass. The description is
already implemented on that branch, so re-reading it concludes "already done"
and wastes the run. The agent commits onto the branch that is already there,
replies in each thread, and leaves the reviewer's thread open, because resolving
it hides the ask from their queue. When the change renamed something the
description names, the description gets fixed in the same pass.

### A build reached the test environment

> the tickets are on TST

That sentence is the only thing that moves a ticket to the deploy-gated state.
`tk state <id> --gate` writes it. Nothing infers the step from a merge, so a
ticket never reaches a tester's queue before the build does.

The reverse case is a tester saying the fix does not work. Then the first check
is the pull request and the environment, not the code. Merged is not deployed.

### The ticket links a Figma frame

> 58120

A Figma url in a ticket is an instruction to read the frame. The agent renders
it and prints resolved values, hex, pixels, font sizes, then builds against
those numbers instead of eyeballing a screenshot. Mapping a value back to a
brand token stays a manual step, because the Figma variables endpoint is
Enterprise only.

### A Jira ticket that ships through GitHub

The tracker and the pull request host are separate blocks in one profile, so
they do not have to match. `examples/projects/globex` reads DIST keys from Jira
and opens the pull request on GitHub. The phases do not change.

## What it never does

- Merge. It opens the pull request, reports the url, and stops there.
- Read a ticket or a design through a browser. Every read is an API call with a
  token you minted, and the token lives in one file that `tk` reads itself. It
  never reads your browser session, your cookie store, or your keyring.
- Invent a behaviour the ticket does not state. A missing string goes back as
  one question, and user-facing copy in another language always does.
- Guess that a build reached the test environment. The deploy-gated state moves
  on your word, never on a merge.
- Resolve a reviewer's thread. It replies and leaves the thread open, because
  closing it hides the ask from that reviewer's queue.
- Link a work item type the profile refuses. A merge completes every linked
  item, and a bug has to reach its test pass instead.

## How it works

Two parts, split on purpose.

`SKILL.md` holds the routine in prose. It has eight numbered phases and three
modes. It never names an endpoint or a body format.

`scripts/tk` holds every API call. So a provider trap is a guard in code with a
test, not a warning in prose that an agent may skip. It prints JSON on stdout.
Every failure prints a fixed code under `error` and a sentence under `message`,
so a caller switches on the code and not on the prose.

Project facts live outside the repository, in
`~/.claude/ticket-workflow/projects/<slug>/`. `config.json` holds the machine
facts, such as the branch pattern and the state each bucket maps to. `notes.md`
holds the knowledge an agent needs but a schema cannot express. Nothing about
your projects is ever committed here.

Tokens live in `~/.claude/ticket-workflow/secrets.env`, mode 0600. `tk` reads
that file itself, so a token never reaches the terminal, a log, or an agent
transcript. Every message `tk` prints goes through a scrubber that masks both
the value in that file and the encoded header built from it. The one exception
is `tk git`, which passes git's own output through untouched, so do not run a
command that prints configuration through it, such as `git config --list`.

## The method

Each phase defers to the Superpowers skill that governs it. A vague ticket goes
to `brainstorming` before any code. A bug goes to `systematic-debugging`, so the
fix follows a cause. The change itself goes to `test-driven-development`. A
reviewer's comment goes to `receiving-code-review`. `SKILL.md` holds the full
table.

## Requirements

- Python 3.11 or later. `tk` itself is standard library only, with no
  dependencies and no virtualenv.
- `git`.
- The Superpowers plugin. `scripts/setup.sh` installs it.
- `curl`, for the setup wizard only.

## Install

Clone into your skills directory. The directory name must match the skill name,
which is the same as the repository name:

```bash
git clone https://github.com/kstulgys/agent-ticket-workflow.git \
  ~/.claude/skills/agent-ticket-workflow
```

That is the whole install. There is no setup step, no token to mint yet, and no
config file to write. The skill asks for a credential the first time one is
refused, and for one provider only.

### Or paste this to your agent

```
Install the agent-ticket-workflow skill for me.

1. Clone https://github.com/kstulgys/agent-ticket-workflow into
   ~/.claude/skills/agent-ticket-workflow. The directory name has to be exactly
   agent-ticket-workflow, because the skill name and the directory name must
   match.
2. From that directory, run: python3 -m unittest discover -s tests -t tests
   Tell me the result.
3. Do not mint any token, do not run scripts/setup.sh, and do not write any
   config file or project profile. The skill asks for what it needs when it
   needs it.
4. Then tell me it is ready, and that I start a job by typing: work on <ticket>
```

## First run

Open the repository the ticket belongs to and type:

```
work on 5438
```

With no profile for that project, the agent reads the git remote first. The
remote names the provider, the owner, the repository, and on Azure DevOps the
organization and the project. It asks you for the tracker only when the remote
cannot name it, and that question is a select of three: GitHub, Azure Boards,
Jira. Then it runs one wizard stage for that provider's token, and that stage
writes the value to `secrets.env` itself. You never paste a token into the chat.
Last, it writes the profile with `tk init`.

Three questions are left, and no machine can answer them:

- The verify gate. The exact commands that prove a change in this repository,
  and what a clean run prints. This one costs a run when it stays empty, because
  a fix then ships on a claim instead of on evidence.
- The board column for each bucket. Your board's own state names.
- The state a tested build reaches, and the word that releases it.

The agent asks for each one the first time it is needed, not before.

Your profile lives in `~/.claude/ticket-workflow/projects/<slug>/`, outside this
repository. Nothing about your projects is ever committed here.

`examples/projects/northwind` is an Azure Boards tracker with an Azure Repos
host. `examples/projects/globex` is a Jira tracker with a GitHub host, which
shows the two provider case. Both are worked examples for a profile written by
hand, and `references/profiles.md` documents every key.

To set a provider up before your first ticket, run `scripts/setup.sh <provider>`
for the one you want, and `scripts/tk doctor` to see what is configured.

## Verbs

```
tk doctor                     every provider and every project
tk detect                     what the working directory knows
tk init --slug S --tracker T  write a project profile
tk resolve <id|key|url>       which project owns this ticket
tk mine                       tickets assigned to you
tk show <id>                  the normalised ticket, with its comments
tk comment <id>               post a comment
tk state <id>                 set the state and the owner
tk assign <id>                set the owner
tk pr <create|threads|comment|describe|attach>
tk figma <url>                render a frame, or list a file
tk git --slug S -- <args>     git with the credential in the environment
```

Exit codes: 0 done, 1 error, 2 only when a ticket matches more than one project
and a human must choose.

## Tests

```bash
python3 -m unittest discover -s tests -t tests
```

483 tests, no network. Every provider response is a fixture, and a test that
queues one asserts the queue drained, so a call the code never makes fails the
test.

## References

- `references/profiles.md` — every profile key
- `references/verification.md` — how to prove a fix
- `references/writing-comments.md` — what a ticket comment says
- `references/figma.md` — reading a design a ticket links to

## License

MIT. See `LICENSE`.
