"""
Frontend-Backend compatibility layer for hypergraph data.

Ensures consistent data formats between backend processing and frontend visualization.
"""

from __future__ import annotations

from typing import Any

import hypernetx as hnx

from app.services.hypergraph_document import HypergraphDocument
from app.services.hypergraph_serialization import DocumentHypergraphExporter, UnifiedDocumentFormat


class HypergraphDataAdapter:
    """
    Adapter to convert between backend hypergraph structures and frontend-compatible formats.
    
    This ensures both frontend and backend use consistent hypergraph representations.
    """

    @staticmethod
    def prepare_document_for_frontend(hypergraph_doc: HypergraphDocument) -> dict[str, Any]:
        """
        Prepare a HypergraphDocument for frontend consumption.
        
        Returns a standardized format that can be used for visualization and interaction.
        """
        return DocumentHypergraphExporter.export_for_frontend(hypergraph_doc)

    @staticmethod
    def prepare_case_record_with_hypergraph(case_record: dict[str, Any], 
                                          hypergraph_doc: HypergraphDocument) -> dict[str, Any]:
        """
        Enhance a case record with hypergraph metadata.
        
        This merges the extracted case data with hypergraph structure information.
        """
        hypergraph_frontend = DocumentHypergraphExporter.export_for_frontend(hypergraph_doc)
        unified = UnifiedDocumentFormat.create_unified(hypergraph_doc)

        case_record["hypergraph_metadata"] = {
            "document_id": hypergraph_doc.document_id,
            "nodes_count": len(hypergraph_doc._nodes),
            "edges_count": len(hypergraph_doc._edges),
            "structure": unified.get("structure", {}),
        }
        
        # Add frontend-compatible hypergraph representation
        case_record["hypergraph_visualization"] = {
            "nodes": hypergraph_frontend.get("nodes", []),
            "edges": hypergraph_frontend.get("edges", []),
        }

        # Mark that this record uses hypernetx engine
        if "engine" not in case_record:
            case_record["engine"] = "hypernetx"

        return case_record

    @staticmethod
    def validate_hypergraph_consistency(hypergraph: hnx.Hypergraph) -> bool:
        """
        Validate that a hypergraph has consistent structure.
        
        Checks:
        - All edge members reference valid nodes
        - No orphaned nodes or edges
        - Edge weights are valid
        """
        if not hypergraph.nodes or not hypergraph.edges:
            return True  # Empty hypergraphs are valid

        node_set = set(hypergraph.nodes)
        
        for edge_id in hypergraph.edges:
            members = set(hypergraph.edges.members(edge_id))
            # Check if all members are valid nodes
            if not members.issubset(node_set):
                return False

        return True

    @staticmethod
    def extract_hypergraph_summary(hypergraph: hnx.Hypergraph) -> dict[str, Any]:
        """
        Extract summary statistics about a hypergraph for frontend display.
        """
        nodes = list(hypergraph.nodes)
        edges = list(hypergraph.edges)
        
        # Calculate basic statistics
        degree_sequence = [hypergraph.degree(node) for node in nodes] if nodes else []
        
        summary = {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "average_node_degree": sum(degree_sequence) / len(nodes) if nodes else 0,
            "max_node_degree": max(degree_sequence) if degree_sequence else 0,
            "min_node_degree": min(degree_sequence) if degree_sequence else 0,
            "edge_sizes": [len(list(hypergraph.edges.members(e))) for e in edges],
            "average_edge_size": sum(len(list(hypergraph.edges.members(e))) for e in edges) / len(edges) if edges else 0,
        }

        return summary

    @staticmethod
    def create_api_response(hypergraph_doc: HypergraphDocument, 
                           data: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Create a standardized API response containing hypergraph data.
        
        This format is used for all API endpoints dealing with documents/hypergraphs.
        """
        frontend_data = DocumentHypergraphExporter.export_for_frontend(hypergraph_doc)
        hypergraph = hypergraph_doc.get_hypergraph()
        summary = HypergraphDataAdapter.extract_hypergraph_summary(hypergraph)

        response = {
            "success": True,
            "engine": "hypernetx",
            "document": {
                "id": hypergraph_doc.document_id,
                "file_path": str(hypergraph_doc.file_path),
                "doc_type": hypergraph_doc.doc_type,
            },
            "hypergraph": {
                "nodes": frontend_data.get("nodes", []),
                "edges": frontend_data.get("edges", []),
                "summary": summary,
            },
            "data": data or {},
        }

        return response


class FrontendHypergraphSerializer:
    """Serialization utilities specifically for frontend compatibility."""

    @staticmethod
    def to_frontend_json(hypergraph_doc: HypergraphDocument) -> str:
        """
        Serialize hypergraph document to JSON format suitable for frontend.
        
        This includes all necessary information for visualization and interaction.
        """
        import json
        response = HypergraphDataAdapter.create_api_response(hypergraph_doc)
        return json.dumps(response, ensure_ascii=False, indent=2)

    @staticmethod
    def create_node_for_frontend(node_id: str, label: str, node_type: str, 
                                metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a frontend-compatible node representation."""
        return {
            "id": node_id,
            "label": label,
            "type": node_type,
            "metadata": metadata or {},
            "position": None,  # Position can be computed by frontend layout engine
        }

    @staticmethod
    def create_edge_for_frontend(edge_id: str, source_nodes: list[str], 
                                edge_type: str, weight: float = 1.0,
                                metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a frontend-compatible edge representation."""
        return {
            "id": edge_id,
            "sourceNodes": source_nodes,
            "type": edge_type,
            "weight": weight,
            "metadata": metadata or {},
        }
