from __future__ import annotations

import configparser
import shutil
from pathlib import Path
from typing import Dict, Optional

DEFAULT_COOKIE = Path("cookie.json")
DEFAULT_DB = Path("userdata") / "actors.db"
DEFAULT_OUTPUT = Path("userdata") / "magnets"
DEFAULT_DELAY_RANGE = "0.8-1.6"
DEFAULT_FETCH_MODE = "browser"
DEFAULT_COLLECT_SCOPE = "actor"
DEFAULT_BASE_DOMAIN_SEGMENT = "javdb"
DEFAULT_BROWSER_USER_DATA_DIR = Path("userdata") / "browser_profile" / "javdb"
DEFAULT_BROWSER_HEADLESS = False
DEFAULT_BROWSER_TIMEOUT_SECONDS = 30
DEFAULT_CHALLENGE_TIMEOUT_SECONDS = 60


def is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def select_runtime_root(
    *, frozen: bool, executable: str, cwd: Path, home: Path
) -> tuple[Path, bool]:
    if frozen:
        preferred = (home / ".crawljav").resolve()
        if is_writable_dir(preferred):
            return preferred, False

        fallback_candidates = (
            Path(executable).resolve().parent,
            cwd.resolve(),
        )
        for candidate in fallback_candidates:
            if is_writable_dir(candidate):
                return candidate, True
        return preferred, True

    preferred = cwd.resolve()
    if is_writable_dir(preferred):
        return preferred, False
    fallback = (home / ".crawljav").resolve()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback, True


def to_storable_path(path: Path, runtime_root: Path) -> str:
    runtime_root = runtime_root.resolve()
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = runtime_root / candidate
    candidate = candidate.resolve(strict=False)
    try:
        rel = candidate.relative_to(runtime_root)
        return str(rel)
    except ValueError:
        return str(candidate)


def resolve_stored_path(value: str, runtime_root: Path) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    return (runtime_root / candidate).resolve(strict=False)


def _normalize_collect_scope(value: str) -> str:
    return DEFAULT_COLLECT_SCOPE


def load_ini_config(config_file: Path, runtime_root: Path) -> Dict[str, object]:
    parser = configparser.ConfigParser()
    parser.read(config_file, encoding="utf-8")
    cookie = parser.get("paths", "cookie", fallback=str(DEFAULT_COOKIE))
    db_path = parser.get("paths", "db", fallback=str(DEFAULT_DB))
    output_dir = parser.get("paths", "output_dir", fallback=str(DEFAULT_OUTPUT))
    delay_range = parser.get("ui", "delay_range", fallback=DEFAULT_DELAY_RANGE)
    fetch_mode = parser.get("fetch", "mode", fallback=DEFAULT_FETCH_MODE)
    if fetch_mode not in ("httpx", "browser"):
        fetch_mode = DEFAULT_FETCH_MODE
    collect_scope = _normalize_collect_scope(
        parser.get("fetch", "collect_scope", fallback=DEFAULT_COLLECT_SCOPE)
    )
    browser_user_data_dir = parser.get(
        "fetch",
        "browser_user_data_dir",
        fallback=str(DEFAULT_BROWSER_USER_DATA_DIR),
    )
    browser_headless = parser.getboolean(
        "fetch",
        "browser_headless",
        fallback=DEFAULT_BROWSER_HEADLESS,
    )
    browser_timeout_seconds = parser.getint(
        "fetch",
        "browser_timeout_seconds",
        fallback=DEFAULT_BROWSER_TIMEOUT_SECONDS,
    )
    challenge_timeout_seconds = parser.getint(
        "fetch",
        "challenge_timeout_seconds",
        fallback=DEFAULT_CHALLENGE_TIMEOUT_SECONDS,
    )
    base_domain_segment = parser.get(
        "site",
        "base_domain_segment",
        fallback=DEFAULT_BASE_DOMAIN_SEGMENT,
    )
    migrated = parser.getboolean("meta", "migrated_from_legacy", fallback=False)
    return {
        "cookie":
            resolve_stored_path(cookie, runtime_root),
        "db":
            resolve_stored_path(db_path, runtime_root),
        "output_dir":
            resolve_stored_path(output_dir, runtime_root),
        "delay_range":
            delay_range,
        "fetch_mode":
            fetch_mode,
        "collect_scope":
            collect_scope,
        "browser_user_data_dir":
            resolve_stored_path(browser_user_data_dir, runtime_root),
        "browser_headless":
            browser_headless,
        "browser_timeout_seconds":
            browser_timeout_seconds,
        "challenge_timeout_seconds":
            challenge_timeout_seconds,
        "base_domain_segment":
            base_domain_segment,
        "migrated_from_legacy":
            migrated,
    }


def save_ini_config(
    *,
    config_file: Path,
    runtime_root: Path,
    cookie_path: Path,
    db_path: Path,
    output_dir: Path,
    delay_range: str,
    fetch_mode: str = DEFAULT_FETCH_MODE,
    collect_scope: str = DEFAULT_COLLECT_SCOPE,
    base_domain_segment: str = DEFAULT_BASE_DOMAIN_SEGMENT,
    browser_user_data_dir: Optional[Path] = None,
    browser_headless: bool = DEFAULT_BROWSER_HEADLESS,
    browser_timeout_seconds: int = DEFAULT_BROWSER_TIMEOUT_SECONDS,
    challenge_timeout_seconds: int = DEFAULT_CHALLENGE_TIMEOUT_SECONDS,
    migrated_from_legacy: bool = False,
) -> None:
    parser = configparser.ConfigParser()
    parser["paths"] = {
        "cookie": to_storable_path(cookie_path, runtime_root),
        "db": to_storable_path(db_path, runtime_root),
        "output_dir": to_storable_path(output_dir, runtime_root),
    }
    parser["ui"] = {"delay_range": delay_range or DEFAULT_DELAY_RANGE}
    parser["fetch"] = {
        "mode":
            fetch_mode if fetch_mode in ("httpx", "browser")
            else DEFAULT_FETCH_MODE,
        "collect_scope":
            _normalize_collect_scope(collect_scope),
        "browser_user_data_dir":
            to_storable_path(
                browser_user_data_dir
                or (runtime_root / DEFAULT_BROWSER_USER_DATA_DIR),
                runtime_root,
            ),
        "browser_headless":
            "true" if browser_headless else "false",
        "browser_timeout_seconds":
            str(
                int(browser_timeout_seconds or DEFAULT_BROWSER_TIMEOUT_SECONDS)
            ),
        "challenge_timeout_seconds":
            str(
                int(
                    challenge_timeout_seconds
                    or DEFAULT_CHALLENGE_TIMEOUT_SECONDS
                )
            ),
    }
    parser["site"] = {
        "base_domain_segment": str(base_domain_segment),
    }
    parser["meta"] = {
        "migrated_from_legacy": "true" if migrated_from_legacy else "false"
    }
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with config_file.open("w", encoding="utf-8") as fp:
        parser.write(fp)


def migrate_legacy_config_once(
    *,
    config_file: Path,
    runtime_root: Path,
    qsettings_defaults: Optional[dict] = None,
    legacy_root: Optional[Path] = None,
) -> dict:
    if config_file.exists():
        return load_ini_config(config_file, runtime_root)

    legacy_root = legacy_root or (Path.home() / ".crawljav")
    defaults = {
        "cookie": (runtime_root / DEFAULT_COOKIE).resolve(strict=False),
        "db": (runtime_root / DEFAULT_DB).resolve(strict=False),
        "output_dir": (runtime_root / DEFAULT_OUTPUT).resolve(strict=False),
        "delay_range":
            DEFAULT_DELAY_RANGE,
        "fetch_mode":
            DEFAULT_FETCH_MODE,
        "collect_scope":
            DEFAULT_COLLECT_SCOPE,
        "base_domain_segment":
            DEFAULT_BASE_DOMAIN_SEGMENT,
        "browser_user_data_dir":
            (runtime_root /
             DEFAULT_BROWSER_USER_DATA_DIR).resolve(strict=False),
        "browser_headless":
            DEFAULT_BROWSER_HEADLESS,
        "browser_timeout_seconds":
            DEFAULT_BROWSER_TIMEOUT_SECONDS,
        "challenge_timeout_seconds":
            DEFAULT_CHALLENGE_TIMEOUT_SECONDS,
    }

    legacy_values = {
        "cookie": legacy_root / "cookie.json",
        "db": legacy_root / "userdata" / "actors.db",
        "output_dir": legacy_root / "userdata" / "magnets",
    }
    for key, path in legacy_values.items():
        if path.exists():
            defaults[key] = path.resolve(strict=False)

    if qsettings_defaults:
        q_cookie = qsettings_defaults.get("cookie")
        q_db = qsettings_defaults.get("db")
        q_output = qsettings_defaults.get("output_dir")
        q_delay = qsettings_defaults.get("delay_range")
        if q_cookie:
            defaults["cookie"] = _resolve_legacy_setting_path(
                str(q_cookie),
                runtime_root=runtime_root,
                legacy_root=legacy_root
            )
        if q_db:
            defaults["db"] = _resolve_legacy_setting_path(
                str(q_db), runtime_root=runtime_root, legacy_root=legacy_root
            )
        if q_output:
            defaults["output_dir"] = _resolve_legacy_setting_path(
                str(q_output),
                runtime_root=runtime_root,
                legacy_root=legacy_root
            )
        if q_delay:
            defaults["delay_range"] = str(q_delay)

    target_cookie = (runtime_root / DEFAULT_COOKIE).resolve(strict=False)
    target_db = (runtime_root / DEFAULT_DB).resolve(strict=False)
    target_output = (runtime_root / DEFAULT_OUTPUT).resolve(strict=False)

    _copy_if_missing(Path(defaults["cookie"]), target_cookie, is_dir=False)
    _copy_if_missing(Path(defaults["db"]), target_db, is_dir=False)
    _copy_if_missing(Path(defaults["output_dir"]), target_output, is_dir=True)

    save_ini_config(
        config_file=config_file,
        runtime_root=runtime_root,
        cookie_path=Path(defaults["cookie"]),
        db_path=Path(defaults["db"]),
        output_dir=Path(defaults["output_dir"]),
        delay_range=str(defaults["delay_range"]),
        fetch_mode=str(defaults["fetch_mode"]),
        collect_scope=str(defaults["collect_scope"]),
        base_domain_segment=str(defaults["base_domain_segment"]),
        browser_user_data_dir=Path(defaults["browser_user_data_dir"]),
        browser_headless=bool(defaults["browser_headless"]),
        browser_timeout_seconds=int(defaults["browser_timeout_seconds"]),
        challenge_timeout_seconds=int(defaults["challenge_timeout_seconds"]),
        migrated_from_legacy=True,
    )
    return load_ini_config(config_file, runtime_root)


def _resolve_legacy_setting_path(
    value: str, *, runtime_root: Path, legacy_root: Path
) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve(strict=False)
    legacy_candidate = (legacy_root / path).resolve(strict=False)
    if legacy_candidate.exists():
        return legacy_candidate
    return (runtime_root / path).resolve(strict=False)


def _copy_if_missing(source: Path, target: Path, *, is_dir: bool) -> None:
    if target.exists() or not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if is_dir:
        shutil.copytree(source, target, dirs_exist_ok=True)
    else:
        shutil.copy2(source, target)
