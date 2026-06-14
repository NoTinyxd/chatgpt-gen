import email as emaillib
import imaplib
import json
import random
import re
import string
import time
import uuid
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import requests
from requests.exceptions import ConnectionError, Timeout

import mail
from console import log
from sdk import SDK


class Registrar:
    def __init__(self, addr: str, pw: str, imap_host: str,
                 fp_data: dict, proxy: str = None):
        self.addr = addr
        self.pw = pw
        self.imap_host = imap_host
        self._submit_t = None
        self._landing = None
        self._sent = None
        self._flow = "oauth_create_account"

        self._fp_raw = fp_data["fp"]
        self._hdrs = {k: v for k, v in fp_data["headers"].items() if v is not None}

        self.sess = requests.Session()
        if proxy:
            self.sess.proxies.update({"http": proxy, "https": proxy})
        self.sess.headers.update(self._hdrs)

        self.did = str(uuid.uuid4())
        self.sess.cookies.set("oai-did", self.did, domain=".chatgpt.com")

        self._sdk = SDK()

    def _fp(self):
        return self._sdk.make_fp({"fp": self._fp_raw})

    def csrf(self) -> str:
        r = self.sess.get("https://chatgpt.com/api/auth/csrf", timeout=30)
        r.raise_for_status()
        t = r.json()["csrfToken"]
        log("VERIFIED", "got CSRF", detail=t[:24] + "…")
        return t

    def sentinel(self) -> str:
        if self._sent is None:
            fp = self._fp()
            sent, _ = self._sdk.full_init(
                did=self.did, fp=fp, sess=self.sess,
                base="https://chatgpt.com/backend-anon/sentinel/",
                flow=self._flow,
            )
            self._sent = sent
        tok = self._sent.token(flow=self._flow)
        try:
            val = json.loads(tok).get("p") if tok.startswith("{") else tok
        except Exception:
            val = tok
        log("VERIFIED", "Got sentinel token", detail=(val or tok)[:5])
        return tok

    def so(self) -> str | None:
        if self._sent is None:
            return None
        try:
            return self._sent.so_token(flow=self._flow)
        except Exception as e:
            log("ERROR", f"so-token failed: {e}")
            return None

    def submit_email(self, csrf: str, sent_tok: str) -> None:
        lid = str(uuid.uuid4())
        url = (
            "https://chatgpt.com/api/auth/signin/openai?"
            f"prompt=login&ext-oai-did={self.did}&"
            f"auth_session_logging_id={lid}&"
            "ext-passkey-client-capabilities=1111&"
            "screen_hint=login_or_signup&"
            f"login_hint={quote_plus(self.addr)}"
        )
        r = self.sess.post(
            url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "openai-sentinel-token": sent_tok,
            },
            data={
                "callbackUrl": "https://chatgpt.com/",
                "csrfToken": csrf,
                "json": "true",
            },
            timeout=30,
        )
        r.raise_for_status()
        auth_url = r.json().get("url")
        if not auth_url:
            log("ERROR", f"signin no auth url (HTTP {r.status_code}); body:\n{r.text}")
            raise RuntimeError("signin did not return auth url")
        followed = self.sess.get(auth_url, headers={"Referer": "https://chatgpt.com/"},
                                 allow_redirects=True, timeout=30)
        self._landing = followed.url
        self._submit_t = time.time()

    def _imap(self) -> imaplib.IMAP4_SSL:
        m = imaplib.IMAP4_SSL(self.imap_host)
        m.login(self.addr, self.pw)
        m.select("inbox")
        return m

    def clear_stale(self) -> int:
        try:
            m = self._imap()
        except Exception as e:
            log("ERROR", f"IMAP login failed while clearing stale: {e}")
            return 0
        try:
            _, ids = m.search(None, '(FROM "openai")')
            mids = ids[0].split()
            for mid in mids:
                m.store(mid, "+FLAGS", "\\Seen")
            if mids:
                log("INFO", f"cleared {len(mids)} prior OpenAI email(s)")
            return len(mids)
        finally:
            try: m.logout()
            except Exception: pass

    @staticmethod
    def _strip_html(h: str) -> str:
        h = re.sub(r"<(style|script)\b[^>]*>.*?</\1>", " ", h, flags=re.DOTALL | re.IGNORECASE)
        return re.sub(r"<[^>]+>", " ", h)

    @staticmethod
    def _body(msg) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    return part.get_payload(decode=True).decode(errors="replace")
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    return Registrar._strip_html(
                        part.get_payload(decode=True).decode(errors="replace"))
            return ""
        raw = msg.get_payload(decode=True).decode(errors="replace")
        if (msg.get_content_type() or "").lower() == "text/html":
            return Registrar._strip_html(raw)
        return raw

    @staticmethod
    def _otp(body: str) -> str | None:
        body = re.sub(r"#[0-9a-fA-F]{6}\b", " ", body)
        m = re.search(
            r"(?:verification code|one[- ]time (?:password|code)|your code|code is)"
            r"[^\d]{0,40}(\d{6})", body, re.IGNORECASE)
        if m:
            return m.group(1)
        m = re.search(r"(?:\d\s+){5}\d", body)
        if m:
            return re.sub(r"\s+", "", m.group(0))
        m = re.search(r"(?<![#\w])(\d{6})(?!\w)", body)
        return m.group(1) if m else None

    def wait_otp(self, timeout: int = 180, poll: float = 3.0) -> str:
        end = time.time() + timeout
        while time.time() < end:
            otp = self._peek_otp()
            if otp:
                log("VERIFIED", "Fetched OTP", detail=otp)
                return otp
            time.sleep(poll)
        raise TimeoutError("OTP did not arrive within timeout")

    @staticmethod
    def _next_url(d: dict) -> str | None:
        return (d.get("continue_url") or d.get("redirect_url") or d.get("url")
                or ((d.get("page") or {}).get("payload") or {}).get("url"))

    def validate_otp(self, otp: str) -> str:
        ref = self._landing or "https://auth.openai.com/email-verification"
        r = self.sess.post(
            "https://auth.openai.com/api/accounts/email-otp/validate",
            headers={"Accept": "application/json", "Content-Type": "application/json",
                     "Origin": "https://auth.openai.com", "Referer": ref},
            json={"code": otp}, timeout=30,
        )
        if not r.ok:
            log("ERROR", f"validate_otp HTTP {r.status_code}; body:\n{r.text}")
            raise RuntimeError(f"validate HTTP {r.status_code}")
        nxt = self._next_url(r.json())
        if not nxt:
            log("ERROR", f"validate_otp no redirect; body:\n{r.text}")
            raise RuntimeError("OTP validation returned no redirect")
        return nxt

    def create_account(self) -> str:
        name = "".join(random.choices(string.ascii_uppercase, k=random.randint(7, 12)))
        bdate = f"{random.randint(1985, 2003):04d}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"
        st = self.sentinel()
        so_tok = self.so()
        hdrs = {
            "Accept": "application/json", "Content-Type": "application/json",
            "Origin": "https://auth.openai.com", "Referer": "https://auth.openai.com/about-you",
            "openai-sentinel-token": st,
        }
        if so_tok:
            hdrs["openai-sentinel-so-token"] = so_tok
        r = self.sess.post(
            "https://auth.openai.com/api/accounts/create_account",
            headers=hdrs, json={"name": name, "birthdate": bdate}, timeout=30,
        )
        if not r.ok:
            log("ERROR", f"create_account HTTP {r.status_code}; body:\n{r.text}")
            raise RuntimeError(f"create_account HTTP {r.status_code}")
        nxt = self._next_url(r.json())
        if not nxt:
            log("ERROR", f"create_account no redirect; body:\n{r.text}")
            raise RuntimeError("create_account returned no redirect")
        return nxt

    def finalize(self, cb_url: str) -> str:
        self.sess.get(cb_url, timeout=30, allow_redirects=True)
        for c in self.sess.cookies:
            if c.name.startswith("__Secure-next-auth.session-token"):
                log("VERIFIED", "got session token", detail=c.value[:24] + "…")
                return c.value
        log("ERROR", "finalize: no session cookie")
        log("ERROR", f"cookie names: {[c.name for c in self.sess.cookies]}")
        raise RuntimeError("session token cookie missing after finalize")

    def _peek_otp(self) -> str | None:
        try:
            m = self._imap()
        except Exception:
            return None
        try:
            cutoff = self._submit_t or 0
            _, ids = m.search(None, '(FROM "openai")')
            mids = ids[0].split()
            hits = []
            for mid in mids:
                _, idata = m.fetch(mid, "(INTERNALDATE)")
                dt = imaplib.Internaldate2tuple(idata[0])
                if dt is None:
                    continue
                ts = time.mktime(dt)
                if ts + 5 >= cutoff:
                    hits.append((ts, mid))
            if not hits:
                return None
            hits.sort()
            _, raw = m.fetch(hits[-1][1], "(BODY.PEEK[])")
            msg = emaillib.message_from_bytes(raw[0][1])
            return self._otp(self._body(msg))
        except Exception:
            return None
        finally:
            try: m.logout()
            except Exception: pass

    def run(self) -> str:
        csrf = self.csrf()
        sent = self.sentinel()
        self.submit_email(csrf, sent)
        otp = self.wait_otp()
        cb = self.validate_otp(otp)
        for _ in range(3):
            if "/about-you" in cb:
                cb = self.create_account()
                continue
            if "auth.openai.com" in cb:
                self.sess.get(cb, timeout=30, allow_redirects=True)
                break
            break
        return self.finalize(cb)


def _imap_host(cfg: dict) -> str:
    return urlparse(cfg["mailcows"][0]["api_url"]).hostname


def _load_fps(fp_dir: str) -> list[dict]:
    p = Path(fp_dir)
    if not p.is_dir():
        return []
    out = []
    for f in sorted(p.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            log("ERROR", f"bad fingerprint {f.name}: {e}")
            continue
        if isinstance(d, dict) and "fp" in d and "headers" in d:
            out.append(d)
        else:
            log("ERROR", f"bad fingerprint {f.name}: missing 'fp' or 'headers'")
    return out


def _load_proxies(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return [l.strip() for l in fh if l.strip() and not l.lstrip().startswith("#")]
    except FileNotFoundError:
        return []


def main() -> None:
    with open("config.json", "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    sess_file = cfg.get("sessions_file", "done.txt")
    fp_dir = cfg.get("fp_dir", "fp")
    imap = cfg.get("imap_host") or _imap_host(cfg)

    use_px = bool(cfg.get("proxies", False))
    px = _load_proxies(cfg.get("proxies_file", "proxies.txt")) if use_px else []
    if use_px and not px:
        log("ERROR", f"proxies enabled but file empty")
        return

    fps = _load_fps(fp_dir)
    if not fps:
        log("ERROR", f"no fingerprints in {fp_dir}/ — run `python3 fp_scraper.py` first")
        return

    raw = input("How many accounts to create? ").strip()
    total = int(raw) if raw and raw.isdigit() else 1
    if total <= 0:
        return

    log("INFO", f"proxies: {str(use_px).lower()} | fps: {len(fps)}")

    ok = 0
    for _ in range(total):
        try:
            addr, pw = mail.create_inbox(cfg)
        except (ConnectionError, Timeout):
            log("ERROR", "Mail Server Down")
            return
        except Exception as e:
            log("FAILED", f"mailcow could not create inbox: {e}")
            continue
        fp = random.choice(fps)
        proxy = random.choice(px) if px else None
        try:
            bot = Registrar(addr, pw, imap_host=imap, fp_data=fp, proxy=proxy)
            tok = bot.run()
            with open(sess_file, "a", encoding="utf-8") as fh:
                fh.write(f"{addr}:{pw}:{tok}\n")
            ok += 1
        except Exception as e:
            log("FAILED", f"{addr}: {e}")

    log("SUCCESS", f"Created {ok} account{'' if ok == 1 else 's'}")


if __name__ == "__main__":
    main()
