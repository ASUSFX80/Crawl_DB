from __future__ import annotations

from typing import Literal, Mapping, Sequence, TypedDict


SearchMode = Literal["actor", "code", "title"]
MagnetState = Literal["all", "with", "without"]
CodeState = Literal["all", "coded", "uncensored"]
SubtitleState = Literal["all", "subtitle", "no_subtitle"]
WorkSortKey = Literal["code", "title"]
CopyKind = Literal["code", "title", "magnet"]


class WorkViewRow(TypedDict):
    actor: str
    code: str
    title: str
    href: str
    has_magnets: bool
    is_uncensored: bool
    has_subtitle: bool


def _unique_preserve_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def build_rows(
    works_cache: dict[str, list[dict]],
    magnets_cache: dict[str, dict[str, list[dict]]],
) -> list[WorkViewRow]:
    rows: list[WorkViewRow] = []
    for actor in sorted(works_cache.keys(), key=lambda item: item.lower()):
        actor_magnets = magnets_cache.get(actor, {})
        for work in works_cache.get(actor, []):
            code = str(work.get("code", "")).strip()
            title = str(work.get("title", "")).strip()
            href = str(work.get("href", "")).strip()
            upper_code = code.upper()
            rows.append(
                {
                    "actor": actor,
                    "code": code,
                    "title": title,
                    "href": href,
                    "has_magnets": bool(actor_magnets.get(code)),
                    "is_uncensored": "-U" in upper_code,
                    "has_subtitle": "-C" in upper_code,
                }
            )
    return rows


def search_rows(rows: list[WorkViewRow], mode: SearchMode, keyword: str) -> list[WorkViewRow]:
    text = keyword.strip().lower()
    if not text:
        return list(rows)
    return [row for row in rows if text in str(row.get(mode, "")).lower()]


def filter_rows(
    rows: list[WorkViewRow],
    *,
    magnet_state: MagnetState,
    code_state: CodeState,
    subtitle_state: SubtitleState,
) -> list[WorkViewRow]:
    filtered = rows
    if magnet_state == "with":
        filtered = [row for row in filtered if row["has_magnets"]]
    elif magnet_state == "without":
        filtered = [row for row in filtered if not row["has_magnets"]]

    if code_state == "coded":
        filtered = [row for row in filtered if not row["is_uncensored"]]
    elif code_state == "uncensored":
        filtered = [row for row in filtered if row["is_uncensored"]]

    if subtitle_state == "subtitle":
        filtered = [row for row in filtered if row["has_subtitle"]]
    elif subtitle_state == "no_subtitle":
        filtered = [row for row in filtered if not row["has_subtitle"]]
    return filtered


def sort_actor_names(rows: list[WorkViewRow], desc: bool = False) -> list[str]:
    names = {row["actor"] for row in rows}
    return sorted(names, key=lambda item: item.lower(), reverse=desc)


def sort_actor_works(
    rows: list[WorkViewRow], *, key: WorkSortKey, desc: bool = False
) -> list[WorkViewRow]:
    return sorted(
        rows,
        key=lambda row: (
            str(row.get(key, "")).lower(),
            row["code"].lower(),
            row["title"].lower(),
        ),
        reverse=desc,
    )


def build_magnet_export_lines(
    selected_rows: Sequence[WorkViewRow],
    actor_magnets: Mapping[str, Sequence[Mapping[str, str]]],
) -> list[str]:
    lines: list[str] = []
    for index, row in enumerate(selected_rows):
        code = str(row.get("code", "")).strip()
        title = str(row.get("title", "")).strip()
        if not code:
            continue
        magnets = actor_magnets.get(code, [])
        magnet_values = _unique_preserve_order(
            [str(item.get("magnet", "")).strip() for item in magnets]
        )
        if not magnet_values:
            continue
        if lines and index > 0:
            lines.append("")
        header = f"# {code}"
        if title:
            header += f" | {title}"
        lines.append(header)
        lines.extend(magnet_values)
    return lines


def build_copy_text(
    kind: CopyKind,
    selected_rows: Sequence[WorkViewRow],
    actor_magnets: Mapping[str, Sequence[Mapping[str, str]]],
) -> str:
    if not selected_rows:
        return ""
    if kind == "code":
        return "\n".join(
            _unique_preserve_order([str(row.get("code", "")) for row in selected_rows])
        )
    if kind == "title":
        return "\n".join(
            _unique_preserve_order([str(row.get("title", "")) for row in selected_rows])
        )
    if kind == "magnet":
        values: list[str] = []
        for row in selected_rows:
            code = str(row.get("code", "")).strip()
            if not code:
                continue
            for item in actor_magnets.get(code, []):
                values.append(str(item.get("magnet", "")).strip())
        return "\n".join(_unique_preserve_order(values))
    return ""
