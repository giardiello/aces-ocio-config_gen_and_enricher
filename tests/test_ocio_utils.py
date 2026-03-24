import pytest


def test_get_transform_ids_returns_list():
    from ocio_aces_tools.ocio_utils import get_transform_ids
    # Minimal mock: object with getDescription returning "ACEStransformID: urn:..."
    class MockItem:
        def getDescription(self):
            return "ACEStransformID: urn:ampas:aces:transformId:v1.0:ODT.test"
        def getInterchangeAttributes(self):
            return None
    result = get_transform_ids(MockItem())
    assert result == ["urn:ampas:aces:transformId:v1.0:ODT.test"]
