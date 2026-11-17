import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

class ConfigError(ValueError):
    """Raised when an environment variable is missing, malformed, or violates safety bounds."""
    pass

def _get_str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()

def _get_bool(key: str, default: bool = True) -> bool:
    val = os.getenv(key)
    if val is None or val.strip() == "":
        return default
    v = val.strip().lower()
    if v in ("1", "true", "yes", "on", "t"):
        return True
    if v in ("0", "false", "no", "off", "f"):
        return False
    raise ConfigError(f"Invalid boolean value for environment variable '{key}': '{val}'. Expected 'true' or 'false'.")

def _get_int(key: str, default: int, min_val: int = 0) -> int:
    val = os.getenv(key)
    if val is None or val.strip() == "":
        return default
    try:
        parsed = int(val.strip())
    except ValueError:
        raise ConfigError(f"Invalid integer value for environment variable '{key}': '{val}'.")
    if parsed < min_val:
        raise ConfigError(f"Environment variable '{key}' must be >= {min_val}, got {parsed}.")
    return parsed

def _get_float(key: str, default: float, min_val: float = 0.0) -> float:
    val = os.getenv(key)
    if val is None or val.strip() == "":
        return default
    clean_val = val.strip().lstrip("$")
    try:
        parsed = float(clean_val)
    except ValueError:
        raise ConfigError(f"Invalid numeric value for environment variable '{key}': '{val}'.")
    if parsed < min_val:
        raise ConfigError(f"Environment variable '{key}' must be >= {min_val}, got {parsed}.")
    return parsed

@dataclass(frozen=True)
class Config:
    # X API Credentials
    x_api_key: str
    x_api_secret: str
    x_access_token: str
    x_access_secret: str
    x_bearer_token: str
    # LLM Settings
    llm_api_key: str
    llm_model: str
    llm_base_url: str | None
    # Safety Invariants & Outbound Controls
    test_mode: bool
    allowed_recipients: set[str]
    daily_send_cap: int
    send_delay_min_s: int
    send_delay_max_s: int
    max_x_spend_usd: float
    db_path: str

    @classmethod
    def load(cls) -> "Config":
        raw_allowed = os.getenv("ALLOWED_RECIPIENTS", "")
        allowed = {
            u.strip().lower().lstrip("@")
            for u in raw_allowed.split(",")
            if u.strip()
        }

        delay_min = _get_int("SEND_DELAY_MIN_S", 30, min_val=0)
        delay_max = _get_int("SEND_DELAY_MAX_S", 90, min_val=0)
        if delay_min > delay_max:
            delay_min, delay_max = delay_max, delay_min

        return cls(
            x_api_key=_get_str("X_API_KEY"),
            x_api_secret=_get_str("X_API_SECRET"),
            x_access_token=_get_str("X_ACCESS_TOKEN"),
            x_access_secret=_get_str("X_ACCESS_TOKEN_SECRET"),
            x_bearer_token=_get_str("X_BEARER_TOKEN"),
            llm_api_key=_get_str("LLM_API_KEY"),
            llm_model=_get_str("LLM_MODEL", default="gpt-4o-mini"),
            llm_base_url=_get_str("LLM_BASE_URL") or None,
            test_mode=_get_bool("TEST_MODE", default=True),
            allowed_recipients=allowed,
            daily_send_cap=_get_int("DAILY_SEND_CAP", default=10, min_val=1),
            send_delay_min_s=delay_min,
            send_delay_max_s=delay_max,
            max_x_spend_usd=_get_float("MAX_X_SPEND_USD", default=5.0, min_val=0.1),
            db_path=_get_str("DB_PATH", default="outreach.db"),
        )
