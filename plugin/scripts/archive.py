#!/usr/bin/env python3
"""Claude Archive plugin: saves each thread's deliverables to Nextcloud, records the work journal and keeps a
handoff doc per thread. The Claude Archive viewer (viewer/ in the repository) shows the result.

Hook commands (run by Claude Cowork / Claude Code, see hooks/hooks.json):
  check     Stop hook: reads the hook JSON on stdin and asks Claude to archive when needed
  prompt    UserPromptSubmit hook: handles "continue <folder>" and "journal: <text>"

Commands Claude runs when the Stop hook asks:
  upload   --session SID --folder FOLDER [extra files...]
  journal  --session SID --folder FOLDER --transcript PATH --tools N --topic "..." [--highlight ...] [--deliverable ...]
  handoff  --session SID --folder FOLDER --tools N --file notes.md
  mark     --session SID PATH...        paths handled (archived or scratch)
  ignore   --session SID NAME...        never archive these output items
  checkname NAME... / checkfolder NAME  check names against the rules
  tidy     [--all] [FOLDER...]          move older file versions into older-versions/
"""
import argparse, datetime, json, os, re, subprocess, sys, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(ROOT, "config.json")))
HOST, USER, PASSWORD = CFG["host"].rstrip("/"), CFG["user"], CFG.get("password", "")
ROOT_FOLDER = CFG.get("root_folder", "claude").strip("/")
USER_ROOT = f"/remote.php/dav/files/{USER}"
DAV_PREFIX = f"{USER_ROOT}/{ROOT_FOLDER}"
DAV = HOST + DAV_PREFIX
TZ = ZoneInfo(CFG.get("timezone", "UTC"))
OUTPUTS = CFG.get("outputs_dir", "/mnt/user-data/outputs")
STATE_DIR = os.path.expanduser("~/.claude-archive")

TYPES = CFG.get("file_types", ["source", "executables", "documentation", "installer", "plugin",
                               "assets", "images", "design", "data", "config", "report", "backup"])
NAME_RE = re.compile(
    r"(?P<project>[a-z0-9]+(?:-[a-z0-9]+)*)"
    r"-(?P<mm>\d{2})-(?P<dd>\d{2})-(?P<yyyy>\d{4})"
    r"-ver(?P<ver>\d+(?:\.\d+)*)"
    r"-(?P<type>[a-z]+)"
    r"(?P<ext>(?:\.[a-z0-9]+)*)"
)
NAME_RULE = ("name-mm-dd-yyyy-verX.Y.Z-type[.ext], all lowercase, no spaces, e.g. "
             "recipe-app-desktop-10-28-2026-ver2.8.9-source.zip; type is one of: " + ", ".join(TYPES))

FOLDER_RE = re.compile(
    r"(?P<project>[a-z0-9]+(?:-[a-z0-9]+)*)"
    r"-(?P<mm>\d{2})-(?P<dd>\d{2})-(?P<yyyy>\d{4})"
    r"-ver(?P<ver>\d+(?:\.\d+)*)"
    r"-(?P<what>[a-z0-9]+(?:-[a-z0-9]+)*)"
)
FOLDER_RULE = ("product-component-mm-dd-yyyy-verX.Y.Z-what-was-done, all lowercase, no spaces, e.g. "
               "recipe-app-desktop-10-17-2026-ver2.6.9-search-feature (name the exact product/component, "
               "e.g. desktop-app vs browser-extension; version = the thread's main deliverable)")


def folder_problem(name):
    if name != name.lower() or " " in name:
        return "has uppercase letters or spaces"
    m = FOLDER_RE.fullmatch(name)
    if not m:
        return "does not match the folder pattern"
    try:
        datetime.date(int(m["yyyy"]), int(m["mm"]), int(m["dd"]))
    except ValueError:
        return "has an invalid date (must be mm-dd-yyyy)"
    return None


def name_problem(name):
    """Return None if `name` follows the naming rule, else a short reason."""
    if name != name.lower():
        return "has uppercase letters"
    if " " in name:
        return "has spaces"
    m = NAME_RE.fullmatch(name)
    if not m:
        return "does not match the pattern"
    try:
        datetime.date(int(m["yyyy"]), int(m["mm"]), int(m["dd"]))
    except ValueError:
        return "has an invalid date (must be mm-dd-yyyy)"
    if m["type"] not in TYPES:
        return f"type '{m['type']}' is not one of the allowed types"
    return None


def thread_url():
    """Link to this Claude thread (cloud threads only; a local terminal has no address)."""
    sid = os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID", "")
    return f"https://claude.ai/code/session_{sid[4:]}" if sid.startswith("cse_") else ""


def now():
    return datetime.datetime.now(TZ)


# ---------------- per-thread state (local file, mirrored to Nextcloud .state/) ----------------

def state_path(sid):
    return os.path.join(STATE_DIR, re.sub(r"[^\w-]", "_", sid) + ".json")


def _remote_state(sid):
    return "/.state/" + re.sub(r"[^\w-]", "_", sid) + ".json"


def load_state(sid):
    try:
        return json.load(open(state_path(sid)))
    except Exception:
        pass
    try:  # workspace was reset: recover from the server copy
        code, body = curl(DAV + q(_remote_state(sid)))
        return json.loads(body) if code == 200 else {}
    except Exception:
        return {}


def save_state(sid, st):
    os.makedirs(STATE_DIR, exist_ok=True)
    json.dump(st, open(state_path(sid), "w"))
    try:
        mkdirs("/.state")
        curl("-X", "PUT", "--data-binary", "@-", DAV + q(_remote_state(sid)), data=json.dumps(st).encode())
    except Exception:
        pass


# ---------------- Nextcloud (WebDAV through curl) ----------------

def q(path):
    return "/".join(urllib.parse.quote(p) for p in path.split("/"))


def _netrc():
    """Credentials go to curl through a private netrc file, never on the command line."""
    if not PASSWORD:
        sys.exit("Claude Archive has no password set: fill in config.json and reinstall the plugin.")
    path = os.path.join(STATE_DIR, ".netrc")
    if not os.path.exists(path):
        os.makedirs(STATE_DIR, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        host = urllib.parse.urlparse(HOST).hostname
        os.write(fd, f"machine {host} login {USER} password {PASSWORD}\n".encode())
        os.close(fd)
    return path


def curl(*args, data=None):
    if args and isinstance(args[-1], str) and args[-1].startswith(DAV):
        ensure_root()
    cmd = ["curl", "-sS", "--netrc-file", _netrc(), "-o", "-", "-w", "\n%{http_code}", *args]
    r = subprocess.run(cmd, input=data, capture_output=True)
    body, _, code = r.stdout.rpartition(b"\n")
    return int(code or 0), body


_root_ok = False


def ensure_root():
    """The shared archive folder must appear under its exact (lowercase) name in the plugin user's files."""
    global _root_ok
    if _root_ok:
        return
    code, body = curl("-X", "PROPFIND", "-H", "Depth: 1", HOST + USER_ROOT + "/")
    names = [urllib.parse.unquote(h).rstrip("/").rsplit("/", 1)[-1]
             for h in re.findall(r"<d:href>(.*?)</d:href>", body.decode("utf-8", "ignore"))][1:]  # [0] is the user root
    if code == 401:
        sys.exit(f"Nextcloud rejected the login for user '{USER}' (wrong app password in config.json?).")
    if ROOT_FOLDER not in names:
        old = next((n for n in names if n.lower() == ROOT_FOLDER), None)
        if not old:
            sys.exit(f"The '{ROOT_FOLDER}' folder is not shared with the Nextcloud user '{USER}'.")
        curl("-X", "MOVE", "-H", f"Destination: {HOST}{USER_ROOT}/{q(ROOT_FOLDER)}", HOST + USER_ROOT + "/" + q(old))
    _root_ok = True


def mkdirs(remote):
    cur = ""
    for part in remote.strip("/").split("/"):
        cur += "/" + part
        curl("-X", "MKCOL", DAV + q(cur))


def put_file(local, remote):
    code, body = curl("-T", local, DAV + q(remote))
    if code == 401:
        sys.exit(f"Upload failed: Nextcloud rejected the login for user '{USER}' (wrong app password in config.json?).")
    if code not in (200, 201, 204):
        sys.exit(f"Upload failed ({code}) for {local}: {body[:200]!r}")


def put_json(path, obj):
    mkdirs(os.path.dirname(path))
    code, body = curl("-X", "PUT", "--data-binary", "@-", DAV + q(path), data=json.dumps(obj).encode())
    if code not in (200, 201, 204):
        raise RuntimeError(f"Could not write {path} ({code}): {body[:200]!r}")


def get_json(path):
    code, body = curl(DAV + q(path))
    try:
        return json.loads(body) if code == 200 else {}
    except Exception:
        return {}


def remote_sizes(base):
    """Map relative path -> size for every file already under `base` on the server."""
    out, todo = {}, [base]
    while todo:
        d = todo.pop()
        code, body = curl("-X", "PROPFIND", "-H", "Depth: 1", DAV + q(d) + "/")
        if code != 207:
            continue
        for resp in re.findall(r"<d:response>(.*?)</d:response>", body.decode("utf-8", "ignore"), re.S):
            href = urllib.parse.unquote(re.search(r"<d:href>(.*?)</d:href>", resp).group(1))
            rel = href.split(DAV_PREFIX, 1)[-1].rstrip("/")
            if rel == d.rstrip("/"):
                continue
            if "<d:collection" in resp:
                todo.append(rel)
            else:
                m = re.search(r"<d:getcontentlength>(\d+)<", resp)
                out[rel[len(base):].lstrip("/")] = int(m.group(1)) if m else -1
    return out


def list_items(folder):
    """Top-level items of a project folder: name -> {dir, mtime}."""
    code, out = curl("-X", "PROPFIND", "-H", "Depth: 1", DAV + "/" + q(folder) + "/")
    items = {}
    if code != 207:
        return items
    for resp in re.findall(r"<d:response>(.*?)</d:response>", out.decode("utf-8", "ignore"), re.S):
        href = urllib.parse.unquote(re.search(r"<d:href>(.*?)</d:href>", resp).group(1)).rstrip("/")
        if href.endswith(f"/{ROOT_FOLDER}/" + folder):
            continue
        lm = re.search(r"<d:getlastmodified>(.*?)<", resp)
        mt = datetime.datetime.strptime(lm.group(1), "%a, %d %b %Y %H:%M:%S %Z").replace(
            tzinfo=datetime.timezone.utc).timestamp() if lm else 0
        items[href.rsplit("/", 1)[-1]] = {"dir": "<d:collection" in resp, "mtime": mt}
    return items


# ---------------- links stored in the journal record (the viewer reads them) ----------------

def files_link(folder):
    return f"{HOST}/index.php/apps/files/files?dir=" + urllib.parse.quote(f"/{ROOT_FOLDER}/{folder}")


def direct_link(path):
    return f"{HOST}/remote.php/webdav/{ROOT_FOLDER}/" + urllib.parse.quote(path)


def handoff_url(folder):
    return files_link(folder) + "&handoff=1"


def file_links(folder, names):
    """[[file name, link], ...] for a deliverable's files, or the folder link when no files are known."""
    items = list_items(folder) if names else {}
    return [[n, files_link(f"{folder}/{n}") if items.get(n, {}).get("dir") else direct_link(f"{folder}/{n}")]
            for n in names] or files_link(folder)


def link_label(url):
    return "files" if url.startswith(HOST + "/index.php/apps/files") else "live page"


NB = " "  # non-breaking space inside two-word link labels
L_THREAD = f"claude{NB}thread"


def hm(secs):
    return f"{int(secs // 3600)}:{int(secs % 3600 // 60):02d}"


def fmt_line(ts, secs, text, link, thread="", handoff=""):
    """One journal line: '- 9:24am (1:32 spent) topic - [files](url) [claude thread](url) [handoff](url)'."""
    t = datetime.datetime.fromtimestamp(ts, TZ)
    clock = t.strftime("%I:%M%p").lstrip("0").lower()
    dur = f"({hm(secs)} spent) " if secs is not None else ""
    parts = ([(l.replace(" ", NB), u) for l, u in link] if isinstance(link, list) else [(link_label(link), link)]) \
        + [(L_THREAD, thread), ("handoff", handoff)]
    links = " ".join(f"[{label}]({url})" for label, url in parts if url)
    return f"- {clock} {dur}{text}" + (f" - {links}" if links else "")


def output_files():
    out = []
    for base, _, names in os.walk(OUTPUTS):
        for n in names:
            out.append(os.path.join(base, n))
    return out


def top_name(p):
    return os.path.relpath(p, OUTPUTS).split(os.sep)[0] if p.startswith(OUTPUTS) else os.path.basename(p)


def count_tool_uses(transcript):
    try:
        with open(transcript, encoding="utf-8", errors="ignore") as f:
            return f.read().count('"type":"tool_use"')
    except Exception:
        return 0


# ---------------- thread folder ----------------

def folder_name(st, folder):
    """Return the thread folder; validate a new name and rename the old folder (and its links) if it changed."""
    old = st.get("folder")
    if not folder:
        if old:
            return old
        sys.exit(f"Give the thread folder with --folder, named {FOLDER_RULE}")
    why = folder_problem(folder)
    if why:
        sys.exit(f"Folder name '{folder}' {why}. Rule: {FOLDER_RULE}")
    if old and old != folder:
        code, _ = curl("-X", "MOVE", "-H", f"Destination: {DAV}/{q(folder)}", DAV + "/" + q(old))
        if code not in (201, 204):
            sys.exit(f"Could not rename folder {old} -> {folder} ({code})")
        pairs = [(files_link(old), files_link(folder)), (direct_link(old + "/"), direct_link(folder + "/"))]
        relink_all(pairs)
        relink_state(st, pairs)
        times = get_json(TIMES)
        if old in times:
            times[folder] = times.pop(old)
            put_json(TIMES, times)
        print("renamed folder:", old, "->", folder)
    st["folder"] = folder
    return folder


def relink_all(pairs):
    """Replace links in the journal record (used when a folder is renamed or files move to older-versions)."""
    if not pairs:
        return
    jd = get_json(JDAYS)
    text = json.dumps(jd)
    new = text
    for old_link, new_link in pairs:
        new = new.replace(json.dumps(old_link)[1:-1], json.dumps(new_link)[1:-1])
    if new != text:
        put_json(JDAYS, json.loads(new))


def relink_state(st, pairs):
    """Keep this thread's stored deliverable links current (they are re-rendered on every refresh)."""
    def fix(u):
        for a, b in pairs:
            u = u.replace(a, b)
        return u
    for d, (ts, link) in st.get("jday", {}).get("deliverables", {}).items():
        st["jday"]["deliverables"][d] = [ts, fix(link) if isinstance(link, str) else [[l, fix(u)] for l, u in link]]


OLDER = "older-versions"


def file_family(name):
    """Same file across versions = same project, type and extension. Returns (family, version tuple, date)."""
    m = NAME_RE.fullmatch(name)
    if not m:
        return None
    ver = tuple(int(x) for x in m["ver"].split("."))
    return (m["project"], m["type"], m["ext"]), ver, (m["yyyy"], m["mm"], m["dd"])


def tidy_folder(folder):
    """Move every non-latest version of a file into <folder>/older-versions. Returns the link pairs that changed."""
    items = list_items(folder)
    fams = {}
    for n, info in items.items():
        if n == OLDER or "-handoff-" in n:
            continue
        f = file_family(n)
        key = f[0] if f else ("", n, "")
        fams.setdefault(key, []).append((f[1:] if f else ((), ()), info["mtime"], n))
    moves = []
    for key, vs in fams.items():
        vs.sort()
        for _, _, n in vs[:-1]:
            mkdirs(f"/{folder}/{OLDER}")
            code, _ = curl("-X", "MOVE", "-H", f"Destination: {DAV}/{q(folder)}/{OLDER}/{q(n)}", "-H", "Overwrite: T",
                           DAV + "/" + q(folder) + "/" + q(n))
            if code in (201, 204):
                moves.append((direct_link(f"{folder}/{n}"), direct_link(f"{folder}/{OLDER}/{n}")))
    relink_all(moves)
    return moves


# ---------------- Stop hook ----------------

SCAN_ROOT = CFG.get("scan_root", "/home/claude")
SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".venv", "site-packages", ".git", ".cache", ".npm", ".npm-global",
             ".claude", ".claude-archive", ".local", ".config", ".cargo", ".pki", ".ssh"}
LONG_THREAD_TOOLS = 250
HANDOFF_MIN_TOOLS = 10
HIGHLIGHT_REFRESH_TOOLS = 40
SILENT_REFRESH_SECS = 10 * 60


def session_start(transcript):
    try:
        with open(transcript, encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = re.search(r'^\{.*?"timestamp":"([^"]+)"', line)
                if m:
                    return datetime.datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).timestamp()
    except Exception:
        pass
    return now().timestamp()


def unarchived(st, since):
    """Top-level items under SCAN_ROOT with files changed this session and not yet marked handled."""
    marks = st.get("marks", {})
    found = {}
    for base, dirs, files in os.walk(SCAN_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for n in files:
            p = os.path.join(base, n)
            try:
                mt = os.path.getmtime(p)
            except OSError:
                continue
            if mt <= since or n.startswith("."):
                continue
            top = os.path.join(SCAN_ROOT, os.path.relpath(p, SCAN_ROOT).split(os.sep)[0])
            if mt > marks.get(top, 0):
                found[top] = found.get(top, 0) + 1
    plugin_root = os.path.realpath(ROOT)
    return {k: v for k, v in found.items() if not os.path.realpath(k).startswith(plugin_root)}


def cmd_mark(a):
    st = load_state(a.session)
    marks = st.get("marks", {})
    t = now().timestamp()
    for p in a.paths:
        marks[os.path.abspath(p).rstrip("/")] = t
    st["marks"] = marks
    save_state(a.session, st)
    print("marked as archived/scratch:", ", ".join(a.paths))


def cmd_check():
    try:
        hook = json.load(sys.stdin)
    except Exception:
        return
    if hook.get("stop_hook_active"):
        return
    sid = hook.get("session_id", "unknown")
    transcript = hook.get("transcript_path", "")
    st = load_state(sid)
    tools = count_tool_uses(transcript)
    new_files = [p for p in output_files() if os.path.getmtime(p) > st.get("uploaded_at", 0)]
    today = f"{now():%Y-%m-%d}"
    has_topic = st.get("jday", {}).get("day") == today and st["jday"].get("topic")
    need_topic = tools >= 3 and not has_topic
    need_highlights = has_topic and tools - st.get("journal_tools", 0) >= HIGHLIGHT_REFRESH_TOOLS
    loose = unarchived(st, session_start(transcript)) if tools >= 3 else {}
    need_handoff = tools >= HANDOFF_MIN_TOOLS and (
        not st.get("handoff_at") or new_files or tools - st.get("handoff_tools", 0) >= HIGHLIGHT_REFRESH_TOOLS
        or datetime.datetime.fromtimestamp(st["handoff_at"], TZ).strftime("%Y-%m-%d") != today)
    long_notice = tools >= LONG_THREAD_TOOLS and not st.get("long_notified")
    if not new_files and not need_topic and not need_highlights and not loose and not need_handoff and not long_notice:
        # just keep today's time-spent figure current, without bothering Claude
        if has_topic and now().timestamp() - st.get("jrefresh", 0) > SILENT_REFRESH_SECS:
            try:
                publish_day(sid, st, transcript)
                refresh_viewer()
            except Exception:
                pass
        return
    script = os.path.abspath(__file__)
    folder = st.get("folder")
    farg = f'--folder "{folder}"' if folder else '--folder "<folder name>"'
    steps = []
    if loose:
        listing = "\n".join(f"  {p} ({n} changed file{'s' if n > 1 else ''})" for p, n in sorted(loose.items()))
        steps.append(
            "FILES NOT YET ARCHIVED - the user wants a copy of everything you create or change (code, plugins, docs, "
            "graphics), including things installed straight onto their sites:\n" + listing + "\n"
            f"For each: zip a project folder (or copy a single file) into {OUTPUTS} named by the file rule, "
            "e.g. recipe-app-desktop-10-18-2026-ver0.17.3-source.zip; scratch/test/downloaded items need no copy. "
            f'Then run: python3 "{script}" mark --session "{sid}" <path> [...] for every path listed.')
        new_files = new_files or loose
    steps.append(f'python3 "{script}" upload --session "{sid}" {farg}')
    steps.append(f'python3 "{script}" journal --session "{sid}" --tools {tools} {farg} --transcript "{transcript}" '
                 '--topic "<topic>" [--highlight "<goal>" ...] [--deliverable "<finished result>" ...]')
    steps.append(JOURNAL_RULE + " Re-send the full current set of highlights; deliverables already logged stay.")
    if need_handoff:
        steps.append(
            "HANDOFF DOC: write markdown to a temp file that lets a brand-new thread continue this work without this one: "
            "goal, what was done (decisions, not steps), current state and versions, where the code/files are "
            "(archive file names, repos, live URLs), open issues, next steps. Keep it tight. Then run: "
            f'python3 "{script}" handoff --session "{sid}" {farg} --tools {tools} --file <temp.md> '
            "(it replaces the previous handoff doc).")
    if long_notice:
        st["long_notified"] = True
        save_state(sid, st)
        steps.append(
            "LONG THREAD: after the handoff doc is updated, end your reply with one short line telling the user this "
            f"thread is getting long and that they can continue in a new thread by sending: continue {folder or '<folder name>'}")
    title_note = (f'This thread\'s folder is "{folder}"; keep it, or pass a new name with a bumped version '
                  "if the main deliverable's version changed (the folder is renamed automatically)."
                  if folder else f"Name this thread's folder {FOLDER_RULE}.")
    reason = (
        "Claude Archive: save this thread's work to Nextcloud before finishing. "
        f"{title_note} Every top-level file/folder in {OUTPUTS} must be named {NAME_RULE} "
        "(wrongly named files are skipped and listed: rename current deliverables, ignore old versions). "
        "Run silently (except the LONG THREAD line if present), then end your turn without writing anything else: "
        "your earlier reply already reached the user, so never repeat or summarize it; mention it only if a command fails.\n"
        + "\n".join(steps)
    )
    print(json.dumps({"decision": "block", "reason": reason}))


# ---------------- upload ----------------

def cmd_upload(a):
    st = load_state(a.session)
    folder = folder_name(st, a.folder)
    base = f"/{folder}"
    mkdirs(base)
    started = now().timestamp()
    ignored = set(st.get("ignore", []))
    files = [p for p in output_files() if os.path.getmtime(p) > st.get("uploaded_at", 0)]
    files += [p for p in a.files if os.path.isfile(p)]
    files = [p for p in files if top_name(p) not in ignored and not top_name(p).startswith(".")]
    existing = remote_sizes(base)
    bad, sent, dup = {}, 0, 0
    for p in files:
        name = top_name(p)
        why = name_problem(name)
        if why:
            bad[name] = why
            continue
        rel = os.path.relpath(p, OUTPUTS) if p.startswith(OUTPUTS) else os.path.basename(p)
        r = rel.replace(os.sep, "/")
        if os.path.getsize(p) in (existing.get(r), existing.get(f"{OLDER}/{r}")):
            dup += 1
            continue
        sub = os.path.dirname(rel)
        if sub:
            mkdirs(f"{base}/{sub}")
        put_file(p, f"{base}/{rel}")
        top = r.split("/")[0]
        if top not in st.setdefault("pending_files", []):
            st["pending_files"].append(top)
        sent += 1
        print("uploaded", rel)
    st["uploaded_at"] = started
    st["files_uploaded"] = st.get("files_uploaded", 0) + sent
    save_state(a.session, st)
    print(f"{sent} uploaded, {dup} already on server. folder: {folder}")
    if sent:
        try:
            relink_state(st, tidy_folder(folder))
            save_state(a.session, st)
        except Exception as e:
            print("older versions not tidied:", e)
    if bad:
        print("\nSKIPPED (name breaks the rule):")
        for n, why in sorted(bad.items()):
            print(f"  {n}: {why}")
        print(f"Rule: {NAME_RULE}")
        print("For each: if it is a current deliverable, rename it in the outputs folder to the rule and run upload again; "
              f'if it is an old/superseded version, run: python3 "{os.path.abspath(__file__)}" ignore '
              f'--session "{a.session}" <name> [...]')


def cmd_ignore(a):
    st = load_state(a.session)
    st["ignore"] = sorted(set(st.get("ignore", [])) | set(a.names))
    save_state(a.session, st)
    print("will not archive:", ", ".join(a.names))


def cmd_tidy(a):
    folders = a.folders
    if a.all:
        code, body = curl("-X", "PROPFIND", "-H", "Depth: 1", DAV + "/")
        folders = [urllib.parse.unquote(h).rstrip("/").rsplit("/", 1)[-1]
                   for h in re.findall(r"<d:href>(.*?)</d:href>", body.decode("utf-8", "ignore"))]
        folders = [f for f in folders if FOLDER_RE.fullmatch(f)]
    for f in folders:
        moved = tidy_folder(f)
        print(f"{f}: {len(moved)} older version{'s' if len(moved) != 1 else ''} moved")


# ---------------- work time ----------------

IDLE_GAP = 15 * 60  # gaps longer than this count as idle (not work time)
TIMES = "/.state/work-times.json"   # folder -> thread -> day -> seconds, plus "_spans" -> day -> thread -> periods
JDAYS = "/.state/journal-days.json"  # day -> claude thread -> {topic, secs, folder, lines}; the viewer reads this


def active_spans(transcript, since, until, anchor=False):
    """Work periods [start, end]: transcript events in (since, until] joined when gaps are <= IDLE_GAP.
    anchor=True starts from `since` (the last counted moment)."""
    stamps = [since] if anchor else []
    try:
        with open(transcript, encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = re.search(r'^\{.*?"timestamp":"([^"]+)"', line)
                if m:
                    ts = datetime.datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).timestamp()
                    if since < ts <= until:
                        stamps.append(ts)
    except Exception:
        return []
    stamps.sort()
    spans = []
    for a in stamps:
        if spans and a - spans[-1][1] <= IDLE_GAP:
            spans[-1][1] = a
        else:
            spans.append([a, a])
    return [x for x in spans if x[1] > x[0]]


def merge_spans(spans):
    """Union of periods, so overlapping threads count each minute once."""
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def span_total(spans):
    return sum(b - a for a, b in merge_spans(spans))


def record_work(folder, sid, day, spans):
    times = get_json(TIMES)
    spans = merge_spans(spans)
    if folder:
        times.setdefault(folder, {}).setdefault(sid, {})[day] = round(span_total(spans))
    times.setdefault("_spans", {}).setdefault(day, {})[sid] = [[round(a), round(b)] for a, b in spans]
    put_json(TIMES, times)


def day_start_ts(transcript, midnight):
    """First transcript event today = when work on this thread started today."""
    try:
        with open(transcript, encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = re.search(r'^\{.*?"timestamp":"([^"]+)"', line)
                if m:
                    ts = datetime.datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).timestamp()
                    if ts >= midnight:
                        return ts
    except Exception:
        pass
    return None


# ---------------- journal ----------------

TOPIC_WORDS, HL_MAX, HL_WORDS, DELIV_WORDS, DELIV_MAX = 8, 3, 6, 10, 10
URL_RE = re.compile(r"https?://\S+")
JOURNAL_RULE = (
    "The journal records what the user worked on, time spent, and deliverables - NOT a tech log. "
    f"--topic: what this thread is about, max {TOPIC_WORDS} words (e.g. 'Recipe app search feature planning'). "
    f"--highlight (0-{HL_MAX}): only when a lot was done today, the main things the user ASKED FOR, phrased as their goals, "
    f"max {HL_WORDS} words, no commas (e.g. 'planned search feature'). Never Claude's steps (reviews, research, prep, forms, setup). "
    f"--deliverable (0-{DELIV_MAX}): a finished result the user can use, max {DELIV_WORDS} words; ONLY allowed when this "
    "thread saved new files to Nextcloud since its last deliverable, or when it includes the URL of something "
    "published/changed live (e.g. 'Updated blog article https://example.com/...'). Most threads have none.")
TOPIC_LINE_RE = re.compile(r"^- \d{1,2}:\d{2}(?:am|pm) \((\d+):(\d{2}) spent\) (.+?)(?: - (?:\[|[^\[]*?- \[)|$)")
FOLDER_IN_LINK_RE = re.compile(r"dir=/" + re.escape(ROOT_FOLDER) + r"/([a-z0-9][a-z0-9.\-]+)")


def text_problem(text, max_words, commas_ok=True):
    if not text.strip():
        return "is empty"
    if re.search(r"[;()\[\]{}\n]", text) or (not commas_ok and "," in text):
        return "contains a semicolon, bracket, comma or line break"
    n = len(URL_RE.sub("", text).split())
    return f"has {n} words (max {max_words})" if n > max_words else None


def record_lines(jd, day, key, lines):
    """Store one thread's lines for the day: the topic line (topic, time, folder) plus its deliverable lines."""
    rec = jd.setdefault(day, {})
    old = rec.get(key, {})
    m = TOPIC_LINE_RE.match(lines[0]) if lines else None
    if m:
        f = FOLDER_IN_LINK_RE.search(lines[0])
        rec[key] = {"topic": m.group(3).split(" - ")[0].strip(),
                    "secs": int(m.group(1)) * 3600 + int(m.group(2)) * 60,
                    "folder": f.group(1) if f else old.get("folder", ""), "lines": list(lines)}
    else:
        rec[key] = {"topic": old.get("topic", ""), "secs": old.get("secs", 0), "folder": old.get("folder", ""),
                    "lines": list(lines)}


def write_journal(t, lines=None, key="", note=""):
    """Save a thread's lines (or one of the user's notes) for today in the journal record."""
    day = f"{t:%Y-%m-%d}"
    jd = get_json(JDAYS)
    if key and lines:
        record_lines(jd, day, key, lines)
    if note:
        jd.setdefault("_notes", {}).setdefault(day, []).append(note)
    put_json(JDAYS, jd)


def render_day(st, day, transcript):
    """Topic line '9:24am (1:32 spent) topic - hl, hl' plus one line per deliverable."""
    j = st.get("jday", {})
    if j.get("day") != day or not j.get("topic"):
        return []
    t = now()
    midnight = t.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    start = j.get("start") or day_start_ts(transcript, midnight) or t.timestamp()
    j["start"] = start
    # Accumulate work periods: compaction trims old events from the transcript, so never recount from midnight.
    spans = j.get("spans") or []
    if transcript:
        last = j.get("secs_ts")
        if last and last >= midnight and spans:
            spans = merge_spans(spans + active_spans(transcript, last, t.timestamp(), anchor=True))
        else:
            spans = active_spans(transcript, midnight, t.timestamp())
        j["secs_ts"] = t.timestamp()
    j["spans"] = spans
    secs = j["secs"] = span_total(spans)
    thread = j.get("thread") or thread_url()
    j["thread"] = thread
    topic = j["topic"] + (" - " + ", ".join(j["highlights"]) if j.get("highlights") else "")
    folder = st.get("folder")
    has_files = bool(folder) and st.get("files_uploaded", 0) > 0
    lines = [fmt_line(start, secs, topic, files_link(folder) if has_files else "", thread,
                      handoff_url(folder) if folder and st.get("handoff_at") else "")]
    for text, (ts, link) in j.get("deliverables", {}).items():
        lines.append(fmt_line(ts, None, URL_RE.sub("", text).strip(" -"), link, thread))
    return lines


def publish_day(sid, st, transcript):
    t = now()
    day = f"{t:%Y-%m-%d}"
    lines = render_day(st, day, transcript)
    if not lines:
        return False
    try:
        record_work(st.get("folder"), sid, day, st["jday"].get("spans") or [])
    except Exception:
        pass
    write_journal(t, lines, st.get("jday", {}).get("thread") or sid)
    st["jrefresh"] = t.timestamp()
    save_state(sid, st)
    return True


def cmd_journal(a):
    bad = []
    if a.topic and text_problem(a.topic, TOPIC_WORDS):
        bad.append((a.topic, text_problem(a.topic, TOPIC_WORDS)))
    if len(a.highlight) > HL_MAX:
        bad.append(("--highlight", f"{len(a.highlight)} given (max {HL_MAX})"))
    bad += [(h, text_problem(h, HL_WORDS, commas_ok=False)) for h in a.highlight if text_problem(h, HL_WORDS, False)]
    bad += [(d, text_problem(d, DELIV_WORDS)) for d in a.deliverable if text_problem(d, DELIV_WORDS)]
    st = load_state(a.session)
    folder = folder_name(st, a.folder)
    t = now()
    day = f"{t:%Y-%m-%d}"
    jd = st.get("jday", {})
    if jd.get("day") != day:
        jd = {"day": day, "deliverables": {}}
    if not (a.topic or jd.get("topic")):
        bad.append(("--topic", "missing"))
    files_now = st.get("files_uploaded", 0)
    new_deliv = [d for d in a.deliverable if d not in jd["deliverables"]]
    no_url = [d for d in new_deliv if not URL_RE.search(d)]
    if no_url and files_now <= st.get("files_mark", 0):
        bad += [(d, "no new files saved to Nextcloud and no live URL - not a deliverable") for d in no_url]
    if len(jd["deliverables"]) + len(new_deliv) > DELIV_MAX:
        bad.append(("--deliverable", f"more than {DELIV_MAX} today"))
    if bad:
        sys.exit("JOURNAL NOT UPDATED. Fix these:\n" + "\n".join(f"  '{x}': {why}" for x, why in bad)
                 + f"\nRule: {JOURNAL_RULE}")
    if a.topic:
        jd["topic"] = " ".join(a.topic.split()).rstrip(".")
    if a.highlight or a.topic:
        jd["highlights"] = [" ".join(h.split()).rstrip(".") for h in a.highlight]
    for d in new_deliv:
        url = URL_RE.search(d)
        jd["deliverables"][d] = [t.timestamp(), url.group(0) if url else file_links(folder, st.get("pending_files", []))]
    if no_url:
        st["files_mark"] = files_now
        st["pending_files"] = []
    st["jday"] = jd
    st["journal_tools"] = int(a.tools) if a.tools else st.get("journal_tools", 0)
    try:
        publish_day(a.session, st, a.transcript)
    except RuntimeError as e:
        sys.exit(str(e))
    print("journal updated for", day)


# ---------------- handoff doc ----------------

def handoff_name(folder):
    m = FOLDER_RE.fullmatch(folder)
    return f"{m['project']}-{m['what']}-handoff-{m['mm']}-{m['dd']}-{m['yyyy']}-ver{m['ver']}-documentation.md"


def cmd_handoff(a):
    """Upload Claude's handoff notes as the thread folder's handoff doc (one per folder, updated in place)."""
    st = load_state(a.session)
    folder = folder_name(st, a.folder)
    body = open(a.file, encoding="utf-8").read().strip()
    if len(body) < 200:
        sys.exit("Handoff doc too short - it must let a new thread continue the work without this one.")
    name = handoff_name(folder)
    existing = [n for n in remote_sizes("/" + folder) if n.endswith("-documentation.md") and "-handoff-" in n]
    threads = []
    for n in existing:
        c, old = curl(DAV + q(f"/{folder}/{n}"))
        if c == 200:
            threads += re.findall(r"\]\((https://claude\.ai/code/session_[^)]+)\)", old.decode("utf-8", "ignore").split("\n\n")[0])
    url = thread_url()
    if url and url not in threads:
        threads.append(url)
    head = (f"# Handoff: {folder}\n\n"
            f"Threads: " + " ".join(f"[{i + 1}]({u})" for i, u in enumerate(threads)) + "\n"
            f"Updated: {now():%m-%d-%Y %I:%M%p}\n\n"
            f"To continue in a new thread, send: continue {folder}\n\n")
    tmp = os.path.join(STATE_DIR, "handoff.md")
    os.makedirs(STATE_DIR, exist_ok=True)
    open(tmp, "w", encoding="utf-8").write(head + body + "\n")
    put_file(tmp, f"/{folder}/{name}")
    for n in existing:
        if n != name:
            curl("-X", "DELETE", DAV + q(f"/{folder}/{n}"))
    st["handoff_at"] = now().timestamp()
    st["handoff_tools"] = int(a.tools) if a.tools else st.get("handoff_tools", 0)
    save_state(a.session, st)
    print("handoff doc updated:", name)


# ---------------- UserPromptSubmit hook ----------------

def cmd_prompt():
    """'continue <folder>' loads that folder's handoff doc; 'journal: text' adds a note for today without a Claude turn."""
    try:
        hook = json.load(sys.stdin)
    except Exception:
        return
    prompt = hook.get("prompt", "")
    # Cowork may prepend hidden context blocks (<system-reminder>...); drop them before matching
    prompt = re.sub(r"<([\w-]+)[^>]*>.*?</\1>", "", prompt, flags=re.S).strip()
    c = re.fullmatch(r"continue\s+([a-z0-9][a-z0-9.\-]+)", prompt, re.I)
    if c:
        return continue_thread(hook, c.group(1).lower())
    m = re.fullmatch(r"journal\s*:\s*(.+)", prompt, re.I | re.S)
    if not m:
        return
    text = " ".join(m.group(1).split())
    t = now()
    try:
        write_journal(t, note=fmt_line(t.timestamp(), None, text, ""))
        refresh_viewer()
        msg = f"Added to journal ({t:%b} {t.day}): {text}"
    except Exception as e:
        msg = f"Journal entry NOT saved: {e}"
    print(json.dumps({"decision": "block", "reason": msg}))


def continue_thread(hook, folder):
    """New thread picks up an old one: load its handoff doc and adopt its folder."""
    docs = [n for n in remote_sizes("/" + folder) if "-handoff-" in n and n.endswith(".md")]
    if not docs:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext":
              f"Claude Archive: no handoff doc found in Nextcloud folder '{folder}'. Tell the user and ask which folder."}}))
        return
    code, body = curl(DAV + q(f"/{folder}/{docs[0]}"))
    sid = hook.get("session_id", "unknown")
    st = load_state(sid)
    st["folder"] = folder
    save_state(sid, st)
    ctx = (f"Claude Archive: the user is continuing earlier work. This thread uses Nextcloud folder '{folder}'. "
           "Read the handoff doc below, then briefly confirm (one or two sentences) where things stand and ask what to do next. "
           "Source files are in that folder (download with curl via the plugin if needed).\n\n" + body.decode("utf-8", "ignore"))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}))


# ---------------- viewer ----------------

def refresh_viewer():
    """Tell the Claude Archive viewer to rebuild its data once, so new work shows up within about 20 seconds.
    The viewer answers at once and works in the background; any error is ignored."""
    url, token = CFG.get("viewer_url"), CFG.get("viewer_token")
    if not url or not token:
        return
    try:
        req = urllib.request.Request(url, data=b"", method="POST", headers={"X-Archive-Token": token})
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        pass


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        return cmd_check()
    if len(sys.argv) > 1 and sys.argv[1] == "checkfolder":
        why = folder_problem(sys.argv[2]) if len(sys.argv) > 2 else "no name given"
        print("OK" if not why else f"BAD ({why}). Rule: {FOLDER_RULE}")
        sys.exit(bool(why))
    if len(sys.argv) > 1 and sys.argv[1] == "checkname":
        rc = 0
        for n in sys.argv[2:]:
            why = name_problem(n)
            print(("OK   " if not why else "BAD  ") + n + ("" if not why else f"  ({why})"))
            rc |= bool(why)
        if rc:
            print("Rule:", NAME_RULE)
        sys.exit(rc)
    if len(sys.argv) > 1 and sys.argv[1] == "prompt":
        return cmd_prompt()
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        ensure_root()
        print(f"OK: logged in to {HOST} as {USER}, archive folder '{ROOT_FOLDER}' found.")
        return
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    u = sp.add_parser("upload"); u.add_argument("--session", required=True)
    u.add_argument("--folder", default=""); u.add_argument("files", nargs="*")
    h = sp.add_parser("handoff"); h.add_argument("--session", required=True); h.add_argument("--folder", default="")
    h.add_argument("--file", required=True); h.add_argument("--tools", default="")
    mk = sp.add_parser("mark"); mk.add_argument("--session", required=True); mk.add_argument("paths", nargs="+")
    i = sp.add_parser("ignore"); i.add_argument("--session", required=True); i.add_argument("names", nargs="+")
    ty = sp.add_parser("tidy"); ty.add_argument("--all", action="store_true"); ty.add_argument("folders", nargs="*")
    j = sp.add_parser("journal"); j.add_argument("--session", required=True)
    j.add_argument("--folder", default="")
    j.add_argument("--topic", default=""); j.add_argument("--highlight", action="append", default=[])
    j.add_argument("--deliverable", action="append", default=[])
    j.add_argument("--transcript", default="")
    j.add_argument("--tools", default="")
    a = p.parse_args()
    try:
        {"upload": cmd_upload, "journal": cmd_journal, "ignore": cmd_ignore,
         "handoff": cmd_handoff, "mark": cmd_mark, "tidy": cmd_tidy}[a.cmd](a)
    finally:
        if a.cmd in ("upload", "journal", "handoff"):
            refresh_viewer()


if __name__ == "__main__":
    main()
