# Proving a change

Every proof below is an observation you can paste. A claim with no output
behind it is not proof.

## Pure logic

Run the real module in a throwaway harness. Import it, mock what it touches,
call it, and assert the documented cases. Paste the counts you got.

## Layout and styling

Measure it. Numbers, not vibes.

Open the component in the project's isolated renderer, then read
`getBoundingClientRect()` per element. Equal `x` and `width` prove one column.
A matching centre `y` proves a label is centred on its input. Numbers make the
pull request comment concrete.

Sweep both sides of each breakpoint, for example 767 and 768.

A media query keys off the viewport, not the component. To reproduce a component
that is narrow inside a wide page, set a desktop viewport and constrain the
container instead of shrinking the window. Shrinking the window tests a
different breakpoint and reports the mobile layout as a regression.

## A deployed change

Exercise it on the deployment the pull request produced. When the environment
sits behind access protection, the profile's `preview.bypass_env` names the
variable that holds the bypass value. `tk` has no verb that resolves it, and
`secrets.env` stays closed, so ask the user for the value. Send that value as a
request header, and keep it out of every url, log line, screenshot, and
comment. A bypass value in a url reaches the browser history and the server
log, and a pasted one reaches the ticket for ever.

Corroborate two ways. Grep the served bundle for a marker your change
introduced, which proves the build shipped. Then run the deployed computation
in the page against the real environment, which proves the values.

## A visual change

The screenshot is the proof. Numbers convince you, and a picture convinces the
reviewer.

Capture the component on both sides of the breakpoint, compose the shots into
one labelled image, then attach it:

```bash
$T pr attach --slug <slug> --pr <id> --file /tmp/panel.png
```

The answer holds a ready markdown line under `markdown`. Put that line in the
pull request description with `$T pr describe`, and in a thread with `$T pr
comment`. The description is never collapsed. Caption what each panel shows.
Call out anything in the shot that is not your change, so it reads as context
and not as a regression.

When a faithful render is out of reach, describe the change precisely in words.
A misleading render is worse than a sentence, and the pull request does not wait
for the picture.
