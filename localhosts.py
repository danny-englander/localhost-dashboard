#!/usr/bin/env python3
"""Tiny landing page listing every local dev server that's listening.

Run:  python3 localhosts.py      then open http://localhost:9999
Press Refresh (or reload the page) to rescan. Add ?all=1 to include non-dev apps.
"""
import getpass, html, os, re, subprocess, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = 9999
DEV_COMMANDS = re.compile(r"^(node|python|python3|Python|ruby|php|deno|bun|java|go|uvicorn|gunicorn|hugo|jekyll|caddy|nginx|httpd|vite|next-serv)", re.I)


def listening():
    out = subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpcn"],
                         capture_output=True, text=True).stdout
    found, pid, cmd = {}, None, None
    for line in out.splitlines():
        tag, val = line[0], line[1:]
        if tag == "p": pid = val
        elif tag == "c": cmd = val
        elif tag == "n":
            port = int(val.rsplit(":", 1)[1])
            found.setdefault(port, (pid, cmd))
    return found


def cwds(pids):
    if not pids: return {}
    out = subprocess.run(["lsof", "-a", "-d", "cwd", "-p", ",".join(pids), "-Fpn"],
                         capture_output=True, text=True).stdout
    res, pid = {}, None
    for line in out.splitlines():
        if line[0] == "p": pid = line[1:]
        elif line[0] == "n": res[pid] = line[1:]
    return res


def probe(port):
    """Fetch the home page. Returns (ok, title): ok means it answered with a real page."""
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/", timeout=2) as r:
            text = r.read(65536).decode("utf-8", "replace")
            m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
            return True, html.unescape(m.group(1).strip()) if m else ""
    except Exception:
        return False, ""


def branch(folder):
    """The git branch checked out in folder, a short commit id if detached, or "" outside a repo."""
    if not folder or folder == "/":
        return ""
    def git(*args):
        r = subprocess.run(["/usr/bin/git", "-C", folder, *args], capture_output=True, text=True, timeout=2)
        return r.stdout.strip() if r.returncode == 0 else ""
    try:
        return git("branch", "--show-current") or (f"detached at {sha}" if (sha := git("rev-parse", "--short", "HEAD")) else "")
    except Exception:
        return ""


def num_mark(n):
    """A row number in the kit's accent number circle. Circles hold two digits; past 99, plain."""
    return f'<span class="num-circle num-circle--accent"><span>{n:02d}</span></span>' if n < 100 else str(n)


def page(show_all):
    ports = listening()
    dirs = cwds(sorted({p for p, _ in ports.values()}))
    home = os.path.expanduser("~")
    candidates = [p for p in sorted(ports) if p != PORT
                  and (show_all or DEV_COMMANDS.match(ports[p][1] or ""))]
    with ThreadPoolExecutor(16) as pool:
        results = dict(zip(candidates, pool.map(probe, candidates)))
        folders = sorted({dirs.get(ports[p][0], "") for p in candidates})
        branches = dict(zip(folders, pool.map(branch, folders)))
    rows = []
    for port in candidates:
        pid, cmd = ports[port]
        ok, title = results[port]
        if not ok and not show_all:
            continue
        folder = dirs.get(pid, "")
        name = "/".join(folder.rstrip("/").split("/")[-2:]) if folder not in ("", "/") else cmd
        b = branches.get(folder, "")
        meta = "<br>".join(html.escape(x) for x in ("" if ok else "No page", f"localhost:{port}",
                                       f"on {b}" if b else "", cmd,
                                       folder.replace(home, "~")) if x)
        rows.append(f"""<li class="row server">
  <span class="num small muted server-num">{num_mark(len(rows) + 1)}</span>
  <span class="server-body">
    <a class="title server-link" href="http://localhost:{port}" target="_blank" rel="noopener">{html.escape(title or name)}<span class="sr-only"> (opens in a new tab)</span></a>
    <span class="row-meta muted server-meta">{meta}</span>
  </span>
  <span class="server-end">
    <a class="row-arrow" href="http://localhost:{port}" target="_blank" rel="noopener" tabindex="-1" aria-hidden="true"><svg viewBox="0 0 20 20"><path d="M3 10h13M11 5l5 5-5 5" /></svg></a>
  </span>
</li>""")
    count = f"{len(rows)} running" if rows else "Nothing running"
    return f"""<!doctype html>
<html lang="en" data-theme="dark" data-accent="azure">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local servers</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="preload" href="/swiss/fonts/OverusedGrotesk-VF.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/swiss/kit/theme.css">
<link rel="stylesheet" href="/site.css">
</head>
<body>
<a class="skip-link" href="#main">Skip to main content</a>
<main id="main" tabindex="-1" class="page">
  <header class="page-title"><h1 class="page-title-text">Local servers on {html.escape(getpass.getuser())}</h1></header>
  <section class="rule-thick servers" aria-labelledby="servers">
    <div class="servers-head">
      <a class="btn-outline btn-outline--tertiary refresh" href="{"/?all=1" if show_all else "/"}">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>
        Refresh
      </a>
      {f'<p class="num small muted servers-range">01–{len(rows):02d}</p>' if rows else ""}
      <h2 class="h2" id="servers">{count}</h2>
    </div>
    <ul class="servers-list">{"".join(rows)}</ul>
  </section>
</main>
</body>
</html>"""


STATIC = os.path.dirname(os.path.abspath(__file__))
TYPES = {".css": "text/css; charset=utf-8", ".woff2": "font/woff2", ".svg": "image/svg+xml",
         ".txt": "text/plain; charset=utf-8"}


def static_file(path):
    """Serve site.css, favicon.svg and the kit files under swiss/, nothing else."""
    full = os.path.realpath(os.path.join(STATIC, path.lstrip("/")))
    allowed = full in (os.path.join(STATIC, "site.css"), os.path.join(STATIC, "favicon.svg")) \
        or full.startswith(os.path.join(STATIC, "swiss") + os.sep)
    if not allowed or not os.path.isfile(full):
        return None
    with open(full, "rb") as f:
        return TYPES.get(os.path.splitext(full)[1], "application/octet-stream"), f.read()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            ctype, data = "text/html; charset=utf-8", page("all" in parse_qs(url.query)).encode()
        else:
            found = static_file(url.path)
            if not found:
                self.send_error(404)
                return
            ctype, data = found
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a): pass


if __name__ == "__main__":
    print(f"Listing local servers at http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
