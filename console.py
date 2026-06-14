from datetime import datetime

R     = "\033[0m"
GREY  = "\033[90m"
WHITE = "\033[97m"

LABELS = {
    "VERIFIED": "\033[92m",
    "SUCCESS":  "\033[92m",
    "FAILED":   "\033[91m",
    "WAITING":  "\033[90m",
    "PENDING":  "\033[90m",
    "ERROR":    "\033[91m",
    "INPUT":    "\033[93m",
    "INFO":     "\033[94m",
    "SOLVING":  "\033[95m",
}


def ts():
    return f"{GREY}{datetime.now().strftime('%H:%M:%S')}{R}"


def log(label: str, message: str, detail: str = None):
    color = LABELS.get(label, WHITE)
    det = f" {GREY}[{detail}]{R}" if detail else ""
    print(f"{ts()} {color}{label}{R} > {WHITE}{message}{R}{det}")
