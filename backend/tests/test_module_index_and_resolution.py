"""Import resolution is the correctness-critical core of the whole tool: a wrong
resolution means a dependency is drawn to the wrong file, a rule is checked
against the wrong component, and a historical trace answers the wrong question."""
import pytest

from analysis.dependency.module_index import ModuleIndex, _dotted_suffixes
from analysis.dependency.repository_scanner import resolve_import, scan_repository
from analysis.parser.base import RawImport
from rules.loader import ComponentMapping


def index(*paths):
    idx = ModuleIndex()
    for p in paths:
        idx.add_file(p)
    return idx


def test_dotted_suffixes_longest_first():
    assert _dotted_suffixes(["backend", "services"], "pay") == ["backend.services.pay", "services.pay", "pay"]
    assert _dotted_suffixes(["a"], "") == ["a"]


class TestAbsolute:
    def test_resolves_full_and_partial_dotted_paths(self):
        idx = index("backend/services/pay.py")
        for mod in ("backend.services.pay", "services.pay", "pay"):
            assert idx.resolve_absolute(mod) == "backend/services/pay.py"

    def test_package_resolves_to_its_init_file(self):
        idx = index("backend/services/__init__.py")
        assert idx.resolve_absolute("backend.services") == "backend/services/__init__.py"
        assert idx.resolve_absolute("services") == "backend/services/__init__.py"

    def test_unknown_module_is_none(self):
        assert index("a/b.py").resolve_absolute("requests") is None

    def test_windows_separators_are_normalised(self):
        assert index("backend\\services\\pay.py").resolve_absolute("services.pay") == "backend/services/pay.py"

    def test_top_level_file(self):
        assert index("main.py").resolve_absolute("main") == "main.py"

    def test_ambiguous_basename_prefers_the_shortest_path_documented_limitation(self):
        idx = index("pkg_a/util.py", "pkg_b/deep/util.py")
        assert idx.resolve_absolute("util") == "pkg_a/util.py"

    def test_adding_a_file_twice_does_not_duplicate_candidates(self):
        idx = index("a/b.py", "a/b.py")
        assert idx.resolve_absolute("b") == "a/b.py"


class TestRelative:
    idx = index(
        "app/__init__.py", "app/services/__init__.py", "app/services/pay.py",
        "app/models/user.py", "app/shared/helpers.py", "top.py",
    )

    def test_single_dot_is_the_current_package(self):
        assert self.idx.resolve_relative("app/services/pay.py", ".") == "app/services/__init__.py"

    def test_dot_module_is_a_sibling(self):
        idx = index("app/services/pay.py", "app/services/refund.py")
        assert idx.resolve_relative("app/services/pay.py", ".refund") == "app/services/refund.py"

    def test_double_dot_goes_up_one_package(self):
        assert self.idx.resolve_relative("app/services/pay.py", "..models.user") == "app/models/user.py"
        assert self.idx.resolve_relative("app/services/pay.py", "..shared.helpers") == "app/shared/helpers.py"

    def test_relative_import_that_leaves_the_repo_is_none(self):
        assert self.idx.resolve_relative("app/services/pay.py", "..missing") is None

    def test_relative_from_a_top_level_file(self):
        idx = index("top.py", "sibling.py")
        assert idx.resolve_relative("top.py", ".sibling") == "sibling.py"

    def test_from_dot_import_name_resolves_the_name_as_a_submodule(self):
        idx = index("app/services/pay.py", "app/services/refund.py")
        assert idx.resolve_relative_name("app/services/pay.py", ".", "refund") == "app/services/refund.py"

    def test_from_dotted_module_import_name(self):
        assert self.idx.resolve_relative_name("app/services/pay.py", "..models", "user") == "app/models/user.py"

    def test_name_that_is_only_an_attribute_does_not_resolve(self):
        assert self.idx.resolve_relative_name("app/services/pay.py", ".", "SomeClass") is None


class TestResolveImport:
    idx = index("app/services/pay.py", "app/services/refund.py", "app/models/user.py", "app/__init__.py")

    def imp(self, module, names=(), relative=False):
        return RawImport(module=module, imported_names=tuple(names), line=1, is_relative=relative)

    def test_absolute_module(self):
        assert resolve_import("app/x.py", self.imp("app.models.user"), self.idx) == "app/models/user.py"

    def test_absolute_package_then_submodule_name(self):
        # `from app.services import pay` : `app.services` has no __init__.py here, `pay` is the module
        assert resolve_import("app/x.py", self.imp("app.services", ["pay"]), self.idx) == "app/services/pay.py"

    def test_relative_import_of_a_submodule_name(self):
        assert resolve_import("app/services/pay.py", self.imp(".", ["refund"], True), self.idx) == "app/services/refund.py"

    def test_relative_module_import(self):
        assert resolve_import("app/services/pay.py", self.imp("..models.user", ["User"], True), self.idx) == "app/models/user.py"

    def test_relative_falls_back_to_the_module_itself(self):
        assert resolve_import("app/services/pay.py", self.imp(".refund", ["Refunder"], True), self.idx) == "app/services/refund.py"

    def test_external_library_is_none(self):
        assert resolve_import("app/x.py", self.imp("requests", ["get"]), self.idx) is None


def test_scan_resolves_relative_imports_end_to_end_and_skips_self_and_external(tmp_path):
    def w(path, text=""):
        f = tmp_path / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    w("app/__init__.py")
    w("app/services/__init__.py")
    w("app/services/pay.py", "from . import refund\nfrom ..models import user\nimport requests\nfrom .pay import X\n")
    w("app/services/refund.py")
    w("app/models/__init__.py")
    w("app/models/user.py")
    mapping = ComponentMapping(mapping={"services": "service", "models": "model"})
    scan = scan_repository(str(tmp_path), mapping)
    edges = {(d.source, d.target) for d in scan.dependencies}
    assert edges == {("app/services/pay.py", "app/services/refund.py"), ("app/services/pay.py", "app/models/user.py")}
    assert "requests" in scan.external_imports
    # `from .pay import X` points at the file itself and must not become a self-dependency
    assert not any(s == t for s, t in edges)
