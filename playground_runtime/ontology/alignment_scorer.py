"""
Ontology alignment scorer.

--- Header Doc ---
Purpose: Score ontology consistency across graph snapshots.
Caller: evaluator and ontology mode.
Dependencies: concept_graph.
Main Functions: score_alignment().
Side Effects: None.
"""

from playground_runtime.ontology.concept_graph import ConceptGraph


def score_alignment(reference: ConceptGraph, candidate: ConceptGraph) -> float:
    ref_nodes = {n.node_id for n in reference.nodes}
    cand_nodes = {n.node_id for n in candidate.nodes}
    if not ref_nodes and not cand_nodes:
        return 1.0
    union = ref_nodes | cand_nodes
    inter = ref_nodes & cand_nodes
    return len(inter) / len(union)
