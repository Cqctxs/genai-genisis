## Plan: Context-Rich Semantic AST Extraction

Enrich the existing AST graph with context-aware typing, parameter shapes, and localized semantic warnings to eliminate LLM blind spots before the code analysis phase begins. Address cross-file myopia and state-awareness to allow inter-procedural and IO-aware optimizations.

**Core Objective: Context-Rich Nodes and Expanded Horizons**
Currently, `tree-sitter` extracts "shallow" function nodes containing just the name, start/end lines, and raw text. The LLM cannot infer deeper relationships (e.g. knowing if a parameter `x` is a `str`, a `List[str]`, or a `Dict`). Additionally, the `optimizer` receives single-file context without the bodies of functions it calls, and without the database schema it interacts with. By augmenting `parser_service.py` to trace input types, inline required dependencies, extract DB states, and add semantic bad-practice flags, the resulting AST JSON sent to the LLM will be heavily context-rich.

**Steps to Implement**

1. **Cross-File Type Extraction & Tracing**
   - **How**: Integrate a static type inference tool (e.g., `jedi` for Python, or utilizing `ts-morph`/type-checker APIs for JS/TS) into `parser_service.py`.
   - **Action**: When parsing a function definition, resolve the types of its parameters and return values, tracing back through the import tree if necessary.
   - **Result Payload**: Attach a `"parameter_types": {}` and `"return_type"` dictionary to the AST node metadata object so the LLM explicitly sees the expected memory footprint and data structures.

2. **Static Pre-Scan Metadata Tags**
   - **How**: Write a library of explicit `tree-sitter` queries in `parser_service.py` targeting common algorithmic and memory management anti-patterns (e.g., nested looping structures, inefficient state accumulators, heavy blocking calls).
   - **Action**: Run these queries over the parsed AST as a secondary pass. When a query matches an anti-pattern within a function's bounds, extract the matched lines and the description of the matched rule.
   - **Result Payload**: Append a `"static_warnings": [ "...description..." ]` list to the function node's metadata. 

3. **Cross-File Symbol Resolution & Definition Inlining (LSP-style Chasing)**
   - **How**: Leverage the call graph extracted in `parser_service.py`.
   - **Action**: Currently, `optimizer.py` only receives the source code of the bottleneck file. A hotspot trace might call an external custom class or generic utility helper located in `utils.py`. The parser must traverse outbound call edges originating from the hotspot and fetch those actual source strings.
   - **Result Payload**: Generate an `External Definitions Appendix` payload consisting of the exact source-code definitions for classes/functions referenced in the hotspot that live outside the optimized file, and inject it into the `optimizer` context. This allows the LLM to perform inter-procedural optimizations (like modifying a helper signature without guessing its behavior).

4. **Database Schema & Data State Context Injection**
   - **How**: Add a dedicated parsing phase for mapping schemas (`models.py`, `schema.prisma`, `*.sql`).
   - **Action**: The LLM is currently asked to find N+1 query patterns but has no context on indexing, ORM relations, or keys. Write a schema parser that extracts Table Names, Foreign Keys, Columns, and Indexes into a mapped dictionary.
   - **Result Payload**: Inject a globally available `SchemaMap` directly into the `ANALYSIS_PROMPT` and `OPTIMIZER_PROMPT`. This ensures the agent accurately flags inefficient joins and can securely restructure `joinedload()` and batched queries via valid database constraints.

5. **AST Payload Refactor & Prompt Extension**
   - **How**: Update `backend/agent/schemas.py`, `backend/agent/nodes/analyzer.py`, and `backend/agent/nodes/optimizer.py`.
   - **Action**: Serialize the new `parameter_types`, `static_warnings`, `schema_map`, and `definition_inlines` cleanly alongside the existing `call_edges` and `imports`. Update the prompts to direct the LLM to cross-reference this newly provided metadata explicitly.

**Relevant files**
- `backend/services/parser_service.py` — Add type tracing, DB schema extraction, definition inlining, and `tree-sitter` static queries.
- `backend/agent/nodes/analyzer.py`/`optimizer.py` — Update prompts to consume the parameter shapes, schema maps, appended code contexts, and static tags.

**Decisions**
- The priority is strictly moving from shallow parsing (just names/lines) to **contextually deep parsing** (types, schemas, state shapes, and structural tags) and breaking single-file dependencies.