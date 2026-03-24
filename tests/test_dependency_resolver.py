import pytest
from graphlib import CycleError

from ocio_vendor_extensions.dependency_resolver import (
    resolve_processing_order,
    expand_dependencies,
)


class TestExpandDependencies:
    def test_no_deps(self):
        requested = {"arri", "davinci"}
        depends_on = {"arri": [], "davinci": []}
        result = expand_dependencies(requested, depends_on)
        assert result == {"arri", "davinci"}

    def test_transitive_dep(self):
        requested = {"sony"}
        depends_on = {"sony": ["filmlight"], "filmlight": []}
        result = expand_dependencies(requested, depends_on)
        assert result == {"sony", "filmlight"}

    def test_already_included(self):
        requested = {"sony", "filmlight"}
        depends_on = {"sony": ["filmlight"], "filmlight": []}
        result = expand_dependencies(requested, depends_on)
        assert result == {"sony", "filmlight"}


class TestResolveProcessingOrder:
    def test_independent_alphabetical(self):
        families = {"davinci", "arri", "filmlight"}
        depends_on = {"davinci": [], "arri": [], "filmlight": []}
        order = resolve_processing_order(families, depends_on)
        assert order == ["arri", "davinci", "filmlight"]

    def test_dependency_before_dependent(self):
        families = {"sony", "filmlight"}
        depends_on = {"sony": ["filmlight"], "filmlight": []}
        order = resolve_processing_order(families, depends_on)
        assert order.index("filmlight") < order.index("sony")

    def test_circular_dependency_raises(self):
        families = {"a", "b"}
        depends_on = {"a": ["b"], "b": ["a"]}
        with pytest.raises(CycleError):
            resolve_processing_order(families, depends_on)
