"""
HyperNetX-based document processing service.

Represents documents as hypergraphs where:
- Nodes: file, sections, paragraphs, sentences, terms
- Hyperedges: represent containment and semantic relationships
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import hypernetx as hnx
from app.services.document_parser import ParsedDocument, TextSegment, parse_document
import textract

@dataclass
class DocumentNode:
    """Represents a node in the document hypergraph."""
    node_id: str
    node_type: str  # "document", "section", "segment", "term"
    label: str
    content: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class DocumentEdge:
    """Represents a hyperedge in the document hypergraph."""
    edge_id: str
    edge_type: str  # "contains", "references", "defines"
    nodes: set[str]
    weight: float = 1.0
    metadata: dict[str, Any] | None = None


class HypergraphDocument:
    """
    A document representation using HyperNetX.
    
    Converts parsed documents into hypergraph structure for unified processing.
    """

    def __init__(self, file_path: Path, doc_type: str):
        self.file_path = Path(file_path)
        self.doc_type = doc_type
        self.document_id = self._make_document_id()
        self._hypergraph: hnx.Hypergraph | None = None
        self._nodes: dict[str, DocumentNode] = {}
        self._edges: dict[str, DocumentEdge] = {}
        self._metadata: dict[str, Any] = {
            "file_path": str(self.file_path),
            "doc_type": doc_type,
            "document_id": self.document_id,
        }

    def _make_document_id(self) -> str:
        """Generate deterministic document ID."""
        digest = hashlib.sha256(str(self.file_path).encode()).hexdigest()[:12]
        return f"doc_{digest}"

    @classmethod
    def from_parsed_document(cls, parsed: ParsedDocument) -> HypergraphDocument:
        """Create HypergraphDocument from ParsedDocument."""
        doc = cls(parsed.file_path, parsed.doc_type)
        doc._build_from_segments(parsed.segments)
        return doc

    @classmethod
    def from_file(cls, file_path: Path, max_pdf_pages: int = 80) -> HypergraphDocument:
        """Parse file and convert to HypergraphDocument. Support .doc via textract if needed."""
        import re
        suffix = file_path.suffix.lower()
        if suffix == ".doc":
            # textract returns bytes
            text = textract.process(str(file_path)).decode("utf-8", errors="ignore")
            # Minimal ParsedDocument mockup for .doc
            from app.services.document_parser import ParsedDocument, TextSegment
            # Split by paragraphs: support \r, \n, \r\n
            paras = [p.strip() for p in re.split(r"\r?\n|\r", text) if p.strip()]
            segments = [TextSegment(index=i, source_unit=f"段落{i+1}", text=p) for i, p in enumerate(paras)]
            parsed = ParsedDocument(file_path=file_path, doc_type="doc", segments=segments)
            return cls.from_parsed_document(parsed)
        else:
            parsed = parse_document(file_path, max_pdf_pages=max_pdf_pages)
            return cls.from_parsed_document(parsed)

    def _build_from_segments(self, segments: list[TextSegment]) -> None:
        """Build hypergraph structure from document segments."""
        # Create document node
        doc_node = DocumentNode(
            node_id=self.document_id,
            node_type="document",
            label=self.file_path.name,
            metadata={"doc_type": self.doc_type},
        )
        self._nodes[self.document_id] = doc_node

        # Create segment nodes and edges
        segment_node_ids: list[str] = []
        for seg in segments:
            seg_id = f"{self.document_id}_seg_{seg.index}"
            seg_node = DocumentNode(
                node_id=seg_id,
                node_type="segment",
                label=seg.source_unit,
                content=seg.text,
                metadata={"index": seg.index, "source_unit": seg.source_unit},
            )
            self._nodes[seg_id] = seg_node
            segment_node_ids.append(seg_id)

        # Create "contains" hyperedge from document to all segments
        if segment_node_ids:
            contains_edge = DocumentEdge(
                edge_id=f"{self.document_id}_contains_segments",
                edge_type="contains",
                nodes={self.document_id}.union(set(segment_node_ids)),
                metadata={"description": "Document contains all segments"},
            )
            self._edges[contains_edge.edge_id] = contains_edge

        # Build hypergraph structure
        self._build_hypergraph()

    def _build_hypergraph(self) -> None:
        """Construct hypernetx Hypergraph from nodes and edges."""
        edge_to_nodes: dict[str, set[str]] = {}
        for edge_id, edge in self._edges.items():
            edge_to_nodes[edge_id] = edge.nodes

        self._hypergraph = hnx.Hypergraph(edge_to_nodes)

    def get_hypergraph(self) -> hnx.Hypergraph:
        """Return the underlying hypernetx.Hypergraph object."""
        if self._hypergraph is None:
            self._build_hypergraph()
        return self._hypergraph

    def to_dict(self) -> dict[str, Any]:
        """Convert document to dictionary representation."""
        return {
            "document_id": self.document_id,
            "file_path": str(self.file_path),
            "doc_type": self.doc_type,
            "nodes": {nid: _node_to_dict(node) for nid, node in self._nodes.items()},
            "edges": {eid: _edge_to_dict(edge) for eid, edge in self._edges.items()},
            "metadata": self._metadata,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HypergraphDocument:
        """Reconstruct from dictionary representation."""
        doc = cls(Path(data["file_path"]), data["doc_type"])
        
        # Reconstruct nodes
        for nid, node_data in data.get("nodes", {}).items():
            node = DocumentNode(
                node_id=node_data["node_id"],
                node_type=node_data["node_type"],
                label=node_data["label"],
                content=node_data.get("content"),
                metadata=node_data.get("metadata"),
            )
            doc._nodes[nid] = node

        # Reconstruct edges
        for eid, edge_data in data.get("edges", {}).items():
            edge = DocumentEdge(
                edge_id=edge_data["edge_id"],
                edge_type=edge_data["edge_type"],
                nodes=set(edge_data["nodes"]),
                weight=edge_data.get("weight", 1.0),
                metadata=edge_data.get("metadata"),
            )
            doc._edges[eid] = edge

        doc._metadata = data.get("metadata", {})
        doc._build_hypergraph()
        return doc

    def get_segments(self) -> list[TextSegment]:
        """Extract segments back to TextSegment list."""
        segments = []
        for nid, node in self._nodes.items():
            if node.node_type == "segment" and node.content:
                idx = node.metadata.get("index", 0) if node.metadata else 0
                source_unit = node.metadata.get("source_unit", "") if node.metadata else ""
                segments.append(TextSegment(
                    index=idx,
                    source_unit=source_unit,
                    text=node.content,
                ))
        # Sort by index
        segments.sort(key=lambda s: s.index)
        return segments

    def get_full_text(self) -> str:
        """Get full text by concatenating all segments."""
        segments = self.get_segments()
        return "\n".join(s.text for s in segments if s.text.strip())

    def get_stats(self) -> dict[str, Any]:
        """Get document statistics."""
        segments = self.get_segments()
        full_text = self.get_full_text()
        return {
            "document_id": self.document_id,
            "file_path": str(self.file_path),
            "doc_type": self.doc_type,
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
            "segment_count": len(segments),
            "text_chars": len(full_text),
            "hypergraph_nodes": len(self._hypergraph.nodes) if self._hypergraph else 0,
            "hypergraph_edges": len(self._hypergraph.edges) if self._hypergraph else 0,
        }


def _node_to_dict(node: DocumentNode) -> dict[str, Any]:
    """Convert DocumentNode to dictionary."""
    return asdict(node)


def _edge_to_dict(edge: DocumentEdge) -> dict[str, Any]:
    """Convert DocumentEdge to dictionary."""
    data = asdict(edge)
    data["nodes"] = list(edge.nodes)  # Convert set to list for JSON
    return data


class HypergraphDocumentCollection:
    """Manage multiple HypergraphDocument instances."""

    def __init__(self):
        self.documents: dict[str, HypergraphDocument] = {}
        self._combined_hypergraph: hnx.Hypergraph | None = None

    def add_document(self, doc: HypergraphDocument) -> None:
        """Add a document to the collection."""
        self.documents[doc.document_id] = doc
        self._combined_hypergraph = None  # Invalidate combined graph

    def add_from_file(self, file_path: Path) -> HypergraphDocument:
        """Parse file and add to collection."""
        doc = HypergraphDocument.from_file(file_path)
        self.add_document(doc)
        return doc

    def get_combined_hypergraph(self) -> hnx.Hypergraph:
        """Get combined hypergraph of all documents."""
        if self._combined_hypergraph is not None:
            return self._combined_hypergraph

        all_edges: dict[str, set[str]] = {}
        for doc in self.documents.values():
            for edge_id, edge in doc._edges.items():
                combined_edge_id = f"{doc.document_id}_{edge_id}" if edge_id not in all_edges else edge_id
                all_edges[combined_edge_id] = edge.nodes

        self._combined_hypergraph = hnx.Hypergraph(all_edges)
        return self._combined_hypergraph

    def get_document_by_id(self, doc_id: str) -> HypergraphDocument | None:
        """Retrieve a document by ID."""
        return self.documents.get(doc_id)

    def to_dict(self) -> dict[str, Any]:
        """Serialize collection to dictionary."""
        return {
            "documents": {doc_id: doc.to_dict() for doc_id, doc in self.documents.items()},
            "document_count": len(self.documents),
        }

    def to_json(self) -> str:
        """Serialize collection to JSON."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
