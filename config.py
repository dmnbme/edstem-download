import os

# Base API host
ED_HOST = "https://edstem.org/api"

# Optional fallback token; prefer env var ED_PAT.
HARD_CODED_TOKEN = ""  # put your PAT here if you don't want to use env var


def get_token() -> str:
    """
    Resolve token from environment first, then optional hard-coded fallback.
    """
    return os.environ.get("ED_PAT", "") or HARD_CODED_TOKEN
