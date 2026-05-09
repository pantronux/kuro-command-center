"""
Ontology package.

--- Header Doc ---
Purpose: Build concept graphs from canonical traces and export ontology artifacts.
Caller: ontology mode and reports.
Dependencies: ontology modules.
Main Functions: reconstruct_ontology_graph.
Side Effects: None.
"""

from .reconstructor import reconstruct_ontology_graph

__all__ = ["reconstruct_ontology_graph"]
