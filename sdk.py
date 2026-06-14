from __future__ import annotations

import base64
import json
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


ERR_PFX = "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D"
MAX_TRIES = 500_000
REQ_PFX = "gAAAAAC"
ENF_PFX = "gAAAAAB"

SENTINEL_URL = "https://chatgpt.com/backend-api/sentinel/"


def b64(d: bytes | str) -> str:
    if isinstance(d, str):
        d = d.encode("latin-1")
    return base64.b64encode(d).decode("ascii")


def ub64(s: str) -> bytes:
    return base64.b64decode(s)


def js_str(v: Any) -> str:
    return json.dumps(v, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def n_enc(v: Any) -> str:
    return b64(js_str(v).encode("utf-8"))


def xorm(msg: str, key: str) -> str:
    if not key:
        return msg
    kl = len(key)
    return "".join(chr((ord(c) ^ ord(key[i % kl])) & 0xFF) for i, c in enumerate(msg))


def murmur_hex(s: str) -> str:
    h = 2166136261
    for c in s:
        h ^= ord(c) & 0xFFFF
        h = (h * 16777619) & 0xFFFFFFFF
    h ^= h >> 16
    h = (h * 2246822507) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 3266489909) & 0xFFFFFFFF
    h ^= h >> 16
    return f"{h:08x}"


@dataclass
class FP:
    screen_sum: int
    date_string: str
    heap_size_limit: Optional[int]
    user_agent: str
    script_src: str
    data_build: Optional[str]
    language: str
    languages: str
    nav_proto_sample: str
    doc_key_sample: str
    window_key_sample: str
    url_param_keys: str
    hardware_concurrency: int
    in_ai: int
    in_install_trigger: int
    in_cache: int
    in_data: int
    in_solana: int
    in_force_sync: int
    in_memory: int


class Prover:
    def __init__(self, fp: FP, sid: str = None, cap: int = MAX_TRIES):
        self.fp = fp
        self.sid = sid or str(uuid.uuid4())
        self.cap = cap
        self.seed = repr(random.random())
        self.cache: dict[str, str] = {}
        self._t0 = time.time() * 1000.0
        self._pt = time.perf_counter()

    def _ms(self) -> float:
        return (time.perf_counter() - self._pt) * 1000.0

    def _gather(self) -> list[Any]:
        f = self.fp
        return [
            f.screen_sum, f.date_string, f.heap_size_limit, random.random(),
            f.user_agent, f.script_src, f.data_build, f.language, f.languages,
            random.random(), f.nav_proto_sample, f.doc_key_sample, f.window_key_sample,
            self._ms(), self.sid, f.url_param_keys, f.hardware_concurrency,
            self._t0, f.in_ai, f.in_install_trigger, f.in_cache, f.in_data,
            f.in_solana, f.in_force_sync, f.in_memory,
        ]

    def _try_once(self, t0: float, seed: str, diff: str, buf: list[Any], i: int) -> str | None:
        buf[3] = i
        buf[9] = round(self._ms() - t0)
        enc = n_enc(buf)
        if murmur_hex(seed + enc)[:len(diff)] <= diff:
            return enc + "~S"
        return None

    def _fail_msg(self) -> str:
        buf = self._gather()
        buf[3] = 1
        buf[9] = 0
        return ERR_PFX + n_enc(buf)

    def _solve(self, seed: str, diff: str) -> str:
        t0 = self._ms()
        try:
            buf = self._gather()
            for i in range(self.cap):
                if (r := self._try_once(t0, seed, diff, buf, i)) is not None:
                    return r
        except Exception as e:
            return ERR_PFX + n_enc(str(e))
        return self._fail_msg()

    def req_token(self) -> str:
        if self.seed not in self.cache:
            self.cache[self.seed] = self._solve(self.seed, "0")
        return REQ_PFX + self.cache[self.seed]

    def req_token_blocking(self) -> str:
        return REQ_PFX + self._fail_msg()

    def enf_token(self, chat_req: dict | None) -> str | None:
        pw = (chat_req or {}).get("proofofwork") if chat_req else None
        if not pw or not pw.get("required"):
            return None
        s, d = pw.get("seed"), pw.get("difficulty")
        if not isinstance(s, str) or not isinstance(d, str):
            return None
        if s not in self.cache:
            self.cache[s] = self._solve(s, d)
        return ENF_PFX + self.cache[s]


OP_OUTER = 0
OP_XOR = 1
OP_LIT = 2
OP_RESOLVE = 3
OP_REJECT = 4
OP_APPEND = 5
OP_PROP = 6
OP_CALL0 = 7
OP_COPY = 8
OP_QUEUE = 9
OP_HOST = 10
OP_SCRIPT = 11
OP_SELF = 12
OP_TRYCALL = 13
OP_JPARSE = 14
OP_JSTR = 15
OP_KEY = 16
OP_AWAIT = 17
OP_ATOB = 18
OP_BTOA = 19
OP_EQCALL = 20
OP_ABSGT = 21
OP_SUB = 22
OP_DEFINED = 23
OP_BIND = 24
OP_NOOP25 = 25
OP_NOOP26 = 26
OP_RM = 27
OP_NOOP28 = 28
OP_LT = 29
OP_DEFN = 30
OP_MUL = 33
OP_PRESOLVE = 34
OP_DIV = 35


@dataclass
class Host:
    scripts: list[dict] = field(default_factory=list)
    x: dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, k: str) -> Any:
        return self.x.get(k)

    def __getitem__(self, k: str) -> Any:
        return self.x.get(k)


class VMError(RuntimeError):
    pass


class VM:
    def __init__(self, host: Host = None, runner: Callable[[str], str] = None):
        self.host = host or Host()
        self.runner = runner
        self.r: dict[int, Any] = {}
        self._val: Any = None
        self._err: Any = None
        self._done = False
        self.steps = 0
        self.step_max = 1_000_000

    def _ok(self, v: Any) -> None:
        if not self._done:
            self._done = True
            self._val = b64(str(v).encode("utf-8"))

    def _fail(self, v: Any) -> None:
        if not self._done:
            self._done = True
            self._err = b64(str(v).encode("utf-8"))

    def _setup(self) -> None:
        R = self.r
        s = lambda k, v: R.__setitem__(k, v)
        g = lambda k: R.get(k)

        R[OP_OUTER] = lambda *a: (
            (self.runner(str(a[0])) if self.runner and a else None)
            if not (self.runner and a and isinstance(exc := None, type(None)))
            else f"{exc}"
        ) if self.runner and a else (lambda *a: None)

        def _outer(*a):
            if self.runner and a:
                try:
                    return self.runner(str(a[0]))
                except Exception as e:
                    return f"{e}"
            return None
        R[OP_OUTER] = _outer

        R[OP_XOR] = lambda n, e: s(n, xorm(str(g(n)), str(g(e))))
        R[OP_LIT] = lambda n, e: s(n, e)

        def _append(n, e):
            cur, rhs = g(n), g(e)
            if isinstance(cur, list):
                cur.append(rhs)
            elif isinstance(cur, (int, float)) and isinstance(rhs, (int, float)):
                s(n, cur + rhs)
            else:
                s(n, f"{cur}{rhs}")
        R[OP_APPEND] = _append

        def _prop(n, e, r):
            obj, key = g(e), g(r)
            try:
                if isinstance(obj, dict):
                    s(n, obj.get(key))
                elif isinstance(obj, list) and isinstance(key, int):
                    s(n, obj[key] if 0 <= key < len(obj) else None)
                else:
                    s(n, getattr(obj, str(key), None))
            except Exception as e:
                s(n, f"{e}")
        R[OP_PROP] = _prop

        def _call0(n, *a):
            fn = g(n)
            if callable(fn):
                fn(*[g(x) for x in a])
        R[OP_CALL0] = _call0

        R[OP_COPY] = lambda n, e: s(n, g(e))
        R[OP_HOST] = self.host

        def _script(n, e):
            needle = str(g(e) or "")
            for sc in self.host.scripts:
                src = sc.get("src") if isinstance(sc, dict) else getattr(sc, "src", None)
                if src and needle in src:
                    s(n, src)
                    return
            s(n, None)
        R[OP_SCRIPT] = _script

        R[OP_SELF] = lambda n: s(n, R)

        def _trycall(n, e, *a):
            fn = g(e)
            try:
                if callable(fn):
                    fn(*a)
            except Exception as ex:
                s(n, f"{ex}")
        R[OP_TRYCALL] = _trycall

        def _jparse(n, e):
            try:
                s(n, json.loads(str(g(e))))
            except Exception as ex:
                s(n, f"{ex}")
        R[OP_JPARSE] = _jparse

        def _jstr(n, e):
            try:
                s(n, js_str(g(e)))
            except Exception as ex:
                s(n, f"{ex}")
        R[OP_JSTR] = _jstr

        def _await(n, e, *a):
            fn = g(e)
            try:
                s(n, fn(*[g(x) for x in a]) if callable(fn) else None)
            except Exception as ex:
                s(n, f"{ex}")
        R[OP_AWAIT] = _await

        def _atob(n):
            try:
                s(n, ub64(str(g(n))).decode("latin-1"))
            except Exception as ex:
                s(n, f"{ex}")
        R[OP_ATOB] = _atob

        R[OP_BTOA] = lambda n: s(n, b64(str(g(n))))

        def _eqcall(n, e, r, *o):
            if g(n) == g(e):
                fn = g(r)
                if callable(fn):
                    fn(*[g(x) for x in o])
        R[OP_EQCALL] = _eqcall

        def _absgt(n, e, r, o, *i):
            try:
                lv, rv, th = float(g(n) or 0), float(g(e) or 0), float(g(r) or 0)
            except Exception:
                return
            if abs(lv - rv) > th:
                fn = g(o)
                if callable(fn):
                    fn(*[g(x) for x in i])
        R[OP_ABSGT] = _absgt

        def _subprog(n, *body):
            prev = list(g(OP_QUEUE) or [])
            s(OP_QUEUE, [list(ins) for ins in body])
            try:
                self._tick()
            except Exception as ex:
                s(n, f"{ex}")
            finally:
                s(OP_QUEUE, prev)
        R[OP_SUB] = _subprog

        def _defined(n, e, *a):
            if g(n) is not None:
                fn = g(e)
                if callable(fn):
                    fn(*a)
        R[OP_DEFINED] = _defined

        def _bind(n, e, r):
            obj, name = g(e), g(r)
            try:
                tgt = obj.get(name) if isinstance(obj, dict) else getattr(obj, str(name), None)
                s(n, (lambda *a, _t=tgt: _t(*a)) if callable(tgt) else tgt)
            except Exception as ex:
                s(n, f"{ex}")
        R[OP_BIND] = _bind

        def _rm(n, e):
            cur, v = g(n), g(e)
            if isinstance(cur, list):
                try:
                    cur.remove(v)
                except ValueError:
                    pass
            else:
                try:
                    s(n, float(cur) - float(v))
                except Exception:
                    s(n, None)
        R[OP_RM] = _rm

        R[OP_LT] = lambda n, e, r: s(n, g(e) < g(r)) if not _catch_lt(n, e, r) else None

        def _catch_lt(n, e, r):
            try:
                return False
            except Exception:
                s(n, False)
                return True

        def _lt(n, e, r):
            try:
                s(n, g(e) < g(r))
            except Exception:
                s(n, False)
        R[OP_LT] = _lt

        def _defn(tgt, ret, params_or_body, body2=None):
            if isinstance(params_or_body, list) and all(isinstance(x, int) for x in params_or_body):
                params, body = params_or_body, body2 or []
            else:
                params, body = [], params_or_body or []

            def fn(*args):
                prev = list(g(OP_QUEUE) or [])
                for idx, p in enumerate(params):
                    if idx < len(args):
                        s(p, args[idx])
                s(OP_QUEUE, [list(ins) for ins in body])
                try:
                    self._tick()
                    return g(ret)
                except Exception as ex:
                    return f"{ex}"
                finally:
                    s(OP_QUEUE, prev)
            s(tgt, fn)
        R[OP_DEFN] = _defn

        def _mul(n, e, r):
            try:
                s(n, float(g(e)) * float(g(r)))
            except Exception:
                s(n, 0)
        R[OP_MUL] = _mul

        R[OP_PRESOLVE] = lambda n, e: s(n, g(e))

        def _div(n, e, r):
            try:
                dn = float(g(r))
                s(n, 0 if dn == 0 else float(g(e)) / dn)
            except Exception:
                s(n, 0)
        R[OP_DIV] = _div

        for nop in (OP_NOOP25, OP_NOOP26, OP_NOOP28):
            R[nop] = lambda *a, **kw: None

        R[OP_RESOLVE] = lambda v=None: self._ok(v)
        R[OP_REJECT] = lambda v=None: self._fail(v)

    def _tick(self) -> None:
        q = self.r.get(OP_QUEUE)
        if not isinstance(q, list):
            return
        while q:
            self.steps += 1
            if self.steps > self.step_max:
                raise VMError("step limit exceeded")
            ins = q.pop(0)
            if not isinstance(ins, list) or not ins:
                continue
            op, *args = ins
            h = self.r.get(op)
            if not callable(h):
                continue
            try:
                h(*args)
            except Exception:
                pass
            if self._done:
                return

    def run(self, dx: str, key: str) -> str:
        self._setup()
        self.r[OP_KEY] = key
        try:
            raw = xorm(ub64(dx).decode("latin-1"), key)
            prog = json.loads(raw)
            if not isinstance(prog, list):
                raise VMError("dx payload is not a program list")
            self.r[OP_QUEUE] = [list(ins) for ins in prog]
            self._tick()
        except Exception as e:
            self._fail(f"{self.steps}: {e}")
        if self._done and self._val is not None:
            return self._val
        if self._done and self._err is not None:
            raise VMError(f"vm rejected: {self._err}")
        return b64(f"{self.steps}: ".encode("utf-8"))


class Sentinel:
    DEF_FLOW = "__default__"

    def __init__(self, did: str, prover: Prover, base: str = SENTINEL_URL,
                 host: Host = None, sess: Any = None):
        self.did = did
        self.base = base.rstrip("/") + "/"
        self.prover = prover
        self.host = host or Host()
        self.sess = sess
        self._st: dict[str, dict] = {}

    def _pack(self, payload: dict, flow: str) -> str:
        body = dict(payload, id=self.did, flow=flow)
        return js_str(body)

    def _post_req(self, flow: str, tok: str) -> dict:
        if self.sess is None:
            try:
                import requests as _r
            except ImportError as e:
                raise RuntimeError("pass session= or install requests") from e
            self.sess = _r.Session()
        r = self.sess.post(
            self.base + "chat-requirements",
            data=self._pack({"p": tok}, flow),
            headers={"content-type": "application/json"},
        )
        r.raise_for_status()
        return r.json()

    def init(self, flow: str = DEF_FLOW) -> dict:
        tok = self.prover.req_token()
        cr = self._post_req(flow, tok)
        self._st[flow] = {"cr": cr, "tok": tok, "at": time.time()}
        return cr

    def token(self, flow: str = DEF_FLOW) -> str:
        st = self._st.get(flow)
        if not st or time.time() - st["at"] > 540:
            self.init(flow)
            st = self._st[flow]
        cr, tok = st["cr"], st["tok"]
        enf = self.prover.enf_token(cr)
        dx = (cr.get("turnstile") or {}).get("dx") if cr else None
        t = VM(host=self.host).run(dx, tok) if dx else None
        return self._pack({"p": enf, "t": t, "c": cr.get("token") if cr else None}, flow)

    def so_token(self, flow: str = DEF_FLOW) -> str | None:
        st = self._st.get(flow)
        if not st:
            return None
        cr = st["cr"]
        so = (cr or {}).get("so") or {}
        if not so.get("required"):
            return None
        sdx = so.get("snapshot_dx")
        if not sdx:
            return None
        vm_tok = VM(host=self.host).run(sdx, st["tok"])
        body: dict[str, Any] = {"so": vm_tok}
        if cr.get("token"):
            body["c"] = cr["token"]
        return self._pack(body, flow)


class SDK:
    FP = FP
    Prover = Prover
    Sentinel = Sentinel
    VM = VM
    Host = Host
    VMError = VMError

    def __init__(self, fp_path: str = "fp"):
        self.fp_path = fp_path

    def load_fps(self) -> list[dict]:
        from pathlib import Path
        p = Path(self.fp_path)
        if not p.is_dir():
            return []
        out = []
        for f in sorted(p.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(d, dict) and "fp" in d and "headers" in d:
                out.append(d)
        return out

    def make_fp(self, data: dict) -> FP:
        return FP(**data["fp"])

    def make_prover(self, fp: FP, **kw) -> Prover:
        return Prover(fp=fp, **kw)

    def make_sentinel(self, did: str, prover: Prover, host: Host = None,
                      sess: Any = None, base: str = SENTINEL_URL) -> Sentinel:
        return Sentinel(did=did, prover=prover, host=host, sess=sess, base=base)

    def make_host(self, fp: FP) -> Host:
        return Host(scripts=[{"src": fp.script_src}])

    def req_token(self, fp: FP, **kw) -> str:
        return self.make_prover(fp, **kw).req_token()

    def enf_token(self, fp: FP, chat_req: dict, **kw) -> str | None:
        return self.make_prover(fp, **kw).enf_token(chat_req)

    def exec_vm(self, dx: str, key: str, host: Host = None) -> str:
        return VM(host=host).run(dx, key)

    def full_init(self, did: str, fp: FP, sess: Any = None,
                  base: str = "https://chatgpt.com/backend-anon/sentinel/",
                  flow: str = "__default__") -> tuple[Sentinel, dict]:
        prover = self.make_prover(fp, cap=2000)
        host = self.make_host(fp)
        sent = self.make_sentinel(did=did, prover=prover, host=host, sess=sess, base=base)
        cr = sent.init(flow=flow)
        return sent, cr


# backwards compat aliases
BrowserFingerprint = FP
ProofGenerator = Prover
SentinelClient = Sentinel
HostEnv = Host


if __name__ == "__main__":
    fp = FP(
        screen_sum=2080,
        date_string="Tue May 19 2026 18:48:31 GMT+0500 (Pakistan Standard Time)",
        heap_size_limit=2248146944,
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        script_src="https://sentinel.openai.com/backend-api/sentinel/sdk.js",
        data_build=None, language="en-US", languages="en-US",
        nav_proto_sample="platform−Linux x86_64",
        doc_key_sample="__reactContainer$t068z63s9k9",
        window_key_sample="navigator", url_param_keys="",
        hardware_concurrency=7,
        in_ai=0, in_install_trigger=0, in_cache=0, in_data=0,
        in_solana=1, in_force_sync=0, in_memory=0,
    )
    sdk = SDK()
    gen = sdk.make_prover(fp, cap=2000)
    rt = gen.req_token()
    assert rt.startswith(REQ_PFX)
    assert rt[len(REQ_PFX):].endswith("~S")
    print("OK req:", rt[:48] + "...")
    cr = {"proofofwork": {"required": True, "seed": "seed-test1234", "difficulty": "00fff"}}
    et = gen.enf_token(cr)
    print("OK enf:", (et or "<fail>")[:48] + "...")
    prog = [[OP_LIT, 50, 42], [OP_CALL0, OP_RESOLVE, 50]]
    key = "k"
    pay = b64(xorm(js_str(prog), key).encode("latin-1"))
    out = sdk.exec_vm(pay, key)
    assert ub64(out).decode("utf-8") == "42"
    print("OK vm:", out)
