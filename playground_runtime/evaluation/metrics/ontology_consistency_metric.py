"""Ontology consistency metric."""

from playground_runtime.ontology.alignment_scorer import score_alignment
from playground_runtime.ontology.concept_graph import ConceptGraph


def score_ontology_consistency(reference: ConceptGraph, candidate: ConceptGraph) -> float:
    return score_alignment(reference, candidate)
