from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

from app.core.storage import Storage
from app.core.utils import sanitize_filename


LOGGER = logging.getLogger("crawljav.mdcx_magnets")
KEYWORDS = {"高清", "字幕"}
SIZE_PATTERN = re.compile(r"([\d.]+)\s*GB", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "根据磁链体积和关键标签，从数据库中挑选每部作品的最佳磁链，"
            "并写入以演员命名的 txt 文件。"
        )
    )
    parser.add_argument(
        "output",
        type=Path,
        help="TXT 输出根目录。",
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        default="userdata/actors.db",
        help="数据库文件路径（默认：userdata/actors.db）。",
    )
    parser.add_argument(
        "-c",
        "--current-only",
        action="store_true",
        help="保持与旧版兼容，但已无实际作用。",
    )
    return parser.parse_args()


def extract_size(size_field: Optional[str]) -> Optional[float]:
    if not size_field:
        return None
    match = SIZE_PATTERN.search(size_field)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def count_keyword_hits(tags_field: Optional[str]) -> int:
    if not tags_field:
        return 0
    tags = [segment.strip() for segment in tags_field.split(",")]
    return sum(1 for tag in tags if tag in KEYWORDS)


def pick_best_magnet(rows: Iterable[Mapping[str, str]]) -> Optional[str]:
    best_magnet: Optional[str] = None
    best_size = -1.0
    best_keyword_hits = -1

    for row in rows:
        magnet = row.get("magnet")
        if not magnet:
            continue

        size_value = extract_size(row.get("size"))
        if size_value is None:
            continue

        keyword_hits = count_keyword_hits(row.get("tags"))

        if size_value > best_size or (
            size_value == best_size and keyword_hits > best_keyword_hits
        ):
            best_size = size_value
            best_keyword_hits = keyword_hits
            best_magnet = magnet

    return best_magnet


def collect_best_magnets(
    works: Mapping[str, List[Dict[str, str]]]
) -> List[str]:
    magnets: List[str] = []
    for code in sorted(works):
        best_magnet = pick_best_magnet(works[code])
        if best_magnet:
            magnets.append(best_magnet)
    return magnets


def write_output(directory: Path, magnets: Iterable[str]) -> int:
    output_path = directory / f"{directory.name}.txt"
    magnets = list(magnets)

    # 去重保持顺序，避免重复写入同一磁链
    unique_magnets: list[str] = []
    seen = set()
    for magnet in magnets:
        if magnet not in seen:
            unique_magnets.append(magnet)
            seen.add(magnet)

    if output_path.exists():
        existing = {
            line.strip()
            for line in output_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    else:
        existing = set()

    new_entries = [magnet for magnet in unique_magnets if magnet not in existing]
    if not new_entries:
        return 0

    with output_path.open("a", encoding="utf-8") as handle:
        for magnet in new_entries:
            handle.write(f"{magnet}\n")

    return len(new_entries)


def process_actor(
    actor_name: str,
    works: Mapping[str, List[Dict[str, str]]],
    output_root: Path,
) -> tuple[int, int, Path]:
    actor_dir = output_root / sanitize_filename(actor_name, default="actor")
    actor_dir.mkdir(parents=True, exist_ok=True)
    magnets = collect_best_magnets(works)
    if not magnets:
        return 0, 0, f"{actor_dir.name}.txt"
    added = write_output(actor_dir, magnets)
    return added, len(magnets), f"{actor_dir.name}.txt"


def run(
    db_path: Path | str,
    output_root: Path | str,
    *,
    current_only: bool = False,
) -> None:
    if current_only:
        LOGGER.debug("--current-only 参数已无实际作用，将忽略。")

    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)

    with Storage(db_path) as store:
        grouped = store.get_magnets_grouped()

    if not grouped:
        LOGGER.warning("数据库中未找到磁链数据。")
        return

    total_written = 0
    had_candidates = False

    for actor_name, works in grouped.items():
        added, processed, output_path = process_actor(
            actor_name, works, output_root_path
        )
        if processed == 0:
            LOGGER.info("%s 未找到符合条件的磁链。", actor_name)
            continue
        had_candidates = True
        if added > 0:
            total_written += added
            LOGGER.info("新增 %d 条磁链到 %s", added, output_path)
        else:
            LOGGER.info("%s 中的磁链已全部存在，未新增。", output_path)

    if total_written == 0:
        if had_candidates:
            LOGGER.info("所有磁链均已存在，未新增。")
        else:
            LOGGER.warning("未写入任何磁链，请检查数据库中的磁链数据。")


def main() -> None:
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )
    from app.core.utils import setup_daily_file_logger

    setup_daily_file_logger()
    args = parse_args()
    try:
        run(
            db_path=args.db_path,
            output_root=args.output,
            current_only=args.current_only,
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("%s", exc)


if __name__ == "__main__":
    main()
