import json
import os
from typing import Any

import structlog
import tree_sitter_javascript as ts_js
import tree_sitter_python as ts_py
import tree_sitter_typescript as ts_ts
from tree_sitter import Language, Parser

from agent.schemas import ASTData, ClassInfo, FunctionInfo, ImportInfo

log = structlog.get_logger()

PY_LANGUAGE = Language(ts_py.language())
JS_LANGUAGE = Language(ts_js.language())
TS_LANGUAGE = Language(ts_ts.language_typescript())


def _get_parser(ext: str) -> Parser | None:
    lang_map = {
        ".py": PY_LANGUAGE,
        ".js": JS_LANGUAGE,
        ".ts": TS_LANGUAGE,
        ".tsx": TS_LANGUAGE,
        ".jsx": JS_LANGUAGE,
    }
    lang = lang_map.get(ext)
    if lang is None:
        return None
    parser = Parser(lang)
    return parser


def _text(node: Any) -> str:
    return node.text.decode("utf-8") if node.text else ""


def parse_file(file_path: str, rel_path: str) -> dict[str, Any]:
    """Parse a single file and extract functions, classes, imports, and call edges."""
    ext = os.path.splitext(file_path)[1]
    parser = _get_parser(ext)
    if parser is None:
        return {"functions": [], "classes": [], "imports": [], "calls": []}

    with open(file_path, "rb") as f:
        source = f.read()

    tree = parser.parse(source)
    root = tree.root_node

    functions: list[dict] = []
    classes: list[dict] = []
    imports: list[dict] = []
    calls: list[tuple[str, str]] = []

    if ext == ".py":
        _extract_python(root, rel_path, functions, classes, imports, calls)
    else:
        _extract_js_ts(root, rel_path, functions, classes, imports, calls)

    return {
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "calls": calls,
    }


def _find_enclosing_function(node: Any) -> str:
    """Walk up from a node to find the nearest enclosing function name."""
    current = node.parent
    while current is not None:
        if current.type in ("function_definition", "function_declaration", "generator_function_declaration", "method_definition", "arrow_function"):
            name_node = current.child_by_field_name("name")
            if name_node:
                return _text(name_node)
            parent = current.parent
            if parent and parent.type == "variable_declarator":
                n = parent.child_by_field_name("name")
                if n:
                    return _text(n)
            return ""
        current = current.parent
    return ""


# ---------------------------------------------------------------------------
# Helpers: Python type extraction
# ---------------------------------------------------------------------------

def _py_extract_params(params_node: Any) -> tuple[list[str], dict[str, str]]:
    """Extract parameter names and their type annotations from a Python parameters node.

    Returns (param_names, param_types) where param_types maps name -> annotation text.
    """
    names: list[str] = []
    types: dict[str, str] = {}
    if params_node is None:
        return names, types
    for p in params_node.children:
        if p.type == "identifier":
            names.append(_text(p))
        elif p.type == "typed_parameter":
            ident = p.child_by_field_name("name") or next(
                (c for c in p.children if c.type == "identifier"), None
            )
            if ident:
                pname = _text(ident)
                names.append(pname)
                type_node = next((c for c in p.children if c.type == "type"), None)
                if type_node:
                    types[pname] = _text(type_node)
        elif p.type == "typed_default_parameter":
            ident = p.child_by_field_name("name") or next(
                (c for c in p.children if c.type == "identifier"), None
            )
            if ident:
                pname = _text(ident)
                names.append(pname)
                type_node = next((c for c in p.children if c.type == "type"), None)
                if type_node:
                    types[pname] = _text(type_node)
        elif p.type == "default_parameter":
            ident = p.child_by_field_name("name") or next(
                (c for c in p.children if c.type == "identifier"), None
            )
            if ident:
                names.append(_text(ident))
        elif p.type == "list_splat_pattern":
            ident = next((c for c in p.children if c.type == "identifier"), None)
            if ident:
                names.append("*" + _text(ident))
        elif p.type == "dictionary_splat_pattern":
            ident = next((c for c in p.children if c.type == "identifier"), None)
            if ident:
                names.append("**" + _text(ident))
    return names, types


def _py_return_type(func_node: Any) -> str:
    """Extract the return type annotation from a Python function_definition."""
    rt = func_node.child_by_field_name("return_type")
    if rt:
        return _text(rt)
    return ""


def _py_decorators(func_node: Any) -> list[str]:
    """Extract decorator names from a Python decorated_definition parent."""
    decorators: list[str] = []
    parent = func_node.parent
    if parent and parent.type == "decorated_definition":
        for child in parent.children:
            if child.type == "decorator":
                # The decorator content is everything after the '@'
                parts = [c for c in child.children if c.type != "@"]
                if parts:
                    decorators.append(_text(parts[0]))
    return decorators


def _py_is_async(func_node: Any) -> bool:
    """Check if a Python function_definition is async."""
    for child in func_node.children:
        if child.type == "async":
            return True
    return False


def _py_is_generator(func_node: Any) -> bool:
    """Check if a Python function body contains yield/yield from."""
    body = func_node.child_by_field_name("body")
    if body is None:
        return False
    for node in _walk(body):
        if node.type == "yield":
            return True
    return False


def _py_docstring(func_node: Any) -> str:
    """Extract the leading docstring from a Python function."""
    body = func_node.child_by_field_name("body")
    if body is None:
        return ""
    for child in body.children:
        if child.type == "expression_statement":
            for c in child.children:
                if c.type == "string":
                    raw = _text(c)
                    # Strip triple-quote delimiters
                    for delim in ('"""', "'''"):
                        if raw.startswith(delim) and raw.endswith(delim):
                            return raw[3:-3].strip()
                    # Strip single-quote delimiters
                    for delim in ('"', "'"):
                        if raw.startswith(delim) and raw.endswith(delim):
                            return raw[1:-1].strip()
                    return raw
            break
        # If the first statement is not an expression_statement, there's no docstring
        break
    return ""


def _py_class_bases(class_node: Any) -> list[str]:
    """Extract base class names from a Python class_definition."""
    bases: list[str] = []
    superclasses = class_node.child_by_field_name("superclasses")
    if superclasses is None:
        # Try argument_list as fallback
        for child in class_node.children:
            if child.type == "argument_list":
                superclasses = child
                break
    if superclasses is None:
        return bases
    for child in superclasses.children:
        if child.type in ("identifier", "dotted_name", "attribute"):
            bases.append(_text(child))
        elif child.type == "keyword_argument":
            # e.g. metaclass=ABCMeta — skip
            pass
    return bases


# ---------------------------------------------------------------------------
# Helpers: JS/TS type extraction
# ---------------------------------------------------------------------------

def _js_extract_params(params_node: Any) -> tuple[list[str], dict[str, str]]:
    """Extract parameter names and type annotations from JS/TS formal_parameters."""
    names: list[str] = []
    types: dict[str, str] = {}
    if params_node is None:
        return names, types
    for p in params_node.children:
        if p.type == "identifier":
            names.append(_text(p))
        elif p.type in ("required_parameter", "optional_parameter"):
            ident = p.child_by_field_name("pattern") or next(
                (c for c in p.children if c.type == "identifier"), None
            )
            if ident:
                pname = _text(ident)
                names.append(pname)
                ta = next((c for c in p.children if c.type == "type_annotation"), None)
                if ta:
                    # Type annotation text without the leading ':'
                    ta_text = _text(ta).lstrip(": ")
                    if ta_text:
                        types[pname] = ta_text
        elif p.type == "rest_parameter":
            ident = next((c for c in p.children if c.type == "identifier"), None)
            if ident:
                names.append("..." + _text(ident))
    return names, types


def _js_return_type(func_node: Any) -> str:
    """Extract return type annotation from a JS/TS function/method/arrow node."""
    # The return type annotation appears as a type_annotation child after the parameters.
    params_seen = False
    for child in func_node.children:
        if child.type in ("formal_parameters", "parameters"):
            params_seen = True
        elif params_seen and child.type == "type_annotation":
            return _text(child).lstrip(": ")
    return ""


def _js_is_async(func_node: Any) -> bool:
    """Check if a JS/TS function is async."""
    for child in func_node.children:
        if child.type == "async":
            return True
    return False


def _js_is_generator(func_node: Any) -> bool:
    """Check if a JS/TS function is a generator (has * or yield)."""
    if func_node.type == "generator_function_declaration":
        return True
    body = func_node.child_by_field_name("body")
    if body is None:
        return False
    for node in _walk(body):
        if node.type == "yield_expression":
            return True
    return False


def _js_decorators(func_node: Any) -> list[str]:
    """Extract decorator names from preceding decorator nodes (TS/experimental)."""
    decorators: list[str] = []
    # For method_definition, decorators are siblings in the class body
    parent = func_node.parent
    if parent is None:
        return decorators
    prev = func_node.prev_named_sibling
    while prev is not None and prev.type == "decorator":
        parts = [c for c in prev.children if c.type != "@"]
        if parts:
            decorators.append(_text(parts[0]))
        prev = prev.prev_named_sibling
    decorators.reverse()
    return decorators


def _js_jsdoc(func_node: Any) -> str:
    """Extract JSDoc comment preceding a JS/TS function."""
    # Check the previous sibling for a block comment starting with /**
    target = func_node
    # For lexical_declaration (arrow functions), the comment is before the declaration
    if func_node.type == "arrow_function" and func_node.parent:
        p = func_node.parent
        if p.type == "variable_declarator" and p.parent:
            target = p.parent  # lexical_declaration or variable_declaration
    prev = target.prev_named_sibling
    if prev is not None and prev.type == "comment":
        text = _text(prev)
        if text.startswith("/**"):
            # Strip /** and */ and leading * from each line
            text = text[3:]
            if text.endswith("*/"):
                text = text[:-2]
            lines = []
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("*"):
                    line = line[1:].strip()
                lines.append(line)
            return "\n".join(lines).strip()
    return ""


def _js_class_heritage(class_node: Any) -> list[str]:
    """Extract base class and interface names from JS/TS class_declaration."""
    bases: list[str] = []
    for child in class_node.children:
        if child.type == "class_heritage":
            for clause in child.children:
                if clause.type in ("extends_clause", "implements_clause"):
                    for c in clause.children:
                        if c.type in ("identifier", "type_identifier", "member_expression"):
                            bases.append(_text(c))
    return bases


def _extract_python(
    root: Any,
    rel_path: str,
    functions: list,
    classes: list,
    imports: list,
    calls: list,
):
    for node in _walk(root):
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            params_node = node.child_by_field_name("parameters")
            params, param_types = _py_extract_params(params_node)
            functions.append({
                "file": rel_path,
                "name": _text(name_node) if name_node else "unknown",
                "line_start": node.start_point[0] + 1,
                "line_end": node.end_point[0] + 1,
                "params": params,
                "calls": [],
                "parameter_types": param_types,
                "return_type": _py_return_type(node),
                "decorators": _py_decorators(node),
                "is_async": _py_is_async(node),
                "is_generator": _py_is_generator(node),
                "docstring": _py_docstring(node),
            })

        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            methods = []
            for child in _walk(node):
                if child.type == "function_definition":
                    mn = child.child_by_field_name("name")
                    if mn:
                        methods.append(_text(mn))
            decorators: list[str] = []
            parent = node.parent
            if parent and parent.type == "decorated_definition":
                for child in parent.children:
                    if child.type == "decorator":
                        parts = [c for c in child.children if c.type != "@"]
                        if parts:
                            decorators.append(_text(parts[0]))
            classes.append({
                "file": rel_path,
                "name": _text(name_node) if name_node else "unknown",
                "line_start": node.start_point[0] + 1,
                "line_end": node.end_point[0] + 1,
                "methods": methods,
                "bases": _py_class_bases(node),
                "decorators": decorators,
            })

        elif node.type in ("import_statement", "import_from_statement"):
            module_node = node.child_by_field_name("module_name") or node.child_by_field_name("name")
            names = []
            for child in node.children:
                if child.type == "dotted_name" and child != module_node:
                    names.append(_text(child))
                elif child.type == "aliased_import":
                    name_part = child.child_by_field_name("name")
                    if name_part:
                        names.append(_text(name_part))
            imports.append({
                "file": rel_path,
                "module": _text(module_node) if module_node else "",
                "names": names,
            })

        elif node.type == "call":
            func_node = node.child_by_field_name("function")
            if func_node:
                caller = _find_enclosing_function(node)
                calls.append((caller, _text(func_node)))


def _extract_js_ts(
    root: Any,
    rel_path: str,
    functions: list,
    classes: list,
    imports: list,
    calls: list,
):
    for node in _walk(root):
        if node.type in ("function_declaration", "generator_function_declaration", "method_definition"):
            name_node = node.child_by_field_name("name")
            params_node = node.child_by_field_name("parameters")
            params, param_types = _js_extract_params(params_node)
            functions.append({
                "file": rel_path,
                "name": _text(name_node) if name_node else "anonymous",
                "line_start": node.start_point[0] + 1,
                "line_end": node.end_point[0] + 1,
                "params": params,
                "calls": [],
                "parameter_types": param_types,
                "return_type": _js_return_type(node),
                "decorators": _js_decorators(node),
                "is_async": _js_is_async(node),
                "is_generator": _js_is_generator(node),
                "docstring": _js_jsdoc(node),
            })

        elif node.type == "arrow_function":
            parent = node.parent
            name = "anonymous"
            if parent and parent.type == "variable_declarator":
                n = parent.child_by_field_name("name")
                if n:
                    name = _text(n)
            params_node = node.child_by_field_name("parameters")
            params, param_types = _js_extract_params(params_node)
            functions.append({
                "file": rel_path,
                "name": name,
                "line_start": node.start_point[0] + 1,
                "line_end": node.end_point[0] + 1,
                "params": params,
                "calls": [],
                "parameter_types": param_types,
                "return_type": _js_return_type(node),
                "decorators": [],
                "is_async": _js_is_async(node),
                "is_generator": False,
                "docstring": _js_jsdoc(node),
            })

        elif node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            methods = []
            for child in _walk(node):
                if child.type == "method_definition":
                    mn = child.child_by_field_name("name")
                    if mn:
                        methods.append(_text(mn))
            classes.append({
                "file": rel_path,
                "name": _text(name_node) if name_node else "unknown",
                "line_start": node.start_point[0] + 1,
                "line_end": node.end_point[0] + 1,
                "methods": methods,
                "bases": _js_class_heritage(node),
                "decorators": [],
            })

        elif node.type == "import_statement":
            source_node = node.child_by_field_name("source")
            names = []
            for child in _walk(node):
                if child.type == "import_specifier":
                    n = child.child_by_field_name("name")
                    if n:
                        names.append(_text(n))
            imports.append({
                "file": rel_path,
                "module": _text(source_node).strip("'\"") if source_node else "",
                "names": names,
            })

        elif node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                caller = _find_enclosing_function(node)
                calls.append((caller, _text(func_node)))


def _walk(node: Any):
    """Depth-first walk of a tree-sitter node."""
    yield node
    for child in node.children:
        yield from _walk(child)


def parse_repo(repo_path: str, file_tree: list[str]) -> ASTData:
    """Parse all source files in a repo and produce a combined ASTData."""
    all_functions: list[FunctionInfo] = []
    all_classes: list[ClassInfo] = []
    all_imports: list[ImportInfo] = []
    all_call_edges: list[tuple[str, str]] = []

    for rel_path in file_tree:
        full_path = os.path.join(repo_path, rel_path)
        if not os.path.isfile(full_path):
            continue

        try:
            result = parse_file(full_path, rel_path)
            for f in result["functions"]:
                all_functions.append(FunctionInfo(**f))
            for c in result["classes"]:
                all_classes.append(ClassInfo(**c))
            for i in result["imports"]:
                all_imports.append(ImportInfo(**i))
            all_call_edges.extend(result["calls"])
        except Exception as e:
            log.warning("parse_error", file=rel_path, error=str(e))

    func_names = {f.name for f in all_functions}
    resolved_edges = [
        (caller, callee) for caller, callee in all_call_edges if callee in func_names
    ]

    log.info(
        "ast_parsing_complete",
        functions=len(all_functions),
        classes=len(all_classes),
        imports=len(all_imports),
        edges=len(resolved_edges),
    )

    ast_result = ASTData(
        functions=all_functions,
        classes=all_classes,
        imports=all_imports,
        call_edges=resolved_edges,
    )

    log.info(
        "enriched_ast_dump",
        ast=json.dumps(ast_result.model_dump(), indent=2, default=str),
    )

    return ast_result
