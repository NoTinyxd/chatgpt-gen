import threading, requests, random, string, json, queue
from typing import List, Tuple

def r(n=8, a=string.ascii_lowercase + string.digits):
    import random
    return ''.join(random.choices(a, k=n))

def load():
    with open('config.json', 'r', encoding='utf-8') as f:
        c = json.load(f)
    if not c.get('mailcows'):
        raise SystemExit("config.json needs 'mailcows'")
    for m in c['mailcows']:
        for k in ('domain', 'api_url', 'api_key'):
            if k not in m:
                raise SystemExit(f"missing {k} in {m}")
        if isinstance(m['domain'], str):
            m['domain'] = [m['domain']]
        elif isinstance(m['domain'], list):
            m['domain'] = [d.strip() for d in m['domain'] if d and d.strip()]
        else:
            raise SystemExit("'domain' must be a string or list of strings")
        if not m['domain']:
            raise SystemExit("at least one domain required in 'domain'")
    return c

def payload(local, domain, name, pw, quota):
    return {
        "local_part": local, "domain": domain, "name": name, "quota": quota,
        "password": pw, "password2": pw, "active": True,
        "force_pw_update": False, "tls_enforce_in": True, "tls_enforce_out": True
    }

def create(url, key, p):
    try:
        res = requests.post(url, json=p,
                            headers={"Content-Type": "application/json", "X-API-Key": key},
                            timeout=45)
    except Exception as e:
        return False, f"request error: {e}"
    try:
        data = res.json()
    except Exception:
        return (True, f"{p['local_part']}@{p['domain']}") if res.ok else (False, f"HTTP {res.status_code}: {res.text.strip()[:300]}")
    if isinstance(data, list) and data:
        t = (data[0].get('type','') or '').lower()
        msg = data[0].get('msg')
        msg = ' | '.join(map(str, msg)) if isinstance(msg, list) else str(msg)
        return (True, f"{p['local_part']}@{p['domain']}") if t == 'success' else (False, msg or t or 'unknown error')
    return (True, f"{p['local_part']}@{p['domain']}") if res.ok else (False, f"HTTP {res.status_code}: {res.text.strip()[:300]}")

def _round_robin_plan(total: int, buckets: List[Tuple[dict, str]]):
    if total <= 0 or not buckets: return []
    base, rem = divmod(total, len(buckets))
    targets = [base + (1 if i < rem else 0) for i in range(len(buckets))]
    plan, remain = [], targets[:]
    i, left = 0, sum(remain)
    while left:
        if remain[i] > 0:
            plan.append(buckets[i]); remain[i] -= 1; left -= 1
        i = (i + 1) % len(buckets)
    return plan

def create_inbox(cfg):
    name = cfg.get('fixed_display_name', 'Mail User')
    pwd_len = int(cfg.get('password_length', 12))
    global_quota = int(cfg.get('quota_mb', 3072))
    out_file = cfg.get('output_file', 'output.txt')

    buckets = []
    for mc in cfg['mailcows']:
        for d in mc['domain']:
            buckets.append((mc, d))
    if not buckets:
        raise RuntimeError("no mailcow buckets configured")

    mc, domain = random.choice(buckets)
    local = r(10)
    pw = r(pwd_len, string.ascii_letters + string.digits)
    quota = int(mc.get('quota_mb', global_quota))
    p = payload(local, domain, name, pw, quota)
    ok, msg = create(mc['api_url'], mc['api_key'], p)
    if not ok:
        raise RuntimeError(f"mailcow create failed: {msg}")
    addr = f"{local}@{domain}"
    with open(out_file, 'a', encoding='utf-8') as f:
        f.write(f"{addr}:{pw}\n")
    return addr, pw


def run(total, cfg):
    of = cfg.get('output_file', 'created_inboxes.txt')
    threads_total = int(cfg.get('threads', 100))  # GLOBAL cap
    global_quota = int(cfg.get('quota_mb', 3072))
    name = cfg.get('fixed_display_name', 'Mail User')
    pwd_len = int(cfg.get('password_length', 12))
    per_instance_limit = int(cfg.get('per_instance_limit', threads_total))  # optional

    # Build (mailcow, domain) buckets
    buckets = []
    for mc in cfg['mailcows']:
        for d in mc['domain']:
            buckets.append((mc, d))
    if not buckets:
        raise SystemExit("No domains found")

    plan = _round_robin_plan(total, buckets)

    q = queue.Queue()
    for mc, domain in plan:
        q.put((mc, domain))

    # Per-instance semaphores so a single Mailcow isn't hit with all threads
    sem_by_instance = {}
    for mc in cfg['mailcows']:
        key = mc['api_url']  # group by API endpoint
        if key not in sem_by_instance:
            sem_by_instance[key] = threading.Semaphore(max(1, min(per_instance_limit, threads_total)))

    created = 0
    created_lock = threading.Lock()
    io_lock = threading.Lock()

    def worker():
        nonlocal created
        while True:
            try:
                mc, domain = q.get_nowait()
            except queue.Empty:
                return
            sem = sem_by_instance[mc['api_url']]
            try:
                with sem:
                    local = r(10)
                    pw = r(pwd_len, string.ascii_letters + string.digits)
                    quota = int(mc.get('quota_mb', global_quota))
                    p = payload(local, domain, name, pw, quota)
                    ok, msg = create(mc['api_url'], mc['api_key'], p)
                    addr = f"{p['local_part']}@{p['domain']}"
                    if ok:
                        with io_lock:
                            with open(of, 'a', encoding='utf-8') as f:
                                f.write(f"{addr}:{pw}\n")
                        with created_lock:
                            created += 1
                            print(f"✅ Created {created}/{total}: {addr}")
                    else:
                        print(f"❌ Failed {addr}: {msg}")
            except Exception as e:
                print(f"❌ Error: {e}")
            finally:
                q.task_done()

    n_workers = max(1, min(threads_total, total))  # GLOBAL threads only
    workers = []
    for _ in range(n_workers):
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        workers.append(t)
    for t in workers:
        t.join()

if __name__ == '__main__':
    try:
        cfg = load()
        raw = input("How many mailboxes to create (total across all domains)? ").strip()
        total = int(raw) if raw else 1
        if total <= 0: raise ValueError
    except Exception:
        print("Invalid number. Using 1."); total = 1

    all_domains = [d for mc in cfg['mailcows'] for d in mc['domain']]
    print("Domains: " + ", ".join(all_domains))
    print(f"Starting creation of {total} mailbox(es) …")
    run(total, cfg)
    print("Done.")