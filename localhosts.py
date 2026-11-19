#!/usr/bin/env python3
"""Tiny landing page listing every local dev server that's listening.

Run:  python3 localhosts.py      then open http://localhost:9999
Press Refresh (or reload the page) to rescan. Add ?all=1 to include non-dev apps.
With ~/.config/localhosts/projects.json, a Projects section starts and stops your dev servers.
"""
import getpass, html, json, os, pwd, re, signal, subprocess, threading, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = 9999
DEV_COMMANDS = re.compile(r"^(node|python|python3|Python|ruby|php|deno|bun|java|go|uvicorn|gunicorn|hugo|jekyll|caddy|nginx|httpd|vite|next-serv)", re.I)
CONFIG = os.path.expanduser("~/.config/localhosts/projects.json")
LOGS = os.path.expanduser("~/Library/Logs/localhosts")
# Screenshot types the page will show. No SVG: opened on its own, an SVG could run script as this dashboard.
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
               ".gif": "image/gif", ".avif": "image/avif"}


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


def glyph(char):
    """An icon drawn from the font itself (▶ ■ ● ↻ …), hidden from screen readers."""
    return f'<span class="glyph" aria-hidden="true">{char}</span>'


# ---------- Projects: dev servers listed in projects.json, started and stopped from the page ----------

started = {}                 # slug -> Popen, for the projects this dashboard started
lock = threading.Lock()


def load_projects():
    """(projects, problems). projects is None when there's no projects.json; problems is a list of messages."""
    if not os.path.exists(CONFIG):
        return None, []
    try:
        with open(CONFIG) as f:
            data = json.load(f)
    except Exception as e:
        return [], [f"Couldn't read {CONFIG.replace(os.path.expanduser('~'), '~')}: {e}"]
    items = data.get("projects") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return [], ['projects.json should hold a "projects" list.']
    projects, problems, slugs = [], [], set()
    for i, p in enumerate(items, 1):
        if not isinstance(p, dict) or not all(isinstance(p.get(k), str) and p[k].strip() for k in ("dir", "command")):
            problems.append(f'Project {i} needs a "dir" and a "command".')
            continue
        folder = os.path.realpath(os.path.expanduser(p["dir"].strip()))
        port = p.get("port")
        if port is not None and not (isinstance(port, int) and 0 < port < 65536):
            problems.append(f'Project {i}: "port" should be a number like 4321.')
            port = None
        name = p.get("name") if isinstance(p.get("name"), str) and p["name"].strip() else os.path.basename(folder)
        slug = base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
        n = 2
        while slug in slugs:
            slug, n = f"{base}-{n}", n + 1
        slugs.add(slug)
        shot = p.get("screenshot")
        if shot is not None and not (isinstance(shot, str) and shot.strip()):
            problems.append(f'Project {i}: "screenshot" should be the path to an image.')
            shot = None
        elif shot:
            # Relative to the folder projects.json is in, so screenshots can sit beside it
            shot = os.path.realpath(os.path.join(os.path.dirname(CONFIG), os.path.expanduser(shot.strip())))
            if os.path.splitext(shot)[1].lower() not in IMAGE_TYPES:
                problems.append(f'Project {i}: the screenshot should be a PNG, JPEG, WebP, GIF or AVIF file.')
                shot = None
        projects.append({"slug": slug, "name": name.strip(), "dir": folder, "command": p["command"].strip(),
                         "port": port, "screenshot": shot})
    return projects, problems


def log_path(slug):
    return os.path.join(LOGS, f"{slug}.log")


def project_ports(project, ports, dirs):
    """The ports a project is listening on. With a "port", just that one. Without, dev servers
    (DEV_COMMANDS) started in its folder: not, say, an editor or an AI agent open in the same folder,
    which Stop would otherwise end too."""
    if project["port"]:
        return [project["port"]] if project["port"] in ports else []
    return sorted(port for port, (pid, cmd) in ports.items()
                  if dirs.get(pid) == project["dir"] and DEV_COMMANDS.match(cmd or ""))


def find_nvmrc(folder):
    while True:
        if os.path.isfile(os.path.join(folder, ".nvmrc")):
            return True
        parent = os.path.dirname(folder)
        if parent == folder:
            return False
        folder = parent


def start_project(project):
    """Run the project's command in its folder, in your login shell, so PATH, nvm and the like are set
    up as in a terminal. With an .nvmrc in the folder or above, `nvm use` runs first. Output goes to its log."""
    with lock:
        proc = started.get(project["slug"])
        if proc and proc.poll() is None:
            return
        if not os.path.isdir(project["dir"]):
            raise FileNotFoundError(project["dir"])
        os.makedirs(LOGS, exist_ok=True)
        script = project["command"]
        if find_nvmrc(project["dir"]):
            script = f"type nvm >/dev/null 2>&1 && nvm use; {script}"
        shell = pwd.getpwuid(os.getuid()).pw_shell or "/bin/zsh"
        with open(log_path(project["slug"]), "ab") as log:
            log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')}  {project['command']}\n".encode())
            log.flush()
            started[project["slug"]] = subprocess.Popen(
                [shell, "-l", "-i", "-c", script], cwd=project["dir"], stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def stop_project(project):
    """Stop what the dashboard started (the shell and everything it ran), or, if it was started some
    other way, the processes listening on the project's ports."""
    with lock:
        proc = started.pop(project["slug"], None)
    if proc and proc.poll() is None:
        for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 2)):
            try:
                os.killpg(proc.pid, sig)
                proc.wait(timeout=wait)
                break
            except subprocess.TimeoutExpired:
                continue
            except ProcessLookupError:
                break
        return
    ports = listening()
    dirs = cwds(sorted({p for p, _ in ports.values()}))
    for pid in {ports[port][0] for port in project_ports(project, ports, dirs) if port != PORT}:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def project_rows(projects, ports, dirs, query):
    home = os.path.expanduser("~")
    rows = []
    for project in projects:
        slug = project["slug"]
        live = [p for p in project_ports(project, ports, dirs) if p != PORT]
        proc = started.get(slug)
        alive = proc is not None and proc.poll() is None
        if live:
            state = f'{glyph("●")} Running on ' + ", ".join(f"localhost:{p}" for p in live)
        elif alive:
            state = f'{glyph("◐")} Starting. Press Refresh in a moment.'
        elif proc is not None:
            state = f'{glyph("×")} Stopped with exit code {proc.returncode}. See the log.'
        elif not os.path.isdir(project["dir"]):
            state = f'{glyph("×")} Folder not found'
        else:
            state = f'{glyph("●")} Stopped'
        name = html.escape(project["name"])
        title = (f'<a href="http://localhost:{live[0]}" target="_blank" rel="noopener">{name}'
                 f'<span class="sr-only"> (opens in a new tab)</span></a>' if live else name)
        shot, shot_html = project["screenshot"], ""
        if shot and os.path.isfile(shot):
            # The file's time in the address, so a new screenshot shows up without a stale cached copy
            shot_html = (f'<img class="project-shot" src="/screenshot/{slug}?v={int(os.path.getmtime(shot))}" '
                         f'alt="" loading="lazy" decoding="async">')
        details = "<br>".join([f'<code>{html.escape(project["command"])}</code>',
                               html.escape(project["dir"].replace(home, "~"))]
                              + ([f'{glyph("×")} Screenshot not found: {html.escape(shot.replace(home, "~"))}']
                                 if shot and not shot_html else []))
        action = "stop" if live or alive else "start"
        button = (f'<form method="post" action="/{action}/{slug}{query}">'
                  f'<button class="btn-outline btn-outline--tertiary" type="submit" aria-label="{action.title()} {name}">'
                  f'{glyph("■" if action == "stop" else "▶")} {action.title()}</button></form>')
        log = (f'<a class="btn-outline btn-outline--tertiary" href="/log/{slug}" target="_blank" rel="noopener" aria-label="Log for {name} (opens in a new tab)">'
               f'Log<span class="ext-arrow" aria-hidden="true">↗</span></a>' if os.path.exists(log_path(slug)) else "")
        # The kit's card: a 2px rule, the number beside the title, then the summary and the buttons
        rows.append(f"""<li class="card project">
  <span class="label num muted">{len(rows) + 1:02d}</span>
  <h3 class="card-title">{title}</h3>
  <p class="card-summary project-state" data-state="{"on" if live else "busy" if alive else "off"}">{state}</p>
  <p class="card-summary project-details">{details}</p>
  {shot_html}
  <div class="project-actions">{button}{log}</div>
</li>""")
    return rows


def page(show_all):
    ports = listening()
    dirs = cwds(sorted({p for p, _ in ports.values()}))
    home = os.path.expanduser("~")
    query = "?all=1" if show_all else ""
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

    projects, problems = load_projects()
    projects_section = ""
    if projects is not None:
        prows = project_rows(projects, ports, dirs, query)
        notes = "".join(f'<p class="row-meta muted project-problem">{glyph("×")} {html.escape(m)}</p>' for m in problems)
        projects_section = f"""
  <section class="rule-thick servers projects" aria-labelledby="projects">
    <div class="servers-head">
      {f'<p class="num small muted servers-range">01–{len(prows):02d}</p>' if prows else ""}
      <h2 class="h2" id="projects">Projects</h2>
    </div>
    {notes}
    <ul class="card-grid">{"".join(prows)}</ul>
  </section>"""

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
      <a class="btn-outline btn-outline--tertiary refresh" href="/{query}">{glyph("↻")} Refresh</a>
      {f'<p class="num small muted servers-range">01–{len(rows):02d}</p>' if rows else ""}
      <h2 class="h2" id="servers">{count}</h2>
    </div>
    <ul class="servers-list">{"".join(rows)}</ul>
  </section>{projects_section}
</main>
<footer class="page">
  <div class="site-footer">
    <p class="site-footer-text byline">By Danny Englander · <a class="link github-link" href="https://github.com/danny-englander/localhost-dashboard"><svg class="github-icon" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" focusable="false"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>Source on GitHub</a></p>
  </div>
</footer>
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


def log_tail(slug):
    """The last 64 KB of a project's log, without terminal color codes."""
    path = log_path(slug)
    if not re.fullmatch(r"[a-z0-9-]+", slug) or not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - 65536))
        text = f.read().decode("utf-8", "replace")
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)
    # An interactive shell with no terminal says this on every start; it means nothing here
    return re.sub(r"^\(eval\):\d+: can't change option: zle\n", "", text, flags=re.M)


def screenshot(slug):
    """A project's screenshot, as (type, bytes). Only files named in projects.json are served."""
    projects, _ = load_projects()
    project = next((p for p in projects or [] if p["slug"] == slug), None)
    if not project or not project["screenshot"] or not os.path.isfile(project["screenshot"]):
        return None
    with open(project["screenshot"], "rb") as f:
        return IMAGE_TYPES[os.path.splitext(project["screenshot"])[1].lower()], f.read()


class Handler(BaseHTTPRequestHandler):
    def own_host(self):
        """Only answer requests addressed to this dashboard. Stops another site from reaching it
        through a hostname that points at 127.0.0.1 (DNS rebinding)."""
        return self.headers.get("Host") in (f"localhost:{PORT}", f"127.0.0.1:{PORT}")

    def send(self, status, ctype=None, data=b"", location=None):
        self.send_response(status)
        if ctype: self.send_header("Content-Type", ctype)
        if location: self.send_header("Location", location)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")                       # no clickjacking the buttons
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass                    # the browser left before the page arrived

    def do_GET(self):
        if not self.own_host():
            return self.send_error(403)
        url = urlparse(self.path)
        if url.path == "/":
            return self.send(200, "text/html; charset=utf-8", page("all" in parse_qs(url.query)).encode())
        if url.path.startswith("/log/"):
            text = log_tail(url.path[5:])
            if text is None:
                return self.send_error(404)
            return self.send(200, "text/plain; charset=utf-8", text.encode())
        if url.path.startswith("/screenshot/"):
            found = screenshot(url.path[12:])
            if not found:
                return self.send_error(404)
            return self.send(200, *found)
        found = static_file(url.path)
        if not found:
            return self.send_error(404)
        self.send(200, *found)

    def do_POST(self):
        """Start and stop, from the page's own buttons only: the browser's Origin header has to be
        this dashboard, so another site you visit can't press them for you."""
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        origin = self.headers.get("Origin")
        if not self.own_host() or origin not in (f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"):
            return self.send_error(403)
        url = urlparse(self.path)
        m = re.fullmatch(r"/(start|stop)/([a-z0-9-]+)", url.path)
        projects, _ = load_projects()
        project = next((p for p in projects or [] if m and p["slug"] == m.group(2)), None)
        if not project:
            return self.send_error(404)
        try:
            (start_project if m.group(1) == "start" else stop_project)(project)
        except FileNotFoundError:
            pass                    # the page shows "Folder not found"
        self.send(303, location="/" + ("?all=1" if "all" in parse_qs(url.query) else ""))

    def log_message(self, *a): pass


if __name__ == "__main__":
    print(f"Listing local servers at http://localhost:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
