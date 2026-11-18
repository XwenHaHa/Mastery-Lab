"""SQLite 持久化验证（只读）。

直连 data/mastery_lab.db，打印表结构、课程/章节/知识点行数与按课程组织的目录树。
后端重启前后各跑一次，用输出对比即可证明数据落在文件里、不依赖进程内存。

运行：apps\\api\\.venv\\Scripts\\python.exe docs\\qa\\db_check.py
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "mastery_lab.db"


def main() -> None:
    print(f"数据库文件: {DB}")
    print(f"文件大小: {DB.stat().st_size} bytes（含 -wal/-shm 说明用了 WAL 模式）")
    for suffix in ("-wal", "-shm"):
        extra = DB.with_name(DB.name + suffix)
        print(f"  伴随文件 {extra.name}: {'存在 ' + str(extra.stat().st_size) + ' bytes' if extra.exists() else '不存在'}")

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    tables = [r[0] for r in con.execute(
        "select name from sqlite_master where type='table' order by name")]
    print(f"\n表: {tables}")
    for table in ("courses", "chapters", "knowledge_points"):
        columns = [r["name"] for r in con.execute(f"pragma table_info({table})")]
        count = con.execute(f"select count(*) from {table}").fetchone()[0]
        print(f"  {table}: {count} 行, 列={columns}")

    print("\n课程目录树（来自 SQL 查询，非接口返回）：")
    tree: list[dict[str, object]] = []
    for course in con.execute(
        "select id, title, status, source_type, source_name from courses order by id"
    ):
        chapters = []
        for chapter in con.execute(
            "select id, title, sort_order from chapters where course_id=? order by sort_order",
            (course["id"],),
        ):
            points = [
                {"title": p["title"], "codeCount": p["code_count"],
                 "status": p["learning_status"]}
                for p in con.execute(
                    "select title, code_count, learning_status from knowledge_points "
                    "where chapter_id=? order by sort_order",
                    (chapter["id"],),
                )
            ]
            chapters.append({"chapter": chapter["title"], "points": points})
        tree.append({
            "id": course["id"], "title": course["title"], "status": course["status"],
            "sourceType": course["source_type"], "sourceName": course["source_name"],
            "chapters": chapters,
        })
    print(json.dumps(tree, ensure_ascii=False, indent=2))

    path = Path(__file__).parent / "db-check-result.json"
    path.write_text(json.dumps(
        {"db": str(DB), "size": DB.stat().st_size, "tables": tables, "tree": tree},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入 {path}")
    con.close()


if __name__ == "__main__":
    main()
