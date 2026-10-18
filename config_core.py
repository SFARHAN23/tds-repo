"""Layered config merge. Pure Python, no web deps."""

DEFAULTS = {"port": 8000, "workers": 1, "debug": False,
            "log_level": "info", "api_key": "default-secret-000"}

YAML_DEV = """
port: 8702
log_level: debug
"""

DOTENV = """
APP_PORT=8581
NUM_WORKERS=10
APP_LOG_LEVEL=info
"""

OS_ENV = {"APP_PORT": "8156", "APP_WORKERS": "16"}

ALIASES = {"num_workers": "workers"}


def _parse_yaml(text):
    out = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].rstrip()
        if not line.strip() or ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip().strip("'\"")
    return out


def _parse_dotenv(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip("'\"")
    return out


def _norm_key(raw):
    k = raw.strip()
    if k.upper().startswith("APP_"):
        k = k[4:]
    k = k.lower()
    return ALIASES.get(k, k)


def _normalize(d):
    return {_norm_key(k): v for k, v in d.items()}


def _coerce(key, value):
    if key in ("port", "workers"):
        if isinstance(value, bool):
            return int(value)
        return int(str(value).strip())
    if key == "debug":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "on")
    return str(value)


def parse_overrides(pairs):
    out = {}
    for p in pairs:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        out[_norm_key(k)] = v.strip()
    return out


def effective_config(set_params=()):
    merged = dict(DEFAULTS)
    merged.update(_normalize(_parse_yaml(YAML_DEV)))
    merged.update(_normalize(_parse_dotenv(DOTENV)))
    merged.update(_normalize(OS_ENV))
    merged.update(parse_overrides(set_params))
    result = {k: _coerce(k, v) for k, v in merged.items()}
    result["api_key"] = "****"
    return result
