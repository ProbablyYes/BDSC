# -*- coding: utf-8 -*-
"""为历史会话补齐规范 `logical_project_id`（P-学号-NN）。

背景：
    旧逻辑下，如果 `_derive_logical_project_id` 在用户尚未填学号时被调用，
    会把 conversation_id（或 project_id）当作 logical_project_id 写入 submissions。
    这些遗留记录会让前端 topbar 把 "#xxx" 当作"历史编号"展示，看起来像是
    "项目编号没出现"。

本脚本的职责：
    遍历 data_root/project_state/*.json：
      - 每个项目所属的 user_id 由 project_id="project-{user_id}" 反推。
      - 取出该用户当前的 student_id；如果没填学号，跳过（保持原状）。
      - 对该项目下所有 submissions 按 conversation_id 分组，按时间顺序：
          * 该 conversation 已有规范编号 P-{sid}-NN → 沿用，不重新分配。
          * 该 conversation 仅有 legacy 编号（等于 conversation_id 或 project_id 或为空）
            → 复用 user.project_serial_counter 自增，得到 P-{sid}-NN，
              并把该 conversation 下所有 submissions 的 logical_project_id 改写为这个新编号。
    最后保存 user store（counter 自增）和 project_state JSON。

使用：
    cd apps/backend
    .venv\\Scripts\\python.exe scripts/backfill_logical_id.py            # 仅打印 dry-run 计划
    .venv\\Scripts\\python.exe scripts/backfill_logical_id.py --apply    # 真正写盘

幂等：再次运行不会再分配新编号（已规范的 conversation 会被识别并跳过）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 复用主进程的存储与配置
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # type: ignore  # noqa: E402
from app.services.storage import JsonStorage, UserStorage  # type: ignore  # noqa: E402

_STD_RE = re.compile(r"^P-[A-Za-z0-9_-]+-\d{2,}$")


def _is_standard(lid: str | None) -> bool:
    return bool(lid) and bool(_STD_RE.match(str(lid)))


def _owner_uid(project_id: str) -> str | None:
    if isinstance(project_id, str) and project_id.startswith("project-"):
        return project_id[len("project-"):]
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正写盘；缺省只 dry-run")
    parser.add_argument("--root", type=str, default=str(settings.data_root), help="data_root 路径，缺省取 settings.data_root")
    parser.add_argument("--user-filter", type=str, default="",
                        help="只处理某个 user (匹配 user_id 或 student_id), e.g. final-01 或 1120230236")
    args = parser.parse_args()

    data_root = Path(args.root)
    project_state_dir = data_root / "project_state"
    if not project_state_dir.exists():
        print(f"[skip] project_state dir not found: {project_state_dir}")
        return 0

    json_store = JsonStorage(project_state_dir)
    user_store = UserStorage(data_root / "users")

    files = sorted(project_state_dir.glob("*.json"))
    total_projects = 0
    total_subs = 0
    total_renamed = 0
    total_new_ids = 0
    total_skipped_no_sid = 0

    for fp in files:
        try:
            project_id = fp.stem
            data = json_store.load_project(project_id)
        except Exception as exc:
            print(f"[warn] cannot load {fp.name}: {exc}")
            continue

        subs = data.get("submissions") or []
        if not subs:
            continue
        total_projects += 1
        total_subs += len(subs)

        owner = _owner_uid(project_id)
        if not owner:
            continue
        user = user_store.get_by_id(owner) or {}
        sid_raw = user.get("student_id")
        sid = "" if sid_raw is None else str(sid_raw).strip()

        # --user-filter 支持匹配 user_id 或 student_id
        if args.user_filter:
            uf = args.user_filter.strip().lower()
            if uf and uf not in (str(owner).lower(), sid.lower()):
                continue
        # 排除掉历史脏数据里的字面量 "None" / "null"
        if sid.lower() in {"", "none", "null", "undefined"}:
            total_skipped_no_sid += 1
            continue
        # 学号必须看起来像学号（数字或者数字+字母），防止把奇怪字符串拼成 P-XX-NN
        if not re.match(r"^[A-Za-z0-9_-]{4,}$", sid):
            total_skipped_no_sid += 1
            print(f"[skip-bad-sid] {project_id} student_id={sid!r}")
            continue

        # 按 conversation_id 分组（None 单独成组）
        groups: dict[str, list[dict]] = {}
        order: list[str] = []
        for idx, row in enumerate(subs):
            # 没有 conversation_id 的行各自成组（避免被合并/丢失）
            cid = str(row.get("conversation_id") or "") or f"__no_conv__{idx}"
            if cid not in groups:
                groups[cid] = []
                order.append(cid)
            groups[cid].append(row)

        dirty = False
        for cid in order:
            rows = groups[cid]
            # 1) 这一组里如果已经有规范编号，沿用之
            existing_std = next(
                (str(r.get("logical_project_id")) for r in rows if _is_standard(r.get("logical_project_id"))),
                None,
            )
            if existing_std:
                # 把组内未规范的也补上同一个标准编号（含 legacy / 空）
                changed_here = 0
                for r in rows:
                    if str(r.get("logical_project_id") or "") != existing_std:
                        if args.apply:
                            r["logical_project_id"] = existing_std
                        changed_here += 1
                if changed_here:
                    dirty = True
                    total_renamed += changed_here
                    print(f"[fix-existing] {project_id} cid={cid[:12]} -> {existing_std} ({changed_here} rows)")
                continue

            # 2) 整组都不规范：分配一个新的 P-{sid}-NN
            #    判定"需要补"的情形：所有行的 logical_project_id 要么为空、要么 == cid、要么 == project_id
            needs = all(
                (not r.get("logical_project_id"))
                or str(r.get("logical_project_id")) == cid
                or str(r.get("logical_project_id")) == project_id
                for r in rows
            )
            if not needs:
                # 出现奇怪混合，跳过更安全
                continue

            if args.apply:
                serial = user_store.allocate_project_serial(owner)
                new_lid = f"P-{sid}-{serial:02d}"
                for r in rows:
                    r["logical_project_id"] = new_lid
                dirty = True
                total_new_ids += 1
                total_renamed += len(rows)
                print(f"[allocate] {project_id} cid={cid[:12]} -> {new_lid} ({len(rows)} rows)")
            else:
                # dry-run：不真分配 counter，只打算盘
                total_new_ids += 1
                total_renamed += len(rows)
                print(f"[would-allocate] {project_id} cid={cid[:12]} -> P-{sid}-NN ({len(rows)} rows)")

        if dirty and args.apply:
            data["submissions"] = [r for cid in order for r in groups[cid]]
            json_store.save_project(project_id, data)

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  scanned projects        : {total_projects}")
    print(f"  scanned submissions     : {total_subs}")
    print(f"  conversations to rename : {total_new_ids}")
    print(f"  rows to rewrite         : {total_renamed}")
    print(f"  projects skipped (no sid): {total_skipped_no_sid}")
    if not args.apply:
        print("(dry-run; pass --apply to write changes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
