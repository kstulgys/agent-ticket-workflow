# Reading a design

A figma link in a ticket, a comment, or a pull request thread is an
instruction. Pull the frame. You get the picture and the exact values, so
"align with the design" stops being guesswork over a compressed screenshot.

`--render` writes the png. Read that file. Actually look at it. A node the file
no longer holds answers a null `path` and a sentence under `error`, so read the
answer before you open the file.

`--specs` prints one row per node: size, radius, fill, stroke, padding, gap,
layout, font as `family weight size/line-height`, and the text itself.

`--specs` on a url with no `node-id` prints the file instead: one row per page,
then one row per node on it, with the page name under `page` and a ready link
under `url`. Pass that link back to this verb to read the node. A row of type
`SECTION` or `GROUP` is a container, and a real file keeps the breakpoint
frames in one, so read that row when no frame on the page carries the name you
want.

The endpoint that holds the brand token names, `variables/local`, needs an
Enterprise plan. Mapping a measured value back to the project's own token is
your step, and `notes.md` names where those tokens live.

## Comparing against the implementation

Measure your side with the same rigour, then diff property by property: radius,
background, text colour, font weight, font size, line height, separator colour,
padding, gaps, button height. Report the diff as a table. That is what makes a
reviewer able to answer.

A computed font weight is not proof that the weight renders. A family that ships
Light, Regular, and Bold only will render 500 as 400. Prove it two ways:

```js
document.fonts.check('700 24px Navigo');
const c = document.createElement('canvas').getContext('2d');
c.font = '700 24px Navigo, sans-serif';
c.measureText('Uitvoeringen').width;   // compare with the figma text node width
```

## Traps

- `--render` refuses a link with no `node-id`. Copy the link from the frame
  itself, not from the address bar of the file.
- A ticket usually links one breakpoint, and the component has a sibling frame
  for the other. Reviewing one is how a desktop regression ships. Run `--specs`
  on the file url, find the sibling by name, then read it through the `url` in
  that row. A `Menu` beside a `Menu - mobile` is what that pair looks like.
- A frame can be superseded by a later decision. Before you "fix" something the
  frame shows and nobody reported, search the backlog for it.
- Match what the reviewer asked for first. Report the other deviations you found
  and let them pick. Keep the diff narrow.
