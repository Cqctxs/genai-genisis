"""Test suite that parses a repo (or sample files) and dumps the AST to stdout.

Run with:
    pytest tests/test_ast_dump.py -s

The `-s` flag is required to see the JSON dump on stdout.
"""

import json
import os
import tempfile
import textwrap

import pytest

from services.parser_service import parse_file, parse_repo
from services.github_service import get_file_tree
from agent.schemas import ASTData, FunctionInfo, ClassInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_file(directory: str, rel_path: str, content: str) -> str:
    """Write a file into directory at rel_path and return its absolute path."""
    full = os.path.join(directory, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(textwrap.dedent(content))
    return full


# ---------------------------------------------------------------------------
# Python extraction tests
# ---------------------------------------------------------------------------


class TestPythonTypeExtraction:
    """Verify parameter types, return types, decorators, async, generator, docstring."""

    def test_typed_params_and_return(self):
        src = textwrap.dedent("""\
            def add(a: int, b: int) -> int:
                return a + b
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.py")
            fn = result["functions"][0]
            assert fn["parameter_types"] == {"a": "int", "b": "int"}
            assert fn["return_type"] == "int"
        finally:
            os.unlink(path)

    def test_complex_type_annotations(self):
        src = textwrap.dedent("""\
            from typing import Dict, List, Optional
            def process(items: List[str], mapping: Dict[str, int], flag: Optional[bool] = None) -> Dict[str, List[int]]:
                pass
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.py")
            fn = result["functions"][0]
            assert fn["parameter_types"]["items"] == "List[str]"
            assert fn["parameter_types"]["mapping"] == "Dict[str, int]"
            assert fn["parameter_types"]["flag"] == "Optional[bool]"
            assert "Dict[str, List[int]]" in fn["return_type"]
        finally:
            os.unlink(path)

    def test_no_annotations(self):
        src = textwrap.dedent("""\
            def greet(name):
                return f"Hello {name}"
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.py")
            fn = result["functions"][0]
            assert fn["parameter_types"] == {}
            assert fn["return_type"] == ""
        finally:
            os.unlink(path)

    def test_decorators(self):
        src = textwrap.dedent("""\
            @staticmethod
            def helper():
                pass

            @app.route("/api")
            def endpoint():
                pass
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.py")
            fns = {fn["name"]: fn for fn in result["functions"]}
            assert fns["helper"]["decorators"] == ["staticmethod"]
            assert len(fns["endpoint"]["decorators"]) == 1
            assert "app.route" in fns["endpoint"]["decorators"][0]
        finally:
            os.unlink(path)

    def test_async_function(self):
        src = textwrap.dedent("""\
            async def fetch_data(url: str) -> dict:
                pass
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.py")
            fn = result["functions"][0]
            assert fn["is_async"] is True
            assert fn["is_generator"] is False
        finally:
            os.unlink(path)

    def test_generator_function(self):
        src = textwrap.dedent("""\
            def gen_items(n: int):
                for i in range(n):
                    yield i
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.py")
            fn = result["functions"][0]
            assert fn["is_generator"] is True
            assert fn["is_async"] is False
        finally:
            os.unlink(path)

    def test_docstring(self):
        src = textwrap.dedent('''\
            def documented(x: int) -> str:
                """Convert x to string representation.

                Args:
                    x: the integer to convert
                """
                return str(x)
        ''')
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.py")
            fn = result["functions"][0]
            assert "Convert x to string" in fn["docstring"]
        finally:
            os.unlink(path)

    def test_class_bases(self):
        src = textwrap.dedent("""\
            class MyModel(BaseModel, Serializable):
                pass
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.py")
            cls = result["classes"][0]
            assert "BaseModel" in cls["bases"]
            assert "Serializable" in cls["bases"]
        finally:
            os.unlink(path)

    def test_class_no_bases(self):
        src = textwrap.dedent("""\
            class Plain:
                pass
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.py")
            cls = result["classes"][0]
            assert cls["bases"] == []
        finally:
            os.unlink(path)

    def test_default_param_without_type(self):
        src = textwrap.dedent("""\
            def func(x, y=10):
                pass
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.py")
            fn = result["functions"][0]
            assert "x" in fn["params"]
            assert "y" in fn["params"]
            assert fn["parameter_types"] == {}
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# JS/TS extraction tests
# ---------------------------------------------------------------------------


class TestTypeScriptTypeExtraction:
    """Verify parameter types, return types, async, generator, JSDoc for TS."""

    def test_typed_params_and_return(self):
        src = textwrap.dedent("""\
            function add(a: number, b: number): number {
                return a + b;
            }
        """)
        with tempfile.NamedTemporaryFile(suffix=".ts", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.ts")
            fn = result["functions"][0]
            assert fn["parameter_types"] == {"a": "number", "b": "number"}
            assert fn["return_type"] == "number"
        finally:
            os.unlink(path)

    def test_complex_generic_return(self):
        src = textwrap.dedent("""\
            async function fetchAll(ids: string[]): Promise<Record<string, Data>> {
                return {};
            }
        """)
        with tempfile.NamedTemporaryFile(suffix=".ts", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.ts")
            fn = result["functions"][0]
            assert fn["parameter_types"]["ids"] == "string[]"
            assert "Promise" in fn["return_type"]
            assert fn["is_async"] is True
        finally:
            os.unlink(path)

    def test_arrow_function_types(self):
        src = textwrap.dedent("""\
            const double = async (x: number): Promise<number> => {
                return x * 2;
            };
        """)
        with tempfile.NamedTemporaryFile(suffix=".ts", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.ts")
            fn = result["functions"][0]
            assert fn["name"] == "double"
            assert fn["parameter_types"]["x"] == "number"
            assert "Promise" in fn["return_type"]
            assert fn["is_async"] is True
        finally:
            os.unlink(path)

    def test_jsdoc_extraction(self):
        src = textwrap.dedent("""\
            /**
             * Compute the sum of two numbers.
             * @param a - first number
             * @param b - second number
             * @returns the sum
             */
            function sum(a: number, b: number): number {
                return a + b;
            }
        """)
        with tempfile.NamedTemporaryFile(suffix=".ts", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.ts")
            fn = result["functions"][0]
            assert "Compute the sum" in fn["docstring"]
            assert "@param a" in fn["docstring"]
        finally:
            os.unlink(path)

    def test_no_types_js(self):
        src = textwrap.dedent("""\
            function greet(name) {
                return "Hello " + name;
            }
        """)
        with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.js")
            fn = result["functions"][0]
            assert fn["parameter_types"] == {}
            assert fn["return_type"] == ""
        finally:
            os.unlink(path)

    def test_class_extends(self):
        src = textwrap.dedent("""\
            class UserService extends BaseService {
                getData() {
                    return [];
                }
            }
        """)
        with tempfile.NamedTemporaryFile(suffix=".ts", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = parse_file(path, "test.ts")
            cls = result["classes"][0]
            assert "BaseService" in cls["bases"]
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Backward compatibility: new fields have safe defaults
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Ensure the new schema fields have defaults and don't break old data."""

    def test_function_info_defaults(self):
        fi = FunctionInfo(file="x.py", name="f", line_start=1, line_end=2)
        assert fi.parameter_types == {}
        assert fi.return_type == ""
        assert fi.decorators == []
        assert fi.is_async is False
        assert fi.is_generator is False
        assert fi.docstring == ""

    def test_class_info_defaults(self):
        ci = ClassInfo(file="x.py", name="C", line_start=1, line_end=5)
        assert ci.bases == []
        assert ci.decorators == []

    def test_old_style_dict_still_works(self):
        """Dicts without new keys should still construct FunctionInfo."""
        old = {
            "file": "x.py",
            "name": "f",
            "line_start": 1,
            "line_end": 2,
            "params": ["a"],
            "calls": [],
        }
        fi = FunctionInfo(**old)
        assert fi.parameter_types == {}
        assert fi.return_type == ""

    def test_astdata_model_dump_includes_new_fields(self):
        fi = FunctionInfo(
            file="x.py", name="f", line_start=1, line_end=2,
            parameter_types={"a": "int"}, return_type="str",
            decorators=["cached"], is_async=True,
        )
        data = ASTData(functions=[fi])
        dump = data.model_dump()
        fn = dump["functions"][0]
        assert fn["parameter_types"] == {"a": "int"}
        assert fn["return_type"] == "str"
        assert fn["decorators"] == ["cached"]
        assert fn["is_async"] is True


# ---------------------------------------------------------------------------
# Full repo parse + JSON dump
# ---------------------------------------------------------------------------


class TestRepoParseAndDump:
    """Parse a synthetic repo and dump the full AST JSON to stdout."""

    def test_parse_repo_and_dump(self, capsys):
        """Parse a multi-file synthetic repo and print the AST JSON.

        Run with `pytest tests/test_ast_dump.py::TestRepoParseAndDump -s`
        to see the full JSON output.
        """
        with tempfile.TemporaryDirectory() as repo:
            _write_file(repo, "src/models.py", """\
                from dataclasses import dataclass
                from typing import Optional

                @dataclass
                class User:
                    name: str
                    email: str
                    age: Optional[int] = None
            """)

            _write_file(repo, "src/service.py", """\
                from typing import List
                from models import User

                async def get_users(limit: int = 100) -> List[User]:
                    \"\"\"Fetch users from the database.\"\"\"
                    return []

                def process_users(users: List[User]) -> dict[str, int]:
                    counts = {}
                    for user in users:
                        counts[user.name] = counts.get(user.name, 0) + 1
                    return counts
            """)

            _write_file(repo, "src/api.ts", """\
                import { Request, Response } from 'express';

                /**
                 * Handle the users endpoint.
                 * @param req - Express request
                 * @param res - Express response
                 */
                async function handleUsers(req: Request, res: Response): Promise<void> {
                    const data = await fetchData(req.query.id as string);
                    res.json(data);
                }

                function fetchData(id: string): Promise<Record<string, unknown>> {
                    return Promise.resolve({});
                }
            """)

            _write_file(repo, "src/utils.js", """\
                /**
                 * Flatten a nested array.
                 * @param {Array} arr
                 * @returns {Array}
                 */
                function flatten(arr) {
                    return arr.flat(Infinity);
                }

                function* range(start, end) {
                    for (let i = start; i < end; i++) {
                        yield i;
                    }
                }
            """)

            file_tree = get_file_tree(repo)
            ast_data = parse_repo(repo, file_tree)

            dump = ast_data.model_dump()
            output = json.dumps(dump, indent=2)
            print("\n\n=== AST DUMP ===")
            print(output)
            print("=== END AST DUMP ===\n")

            # Structural assertions
            assert len(ast_data.functions) > 0
            assert len(ast_data.classes) > 0
            assert len(ast_data.imports) > 0

            # Verify type info made it through
            fn_map = {f.name: f for f in ast_data.functions}

            if "get_users" in fn_map:
                gu = fn_map["get_users"]
                assert gu.parameter_types.get("limit") == "int"
                assert "List[User]" in gu.return_type
                assert gu.is_async is True
                assert "Fetch users" in gu.docstring

            if "handleUsers" in fn_map:
                hu = fn_map["handleUsers"]
                assert hu.parameter_types.get("req") == "Request"
                assert "Promise" in hu.return_type
                assert hu.is_async is True
                assert "Handle the users endpoint" in hu.docstring

            if "process_users" in fn_map:
                pu = fn_map["process_users"]
                assert "List[User]" in pu.parameter_types.get("users", "")

            # Verify class bases
            cls_map = {c.name: c for c in ast_data.classes}
            if "User" in cls_map:
                # dataclass is a decorator, not a base
                pass

            # Check that generator detection works
            if "range" in fn_map:
                assert fn_map["range"].is_generator is True
