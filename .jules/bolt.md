## 2024-05-18 - [Semantic Cache Cosine Similarity Optimization]
**Learning:** In purely Python-based vector operations (like in-memory semantic caches without C-extensions like numpy), evaluating the full cosine similarity formula (which involves multiplications, tracking sums of squares, and a square root) inside a loop over cached items is a significant overhead.
**Action:** Always consider pre-normalizing vectors when they are stored. If both the cached vector and the query vector are unit-normalized ($L_2$ norm = 1), their cosine similarity is exactly equal to their dot product. Substituting a full cosine similarity calculation with a single-pass dot product loop speeds up lookup by ~2.6x.

## 2026-05-14 - Replace Multiple Independent Generator Expressions with Single Loop
**Learning:** When calculating multiple aggregates over the same sequence (e.g., tallying different statuses, computing sums, or checking conditions with `any()`), replacing multiple independent generator expressions with a single explicit `for` loop prevents redundant O(n) traversals and avoids the overhead of allocating multiple intermediate objects. This significantly speeds up aggregation in paths that run frequently.
**Action:** Always combine iterations over the same collection into a single pass when computing multiple separate aggregated values (counts, sums, boolean flags). Also remember to always add inline comments and metrics to performance optimizations and to APPEND instead of overwrite the `.jules/bolt.md` journal.

## 2026-05-16 - [Early Return via Explicit Loops instead of sum()]
**Learning:** Using `sum()` with a generator expression to count items or check for non-zero counts (e.g., `hits = sum(1 for tok in query_tokens if tok in evidence)`) prevents Python from short-circuiting. If you only need to know if any match exists (e.g., `hits == 0`), an explicit `for` loop with an early `return False` as soon as a match is found is significantly faster (O(1) vs O(N)).
**Action:** Replace counting generator expressions with explicit loops when a simple boolean check (like finding ANY match) is sufficient, enabling early returns and preventing full traversals.
