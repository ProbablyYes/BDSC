"""
HyperNetX serialization utilities.

Supports multiple hypergraph serialization formats:
- Native HyperNetX format
- HIF (Hypergraph Interchange Format)
- Custom document-tagged format for education context
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import hypernetx as hnx


class HypergraphSerializer:
    """Serialize and deserialize hypergraphs in various formats."""

    @staticmethod
    def to_hif_dict(hypergraph: hnx.Hypergraph, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Convert HyperNetX Hypergraph to HIF (Hypergraph Interchange Format) dictionary.
        
        HIF is a standard JSON format for representing hypergraphs.
        See: https://github.com/pszufe/HIF-standard
        """
        hif_dict: dict[str, Any] = {
            "hypergraph": {
                "metadata": metadata or {},
                "nodes": [],
                "hyperedges": [],
            }
        }

        # Extract nodes
        node_dict: dict[str, dict] = {}
        for node in hypergraph.nodes:
            node_id = str(node)
            node_dict[node_id] = {
                "id": node_id,
                "label": str(node),
            }
            hif_dict["hypergraph"]["nodes"].append(node_dict[node_id])

        # Extract hyperedges
        for edge_id in hypergraph.edges:
            edge = hypergraph.edges[edge_id]
            members = [str(node) for node in hypergraph.edges.members(edge)]
            hif_dict["hypergraph"]["hyperedges"].append({
                "id": str(edge_id),
                "label": str(edge_id),
                "members": members,
            })

        return hif_dict

    @staticmethod
    def to_hif_json(hypergraph: hnx.Hypergraph, metadata: dict[str, Any] | None = None) -> str:
        """Convert to HIF JSON string."""
        hif_dict = HypergraphSerializer.to_hif_dict(hypergraph, metadata)
        return json.dumps(hif_dict, ensure_ascii=False, indent=2)

    @staticmethod
    def to_native_dict(hypergraph: hnx.Hypergraph) -> dict[str, Any]:
        """Convert to HyperNetX native dictionary format (edge-to-nodes mapping)."""
        return {
            "edges": {
                str(edge_id): [str(node) for node in hypergraph.edges.members(edge_id)]
                for edge_id in hypergraph.edges
            }
        }

    @staticmethod
    def from_hif_dict(hif_dict: dict[str, Any]) -> hnx.Hypergraph:
        """Reconstruct HyperNetX Hypergraph from HIF dictionary."""
        hg_data = hif_dict.get("hypergraph", {})
        edges = hg_data.get("hyperedges", [])
        
        edge_to_nodes: dict[str, set[str]] = {}
        for edge in edges:
            edge_id = edge.get("id", "")
            members = set(edge.get("members", []))
            if edge_id and members:
                edge_to_nodes[edge_id] = members

        return hnx.Hypergraph(edge_to_nodes)

    @staticmethod
    def from_hif_json(json_str: str) -> hnx.Hypergraph:
        """Reconstruct from HIF JSON string."""
        hif_dict = json.loads(json_str)
        return HypergraphSerializer.from_hif_dict(hif_dict)


class DocumentHypergraphExporter:
    """Export document hypergraphs for frontend consumption."""

    @staticmethod
    def export_for_frontend(hypergraph_doc) -> dict[str, Any]:
        """
        Export HypergraphDocument in a format suitable for frontend visualization.
        
        This format includes:
        - Nodes with labels and metadata
        - Edges with types and relationships
        - Document structure information
        """
        nodes_list = []
        edges_list = []

        # Export nodes with metadata
        for node_id, node in hypergraph_doc._nodes.items():
            node_data = {
                "id": node_id,
                "label": node.label,
                "type": node.node_type,
                "content": node.content[:200] if node.content else None,  # Truncate for frontend
                "metadata": node.metadata or {},
            }
            nodes_list.append(node_data)

        # Export edges with relationship type
        for edge_id, edge in hypergraph_doc._edges.items():
            edge_data = {
                "id": edge_id,
                "type": edge.edge_type,
                "sourceNodes": list(edge.nodes),
                "weight": edge.weight,
                "metadata": edge.metadata or {},
            }
            edges_list.append(edge_data)

        return {
            "document_id": hypergraph_doc.document_id,
            "file_path": str(hypergraph_doc.file_path),
            "doc_type": hypergraph_doc.doc_type,
            "nodes": nodes_list,
            "edges": edges_list,
            "stats": hypergraph_doc.get_stats(),
        }

    @staticmethod
    def export_collection_for_frontend(collection) -> dict[str, Any]:
        """Export HypergraphDocumentCollection for frontend."""
        return {
            "total_documents": len(collection.documents),
            "documents": [
                DocumentHypergraphExporter.export_for_frontend(doc)
                for doc in collection.documents.values()
            ],
        }


class UnifiedDocumentFormat:
    """
    Unified format for document representation across frontend/backend.
    
    Combines document metadata, content structure, and hypergraph relationships.
    """

    @staticmethod
    def create_unified(hypergraph_doc) -> dict[str, Any]:
        """Create unified document representation."""
        stats = hypergraph_doc.get_stats()
        segments = hypergraph_doc.get_segments()
        
        return {
            "document": {
                "id": hypergraph_doc.document_id,
                "file_path": str(hypergraph_doc.file_path),
                "doc_type": hypergraph_doc.doc_type,
                "created_at": None,  # Can be added to HypergraphDocument
                "engine": "hypernetx",
            },
            "structure": {
                "segment_count": len(segments),
                "hypergraph_nodes": stats.get("node_count", 0),
                "hypergraph_edges": stats.get("edge_count", 0),
                "text_chars": stats.get("text_chars", 0),
            },
            "content": {
                "segments": [
                    {
                        "index": seg.index,
                        "source_unit": seg.source_unit,
                        "text": seg.text,
                    }
                    for seg in segments
                ],
            },
            "hypergraph": {
                "nodes": [
                    {
                        "id": node_id,
                        "label": node.label,
                        "type": node.node_type,
                        "metadata": node.metadata or {},
                    }
                    for node_id, node in hypergraph_doc._nodes.items()
                ],
                "edges": [
                    {
                        "id": edge_id,
                        "type": edge.edge_type,
                        "nodes": list(edge.nodes),
                        "weight": edge.weight,
                        "metadata": edge.metadata or {},
                    }
                    for edge_id, edge in hypergraph_doc._edges.items()
                ],
            },
        }

    @staticmethod
    def to_json(hypergraph_doc) -> str:
        """Serialize to unified JSON format."""
        unified = UnifiedDocumentFormat.create_unified(hypergraph_doc)
        return json.dumps(unified, ensure_ascii=False, indent=2)

    @staticmethod
    def save_to_file(hypergraph_doc, output_path: Path) -> None:
        """Save unified format to file."""
        with output_path.open("w", encoding="utf-8") as f:
            f.write(UnifiedDocumentFormat.to_json(hypergraph_doc))
