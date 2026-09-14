import pytest

from girder.exceptions import ValidationException
from girder_jsonforms.models.deposition import PrefixCounter

@pytest.mark.plugin("jsonforms")
def test_prefix_counter(db):
    """
    Test the PrefixCounter class.
    """
    with pytest.raises(ValidationException) as excinfo:
        PrefixCounter().get_counter("foo")
    assert str(excinfo.value) == "Prefix must be 6 characters long"

    with pytest.raises(ValidationException) as excinfo:
        PrefixCounter().get_counter("ZZCDEF")
    assert str(excinfo.value) == "Invalid institution ZZ"

    with pytest.raises(ValidationException) as excinfo:
        PrefixCounter().get_counter("JHZDEF")
    assert str(excinfo.value) == "Invalid subinstitution Z"

    with pytest.raises(ValidationException) as excinfo:
        PrefixCounter().get_counter("JHXZZZ")
    assert str(excinfo.value) == "Invalid material ZZ"

    with pytest.raises(ValidationException) as excinfo:
        PrefixCounter().get_counter("JHXMAZ")
    assert str(excinfo.value) == "Invalid submaterial Z"

    # Valid prefix
    counter = PrefixCounter().get_counter(
        "JHXMAA"
    )  # Set initial counter for prefix JHXDEF
    assert counter["prefix"] == "JHXMAA" and counter["seq"] == 0

    counter = PrefixCounter().increment(counter)
    assert counter["prefix"] == "JHXMAA" and counter["seq"] == 1

    prefix = PrefixCounter().get_next("JHXMAA")  # Get the current prefix counter
    assert prefix == "JHXMAA00002"  # Ensure the prefix is correct

