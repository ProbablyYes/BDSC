# -*- coding: utf-8 -*-
"""快速检查 final-01 账号的项目编号是否都已关联到学号。"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

USER_ID = "99fed9ab-486c-4b22-8329-b3c6466e17d2"
SID = "1120230236"
ROOT = Path(__file__).resolve().parents[3]
PROJ_FILE = ROOT / "data" / "project_state" / f"project-{USER_ID}.json"
USERS_FILE = ROOT / "data" / "users" / "users.json"


def main() -> int:
    proj = json.loads(PROJ_FILE.read_text(encoding="utf-8"))
    users = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    me = next((u for u in users if u.get("user_id") == USER_ID), None)
    if not me:
        print(f"[FATAL] 没找到 user_id={USER_ID}")
        return 1

    print(f"账号 final-01 / {me.get('display_name')}  user_id={USER_ID}")
    print(f"  student_id              = {me.get('student_id')!r}")
    print(f"  project_serial_counter  = {me.get('project_serial_counter')}")
    print()

    submissions = proj.get("submissions") or []
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for s in submissions:
        lid = str(s.get("logical_project_id") or "<empty>")
        groups[lid].append(s)

    print("项目编号汇总（按编号升序）：")
    print(f"{'状态':<4} {'项目编号':<20} {'提交数':>6} {'会话数':>6}  最近时间")
    print("-" * 70)
    for lid in sorted(groups.keys()):
        rows = groups[lid]
        convs = {r.get("conversation_id") for r in rows}
        last = max((r.get("created_at", "") for r in rows), default="")
        flag = "OK" if lid.startswith(f"P-{SID}-") else "!!"
        print(f"{flag:<4} {lid:<20} {len(rows):>6} {len(convs):>6}  {last[:19]}")

    mismatched = [lid for lid in groups if not lid.startswith(f"P-{SID}-")]
    print()
    print(
        f"总计 {len(submissions)} 条提交 / {len(groups)} 个项目编号 / "
        f"未关联到学号 {SID} 的编号: {len(mismatched)}"
    )
    if not mismatched:
        print("[OK] final-01 账号下所有项目编号已经关联到学号 1120230236。")
        return 0
    print("[WARN] 下列项目编号需要回填 / 修复：")
    for lid in mismatched:
        print(f"  - {lid}（{len(groups[lid])} 条）")
    return 2


if __name__ == "__main__":
    sys.exit(main())
