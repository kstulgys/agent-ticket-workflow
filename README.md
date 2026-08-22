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
transcript. No verb prints a secret.

## The method

Each phase defers to the Superpowers skill that governs it. A vague ticket goes
to `brainstorming` before any code. A bug goes to `systematic-debugging`, so the
fix follows a cause. The change itself goes to `test-driven-development`. A
reviewer's comment goes to `receiving-code-review`. `SKILL.md` holds the full
table.

## Requirements

- Python 3.11 or later. Standard library only, no dependencies, no virtualenv.
- `git`.
- The Superpowers plugin. `scripts/setup.sh` installs it.
- `curl`, for the setup wizard only.

## Install

Clone into your skills directory. The directory name must match the skill name,
which is the same as the repository name:

```bash
git clone https://github.com/kstulgys/agent-ticket-workflow.git \
  ~/.claude/skills/agent-ticket-workflow
cd ~/.claude/skills/agent-ticket-workflow
```

Then run the wizard. It installs the Superpowers plugin, then walks you through
one provider at a time and writes each token to `secrets.env`:

```bash
scripts/setup.sh
```

Run one step on its own with `scripts/setup.sh superpowers`, or `azure`, `jira`,
`github`, or `figma`.

## Set up a project

Copy an example and edit it:

```bash
mkdir -p ~/.claude/ticket-workflow/projects/myproject
cp examples/projects/northwind/config.json \
  ~/.claude/ticket-workflow/projects/myproject/
```

`examples/projects/northwind` is an Azure Boards tracker with an Azure Repos
host. `examples/projects/globex` is a Jira tracker with a GitHub host, which
shows the two provider case. `references/profiles.md` documents every key.

Then check it:

```bash
scripts/tk doctor
```

`doctor` reads each provider, then reads a real ticket through it. Two calls,
because they fail apart: a token can name the right account and still read no
ticket. Exit 0 means every provider answered. Exit 1 prints one row per provider
with its own `ok`, and a `fix` command per gap.

## Verbs

```
tk doctor                     every provider and every project
tk resolve <id|key|url>       which project owns this ticket
tk mine                       tickets assigned to you
tk show <id>                  the ticket, its comments and its attachments
tk comment <id>               post a comment
tk state <id>                 set the state and the owner
tk assign <id>                set the owner
tk pr <create|threads|comment|describe|attach>
tk figma <url>                render a frame, or list a file
tk git -- <args>              git with the credential in the environment
```

Exit codes: 0 done, 1 error, 2 only when a ticket matches more than one project
and a human must choose.

## Tests

```bash
python3 -m unittest discover -s tests -t tests
```

388 tests, no network. Every provider response is a fixture, and a test that
queues one asserts the queue drained, so a call the code never makes fails the
test.

## References

- `references/profiles.md` — every profile key
- `references/verification.md` — how to prove a fix
- `references/writing-comments.md` — what a ticket comment says
- `references/figma.md` — reading a design a ticket links to
- `references/jira-cookie-fallback.md` — when an org blocks Jira API tokens

## License

MIT. See `LICENSE`.
