"""
Concept graph primitives.

--- Header Doc ---
Purpose: Define minimal graph model for ontology extraction outputs.
Caller: ontology reconstructor and exporters.
Dependencies: dataclasses.
Main Functions: ConceptNode, ConceptEdge, ConceptGraph.
Side Effects: None.
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ConceptNode:
    node_id: str
    label: str
    attributes: Dict[str, object] = field(default_factory=dict)


@dataclass
class ConceptEdge:
    source: str
    target: str
    relation: str
    weight: float = 1.0


@dataclass
class ConceptGraph:
    nodes: List[ConceptNode] = field(default_factory=list)
    edges: List[ConceptEdge] = field(default_factory=list)
