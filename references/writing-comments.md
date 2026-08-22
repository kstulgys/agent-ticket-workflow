# Writing a comment or a pull request body

Write for a reader with none of your session context. Lead with the point. One
idea per paragraph. Two or three sentences is the target length.

Give the result, never the mechanics. The resulting payload, the before and
after, the behaviour. How you drove the browser stays in your notes.

Bad, because it is opaque to a reviewer:

> Installed a window.fetch spy and invoked the deployed form's onSubmit through
> its React fiber with a dummy captcha token.

Good, because it states what changed:

> Tested on the Hillcrest preview. The submit payload now carries the tracking
> values inside `row-hidden`, which were `*-UNKNOWN` before. No top-level
> copies.

Then the payload.

## Per bucket

| Bucket | The comment carries |
|---|---|
| `fixable-here` | what changed, and the pull request link |
| `owned-elsewhere` | why it belongs to the other owner, and the concrete fix: the field, the mapper, or the flag |
| `split` | the part that shipped, and the part that remains |
| `needs-clarification` | one specific question |

An `owned-elsewhere` ticket handed over without that comment is unfinished work.
The comment carries the whole investigation to somebody who was not in it.

## Language

Write in the team's working language. Quote user-facing copy in its own language
verbatim when the ticket turns on that copy, and keep the explanation around it
in the team's language.

## Keep the record true

When a later change makes an earlier comment wrong, correct that comment. `tk`
has no edit verb, so edit or delete the comment in the web UI. A second comment
that names the one it replaces also works. Two contradictory threads leave the
reader to guess which one holds.
