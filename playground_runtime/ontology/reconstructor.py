"""
Ontology reconstructor.

--- Header Doc ---
Purpose: Extract concept nodes/edges from canonical traces.
Caller: ontology mode runtime.
Dependencies: hashlib, concept_graph.
Main Functions: reconstruct_ontology_graph().
Side Effects: None.
"""

from __future__ import annotations

from hashlib import sha1

from playground_runtime.ontology.concept_graph import ConceptEdge, ConceptGraph, ConceptNode
from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def reconstruct_ontology_graph(traces: list[CanonicalInferenceTrace]) -> ConceptGraph:
    graph = ConceptGraph()
    node_seen = set()
    for trace in traces:
        words = [w.strip(".,:;!?()[]{}\"") for w in (trace.response_text or "").split()]
        words = [w for w in words if len(w) > 3]
        for i, word in enumerate(words[:40]):
            node_id = sha1(word.lower().encode("utf-8")).hexdigest()[:12]
            if node_id not in node_seen:
                graph.nodes.append(ConceptNode(node_id=node_id, label=word.lower()))
                node_seen.add(node_id)
            if i > 0:
                prev = words[i - 1].lower()
                prev_id = sha1(prev.encode("utf-8")).hexdigest()[:12]
                if prev_id != node_id:
                    graph.edges.append(ConceptEdge(source=prev_id, target=node_id, relation="co_occurs"))
    return graph
