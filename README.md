# localhosts

A tiny dark-mode landing page that lists every local dev server running on this Mac, with a clickable link to each.

Run `python3 localhosts.py`, then open **http://localhost:9999**.

## What it shows

- Each server that's listening and answers with a real page, labeled with the page's own title and the project folder it was started from.
- The git branch checked out in that folder ("on main"), when the folder is in a git repository.
- Servers that return an error (like "not found") or don't answer within 2 seconds are hidden.
- The page refreshes itself every 5 seconds. To change that, edit `content=5` in `localhosts.py`.
- To also see non-dev apps (Adobe, Control Center, etc.) and the servers with no page, open **http://localhost:9999/?all=1**.

It only checks common dev tools: Node, Python, Ruby, PHP, Deno, Bun, Java, Go, Hugo, Jekyll, Caddy, nginx and similar. To add another, edit `DEV_COMMANDS` in `localhosts.py`.

No dependencies: just Python 3 and macOS's built-in `lsof`. See "Requirements".

## Styling

The page uses the [Swiss Minimal](../swiss-minimal) design kit in dark mode with the azure accent: a page title, then the kit's list row section, numbered with accent number circles.

- `swiss/kit/theme.css` and `swiss/kit/fonts.css`: copied from the kit, unchanged. The kit runs as plain CSS here, with no Tailwind.
- `swiss/fonts/`: Overused Grotesk and Source Code Pro, each with its license (SIL OFL 1.1).
- `site.css`: the list row grid, which the kit writes with Tailwind classes, written out with the kit's tokens.
- `favicon.svg`: the kit's square favicon.

To pick up a newer version of the kit, copy those two CSS files and the fonts over again.

## Running it

From the repository's folder:

```bash
python3 localhosts.py
```

Then open **http://localhost:9999**. It runs until you press Ctrl+C or close the terminal. After editing `localhosts.py`, stop it and start it again to see the change.

To use a different port, change `PORT` at the top of `localhosts.py`.

## Requirements

- **macOS.** It should mostly work on Linux, as it relies on `lsof`, which you may need to install, but it hasn't been tested there. It doesn't work on Windows.
- **Python 3.8 or newer.** It uses only Python's standard library, so there's nothing to install.
- **Git**, for the branch line. It calls `/usr/bin/git`, which macOS offers to install with the Xcode command line tools the first time it's used. Without git, the page still works and leaves the branch line out.
- **Port 9999 free.** Otherwise it stops with "Address already in use".
