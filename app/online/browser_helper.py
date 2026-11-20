"""
A real browser window (Edge WebView2 on Windows, via pywebview) running in its own process.

Some mod sites now put Cloudflare human checks in front of their pages, and modsbase.com (where
SkyMods keeps its files) puts a Turnstile widget on every download form. A plain HTTP client can't
pass either, and this app never tries to tick them for you. Instead the page is opened in this
window, where the checks run the way they do in any browser:
  * if a check finishes by itself, nothing is shown;
  * if it wants a click, the window appears, you tick it, and the window hides itself again.
The window stays hidden otherwise and is closed when a run ends.

It lives in a separate process because pywebview and tkinter both need the main thread.
"""
import json
import multiprocessing
import threading
import time
import urllib.parse

CHALLENGE_TITLES = ("just a moment", "attention required", "performing security verification",
                    "verify you are human", "checking your browser", "один момент", "لحظة")

# true while a Cloudflare full-page check is showing (works whatever language the page is in)
_JS_PAGE_CHALLENGED = """(function () {
    var t = (document.title || '').toLowerCase();
    var titles = %s;
    for (var i = 0; i < titles.length; i++) { if (t.indexOf(titles[i]) >= 0) return true; }
    return !!(window._cf_chl_opt || document.querySelector(
        '#challenge-form, #challenge-running, #cf-challenge-running, script[src*="/cdn-cgi/challenge-platform/"]'));
})()""" % json.dumps(CHALLENGE_TITLES)


def looks_like_challenge(status, text):
    head = text[:6000].lower()
    return (status in (403, 429, 503) and ("cf-chl" in head or "challenge-platform" in head
                                           or any(t in head for t in CHALLENGE_TITLES)))


# ====================================================================== child process
def _helper_main(conn, title):
    import webview

    def js(win, script, tries=6):
        """evaluate_js with retries: right after a navigation the page bridge may not be ready yet."""
        last = None
        for _ in range(tries):
            try:
                return win.evaluate_js(script)
            except Exception as e:
                last = e
                time.sleep(0.6)
        raise RuntimeError(f"browser script failed: {last}")

    def soft(win, script):
        try:
            return js(win, script, tries=1)
        except Exception:
            return None

    def show(win):
        for step in (win.show, win.restore):
            try:
                step()
            except Exception:
                pass
        try:                                   # bring it to the front once
            win.on_top = True
            time.sleep(0.3)
            win.on_top = False
        except Exception:
            pass

    def hide(win):
        try:
            win.hide()
        except Exception:
            pass

    def wait_dom(win, limit=60):
        end = time.time() + limit
        while time.time() < end:
            time.sleep(0.4)
            if soft(win, "document.readyState") in ("interactive", "complete"):
                return True
        return False

    def navigate(win, url, verify_timeout):
        """Open url. If a full-page human check appears, show the window until it is passed."""
        win.load_url(url)
        time.sleep(0.8)
        wait_dom(win)
        end = time.time() + 6                  # many checks finish by themselves within seconds
        while time.time() < end and soft(win, _JS_PAGE_CHALLENGED):
            time.sleep(0.5)
        if soft(win, _JS_PAGE_CHALLENGED):
            host = urllib.parse.urlsplit(url).netloc
            conn.send({"event": "verify_needed", "host": host, "kind": "page"})
            show(win)
            end = time.time() + verify_timeout
            while time.time() < end and soft(win, _JS_PAGE_CHALLENGED) is not False:
                time.sleep(1)
            if soft(win, _JS_PAGE_CHALLENGED) is not False:
                hide(win)
                return False
            wait_dom(win)
            hide(win)
            conn.send({"event": "verified", "host": host})
        return True

    def page_html(win):
        raw = js(win, "JSON.stringify({url: location.href, html: document.documentElement.outerHTML})")
        d = json.loads(raw)
        return d["url"], d["html"]

    def run_async(win, start_script, limit):
        """Run a script that eventually stores a JSON string in window[key]; poll for it."""
        key = "__pmc_%d" % int(time.time() * 1000)
        js(win, "window.%s = null; %s; 'started'" % (key, start_script.replace("__KEY__", key)))
        end = time.time() + limit
        while time.time() < end:
            time.sleep(0.4)
            raw = js(win, "window.%s" % key)
            if raw:
                js(win, "window.%s = undefined; 'ok'" % key)
                res = json.loads(raw)
                if "error" in res:
                    raise RuntimeError("browser request failed: " + res["error"])
                return res
        raise TimeoutError("browser request timed out")

    def fetch_post(win, url, data, limit=120):
        script = """
            fetch(%s, {method: 'POST', credentials: 'include',
                       headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                       body: new URLSearchParams(%s).toString()})
            .then(function (r) { return r.text().then(function (t) {
                window.__KEY__ = JSON.stringify({status: r.status, url: r.url, text: t}); }); })
            .catch(function (e) { window.__KEY__ = JSON.stringify({error: String(e)}); })""" % (
            json.dumps(url), json.dumps(data or {}))
        return run_async(win, script, limit)

    # ---------------------------------------------------------------- operations
    def op_get(win, msg):
        if not navigate(win, msg["url"], msg.get("verify_timeout", 300)):
            return {"ok": False, "challenge": True, "error": "the human check was not completed"}
        url, html = page_html(win)
        return {"ok": True, "status": 200, "url": url, "text": html}

    def op_post(win, msg):
        parts = urllib.parse.urlsplit(msg["url"])
        origin = f"{parts.scheme}://{parts.netloc}"
        here = soft(win, "location.origin")
        if here != origin and not navigate(win, origin + "/", msg.get("verify_timeout", 300)):
            return {"ok": False, "challenge": True, "error": "the human check was not completed"}
        res = fetch_post(win, msg["url"], msg.get("data"))
        res["ok"] = True
        return res

    def op_form(win, msg):
        """Open a download page, wait for its countdown and its Turnstile widget, submit form F1."""
        verify_timeout = msg.get("verify_timeout", 300)
        if not navigate(win, msg["url"], verify_timeout):
            return {"ok": False, "challenge": True, "error": "the human check was not completed"}
        form = msg.get("form", "F1")
        state_js = """JSON.stringify((function () {
            var f = document.forms[%s];
            var tok = document.querySelector('[name="cf-turnstile-response"], [name="g-recaptcha-response"], [name="h-captcha-response"]');
            var widget = document.querySelector('.cf-turnstile, .g-recaptcha, .h-captcha');
            var secs = document.getElementById('seconds');
            return {form: !!f, widget: !!widget, token: tok ? tok.value : '',
                    secs: secs ? parseInt(secs.textContent || '0', 10) : 0,
                    pw: !!(f && f.querySelector('[name="password"]'))};
        })())""" % json.dumps(form)
        st = json.loads(js(win, state_js))
        if not st["form"]:
            return {"ok": False, "error": "the download page has no download form"}
        if st["pw"]:
            return {"ok": False, "error": "the file is password protected"}
        started, shown = time.time(), False
        while True:
            st = json.loads(js(win, state_js))
            ready = (not st["widget"] or st["token"]) and st["secs"] <= 0
            if ready:
                break
            waited = time.time() - started
            if st["widget"] and not st["token"] and waited > 12 and not shown:
                conn.send({"event": "verify_needed", "host": urllib.parse.urlsplit(msg["url"]).netloc,
                           "kind": "file"})
                show(win)
                shown = True
            if waited > verify_timeout + 15:
                hide(win)
                return {"ok": False, "challenge": True, "error": "the download's human check was not completed"}
            time.sleep(0.5)
        if shown:
            hide(win)
            conn.send({"event": "verified", "host": urllib.parse.urlsplit(msg["url"]).netloc})
        script = """
            (function () {
                var f = document.forms[%s];
                var target = f.getAttribute('action') || location.href;
                fetch(target, {method: 'POST', credentials: 'include',
                               headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                               body: new URLSearchParams(new FormData(f)).toString()})
                .then(function (r) { return r.text().then(function (t) {
                    window.__KEY__ = JSON.stringify({status: r.status, url: r.url, text: t}); }); })
                .catch(function (e) { window.__KEY__ = JSON.stringify({error: String(e)}); });
            })()""" % json.dumps(form)
        res = run_async(win, script, 120)
        res["ok"] = True
        return res

    OPS = {"get": op_get, "post": op_post, "form": op_form}

    def serve(win):
        while True:
            try:
                msg = conn.recv()
            except (EOFError, OSError):
                break
            if msg.get("op") == "quit":
                break
            try:
                conn.send(OPS[msg["op"]](win, msg))
            except Exception as e:
                hide(win)
                conn.send({"ok": False, "error": f"{type(e).__name__}: {e}"})
        try:
            win.destroy()
        except Exception:
            pass

    win = webview.create_window(title, "about:blank", width=560, height=700, hidden=True)
    webview.start(serve, win, private_mode=False)


# ====================================================================== app side
class BrowserBridge:
    """Thread-safe handle to the helper window. One request at a time."""

    def __init__(self, on_event=None, title="Site check"):
        self.on_event = on_event or (lambda e: None)
        self.title = title
        self.proc = self.conn = None
        self.lock = threading.Lock()

    @staticmethod
    def available():
        import importlib.util
        return importlib.util.find_spec("webview") is not None

    def _ensure(self):
        if self.proc and self.proc.is_alive():
            return
        ctx = multiprocessing.get_context("spawn")
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=_helper_main, args=(child, self.title), daemon=True)
        self.proc.start()

    def _call(self, msg, timeout, stop):
        with self.lock:
            self._ensure()
            self.conn.send(msg)
            end = time.time() + timeout
            while time.time() < end:
                if stop is not None and stop.is_set():
                    self._kill()
                    raise InterruptedError("stopped")
                if not self.proc.is_alive():
                    self.proc = None
                    raise RuntimeError("the check window was closed")
                if self.conn.poll(0.5):
                    reply = self.conn.recv()
                    if "event" in reply:
                        self.on_event(reply)
                        continue
                    return reply
            self._kill()                       # stuck: start a fresh window next time
            raise TimeoutError("the check window did not answer")

    def request(self, method, url, data=None, timeout=480, verify_timeout=300, stop=None):
        op = "get" if method.upper() == "GET" else "post"
        return self._call({"op": op, "url": url, "data": data, "verify_timeout": verify_timeout},
                          timeout, stop)

    def submit_form(self, url, form="F1", timeout=480, verify_timeout=300, stop=None):
        return self._call({"op": "form", "url": url, "form": form, "verify_timeout": verify_timeout},
                          timeout, stop)

    def _kill(self):
        try:
            if self.proc and self.proc.is_alive():
                self.proc.terminate()
        except Exception:
            pass
        self.proc = self.conn = None

    def close(self):
        with self.lock:
            try:
                if self.conn:
                    self.conn.send({"op": "quit"})
            except Exception:
                pass
            if self.proc:
                self.proc.join(3)
            self._kill()
