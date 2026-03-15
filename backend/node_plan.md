# AST Node Selection Mode - Fix Plan

## 1. Problem Description
Currently, when a user selects specific nodes to be optimized (via "node selection" mode), the system only chunks those selected nodes. However, this causes an issue where unselected surrounding nodes or nested unselected logic can "bleed" into the optimization context, leading to unintended modifications outside the approved scope. 

## 2. Intended Solution
The intended behavior is to build the complete Abstract Syntax Tree (AST) of the file first. Before the AST is passed to the chunking mechanism, we will actively traverse it and **delete/prune any nodes that were not explicitly selected**. This ensures that the chunking logic only receives a sanitized, pruned tree (or source representation) containing *only* the elected nodes, guaranteeing strict isolation.

---

## 3. Step-by-Step Implementation Plan

### Step 1: Locate AST Generation Logic
Identify where the complete AST is generated (likely inside `backend/agent/nodes/analyzer.py` or a dedicated parser service using `tree-sitter` / `ast`). This happens before chunks are formulated and sent to the LLM.

### Step 2: Implement an AST Pruning Function
Create a new function, e.g., `prune_unselected_nodes(ast_root, selected_node_ids)`, which performs a depth-first or breadth-first traversal of the AST.
- **Traversal logic:** For each node, check if it or its immediate descendants match the `selected_node_ids`.
- **Deletion logic:** If a node is completely unselected (and does not contain selected children), remove it from the tree structure or replace it with a placeholder (e.g., `pass` or a no-op marker) to maintain syntactical validity where required.

### Step 3: Inject Pruning Before Chunking
Modify the control flow (e.g., in `chunk_analyze_node` or the corresponding handler in `analyzer.py`):
1. Parse the original source into the full AST.
2. Check if `selected_node_ids` exist in the state payload.
3. If they exist, invoke `prune_unselected_nodes` on the generated AST.
4. Pass the *modified/pruned* AST output down to the chunking logic.

### Step 4: Validate Syntactic Integrity
Ensure that deleting nodes does not break the foundational structure of the file if a parent was retained but a required child was unselected. If a class gets selected but some of its methods don't, only the unselected methods should be stripped.

### Step 5: Update Unit Tests (`pytest`)
It is crucial to validate all changes with `pytest`:
- **Test 1:** Verify that an AST with 5 functions correctly drops 3 when only 2 are in `selected_node_ids`.
- **Test 2:** Ensure the chunking service does not throw errors when receiving the artificially pruned AST.
- **Test 3:** Provide an end-to-end mock using the `runner.py` to confirm that the generated code diff only affects the selected lines and never bleeds into pruned areas.

## 4. Risks & Mitigations
- **Broken formatting/syntax errors:** Completely deleting nodes from an AST might break indentation or block formatting (like an empty `if` statement). **Mitigation:** We can replace pruned nodes with a minimal valid replacement like `pass` if they are structurally necessary, instead of a raw deletion.
