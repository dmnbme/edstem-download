import os
import pathlib
import tomllib

DEFAULT_CONFIG = {
    "ed": {
        "host": "https://edstem.org/api",
        "token": "",
    },
    "export": {
        "image_mode": "base64",
        "output_dir": "",
    },
}


def _deep_merge_dict(base: dict, override: dict) -> dict:
    """
    simple recursive dict merge
    values from override will cover base
    """
    result = dict(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | os.PathLike | None = None) -> dict:
    """
    get config from config
    use base config if config.toml not found
    """
    base_cfg = DEFAULT_CONFIG

    if path is None:
        path = pathlib.Path("config.toml")
    else:
        path = pathlib.Path(path)

    if path.is_file():
        with path.open("rb") as f:
            file_cfg = tomllib.load(f)
        return _deep_merge_dict(base_cfg, file_cfg)

    return base_cfg


def get_ed_host(cfg: dict) -> str:
    """
    get ed_host url from config
    use base config if config.toml not found
    """
    return cfg.get("ed", {}).get("host") or DEFAULT_CONFIG["ed"]["host"]


def get_token(cfg: dict) -> str:
    """
    get Ed API token from env var, or config
    return empty string if both do not exist
    """
    env_token = os.environ.get("ED_PAT", "")
    if env_token:
        return env_token

    return cfg.get("ed", {}).get("token", "") or ""


def get_image_mode(cfg: dict) -> str:
    """
    get image export mode: "base64" | "file" | "url"
    use base64 if config not found or invalid config item
    """
    mode = cfg.get("export", {}).get("image_mode", "") or ""
    mode = mode.lower().strip()
    if mode in {"base64", "file", "url"}:
        return mode
    return DEFAULT_CONFIG["export"]["image_mode"]


def get_output_dir(cfg: dict) -> pathlib.Path:
    """
    get export directory from config
    use current working dir if not set
    """
    raw = cfg.get("export", {}).get("output_dir", "") or ""
    if not raw:
        return pathlib.Path.cwd()
    return pathlib.Path(raw).expanduser().resolve()