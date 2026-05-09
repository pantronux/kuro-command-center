"""
Ontology graph exporter.

--- Header Doc ---
Purpose: Export ontology graphs to JSON-LD and RDF-star-like text formats.
Caller: report exporter and ontology mode.
Dependencies: json.
Main Functions: export_jsonld(), export_rdf_star().
Side Effects: None.
"""

import json

from playground_runtime.ontology.concept_graph import ConceptGraph


def export_jsonld(graph: ConceptGraph) -> str:
    payload = {
        "@context": {"label": "http://www.w3.org/2000/01/rdf-schema#label"},
        "@graph": [
            {"@id": f"node:{n.node_id}", "label": n.label, **n.attributes}
            for n in graph.nodes
        ],
        "edges": [
            {
                "source": f"node:{e.source}",
                "target": f"node:{e.target}",
                "relation": e.relation,
                "weight": e.weight,
            }
            for e in graph.edges
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def export_rdf_star(graph: ConceptGraph) -> str:
    lines = []
    for e in graph.edges:
        lines.append(f"<< node:{e.source} :{e.relation} node:{e.target} >> :weight \"{e.weight}\" .")
    return "\n".join(lines)
