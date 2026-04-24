from __future__ import annotations

"""OntologyResolver — 把"本体"从展示项升级为运行时语义骨架。

提供四件事：
  1. normalize(text)       → 文本中出现的所有 canonical_id（label/aliases 命中）
  2. expand(node_id)       → 节点自身 + 全部子孙 id（用于"父命中=子也命中"推理）
  3. query(...)            → 按 kind/parent/stage_expected 等结构化条件检索本体
  4. covered(hits)         → 把命中集合做"上推 + 下展"得到的语义覆盖集合
  5. stage_gap(stage,hits) → 当前 stage 期望覆盖、但还没被覆盖的节点列表

Resolver 是无状态的（除了在 __init__ 时一次性构建反向索引），可以做成单例
`get_resolver()` 在多处复用，避免每次重新扫表。
"""

import re
from collections import defaultdict
from threading import Lock
from typing import Iterable

from .kg_ontology import (
    ONTOLOGY_NODES,
    OntologyNode,
    serialize_node,
)


# 简单的中英混合切词：尽量保留连续的中文 / 英文 / 数字片段
_TOKEN_RE = re.compile(r"[A-Za-z0-9_+]+|[\u4e00-\u9fff]+")


def _tokenize_lower(text: str) -> list[str]:
    if not text:
        return []
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


class OntologyResolver:
    def __init__(self) -> None:
        # alias(lower) → list[node_id]，一个别名可能映射多个节点（例如 "TAM" 同时映射指标和方法）
        self._alias_index: dict[str, list[str]] = defaultdict(list)
        # parent → 直接子节点 ids
        self._children_index: dict[str, list[str]] = defaultdict(list)
        # 每个节点 id → 所有后代 id（含自身），lazy 计算
        self._descendants_cache: dict[str, set[str]] = {}

        for nid, node in ONTOLOGY_NODES.items():
            self._index_node(node)
            if node.parent:
                self._children_index[node.parent].append(nid)

    # ── 索引构建 ──
    def _index_node(self, node: OntologyNode) -> None:
        # label 自身也算一个 alias（按"按整词包含"匹配，不区分大小写）
        for token in {node.label, *node.aliases}:
            tok = (token or "").strip().lower()
            if not tok:
                continue
            self._alias_index[tok].append(node.id)

    # ── 1. 文本归一 ──
    def normalize(self, text: str) -> list[str]:
        """从一段文本中识别出可被映射到本体的 canonical_id 列表（去重，保持原文出现顺序）。

        实现方式：把 alias_index 里的每个 alias 当作子串去 text 里查找。
        - 英文/数字 alias：要求以非字母数字边界出现，避免 "AI" 命中 "AIM"
        - 中文 alias：直接 substring 匹配
        """
        if not text:
            return []
        text_l = text.lower()
        seen: set[str] = set()
        ordered: list[str] = []

        # 排序：长 alias 优先，避免 "市场规模" 被 "市场" 抢先匹配
        sorted_aliases = sorted(self._alias_index.keys(), key=lambda x: -len(x))

        for alias in sorted_aliases:
            if not alias:
                continue
            if self._is_ascii(alias):
                # 词边界匹配
                pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])")
                if not pattern.search(text_l):
                    continue
            else:
                if alias not in text_l:
                    continue
            for nid in self._alias_index[alias]:
                if nid not in seen:
                    seen.add(nid)
                    ordered.append(nid)
        return ordered

    @staticmethod
    def _is_ascii(s: str) -> bool:
        try:
            s.encode("ascii")
            return True
        except UnicodeEncodeError:
            return False

    # ── 2. 上下位展开 ──
    def expand(self, node_id: str) -> set[str]:
        """返回 node_id 自身 + 全部后代 id。父命中→子也算覆盖。"""
        if node_id in self._descendants_cache:
            return self._descendants_cache[node_id]
        if node_id not in ONTOLOGY_NODES:
            return set()
        out: set[str] = {node_id}
        stack = [node_id]
        while stack:
            cur = stack.pop()
            for child in self._children_index.get(cur, []):
                if child not in out:
                    out.add(child)
                    stack.append(child)
        self._descendants_cache[node_id] = out
        return out

    def ancestors(self, node_id: str) -> list[str]:
        """从 node_id 一直追溯到根的 parent 链（不含自身）。"""
        chain: list[str] = []
        seen: set[str] = set()
        cur = ONTOLOGY_NODES.get(node_id)
        while cur and cur.parent and cur.parent not in seen:
            chain.append(cur.parent)
            seen.add(cur.parent)
            cur = ONTOLOGY_NODES.get(cur.parent)
        return chain

    # ── 3. 结构化查询 ──
    def query(
        self,
        *,
        kinds: Iterable[str] | None = None,
        parent: str | None = None,
        stage: str | None = None,
    ) -> list[OntologyNode]:
        """按维度过滤本体节点，方便前端按 kind 分组、agent 按 stage 拉期望。"""
        kind_set = set(kinds) if kinds else None
        out: list[OntologyNode] = []
        for node in ONTOLOGY_NODES.values():
            if kind_set and node.kind not in kind_set:
                continue
            if parent and node.parent != parent:
                continue
            if stage and stage not in node.stage_expected:
                continue
            out.append(node)
        return out

    # ── 4. 覆盖集合 ──
    def covered(self, hits: Iterable[str]) -> set[str]:
        """把直接命中的节点 → 上推到祖先 + 下展到后代后的"语义覆盖集合"。

        - 子节点命中→父概念也算覆盖（业务上：你提到 CAC，等于触及了 Financial Risk）
        - 父节点命中→子节点是否覆盖取决于上下文，这里不做下展（避免误判，否则
          "提到了风险控制" 就会被当成"已覆盖合规清单"，过于宽松）
        """
        out: set[str] = set()
        for hid in hits:
            if hid not in ONTOLOGY_NODES:
                continue
            out.add(hid)
            out.update(self.ancestors(hid))
        return out

    # ── 5. Stage 缺口 ──
    def stage_gap(
        self,
        stage: str,
        hits: Iterable[str],
        *,
        kinds: Iterable[str] | None = None,
    ) -> list[OntologyNode]:
        """当前 stage 应当覆盖、但实际没覆盖到的节点列表。

        kinds 默认只看 concept（追问素材最多的那一层），可以按需扩展。
        """
        if not stage:
            return []
        covered_set = self.covered(hits)
        kind_set = set(kinds) if kinds else {"concept"}
        gap: list[OntologyNode] = []
        for node in ONTOLOGY_NODES.values():
            if node.kind not in kind_set:
                continue
            if stage not in node.stage_expected:
                continue
            if node.id in covered_set:
                continue
            gap.append(node)
        return gap

    # ── 序列化辅助 ──
    @staticmethod
    def to_dict(node: OntologyNode) -> dict:
        return serialize_node(node)


# 单例（线程安全）
_resolver_lock = Lock()
_resolver_singleton: OntologyResolver | None = None


def get_resolver() -> OntologyResolver:
    global _resolver_singleton  # noqa: PLW0603
    with _resolver_lock:
        if _resolver_singleton is None:
            _resolver_singleton = OntologyResolver()
        return _resolver_singleton
