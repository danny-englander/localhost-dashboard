# localhosts

A tiny dark-mode landing page that lists every local dev server running on this Mac, with a clickable link to each.

Open **http://localhost:9999**

## What it shows

- Each server that's listening and answers with a real page, labeled with the page's own title and the project folder it was started from.
- The git branch checked out in that folder ("on main"), when the folder is in a git repository.
- Servers that return an error (like "not found") or don't answer within 2 seconds are hidden.
- The page refreshes itself every 5 seconds. To change that, edit `content=5` in `localhosts.py`.
- To also see non-dev apps (Adobe, Control Center, etc.) and the servers with no page, open **http://localhost:9999/?all=1**.

It only checks common dev tools: Node, Python, Ruby, PHP, Deno, Bun, Java, Go, Hugo, Jekyll, Caddy, nginx and similar. To add another, edit `DEV_COMMANDS` in `localhosts.py`.

No dependencies: just Python 3 and macOS's built-in `lsof`.

## Styling

The page uses the [Swiss Minimal](../swiss-minimal) design kit in dark mode with the azure accent: a page title, then the kit's list row section, numbered with accent number circles.

- `swiss/kit/theme.css` and `swiss/kit/fonts.css`: copied from the kit, unchanged. The kit runs as plain CSS here, with no Tailwind.
- `swiss/fonts/`: Overused Grotesk and Source Code Pro, each with its license (SIL OFL 1.1).
- `site.css`: the list row grid, which the kit writes with Tailwind classes, written out with the kit's tokens.
- `favicon.svg`: the kit's square favicon.

To pick up a newer version of the kit, copy those two CSS files and the fonts over again.

## Starts automatically

A login item starts it when you log in and restarts it if it crashes:

`~/Library/LaunchAgents/com.localhosts.dashboard.plist`

Output and errors go to `~/Library/Logs/localhosts.log`.

Restart it (after editing `localhosts.py`):

```bash
launchctl kickstart -k gui/$(id -u)/com.localhosts.dashboard
```

Turn it off:

```bash
launchctl bootout gui/$(id -u)/com.localhosts.dashboard
```

Turn it back on:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.localhosts.dashboard.plist
```

To remove it for good, turn it off and then delete the `.plist` file.

## Running it by hand

Turn off the login item first (it uses the same port), then:

```bash
python3 localhosts.py
```

To use a different port, change `PORT` at the top of `localhosts.py`.
