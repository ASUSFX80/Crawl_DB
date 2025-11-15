import argparse
from pathlib import Path

from config import LOGGER
from get_collect_actors import run_collect_actors
from get_actor_works import run_actor_works
from get_works_magnet import run_magnet_jobs
import mdcx_magnets
from storage import Storage


def prepare_environment(db_path: str, magnets_dir: str) -> None:
    """
    初始化运行所需的数据库结构与磁链目录。
    """
    db_file = Path(db_path)
    if db_file.parent:
        db_file.parent.mkdir(parents=True, exist_ok=True)
    # 打开后立即关闭，确保 schema.sql 被执行并创建数据库文件
    with Storage(db_file) as _:
        pass

    Path(magnets_dir).mkdir(parents=True, exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description="抓取收藏演员、作品及磁链的完整流程")
    parser.add_argument(
        "--cookie", default="cookie.json", help="Cookie JSON 路径，默认 cookie.json"
    )
    parser.add_argument(
        "--db-path",
        default="userdata/actors.db",
        help="SQLite 数据库文件路径，默认 userdata/actors.db。",
    )
    parser.add_argument(
        "--magnets-dir",
        default="userdata/magnets",
        help="磁链 TXT 输出目录，默认 userdata/magnets",
    )
    parser.add_argument(
        "--tags", help="作品抓取标签过滤，逗号分隔，例如 s 或 s,d", default=None
    )
    parser.add_argument(
        "--sort-type", help="作品抓取 sort_type 参数，例如 0", default=None
    )
    parser.add_argument(
        "--skip-collect", action="store_true", help="跳过收藏演员抓取步骤"
    )
    parser.add_argument("--skip-works", action="store_true", help="跳过作品抓取步骤")
    parser.add_argument("--skip-magnets", action="store_true", help="跳过磁链抓取步骤")
    args = parser.parse_args()

    prepare_environment(args.db_path, args.magnets_dir)

    if not args.skip_collect:
        run_collect_actors(cookie_json=args.cookie, db_path=args.db_path)
    else:
        LOGGER.info("跳过收藏演员抓取。")

    if not args.skip_works:
        run_actor_works(
            db_path=args.db_path,
            tags=args.tags,
            sort_type=args.sort_type,
            cookie_json=args.cookie,
        )
    else:
        LOGGER.info("跳过作品列表抓取。")

    if not args.skip_magnets:
        run_magnet_jobs(
            out_root=args.magnets_dir,
            cookie_json=args.cookie,
            db_path=args.db_path,
        )
    else:
        LOGGER.info("跳过磁链抓取。")

    try:
        mdcx_magnets.run(
            db_path=args.db_path,
            output_root=args.magnets_dir,
        )
    except Exception as exc:  
        LOGGER.error("磁链筛选失败: %s", exc)


if __name__ == "__main__":
    main()
