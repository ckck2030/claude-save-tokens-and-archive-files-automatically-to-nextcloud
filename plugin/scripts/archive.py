#!/usr/bin/env python3
"""Claude Archive plugin 2.3.2: saves each thread's deliverables to Nextcloud, records the work journal and keeps a
handoff doc per thread. The Claude Archive viewer (viewer/ in the repository) shows the result.

Hooks (hooks/hooks.json):
  check         Stop: shows "<size>K continue <chain>-v<N>" as a systemMessage (no model call) and starts a background
                save (`bg save`): uploads rule-named files from the outputs folder and files sent with SendUserFile,
                names the folder, tidies older versions, writes the journal. It blocks only once, when the thread
                passes 150K, to get the handoff doc written.
  prompt        UserPromptSubmit: "continue <chain>-v<N>", "journal: <text>", "handoff", named handoffs, and a one-line
                note about rule-breaking file names found by the last save.
  sessionstart  SessionStart: gives a new thread the name the last handoff chose.

Commands Claude runs:
  handoff  --session SID --file notes.md [--chain NAME] [--folder F] [--as <chain>-v<N> [--scope "<topic>"]]
  folder   --session SID NAME           set/fix the thread folder name
  upload   --session SID [--folder F] FILE...   extra files outside the outputs folder
  journal  --session SID [--topic ...] [--highlight ...] [--deliverable ...]
  ignore   --session SID NAME...        never archive these output items
  checkname NAME... / checkfolder NAME / tidy [--all] [FOLDER...] / test
"""
import argparse, datetime, glob, json, os, re, shlex, subprocess, sys, urllib.parse, urllib.request
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


def load_state(sid, local_only=False):
    try:
        return json.load(open(state_path(sid)))
    except Exception:
        if local_only:
            return {}
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
    cmd = ["curl", "-sS", "--connect-timeout", "5", "--netrc-file", _netrc(), "-o", "-", "-w", "\n%{http_code}", *args]
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


# ---------------- thread folder ----------------

def folder_name(st, folder):
    """Return the thread folder; validate a new name and rename the old folder (and its links) if it changed."""
    old = st.get("folder")
    if not folder:
        if old:
            return old
        sys.exit(f"This thread has no folder yet: pass --folder, named {FOLDER_RULE}")
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
        chain_rename_folder(old, folder)
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


# ---------------- thread chains ----------------

CHAINS = "/.state/chains.json"  # chain name -> [{"n": 1, "sid": ..., "folder": ..., "thread": ...}, ...] sorted by n
CHAIN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
CHAIN_RULE = ("lowercase letters, digits and single hyphens only, no date or version, e.g. garden-planner or "
              "recipe-app-desktop (the short name the user calls the product)")


def chain_problem(name):
    """Return None if `name` is a valid chain name, else a short reason."""
    if not name or not CHAIN_RE.fullmatch(name):
        return "must be lowercase letters, digits and single hyphens"
    if re.search(r"\d{2}-\d{2}-\d{4}", name) or re.search(r"(?:^|-)ver?\d+(?:\.\d+)*(?:-|$)", name):
        return "must not contain a date or version"
    return None


def transcript_path(sid):
    """This thread's transcript file (Claude Code keeps one .jsonl per session under ~/.claude/projects)."""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    hits = glob.glob(os.path.join(base, "projects", "*", f"{sid}.jsonl"))
    return max(hits, key=os.path.getmtime) if hits else ""


def thread_title_name(sid):
    """(chain, N) when this thread's title is a thread name like 'garden-planner-redesign-v1' (case ignored), else None."""
    m = re.fullmatch(r"([a-z0-9]+(?:-[a-z0-9]+)*)-v(\d+)", thread_title(sid).lower())
    if not m or chain_problem(m.group(1)):
        return None
    return m.group(1), int(m.group(2))


def chain_default(folder):
    m = FOLDER_RE.fullmatch(folder or "")
    return m["project"] if m else ""


def load_chains():
    ch = get_json(CHAINS)
    return ch if isinstance(ch, dict) else {}


def chain_entries(chains, chain):
    return sorted((e for e in chains.get(chain, []) if isinstance(e, dict)), key=lambda e: int(e.get("n", 0)))


def chain_max(entries):
    return max((int(e.get("n", 0)) for e in entries), default=0)


def chain_register(st, sid, chain, folder, n=None):
    """Make sure session `sid` is a link of `chain`: update its entry, take over link n when the thread re-opened it,
    or append it as n (default: max n + 1). Stores chain/chain_n in the thread state and returns n."""
    chains = load_chains()
    entries = chain_entries(chains, chain)
    thread = st.get("jday", {}).get("thread") or thread_url()
    mine = next((e for e in entries if e.get("sid") == sid), None)
    if not mine and n is not None:  # a thread that re-opened link n takes that link over (no duplicate number)
        mine = next((e for e in entries if int(e.get("n", 0)) == n), None)
    if mine:
        mine.update({"sid": sid, "folder": folder})
        if thread:
            mine["thread"] = thread
        n = int(mine["n"])
    else:
        if n is None:
            n = chain_max(entries) + 1
        entries.append({"n": n, "sid": sid, "folder": folder, "thread": thread})
        entries.sort(key=lambda e: int(e["n"]))
    chains[chain] = entries
    put_json(CHAINS, chains)
    st["chain"], st["chain_n"] = chain, n
    return n


def chain_unregister(sid, chain):
    chains = load_chains()
    entries = [e for e in chain_entries(chains, chain) if e.get("sid") != sid]
    if entries:
        chains[chain] = entries
    else:
        chains.pop(chain, None)
    put_json(CHAINS, chains)


def chain_of_folder(chains, folder):
    """(chain, entries) of the chain that holds `folder` (pending links do not count), or (None, [])."""
    for c, entries in chains.items():
        if any(isinstance(e, dict) and e.get("folder") == folder and not e.get("pending") for e in entries):
            return c, chain_entries(chains, c)
    return None, []


def pending_of_folder(chains, folder):
    """(chain, entry) of a named handoff waiting for its thread in `folder`, or (None, None)."""
    for c, entries in chains.items():
        for e in entries:
            if isinstance(e, dict) and e.get("pending") and e.get("folder") == folder:
                return c, e
    return None, None


def parse_thread_name(value):
    """'<chain>-v<N>' -> (chain, N); exits with a clear message when the name breaks the rules."""
    m = re.fullmatch(r"(.+)-v(\d+)", (value or "").strip().lower())
    if not m:
        sys.exit(f"Thread name '{value}' must look like <chain>-v<N>, e.g. recipe-app-research-v1.")
    chain, n = m.group(1), int(m.group(2))
    why = chain_problem(chain)
    if why:
        sys.exit(f"Chain name '{chain}' {why}. Rule: {CHAIN_RULE}")
    if n < 1:
        sys.exit(f"Thread name '{value}': the number must be 1 or higher.")
    return chain, n


def check_next_number(chain, n):
    """A named handoff may use the chain's next number (max + 1) or re-use its own pending number.
    Returns the pending entry it re-uses, or None."""
    entries = chain_entries(load_chains(), chain)
    pend = next((e for e in entries if int(e.get("n", 0)) == n and e.get("pending")), None)
    mx = chain_max(entries)
    if entries and not pend and n != mx + 1:
        sys.exit(f"Thread name '{chain}-v{n}' refused: the chain '{chain}' already goes up to v{mx}, so the next "
                 f"thread is {chain}-v{mx + 1}. Run the command again with --as {chain}-v{mx + 1}.")
    return pend


def chain_add_pending(chain, n, folder, frm, scope=""):
    """Register link n of `chain` as waiting for the thread that will send 'continue <chain>-v<n>'."""
    chains = load_chains()
    entries = [e for e in chain_entries(chains, chain) if int(e.get("n", 0)) != n]  # replaces its own pending entry
    e = {"n": n, "sid": "", "folder": folder, "thread": "", "pending": True, "from": frm}
    if scope:
        e["scope"] = scope
    entries.append(e)
    entries.sort(key=lambda x: int(x["n"]))
    chains[chain] = entries
    put_json(CHAINS, chains)


def chain_claim(chain, n, sid, thread):
    """The thread that sent 'continue <chain>-v<n>' takes over the pending entry n."""
    chains = load_chains()
    entries = chain_entries(chains, chain)
    for e in entries:
        if int(e.get("n", 0)) == n and e.get("pending"):
            e.update({"sid": sid, "thread": thread})
            e.pop("pending", None)
    chains[chain] = entries
    put_json(CHAINS, chains)


def chain_rename_folder(old, new):
    chains = load_chains()
    changed = False
    for entries in chains.values():
        for e in entries:
            if isinstance(e, dict) and e.get("folder") == old:
                e["folder"] = new
                changed = True
    if changed:
        put_json(CHAINS, chains)


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


# ---------------- Stop hook (2.3.0: never blocks below 150K; saving runs in the background) ----------------

HANDOFF_AT = 150_000        # thread size that triggers the one handoff request and the "new thread" note
HANDOFF_FRESH = 120_000     # a handoff written at this size or later counts as the 150K handoff
SILENT_REFRESH_SECS = 10 * 60
ATTEMPT_RE = re.compile(r"\d{2}-\d{2}-\d{4}|-ver\d")  # a name that tries to follow the rule (else: junk, skip silently)


def thread_tokens(transcript):
    """Current thread size: input + cache tokens of the last main-thread (not sidechain) assistant message."""
    size = 0
    try:
        with open(transcript, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if '"usage"' not in line or '"assistant"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") != "assistant" or d.get("isSidechain"):
                    continue
                u = (d.get("message") or {}).get("usage") or {}
                t = sum(int(u.get(k) or 0) for k in
                        ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
                if t:
                    size = t
    except Exception:
        pass
    return size


# ---------------- token use (2.3.1; read from the transcript by the background save: no model call) ----------------

def _chars(x):
    return len(x if isinstance(x, str) else json.dumps(x, ensure_ascii=False))


ARCH_CMD_RE = re.compile(r"archive\.py[\"']?\s+(?:handoff|journal|upload|folder|ignore|tidy|checkname|checkfolder)\b")


def token_stats(transcript):
    """Tokens this thread used, per local day: {day: {"t": total, "b": base, "a": archive, "n": calls}}.
    total = every API call's input + cache + output tokens (subagents included).
    base  = the thread's starting context (system prompt, tools, memory) re-read by every main-thread call.
    archive = estimate: this plugin's text in the context (hook notes, its skill, its commands and their output,
    Stop-hook requests) re-read by every later main-thread call, plus the output of calls that run archive.py."""
    days, seen, arch_ids = {}, set(), set()
    arch = 0      # archive text in the context so far (tokens, chars/4)
    base = None
    try:
        f = open(transcript, encoding="utf-8", errors="ignore")
    except Exception:
        return days
    with f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            typ, side = d.get("type"), d.get("isSidechain")
            if typ == "attachment" and not side:
                a = d.get("attachment") or {}
                if a.get("type") == "hook_additional_context":
                    arch += _chars(a.get("content", "")) // 4
                continue
            msg = d.get("message") or {}
            content = msg.get("content")
            if typ == "user" and not side:
                text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                if ("Stop hook feedback" in text or "claude-archive/skills" in text
                        or any(i in text for i in arch_ids)):
                    arch += len(text) // 4
                continue
            if typ != "assistant":
                continue
            u = msg.get("usage") or {}
            key = (msg.get("id"), d.get("requestId"))
            if not u or key in seen:
                continue
            seen.add(key)
            ctx = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            out = int(u.get("output_tokens") or 0)
            try:
                ts = datetime.datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).astimezone(TZ)
            except Exception:
                continue
            r = days.setdefault(f"{ts:%Y-%m-%d}", {"t": 0, "b": 0, "a": 0, "n": 0})
            r["t"] += ctx + out
            r["n"] += 1
            if side:
                continue
            if base is None:
                base = max(ctx - arch, 0)
            r["b"] += min(base, ctx)
            a_now = min(arch, max(ctx - base, 0))
            calls = [c for c in (content if isinstance(content, list) else []) if c.get("type") == "tool_use"
                     and ARCH_CMD_RE.search(json.dumps(c.get("input"), ensure_ascii=False))]
            if calls:
                arch_ids.update(c.get("id") for c in calls if c.get("id"))
                a_now += out
            r["a"] += a_now
    return days


def thread_project(st):
    """The project a thread's tokens count toward: its chain name, else the product part of its folder name."""
    if st.get("chain"):
        return st["chain"]
    m = FOLDER_RE.fullmatch(st.get("folder") or "")
    return m["project"] if m else ""


def next_thread_name(st):
    """The name the user sends in a new thread to continue this one: a named next thread, else <chain>-v<max+1>."""
    if st.get("named_next"):
        return st["named_next"]
    chain = st.get("chain")
    if chain:
        return f"{chain}-v{chain_max(chain_entries(load_chains(), chain)) + 1}"
    return st.get("folder", "")


def end_line(st, size):
    """'110K continue claude-archive-v3', or '110K send handoff' when the thread has no name yet (shown to the user as a systemMessage: no model call)."""
    name = next_thread_name(st)
    # 2.3.2: a thread with no saved file or handoff yet has no name to continue with; tell the user how to get one
    line = f"{round(size / 1000)}K" + (f" continue {name}" if name else " send handoff")
    return line + (" (over 150K: start a new thread)" if size >= HANDOFF_AT else "")


def handoff_cmd(sid, st):
    script = shlex.quote(os.path.abspath(__file__))
    chain = "" if st.get("chain") else " [--chain <short product name, e.g. garden-planner>]"
    return f"python3 {script} handoff --session {shlex.quote(sid)} --file /tmp/handoff.md{chain}"


HANDOFF_DOC = ("Doc sections: '# <topic, max 8 words>', ## Goal, ## Decisions, ## Current state (versions, file "
               "names, live URLs), ## Next steps, ## Key numbers, ## Highlights (0-3 of the user's goals, max 6 words, "
               "no commas), ## Deliverables (optional: live URLs changed today).")


def cmd_check():
    try:
        hook = json.load(sys.stdin)
    except Exception:
        return
    sid = hook.get("session_id", "unknown")
    transcript = hook.get("transcript_path", "")
    st = load_state(sid)
    size = thread_tokens(transcript)
    # never blocks: a block makes Cowork ask for a second reply, which repeats the first one
    out = {"systemMessage": end_line(st, size)} if size else {}
    background("save", sid, transcript, hook.get("cwd") or os.getcwd())
    if out:
        print(json.dumps(out))


_lock = None


def state_lock():
    """Hold the archive lock until this process ends, so the background save and Claude's commands never
    load and save the thread state at the same time (a handoff during a folder rename would hit a 404)."""
    global _lock
    import fcntl
    os.makedirs(STATE_DIR, exist_ok=True)
    _lock = open(os.path.join(STATE_DIR, "bg.lock"), "w")
    fcntl.flock(_lock, fcntl.LOCK_EX)


def background(*args):
    """Run `archive.py bg <args>` detached, so the turn never waits for uploads."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        log = open(os.path.join(STATE_DIR, "background.log"), "a")
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "bg", *args], stdin=subprocess.DEVNULL,
                         stdout=log, stderr=log, start_new_session=True, close_fds=True)
    except Exception:
        pass


def sent_files(transcript, cwd):
    """Files Claude sent to the user with SendUserFile in this thread."""
    out = []
    try:
        with open(transcript, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if '"SendUserFile"' not in line or '"tool_use"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                for c in (d.get("message") or {}).get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "SendUserFile":
                        for p in (c.get("input") or {}).get("files") or []:
                            out.append(os.path.normpath(os.path.join(cwd, os.path.expanduser(str(p)))))
    except Exception:
        pass
    return out


def thread_title(sid, transcript=""):
    """The chat title: the user's own title wins over the automatic one."""
    path = transcript or transcript_path(sid)
    custom = auto = ""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if '"custom-title"' not in line and '"ai-title"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") == "custom-title" and d.get("customTitle"):
                    custom = str(d["customTitle"])
                elif d.get("type") == "ai-title" and d.get("aiTitle"):
                    auto = str(d["aiTitle"])
    except OSError:
        pass
    return (custom or auto).strip()


def slug(text, words=5):
    return "-".join(re.findall(r"[a-z0-9]+", text.lower())[:words])


def what_part(st, sid, transcript=""):
    """The what-was-done part of an automatic folder name: the thread name (e.g. claude-archive-v4), else the title."""
    return thread_chain_name(st) or slug(thread_title(sid, transcript)) or "work"


def clean_topic(text):
    text = re.sub(r"[;()\[\]{}\n,]", " ", text)
    return " ".join(URL_RE.sub("", text).split()[:TOPIC_WORDS]).rstrip(".:-")


def auto_topic(st, sid, transcript=""):
    """Topic for the journal: the topic line of the handoff doc this thread continued from, else the chat title,
    else the thread name."""
    return clean_topic(st.get("topic_hint") or thread_title(sid, transcript) or thread_chain_name(st)
                       or st.get("folder", ""))


def ver_tuple(v):
    return tuple(int(x) for x in v.split("."))


def auto_folder(st, sid, names, transcript=""):
    """Folder from the deliverable names: <project>-<mm-dd-yyyy>-ver<X.Y.Z>-<thread name>. A newer version of the
    folder's own product renames the folder (links follow)."""
    ms = [NAME_RE.fullmatch(n) for n in names]
    ms = [m for m in ms if m]
    old = st.get("folder")
    fm = FOLDER_RE.fullmatch(old or "")
    if fm:
        same = [m for m in ms if m["project"] == fm["project"]]
        if not same:
            return old
        m = max(same, key=lambda x: ver_tuple(x["ver"]))
        if ver_tuple(m["ver"]) <= ver_tuple(fm["ver"]):
            return old
    elif old:
        return old
    elif ms:
        m = ms[0]
    else:
        return ""
    new = f"{m['project']}-{m['mm']}-{m['dd']}-{m['yyyy']}-ver{m['ver']}-{what_part(st, sid, transcript)}"
    return folder_name(st, new) if not folder_problem(new) else (old or "")


def cmd_bg(args):
    """Background save after each turn: upload rule-named files (outputs folder + files sent with SendUserFile),
    tidy older versions, keep the journal current, refresh the viewer. Never talks to the model."""
    if len(args) < 4 or args[0] != "save":
        return
    sid, transcript, cwd = args[1], args[2], args[3]
    state_lock()  # one save at a time; a later turn's save (or a handoff) waits for this one
    st = load_state(sid)
    t = now()
    day = f"{t:%Y-%m-%d}"
    jd = st.get("jday", {})
    if jd.get("day") != day:
        jd = st["jday"] = {"day": day, "deliverables": {}}
    changed = False
    if not jd.get("topic"):
        jd["topic"] = auto_topic(st, sid, transcript)
        changed = bool(jd["topic"])
    # candidate files
    ignored = set(st.get("ignore", []))
    seen, todo = set(), []
    for p in output_files() + sent_files(transcript, cwd):
        rp = os.path.realpath(p)
        if rp in seen or not os.path.isfile(p):
            continue
        seen.add(rp)
        name = top_name(p)
        if name in ignored or name.startswith("."):
            continue
        why = name_problem(name)
        if why:
            if ATTEMPT_RE.search(name) and name not in st.get("reported", []):
                st.setdefault("problems", {})[name] = why
            continue
        sig = [os.path.getmtime(p), os.path.getsize(p)]
        if st.get("up", {}).get(p) != sig:
            todo.append((p, name, sig))
    if todo:
        folder = auto_folder(st, sid, sorted({n for _, n, _ in todo}), transcript)
        if folder:
            base = f"/{folder}"
            mkdirs(base)
            existing = remote_sizes(base)
            new_tops = set()
            for p, name, sig in todo:
                rel = os.path.relpath(p, OUTPUTS) if p.startswith(OUTPUTS + os.sep) else os.path.basename(p)
                r = rel.replace(os.sep, "/")
                if sig[1] not in (existing.get(r), existing.get(f"{OLDER}/{r}")):
                    if os.path.dirname(rel):
                        mkdirs(f"{base}/{os.path.dirname(r)}")
                    code, _ = curl("-T", p, DAV + q(f"{base}/{r}"))
                    if code not in (200, 201, 204):
                        print(f"{t:%m-%d-%Y %H:%M} upload failed ({code}): {p}")
                        continue  # retried after the next turn
                    new_tops.add(name)
                    st["files_uploaded"] = st.get("files_uploaded", 0) + 1
                    print(f"{t:%m-%d-%Y %H:%M} uploaded {folder}/{r}")
                st.setdefault("up", {})[p] = sig
            for name in sorted(new_tops):
                m = NAME_RE.fullmatch(name)
                text = f"{m['project']} ver{m['ver']} {m['type']}"
                jd["deliverables"][text] = [t.timestamp(), file_links(folder, [name])]
                changed = True
            save_state(sid, st)
            if new_tops:
                try:
                    relink_state(st, tidy_folder(folder))
                except Exception as e:
                    print("older versions not tidied:", e)
    if changed or t.timestamp() - st.get("jrefresh", 0) > SILENT_REFRESH_SECS:
        try:
            publish_day(sid, st, transcript)
            changed = True
        except Exception as e:
            print("journal not updated:", e)
    save_state(sid, st)
    if changed:
        refresh_viewer()


# ---------------- upload (manual) ----------------

def cmd_upload(a):
    st = load_state(a.session)
    folder = folder_name(st, a.folder)
    base = f"/{folder}"
    mkdirs(base)
    existing = remote_sizes(base)
    sent = 0
    for p in [p for p in a.files if os.path.isfile(p)]:
        name = os.path.basename(p)
        if os.path.getsize(p) in (existing.get(name), existing.get(f"{OLDER}/{name}")):
            continue
        put_file(p, f"{base}/{name}")
        sent += 1
        print("uploaded", name)
    st["files_uploaded"] = st.get("files_uploaded", 0) + sent
    save_state(a.session, st)
    print(f"{sent} uploaded. folder: {folder}")


def cmd_folder(a):
    """Set or fix this thread's folder name (the folder is renamed on Nextcloud and its links follow)."""
    st = load_state(a.session)
    print("folder:", folder_name(st, a.name))
    save_state(a.session, st)


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


def record_lines(jd, day, key, lines, chain="", tok=None):
    """Store one thread's lines for the day: the topic line (topic, time, folder) plus its deliverable lines.
    `chain` is the thread's chain name (e.g. garden-planner-v3) when it has one."""
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
    chain = chain or old.get("chain", "")
    if chain:
        rec[key]["chain"] = chain
    if tok or old.get("tok"):
        rec[key]["tok"] = tok or old["tok"]


def thread_chain_name(st):
    """'<chain>-v<n>' for a thread that belongs to a chain, else ''."""
    return f"{st['chain']}-v{st['chain_n']}" if st.get("chain") and st.get("chain_n") else ""


def write_journal(t, lines=None, key="", note="", chain="", toks=None, project=""):
    """Save a thread's lines (or one of the user's notes) for today in the journal record, plus its token use
    for each day it ran (toks: {day: {...}} from token_stats)."""
    day = f"{t:%Y-%m-%d}"
    jd = get_json(JDAYS)
    if key and lines:
        tk = (toks or {}).get(day)
        record_lines(jd, day, key, lines, chain, dict(tk, p=project) if tk else None)
    if key:
        for d, tk in (toks or {}).items():  # earlier days of a thread that ran past midnight
            e = jd.get(d, {}).get(key)
            if d != day and isinstance(e, dict):
                e["tok"] = dict(tk, p=project)
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
    try:
        toks = token_stats(transcript) if transcript else {}
    except Exception:
        toks = {}
    write_journal(t, lines, st.get("jday", {}).get("thread") or sid, chain=thread_chain_name(st),
                  toks=toks, project=thread_project(st))
    st["jrefresh"] = t.timestamp()
    save_state(sid, st)
    return True


def cmd_journal(a):
    """Manual journal edit (rarely needed: the background save writes topic and file deliverables itself)."""
    bad = []
    if a.topic and text_problem(a.topic, TOPIC_WORDS):
        bad.append((a.topic, text_problem(a.topic, TOPIC_WORDS)))
    if len(a.highlight) > HL_MAX:
        bad.append(("--highlight", f"{len(a.highlight)} given (max {HL_MAX})"))
    bad += [(h, text_problem(h, HL_WORDS, commas_ok=False)) for h in a.highlight if text_problem(h, HL_WORDS, False)]
    bad += [(d, text_problem(d, DELIV_WORDS) or "needs the URL of the live page") for d in a.deliverable
            if text_problem(d, DELIV_WORDS) or not URL_RE.search(d)]
    if bad:
        sys.exit("JOURNAL NOT UPDATED. Fix these:\n" + "\n".join(f"  '{x}': {why}" for x, why in bad)
                 + f"\nRule: {JOURNAL_RULE}")
    st = load_state(a.session)
    if a.folder:
        folder_name(st, a.folder)
    set_journal(st, a.topic, a.highlight, a.deliverable)
    try:
        publish_day(a.session, st, a.transcript or transcript_path(a.session))
    except RuntimeError as e:
        sys.exit(str(e))
    print("journal updated")


def set_journal(st, topic="", highlights=None, deliverables=()):
    """Store today's topic, highlights (full set) and live-URL deliverables in the thread state."""
    t = now()
    jd = st.get("jday", {})
    if jd.get("day") != f"{t:%Y-%m-%d}":
        jd = {"day": f"{t:%Y-%m-%d}", "deliverables": {}}
    if topic:
        jd["topic"] = clean_topic(topic)
    if highlights is not None and (highlights or topic):
        jd["highlights"] = [" ".join(h.replace(",", " ").split()[:HL_WORDS]).rstrip(".") for h in highlights[:HL_MAX]]
    for d in deliverables:
        url = URL_RE.search(d)
        if url and d not in jd["deliverables"]:
            jd["deliverables"][" ".join(d.split())] = [t.timestamp(), url.group(0)]
    st["jday"] = jd


# ---------------- handoff doc ----------------

def handoff_name(folder):
    m = FOLDER_RE.fullmatch(folder)
    what = "" if m["what"] == "handoff" else f"{m['what']}-"  # a named-handoff folder (...-ver0.1.0-handoff)
    return f"{m['project']}-{what}handoff-{m['mm']}-{m['dd']}-{m['yyyy']}-ver{m['ver']}-documentation.md"


def _str_arg(a, name):
    v = getattr(a, name, "")
    return v.strip() if isinstance(v, str) else ""


def from_thread(st, sid):
    return thread_url() or st.get("jday", {}).get("thread") or sid


def cmd_handoff(a):
    """Upload Claude's handoff notes as the thread folder's handoff doc (one per folder, updated in place).
    --as <chain>-v<N> names the NEXT thread (pending chain entry); --scope adds a topic-only doc in its own folder."""
    st = load_state(a.session)
    as_name, scope = _str_arg(a, "as_name").lower(), " ".join(_str_arg(a, "scope").split())
    if scope and not as_name:
        sys.exit("--scope needs --as <chain>-v<N> (the name of the new thread that takes over that topic).")
    body = open(a.file, encoding="utf-8").read().strip()
    if len(body) < 200:
        sys.exit("Handoff doc too short - it must let a new thread continue the work without this one.")
    next_chain = next_n = None
    if as_name:
        next_chain, next_n = parse_thread_name(as_name)
        pend = check_next_number(next_chain, next_n)
        if scope:
            return scoped_handoff(a, st, next_chain, next_n, scope, body, pend)
    if not a.folder and not st.get("folder"):  # no deliverables yet: a work folder named after the chain/title
        tn = thread_title_name(a.session)
        base = _str_arg(a, "chain").lower() or (tn[0] if tn else "") or st.get("chain") \
            or slug(thread_title(a.session), 4) or "thread"
        a.folder = f"{base}-{now():%m-%d-%Y}-ver0.1.0-work"
    folder = folder_name(st, a.folder)
    # thread chain: --chain, else the chain this thread already belongs to, else the folder's project name
    # (a named handoff never puts this thread into a chain it is not in yet)
    chain = _str_arg(a, "chain").lower()
    if chain:
        why = chain_problem(chain)
        if why:
            sys.exit(f"Chain name '{chain}' {why}. Rule: {CHAIN_RULE}")
    title_n = None
    if not chain:
        # 2.2.1: a thread the user named like "garden-planner-redesign-v1" uses that name, over an inherited chain
        named_title = thread_title_name(a.session)
        if named_title:
            chain, title_n = named_title
        else:
            chain = st.get("chain") or ("" if as_name else chain_default(folder))
    if st.get("chain") and chain and st["chain"] != chain:  # moved to another chain: leave the old one
        chain_unregister(a.session, st["chain"])
        st.pop("chain_n", None)
    n = nxt = None
    if chain:
        # a thread that re-opened link n keeps that number; a new thread gets the next free one;
        # a thread named <chain>-v<N> takes link N unless another thread already holds it
        want = st.get("chain_n") if st.get("chain") == chain else None
        if title_n is not None and want is None:
            held = next((e for e in chain_entries(load_chains(), chain)
                         if int(e.get("n", 0)) == title_n and e.get("sid") not in ("", a.session) and not e.get("pending")), None)
            want = None if held else title_n
        n = chain_register(st, a.session, chain, folder, want)
        nxt = chain_max(chain_entries(load_chains(), chain)) + 1  # the next free number = a new link in the chain
    # the next thread's name: given now with --as, or an earlier named handoff of this thread still waiting
    named = f"{next_chain}-v{next_n}" if as_name else ""
    if not named and st.get("named_next"):
        c, _, k = st["named_next"].rpartition("-v")
        e = next((x for x in chain_entries(load_chains(), c) if str(x.get("n")) == k), None)
        if e and e.get("pending") and e.get("folder") == folder:
            named = st["named_next"]
        else:
            st.pop("named_next", None)
    cont = named or f"{chain}-v{nxt}"
    name = handoff_name(folder)
    existing = [n_ for n_ in remote_sizes("/" + folder) if n_.endswith("-documentation.md") and "-handoff-" in n_]
    threads = []
    for n_ in existing:
        c, old = curl(DAV + q(f"/{folder}/{n_}"))
        if c == 200:
            for u in re.findall(r"\]\((https://claude\.ai/code/session_[^)]+)\)", handoff_head(old)):
                if u not in threads:
                    threads.append(u)
    url = thread_url()
    if url and url not in threads:
        threads.append(url)
    head = (f"# Handoff: {folder}\n"
            + (f"Thread name: {chain}-v{n}\n" if chain else "")
            + (f"Next thread name: {named}\n" if named else "")
            + "Threads: " + " ".join(f"[{i + 1}]({u})" for i, u in enumerate(threads)) + "\n"
            f"Updated: {now():%m-%d-%Y %I:%M%p}\n"
            f"To continue in a new thread, send: continue {cont}\n\n")
    tmp = os.path.join(STATE_DIR, "handoff.md")
    os.makedirs(STATE_DIR, exist_ok=True)
    open(tmp, "w", encoding="utf-8").write(head + body + "\n")
    put_file(tmp, f"/{folder}/{name}")
    for n_ in existing:
        if n_ != name:
            curl("-X", "DELETE", DAV + q(f"/{folder}/{n_}"))
    if as_name:
        chain_add_pending(next_chain, next_n, folder, from_thread(st, a.session))
        st["named_next"] = named
    st["handoff_at"] = now().timestamp()
    st["handoff_tokens"] = thread_tokens(transcript_path(a.session))
    topic, hls, dls = doc_journal(body)
    set_journal(st, topic, hls, dls)
    try:
        publish_day(a.session, st, transcript_path(a.session))
    except Exception:
        pass
    save_state(a.session, st)
    try:  # 2.2.2: the next new thread takes this name as its chat title (SessionStart hook)
        put_json(NEXT_TITLE, {"title": cont, "at": now().timestamp(), "from": a.session})
    except Exception:
        pass
    print(f"handoff doc updated: {name}"
          + (f"\nthread name: {chain}-v{n}" if chain else "")
          + (f"\nnext thread name: {named}" if named else "")
          + f"\nto continue in a new thread, send: continue {cont}")


def doc_section(body, title):
    m = re.search(r"^##\s*" + title + r"\s*\n(.*?)(?=^#|\Z)", body, re.M | re.S | re.I)
    return [re.sub(r"^[-*\d.)\s]+", "", x).strip() for x in m.group(1).splitlines() if x.strip()] if m else []


def doc_journal(body):
    """(topic, highlights, deliverables) from a handoff doc: its '# ' title, '## Highlights', '## Deliverables'."""
    m = re.search(r"^# (.+)$", body, re.M)
    hls = doc_section(body, "Highlights")
    return (m.group(1) if m else ""), (hls if hls else None), doc_section(body, "Deliverables")


def scoped_handoff(a, st, chain, n, scope, body, pend):
    """'handoff just the discussion about X as <chain>-v<N>': a topic-only handoff doc in its own new folder.
    The current thread's own handoff doc, folder and state stay as they are."""
    folder = pend.get("folder") if pend and pend.get("scope") and pend.get("folder") else \
        f"{chain}-{now():%m-%d-%Y}-ver0.1.0-handoff"
    used = {e.get("folder") for e in chain_entries(load_chains(), chain) if int(e.get("n", 0)) != n}
    if folder in used:  # another link of this chain already uses that folder (same day): keep them apart
        folder = f"{folder}-v{n}"
    why = folder_problem(folder)
    if why:
        sys.exit(f"Folder name '{folder}' {why}. Rule: {FOLDER_RULE}")
    frm = from_thread(st, a.session)
    name = handoff_name(folder)
    head = (f"# Handoff: {folder}\n"
            f"Next thread name: {chain}-v{n}\n"
            f"Scope: {scope}\n"
            f"From thread: " + (f"[{frm}]({frm})" if frm.startswith("http") else frm) + "\n"
            f"Updated: {now():%m-%d-%Y %I:%M%p}\n"
            f"To continue in a new thread, send: continue {chain}-v{n}\n\n")
    tmp = os.path.join(STATE_DIR, "handoff-scoped.md")
    os.makedirs(STATE_DIR, exist_ok=True)
    open(tmp, "w", encoding="utf-8").write(head + body + "\n")
    mkdirs("/" + folder)
    put_file(tmp, f"/{folder}/{name}")
    chain_add_pending(chain, n, folder, frm, scope)
    print(f"scoped handoff doc saved: {folder}/{name}\nscope: {scope}\nnext thread name: {chain}-v{n}\n"
          f"(this thread's own handoff doc is unchanged)\nto continue in a new thread, send: continue {chain}-v{n}")


def handoff_head(doc):
    """The header part of a handoff doc (everything before the notes), where the thread links live."""
    text = doc.decode("utf-8", "ignore") if isinstance(doc, bytes) else doc
    i = text.find("To continue in a new thread")
    return text[:i] if i >= 0 else text.split("\n\n")[0]


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
        name = c.group(1).lower()
        v = re.fullmatch(r"(.+)-v(\d+)", name)
        if v and not chain_problem(v.group(1)):
            return continue_chain(hook, v.group(1), int(v.group(2)))
        return continue_thread(hook, name)
    m = re.fullmatch(r"journal\s*:\s*(.+)", prompt, re.I | re.S)
    if not m:
        named = NAMED_HANDOFF_RE.search(prompt)
        if named:
            return named_handoff_context(hook, named)
        notes = []
        sid = hook.get("session_id", "unknown")
        st = load_state(sid, local_only=True)
        size = thread_tokens(hook.get("transcript_path", ""))
        if size >= HANDOFF_AT:
            if not st.get("asked_150") and st.get("handoff_tokens", 0) < HANDOFF_FRESH \
                    and not PLAIN_HANDOFF_RE.fullmatch(prompt):
                st["asked_150"] = True
                save_state(sid, st)
                notes.append(f"Claude Archive: thread passed 150K. While answering, also write the handoff doc "
                             f"(heredoc to /tmp/handoff.md, inside a Bash call you make anyway if you can) and run: "
                             f"{handoff_cmd(sid, st)}. {HANDOFF_DOC}")
            notes.append(f"Claude Archive: end your reply with this line: {end_line(st, size)}")
        if PLAIN_HANDOFF_RE.fullmatch(prompt):
            notes.append(f"Claude Archive: write the handoff doc in ONE Bash call (heredoc to /tmp/handoff.md), then "
                         f"run: {handoff_cmd(sid, st)}. {HANDOFF_DOC}")
        if st.get("problems"):
            notes.append("Claude Archive skipped these (name breaks name-mm-dd-yyyy-verX.Y.Z-type): "
                         + ", ".join(f"{n} ({w})" for n, w in sorted(st["problems"].items()))
                         + ". Rename current deliverables inside a call you make anyway; ignore old ones "
                         f"(python3 {shlex.quote(os.path.abspath(__file__))} ignore --session {sid} <name>).")
            st["reported"] = sorted(set(st.get("reported", [])) | set(st["problems"]))
            st["problems"] = {}
            save_state(sid, st)
        if notes:
            hook_context("\n".join(notes))
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


PLAIN_HANDOFF_RE = re.compile(r"(?:please\s+)?(?:make|write|do|update)?\s*(?:a|the)?\s*hand[\s-]?off(?:\s+doc)?"
                              r"(?:\s+now)?[.!]?", re.I)


def hook_context(text):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}))


# "start the new thread as X-v1" / "handoff thread as X-v1" / "handoff just the discussion about T as X-v1"
NAMED_HANDOFF_RE = re.compile(
    r"\b(?:start(?:ing)?\s+(?:a\s+|the\s+)?new\s+thread"
    r"|hand[\s-]?off\s+(?:this\s+|the\s+)?thread"
    r"|hand[\s-]?off\s+(?:just|only)\s+(?:the\s+)?(?:discussion|part|conversation|work|topic|bit)\s+"
    r"(?:about|on|of|regarding|re:?)\s+(?P<topic>.+?))"
    r"[\s,:;]+as\s*[:=]?\s*[\"'`*]*(?P<name>[a-z0-9]+(?:-[a-z0-9]+)*-v\d+)\b",
    re.I | re.S)


def named_handoff_context(hook, m):
    """Tell Claude how to write and register the handoff the user just asked for (the prompt is not blocked)."""
    name = m.group("name").lower()
    topic = " ".join((m.group("topic") or "").split()).strip(" \"'`*,.;:")
    sid = hook.get("session_id", "unknown")
    v = re.fullmatch(r"(.+)-v(\d+)", name)
    why = chain_problem(v.group(1)) if v else "is not <chain>-v<N>"
    if why or int(v.group(2)) < 1:
        return hook_context(
            f"Claude Archive: the user asked for a handoff to a new thread named '{name}', but that name "
            f"{why or 'needs a number of 1 or higher'} (rule for the part before -v<N>: {CHAIN_RULE}). Tell the user "
            "in one sentence and suggest a corrected name; do not run the handoff command until they confirm it.")
    st = load_state(sid)
    cmd = f"{handoff_cmd(sid, st).split(' [--chain')[0]} --as {shlex.quote(name)}"
    if topic:
        cmd += f" --scope {shlex.quote(topic)}"
        what = f"ONLY the discussion about \"{topic}\" (it goes into its own new folder)"
    else:
        what = "the whole thread"
    hook_context(
        f"Claude Archive: the user wants a handoff to a new thread named {name}. In ONE Bash call write the doc for "
        f"{what} with a heredoc to /tmp/handoff.md and run: {cmd}. {HANDOFF_DOC} If the command refuses the number, "
        "tell the user the number it says is next. "
        + (f"Tell the user to paste this as the only text in a new thread: continue {name}" if topic else
           "Write no continue line yourself."))


def continue_chain(hook, chain, want):
    """'continue <chain>-v<N>': N = next number -> this thread becomes link N of the chain (continuing the newest
    thread's handoff); N = an existing link -> re-open that thread's work; N too high -> adjusted to the next number.
    N = a pending link (named in an earlier handoff) -> this thread claims it and loads that handoff doc."""
    chains = load_chains()
    entries = chain_entries(chains, chain)
    if not entries:
        return hook_context(f"Claude Archive: there is no thread chain named '{chain}' (the user sent 'continue "
                            f"{chain}-v{want}'). Tell the user no thread chain of that name exists and ask for the "
                            "Nextcloud folder name (or the right chain name) to continue from.")
    pend = next((e for e in entries if int(e.get("n", 0)) == want and e.get("pending")), None)
    if pend:
        return continue_thread(hook, pend["folder"], chain=chain, n=want, register=False, claim=True,
                               note=pending_note(chain, want, pend))
    mx = chain_max(entries)
    if want <= mx:
        e = ([x for x in entries if int(x.get("n", 0)) <= want] or entries[:1])[-1]  # the link asked for (or nearest)
        want = int(e["n"])
        return continue_thread(hook, e["folder"], chain=chain, n=want, register=False,
                               note=f"This thread re-opens {chain}-v{want}.")
    note = f"This thread is {chain}-v{mx + 1}, the newest link of the chain."
    if want > mx + 1:
        note += (f" The user asked for v{want}, but the chain only had v1-v{mx}, so the number was adjusted to "
                 f"v{mx + 1}: mention that.")
    return continue_thread(hook, entries[-1]["folder"], chain=chain, n=mx + 1, register=True, note=note)


def pending_note(chain, n, entry):
    scope = entry.get("scope")
    return (f"This thread is {chain}-v{n}, the new thread the user named in an earlier handoff"
            + (f" (it covers only: {scope})" if scope else "") + ".")


def continue_thread(hook, folder, chain=None, n=None, register=True, note="", claim=False):
    """New thread picks up an old one: load its handoff doc and adopt its folder (and chain).
    claim=True: take over the pending chain entry n (a named handoff waiting for this thread)."""
    docs = [d for d in remote_sizes("/" + folder) if "-handoff-" in d and d.endswith(".md")]
    if not docs:
        return hook_context(f"Claude Archive: no handoff doc found in Nextcloud folder '{folder}'. "
                            "Tell the user and ask which folder.")
    code, body = curl(DAV + q(f"/{folder}/{docs[0]}"))
    sid = hook.get("session_id", "unknown")
    st = load_state(sid)
    st["folder"] = folder
    if chain is None:  # plain 'continue <folder>': claim a named handoff waiting there, else join the folder's chain
        chains = load_chains()
        pc, pe = pending_of_folder(chains, folder)
        if pc:
            chain, n, register, claim = pc, int(pe["n"]), False, True
            note = pending_note(pc, n, pe)
        else:
            chain, _ = chain_of_folder(chains, folder)
            n, register = None, True
    if claim:
        chain_claim(chain, n, sid, st.get("jday", {}).get("thread") or thread_url())
        st.pop("named_next", None)
    if chain:
        if register:
            n = chain_register(st, sid, chain, folder, n)
        else:
            st["chain"], st["chain_n"] = chain, n
        note = note or f"This thread is {chain}-v{n}."
        note += " Say the thread name in your first reply."
    doc = body.decode("utf-8", "ignore")
    topic, _, _ = doc_journal(doc[len(handoff_head(doc)):])
    if topic:
        st["topic_hint"] = topic
    save_state(sid, st)
    ctx = (f"Claude Archive: continuing earlier work; folder '{folder}'. " + (note + " " if note else "")
           + "Confirm in one or two sentences where things stand and ask what to do next.\n\n" + doc)
    hook_context(ctx)


# ---------------- chat title (2.2.2, test) ----------------

NEXT_TITLE = "/.state/next-thread-title.json"  # {"title": "<chain>-v<N>", "at": ts, "from": sid}, written by handoff
TITLE_LOG = "/.state/sessionstart-log.json"    # last SessionStart runs, to check whether the title was set
NEXT_TITLE_MAX_AGE = 48 * 3600


def cmd_sessionstart():
    """SessionStart hook: a newly opened thread takes the name the last handoff gave the next thread
    (e.g. recipe-app-v3) as its chat title. The name is used once, then cleared."""
    try:
        hook = json.load(sys.stdin)
    except Exception:
        hook = {}
    sid, source = hook.get("session_id", ""), hook.get("source", "")
    title, why = "", ""
    try:
        nt = get_json(NEXT_TITLE)
        if source != "startup":
            why = f"source {source or 'unknown'}: only new threads get a title"
        elif not nt.get("title"):
            why = "no waiting name"
        elif nt.get("from") == sid:
            why = "same thread that made the handoff"
        elif now().timestamp() - float(nt.get("at", 0)) > NEXT_TITLE_MAX_AGE:
            why = "waiting name older than 48 hours"
        else:
            title = str(nt["title"])
            curl("-X", "DELETE", DAV + q(NEXT_TITLE))
        log = get_json(TITLE_LOG)
        runs = log.get("runs", []) if isinstance(log, dict) else []
        runs = (runs + [{"at": f"{now():%m-%d-%Y %I:%M:%S%p}", "sid": sid, "source": source, "title": title, "why": why}])[-20:]
        put_json(TITLE_LOG, {"runs": runs})
    except Exception:
        pass
    if title:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "sessionTitle": title}}))


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
    if len(sys.argv) > 1 and sys.argv[1] == "sessionstart":
        return cmd_sessionstart()
    if len(sys.argv) > 1 and sys.argv[1] == "prompt":
        return cmd_prompt()
    if len(sys.argv) > 1 and sys.argv[1] == "bg":
        return cmd_bg(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        ensure_root()
        print(f"OK: logged in to {HOST} as {USER}, archive folder '{ROOT_FOLDER}' found.")
        return
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    u = sp.add_parser("upload"); u.add_argument("--session", required=True)
    u.add_argument("--folder", default=""); u.add_argument("files", nargs="+")
    h = sp.add_parser("handoff"); h.add_argument("--session", required=True); h.add_argument("--folder", default="")
    h.add_argument("--file", required=True); h.add_argument("--chain", default="")
    h.add_argument("--tools", default="", help=argparse.SUPPRESS)  # accepted for old commands, unused
    h.add_argument("--as", dest="as_name", default="", help="name the NEXT thread: <chain>-v<N>")
    h.add_argument("--scope", default="", help="with --as: hand off only this topic, into its own new folder")
    fo = sp.add_parser("folder"); fo.add_argument("--session", required=True); fo.add_argument("name")
    i = sp.add_parser("ignore"); i.add_argument("--session", required=True); i.add_argument("names", nargs="+")
    ty = sp.add_parser("tidy"); ty.add_argument("--all", action="store_true"); ty.add_argument("folders", nargs="*")
    j = sp.add_parser("journal"); j.add_argument("--session", required=True)
    j.add_argument("--folder", default="")
    j.add_argument("--topic", default=""); j.add_argument("--highlight", action="append", default=[])
    j.add_argument("--deliverable", action="append", default=[])
    j.add_argument("--transcript", default="")
    a = p.parse_args()
    state_lock()
    try:
        {"upload": cmd_upload, "journal": cmd_journal, "ignore": cmd_ignore, "folder": cmd_folder,
         "handoff": cmd_handoff, "tidy": cmd_tidy}[a.cmd](a)
    finally:
        if a.cmd in ("upload", "journal", "handoff", "folder"):
            refresh_viewer()


if __name__ == "__main__":
    main()
