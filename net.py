"""
HTTP for the whole app.

* Safe to use from several download threads at once (one curl session per thread).
* Per-site pacing is shared by all threads, so 5 parallel downloads never hammer one site.
* Cloudflare "human check" pages are recognised instead of being mistaken for empty results.
  If the check window is available, that site's pages are then fetched through it.
* Big downloads retry and resume where they stopped instead of starting over.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile

from browser_helper import looks_like_challenge

try:
    from curl_cffi import requests as _cffi
except Exception:            # still runs, but Cloudflare-protected hosts will refuse
    _cffi = None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
IS_WIN = sys.platform.startswith("win")


class Stopped(Exception):
    pass


class SourceError(Exception):
    """A source tried and gave a clear reason why it could not deliver."""


class Interrupted(SourceError):
    """A download kept failing part-way. What arrived so far is kept, so it can resume later."""

    def __init__(self, host, got):
        self.host, self.got = host, got
        super().__init__(f"connection to {host} kept dropping ({got // 1024} KB kept; press Resume to continue)")


class ChallengeError(SourceError):
    """A site answered with a Cloudflare human check that was not passed."""

    def __init__(self, host, detail=""):
        self.host = host
        super().__init__(f"{host} is showing a 'verify you are human' check"
                         + (f" ({detail})" if detail else ""))


class Resp:
    def __init__(self, status, content, headers, url):
        self.status, self.content, self.headers, self.url = status, content, headers, url

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)


def is_challenge(resp):
    if resp.headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    return looks_like_challenge(resp.status, resp.text[:6000])


class Net:
    def __init__(self, bridge=None, stop=None, log=None, verify_timeout=300):
        self._tl = threading.local()
        self._lock = threading.Lock()
        self._browser_lock = threading.Lock()   # one check-window request at a time
        self._next = {}                 # host -> earliest time the next request may start
        self.bridge = bridge            # BrowserBridge or None
        self.browser_hosts = set()      # hosts whose pages now go through the check window
        self.failed_hosts = {}          # host -> reason: the human check was not passed this run
        self.stop = stop or threading.Event()
        self.log = log or (lambda m: None)
        self.verify_timeout = verify_timeout

    # ---------------------------------------------------------------- plumbing
    def _session(self):
        s = getattr(self._tl, "s", None)
        if s is None and _cffi:
            s = self._tl.s = _cffi.Session(impersonate="chrome")
        return s

    def _sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self.stop.is_set():
                raise Stopped()
            time.sleep(min(0.25, max(0.0, end - time.time())))

    def _slot(self, url, gap):
        """Reserve this host's next free time slot (shared by all threads) and wait for it."""
        if gap <= 0:
            return
        host = urllib.parse.urlsplit(url).netloc
        with self._lock:
            now = time.time()
            start = max(now, self._next.get(host, 0.0))
            self._next[host] = start + gap
        self._sleep(start - now)

    def _direct(self, method, url, data, json_body, headers, timeout, allow_redirects):
        h = {"Accept-Language": "en-US,en;q=0.9"}
        h.update(headers or {})
        s = self._session()
        if s:
            r = s.request(method, url, data=data, json=json_body, headers=h, timeout=timeout,
                          allow_redirects=allow_redirects)
            return Resp(r.status_code, r.content, {k.lower(): v for k, v in r.headers.items()}, str(r.url))
        h.setdefault("User-Agent", UA)
        body = None
        if json_body is not None:
            body = json.dumps(json_body).encode()
            h["Content-Type"] = "application/json"
        elif data is not None:
            body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(url, data=body, headers=h, method=method)
        opener = urllib.request.build_opener(*([] if allow_redirects else [_NoRedirect()]))
        try:
            with opener.open(req, timeout=timeout) as r:
                return Resp(r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}, r.geturl())
        except urllib.error.HTTPError as e:
            return Resp(e.code, e.read() or b"", {k.lower(): v for k, v in e.headers.items()}, url)

    def _via_browser(self, method, url, data, allow_redirects):
        host = urllib.parse.urlsplit(url).netloc
        if host in self.failed_hosts:            # another thread already waited for this check
            raise ChallengeError(host, self.failed_hosts[host])
        if not allow_redirects:
            raise SourceError(f"{host} needs the check window, which can't do this step")
        with self._browser_lock:
            if host in self.failed_hosts:        # failed while this thread was queued
                raise ChallengeError(host, self.failed_hosts[host])
            try:
                res = self.bridge.request(method, url, data=data, verify_timeout=self.verify_timeout,
                                          stop=self.stop)
            except InterruptedError:
                raise Stopped()
            except Exception as e:
                raise SourceError(f"check window: {e}")
            if not res.get("ok") and res.get("challenge"):
                self.failed_hosts.setdefault(host, res.get("error", "not completed"))
        if not res.get("ok"):
            if res.get("challenge"):
                raise ChallengeError(host, self.failed_hosts[host])
            raise SourceError(f"check window: {res.get('error', 'failed')}")
        return Resp(res.get("status", 0), (res.get("text") or "").encode("utf-8"), {}, res.get("url") or url)

    def browser_form(self, url, form="F1"):
        """Let the check window open a download page, pass its widget/countdown and submit the form."""
        host = urllib.parse.urlsplit(url).netloc
        if self.bridge is None:
            raise ChallengeError(host, "turn on the check window in Settings to pass it")
        with self._browser_lock:
            if host in self.failed_hosts:
                raise ChallengeError(host, self.failed_hosts[host])
            try:
                res = self.bridge.submit_form(url, form=form, verify_timeout=self.verify_timeout, stop=self.stop)
            except InterruptedError:
                raise Stopped()
            except Exception as e:
                raise SourceError(f"check window: {e}")
            if not res.get("ok") and res.get("challenge"):
                self.failed_hosts.setdefault(host, res.get("error", "not completed"))
        if not res.get("ok"):
            if res.get("challenge"):
                raise ChallengeError(host, self.failed_hosts[host])
            raise SourceError(f"check window: {res.get('error', 'failed')}")
        return Resp(res.get("status", 0), (res.get("text") or "").encode("utf-8"), {}, res.get("url") or url)

    # ---------------------------------------------------------------- public
    def request(self, method, url, data=None, json_body=None, headers=None, timeout=40, gap=0.0,
                allow_redirects=True, retries=2):
        host = urllib.parse.urlsplit(url).netloc
        if host in self.browser_hosts and json_body is None:
            self._slot(url, gap)
            return self._via_browser(method, url, data, allow_redirects)
        resp, last_err = None, None
        for attempt in range(retries + 1):
            if self.stop.is_set():
                raise Stopped()
            self._slot(url, gap)
            try:
                resp = self._direct(method, url, data, json_body, headers, timeout, allow_redirects)
            except Exception as e:                       # connection reset, DNS, timeout...
                last_err, resp = e, None
                if attempt < retries:
                    self._sleep(3 * (attempt + 1))
                    continue
                raise SourceError(f"could not reach {host} ({type(e).__name__})")
            if is_challenge(resp):
                break
            if resp.status in (429, 500, 502, 503, 504) and attempt < retries:
                self._sleep(5 * (attempt + 1))
                continue
            break
        if resp is None:
            raise SourceError(f"could not reach {host} ({last_err})")
        if is_challenge(resp):
            if self.bridge is not None and json_body is None:
                with self._lock:
                    first = host not in self.browser_hosts
                    self.browser_hosts.add(host)
                if first:
                    self.log(f"{host} wants a human check; opening it in the check window.")
                return self._via_browser(method, url, data, allow_redirects)
            raise ChallengeError(host, "turn on the check window in Settings to pass it")
        return resp

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def get_json(self, url, **kw):
        r = self.get(url, headers={"Accept": "application/json", **kw.pop("headers", {})}, **kw)
        if r.status != 200:
            raise SourceError(f"HTTP {r.status} from {urllib.parse.urlsplit(url).netloc}")
        return r.json()

    def download(self, url, folder, filename=None, headers=None, progress=None, retries=6, key=None):
        """Stream url into folder and return the saved path.

        Resumable across dropped connections, Pause and app restarts: what arrived is kept in
        `.partial` with a small `.partial.json` note (which file it is, its size and the server's
        version tag). Next time the download continues from there with a Range request; If-Range makes
        the server send the whole file instead if it changed meanwhile. `key` identifies the file across
        sessions (signed links change every time); by default the link without its query string."""
        os.makedirs(folder, exist_ok=True)
        part = os.path.join(folder, ".partial")
        note_path = part + ".json"
        key = key or url.split("?", 1)[0]
        note = {}
        try:
            with open(note_path, encoding="utf-8") as f:
                note = json.load(f)
        except Exception:
            note = {}
        if note.get("key") != key or not os.path.exists(part):
            for p in (part, note_path):
                if os.path.exists(p):
                    os.remove(p)
            note = {"key": key}
        h = {"User-Agent": UA, **(headers or {})}
        host = urllib.parse.urlsplit(url).netloc
        cd, final_url = note.get("cd", ""), url
        total = int(note.get("total") or 0)
        last_pct = -1.0
        if os.path.exists(part) and os.path.getsize(part):
            self.log(f"   resuming {host} download at {os.path.getsize(part) // 1024} KB")

        def save_note():
            with open(note_path, "w", encoding="utf-8") as f:
                json.dump(note, f)

        attempt = 0
        while True:
            have = os.path.getsize(part) if os.path.exists(part) else 0
            hh = dict(h)
            if have:
                hh["Range"] = f"bytes={have}-"
                tag = note.get("etag") or note.get("last_modified")
                if tag:
                    hh["If-Range"] = tag
            try:
                r = self._open_stream(url, hh)
                status = r.status
                if status == 416 and have and (have >= total > 0 or not total):
                    r.close()
                    break                                   # already complete
                if status not in (200, 206):
                    r.close()
                    if status in (403, 404, 410):
                        raise SourceError(f"file host answered HTTP {status}")
                    raise IOError(f"HTTP {status}")
                if status == 206:
                    m = re.search(r"/(\d+)\s*$", r.headers.get("content-range", ""))
                    whole = int(m.group(1)) if m else 0
                    if total and whole and whole != total:  # a different file than the one we started
                        r.close()
                        os.remove(part)
                        total = 0
                        continue
                    total = whole or total
                else:
                    have = 0                                # server sent the whole file: start over
                    length = int(r.headers.get("content-length") or 0)
                    total = length
                cd = r.headers.get("content-disposition", "") or cd
                final_url = r.url or final_url
                note.update(total=total, cd=cd, etag=r.headers.get("etag", "") if not
                            r.headers.get("etag", "").startswith("W/") else "",
                            last_modified=r.headers.get("last-modified", ""))
                save_note()
                with open(part, "ab" if have else "wb") as f:
                    done = have
                    for chunk in r.chunks():
                        if self.stop.is_set():
                            r.close()
                            raise Stopped()
                        f.write(chunk)
                        done += len(chunk)
                        if progress and total:
                            pct = done / total
                            if pct - last_pct >= 0.01 or pct >= 1:
                                last_pct = pct
                                progress(pct)
                r.close()
                if total and os.path.getsize(part) < total:
                    raise IOError("connection closed early")
                break
            except (Stopped, SourceError):
                raise
            except Exception as e:
                got = os.path.getsize(part) if os.path.exists(part) else 0
                if attempt >= retries:
                    if got:
                        raise Interrupted(host, got)
                    raise SourceError(f"download from {host} kept failing ({type(e).__name__}: {e})")
                attempt += 1
                self.log(f"   download from {host} interrupted at {got // 1024} KB, resuming...")
                self._sleep(min(30, 4 * attempt))
        if not filename:
            m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
            filename = urllib.parse.unquote(m.group(1)) if m else os.path.basename(
                urllib.parse.urlsplit(final_url).path) or "download.bin"
        path = os.path.join(folder, safe_name(filename))
        os.replace(part, path)
        if os.path.exists(note_path):
            os.remove(note_path)
        return path

    def _open_stream(self, url, headers):
        s = self._session()
        if s:
            # (connect timeout, stall timeout): curl aborts only if no data arrives for ~2 minutes
            r = s.get(url, headers=headers, stream=True, timeout=(20, 120), allow_redirects=True)
            return _Stream(r.status_code, {k.lower(): v for k, v in r.headers.items()}, str(r.url),
                           lambda: r.iter_content(1 << 16), r.close)
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120)
        except urllib.error.HTTPError as e:
            return _Stream(e.code, {}, url, lambda: iter(()), lambda: None)
        return _Stream(r.status, {k.lower(): v for k, v in r.headers.items()}, r.geturl(),
                       lambda: iter(lambda: r.read(1 << 16), b""), r.close)


class _Stream:
    def __init__(self, status, headers, url, chunks, close):
        self.status, self.headers, self.url = status, headers, url
        self.chunks, self._close = chunks, close

    def close(self):
        try:
            self._close()
        except Exception:
            pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


# ------------------------------------------------------------------ files
def safe_name(s):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(s)).strip(" .")
    return s[:110] or "unnamed"


def _tar_tool():
    """libarchive's tar: built into Windows 10 (1803+) and 11 as System32\\tar.exe; bsdtar elsewhere."""
    if IS_WIN:
        p = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
        return p if os.path.exists(p) else None
    return shutil.which("bsdtar")


def _extract_other(path, dest):
    """.rar / .7z on Linux and macOS without bsdtar: 7-Zip or unrar, if one is installed. True when done."""
    low = path.lower()
    tries = []
    for seven in ("7z", "7zz", "7za"):
        if shutil.which(seven):
            tries.append([seven, "x", "-y", f"-o{dest}", path])
    if low.endswith(".rar") and shutil.which("unrar"):
        tries.append(["unrar", "x", "-o+", path, dest + os.sep])
    if low.endswith(".rar") and shutil.which("unar"):
        tries.append(["unar", "-f", "-o", dest, path])
    for cmd in tries:
        try:
            if subprocess.run(cmd, capture_output=True, timeout=1800).returncode == 0:
                return True
        except Exception:
            continue
    return False


def unpack(path, dest):
    """Extract an archive into dest and delete it. .zip in Python, .rar/.7z through libarchive's tar."""
    low = path.lower()
    if low.endswith(".zip") and not zipfile.is_zipfile(path):
        os.remove(path)
        raise SourceError("the downloaded .zip is damaged (it will be downloaded again next time)")
    if low.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.strip("/")]
            base = os.path.normpath(dest)
            for info in z.infolist():
                target = os.path.normpath(os.path.join(dest, info.filename))
                if not target.startswith(base + os.sep):
                    continue                                 # zip-slip guard
                if info.is_dir():
                    os.makedirs(target, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
        os.remove(path)
        return f"extracted {len(names)} entries"
    if low.endswith((".tar", ".tar.gz", ".tgz", ".tar.xz", ".tar.bz2")):
        import tarfile
        try:
            with tarfile.open(path) as t:
                base = os.path.normpath(dest)
                safe = [m for m in t.getmembers() if (m.isfile() or m.isdir()) and
                        os.path.normpath(os.path.join(dest, m.name)).startswith(base + os.sep)]
                t.extractall(dest, members=safe)
            os.remove(path)
            return f"extracted {os.path.basename(path)}"
        except (tarfile.TarError, OSError) as e:
            raise SourceError(f"could not extract {os.path.basename(path)} ({e})")
    if low.endswith((".rar", ".7z")):
        tool = _tar_tool()
        if tool:
            r = subprocess.run([tool, "-xf", path, "-C", dest], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode == 0:
                os.remove(path)
                return f"extracted {os.path.basename(path)}"
        if not IS_WIN and _extract_other(path, dest):
            os.remove(path)
            return f"extracted {os.path.basename(path)}"
        raise SourceError(f"could not extract {os.path.basename(path)} (" + (
            "needs Windows 10 or newer" if IS_WIN else "install libarchive-tools (bsdtar), 7-Zip (7z) or unrar") + ")")
    return f"kept {os.path.basename(path)}"
