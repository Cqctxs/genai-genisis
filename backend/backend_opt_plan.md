## Plan: Context-Rich Semantic AST Extraction

Enrich the existing AST graph with context-aware typing, parameter shapes, and localized semantic warnings to eliminate LLM blind spots before the code analysis phase begins.

**Core Objective: Context-Rich Nodes**
Currently, `tree-sitter` extracts "shallow" function nodes containing just the name, start/end lines, and raw text. The LLM cannot infer deeper relationships (e.g. knowing if a parameter `x` is a `str`, a `List[str]`, or a `Dict`). By augmenting `parser_service.py` to trace input types across files and extract semantic bad-practice flags, the resulting AST JSON sent to the LLM will be rich with structural context, preventing naive optimization misses without running blind global benchmarks.

**Steps to Implement**

1. **Cross-File Type Extraction & Tracing**
   - **How**: Integrate a static type inference tool (e.g., `jedi` for Python, or utilizing `ts-morph`/type-checker APIs for JS/TS) into `parser_service.py`.
   - **Action**: When parsing a function definition, resolve the types of its parameters and return values, tracing back through the import tree if necessary.
   - **Result Payload**: Attach a `"parameter_types": {}` and `"return_type"` dictionary to the AST node metadata object so the LLM explicitly sees the expected memory footprint and data structures.

2. **Static Pre-Scan Metadata Tags**
   - **How**: Write a library of explicit `tree-sitter` queries in `parser_service.py` targeting common algorithmic and memory management anti-patterns (e.g., nested looping structures, inefficient state accumulators, heavy blocking calls).
   - **Action**: Run these queries over the parsed AST as a secondary pass. When a query matches an anti-pattern within a function's bounds, extract the matched lines and the description of the matched rule.
   - **Result Payload**: Append a `"static_warnings": [ "...description..." ]` list to the function node's metadata. 

3. **AST Payload Refactor**
   - **How**: Update the JSON schema representing the AST map that is serialized and passed into the `Analyzer` agent (`backend/agent/schemas.py` or similar).
   - **Action**: Ensure the new `parameter_types`, `return_type`, and `static_warnings` properties are cleanly formatted and serialized alongside the existing `call_edges` and `imports`.
   - **Result Payload**: The `ANALYSIS_PROMPT` receives a deeply informative JSON structure instead of just raw code strings.

4. **Context-Aware Prompt Extension**
   - **How**: Update `backend/agent/nodes/analyzer.py` and `optimizer.py` prompts to direct the LLM to leverage this new metadata.
   - **Action**: Add explicit instructions like "Cross-reference the provided `static_warnings` to target structural anomalies instantly" and "Rely on the `parameter_types` metadata to determine the optimal iteration strategies and data structures (e.g., recognizing nested structural loops vs simple lists)."

**Relevant files**
- `backend/services/parser_service.py` — Add type tracing (Jedi/tsc) and `tree-sitter` queries to tag function nodes.
- `backend/agent/nodes/analyzer.py`/`optimizer.py` — Update prompts to consume the parameter shapes and static tags.

**Decisions**
- The priority is strictly moving from shallow parsing (just names/lines) to **contextually deep parsing** (types, imports, parameter shapes, and anti-pattern signatures) directly in the AST map.