from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Sequence

from app.collection.actors.actor_magnets import run_magnet_jobs
from app.collection.actors.actor_works import run_actor_works
from app.collection.actors.collect_actors import run_collect_actors

FilterMode = Literal["actor", "code", "series"]


@dataclass(frozen=True)
class ActorPipeline:
    run_collect: Callable[..., Any]
    run_works: Callable[..., Any]
    run_magnets: Callable[..., Any]


def _run_collect(*, cookie_path: str, db_path: str, fetch_config: Any) -> Any:
    return run_collect_actors(
        cookie_json=cookie_path,
        db_path=db_path,
        fetch_config=fetch_config,
    )


def _run_works(
    *,
    db_path: str,
    tags: str,
    cookie_path: str,
    filter_mode: FilterMode,
    filter_values: Sequence[str],
    fetch_config: Any,
) -> Any:
    actor_name = list(filter_values) if filter_mode == "actor" else None
    return run_actor_works(
        db_path=db_path,
        tags=tags,
        cookie_json=cookie_path,
        actor_name=actor_name,
        fetch_config=fetch_config,
    )


def _run_magnets(
    *,
    output_dir: str,
    cookie_path: str,
    db_path: str,
    filter_mode: FilterMode,
    filter_values: Sequence[str],
    fetch_config: Any,
) -> Any:
    actor_name = list(filter_values) if filter_mode == "actor" else None
    code_keywords = list(filter_values) if filter_mode == "code" else None
    series_prefixes = list(filter_values) if filter_mode == "series" else None
    return run_magnet_jobs(
        out_root=output_dir,
        cookie_json=cookie_path,
        db_path=db_path,
        actor_name=actor_name,
        code_keywords=code_keywords,
        series_prefixes=series_prefixes,
        fetch_config=fetch_config,
    )


_PIPELINE = ActorPipeline(
    run_collect=_run_collect,
    run_works=_run_works,
    run_magnets=_run_magnets,
)


def get_actor_pipeline() -> ActorPipeline:
    return _PIPELINE
