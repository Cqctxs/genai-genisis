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
        if current.type in ("function_definition", "function_declaration", "method_definition", "arrow_function"):
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
            params = []
            if params_node:
                for p in params_node.children:
                    if p.type == "identifier":
                        params.append(_text(p))
            functions.append({
                "file": rel_path,
                "name": _text(name_node) if name_node else "unknown",
                "line_start": node.start_point[0] + 1,
                "line_end": node.end_point[0] + 1,
                "params": params,
                "calls": [],
            })

        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            methods = []
            for child in _walk(node):
                if child.type == "function_definition":
                    mn = child.child_by_field_name("name")
                    if mn:
                        methods.append(_text(mn))
            classes.append({
                "file": rel_path,
                "name": _text(name_node) if name_node else "unknown",
                "line_start": node.start_point[0] + 1,
                "line_end": node.end_point[0] + 1,
                "methods": methods,
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
        if node.type in ("function_declaration", "method_definition"):
            name_node = node.child_by_field_name("name")
            params_node = node.child_by_field_name("parameters")
            params = []
            if params_node:
                for p in params_node.children:
                    if p.type in ("identifier", "required_parameter", "optional_parameter"):
                        name = p.child_by_field_name("pattern") or p
                        params.append(_text(name))
            functions.append({
                "file": rel_path,
                "name": _text(name_node) if name_node else "anonymous",
                "line_start": node.start_point[0] + 1,
                "line_end": node.end_point[0] + 1,
                "params": params,
                "calls": [],
            })

        elif node.type == "arrow_function":
            parent = node.parent
            name = "anonymous"
            if parent and parent.type == "variable_declarator":
                n = parent.child_by_field_name("name")
                if n:
                    name = _text(n)
            functions.append({
                "file": rel_path,
                "name": name,
                "line_start": node.start_point[0] + 1,
                "line_end": node.end_point[0] + 1,
                "params": [],
                "calls": [],
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

    return ASTData(
        functions=all_functions,
        classes=all_classes,
        imports=all_imports,
        call_edges=resolved_edges,
    )
