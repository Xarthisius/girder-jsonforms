import pytest

from ..lib.jq import (
    JqPathError,
    convert_to_jq_notation,
    find_key_paths,
    get_value,
    iter_values,
    parse_jq_notation,
    set_value,
)


@pytest.fixture
def nested_data():
    return {
        "key1": "value1",
        "key2": {
            "key3": "value3",
            "key4": [{"key5": "value5"}, {"keyname": "target_value"}],
        },
        "key3": {"key4": [{"key5": "value5"}, {"keyname": "target_value"}]},
        "key4": {"keyname": "target_value"},
    }


@pytest.fixture
def keys_for_target_value():
    return ["key2.key4.[1].keyname", "key3.key4.[1].keyname", "key4.keyname"]


@pytest.fixture
def jq_data():
    return {
        "data.key": 1,
        "data.list.[0].first_name": "Alan",
        "data.list.[0].last_name": "Doe",
        "data.list.[1].first_name.0": "Bob",
        "data.list.[1].first_name.1": "John",
        "data.list.[2].first_name.[0]": "John",
        "data.list.[2].first_name.[1]": "Paul",
        "data.list.[1].last_name": "Smith",
        "data.rawlist.[0]": "one",
        "data.rawlist.[1]": "two",
        "data.foo.bar": "baz",
    }


@pytest.fixture
def list_of_lists_jq():
    return {
        "data.nestedlist.[0].[0].key": "value1",
        "data.nestedlist.[0].[1]": "value2",
    }


@pytest.fixture
def jq_result():
    return {
        "data": {
            "key": 1,
            "list": [
                {"first_name": "Alan", "last_name": "Doe"},
                {"first_name": {"0": "Bob", "1": "John"}, "last_name": "Smith"},
                {"first_name": ["John", "Paul"]},
            ],
            "rawlist": ["one", "two"],
            "foo": {"bar": "baz"},
        }
    }

@pytest.fixture
def list_of_lists():
    return {"data": {"nestedlist": [[{"key": "value1"}, "value2"]]}}

def test_find_key_paths(nested_data, keys_for_target_value):
    key_to_find = "keyname"
    result = find_key_paths(nested_data, key_to_find)
    assert result == keys_for_target_value


def test_get_value(nested_data, keys_for_target_value):
    for path in keys_for_target_value:
        assert get_value(nested_data, path) == "target_value"


def test_set_value(nested_data):
    set_value(nested_data, "key2.key4.[1].keyname", "new_value")
    assert get_value(nested_data, "key2.key4.[1].keyname") == "new_value"


def test_jq_notation(jq_data, jq_result):
    assert parse_jq_notation(jq_data) == jq_result


def test_convert_to_jq_notation(jq_result, jq_data):
    assert convert_to_jq_notation(jq_result) == jq_data


def test_convert_list_of_lists(list_of_lists_jq, list_of_lists):
    result = convert_to_jq_notation(parse_jq_notation(list_of_lists))
    assert result == list_of_lists_jq

def test_list_of_lists(list_of_lists, list_of_lists_jq):
    result = parse_jq_notation(list_of_lists_jq)
    assert result == list_of_lists


@pytest.fixture
def measurements():
    return {
        "measurements": [
            {"thickness": 12.5},
            {"thickness": 13.1},
            {"thickness": 11.9},
        ]
    }


def test_iter_values_single_wildcard(measurements):
    assert list(iter_values(measurements, "measurements.[].thickness")) == [
        ("measurements.[0].thickness", 12.5),
        ("measurements.[1].thickness", 13.1),
        ("measurements.[2].thickness", 11.9),
    ]


def test_iter_values_paths_round_trip_through_get_value(measurements):
    for path, value in iter_values(measurements, "measurements.[].thickness"):
        assert get_value(measurements, path) == value


def test_iter_values_paths_agree_with_find_key_paths(measurements):
    paths = [path for path, _ in iter_values(measurements, "measurements.[].thickness")]
    assert paths == find_key_paths(measurements, "thickness")


def test_iter_values_without_wildcard(nested_data):
    path = "key2.key4.[1].keyname"
    expected = [(path, get_value(nested_data, path))]
    assert list(iter_values(nested_data, path)) == expected


def test_iter_values_without_wildcard_missing_key(nested_data):
    assert list(iter_values(nested_data, "key2.nope.keyname")) == []


def test_iter_values_skips_elements_missing_the_key():
    data = {
        "measurements": [{"thickness": 12.5}, {"note": "skipped"}, {"thickness": 11.9}]
    }
    assert list(iter_values(data, "measurements.[].thickness")) == [
        ("measurements.[0].thickness", 12.5),
        ("measurements.[2].thickness", 11.9),
    ]


def test_iter_values_nested_wildcards():
    data = {"a": [{"b": [{"c": 1}, {"c": 2}]}, {"b": [{"c": 3}]}]}
    assert list(iter_values(data, "a.[].b.[].c")) == [
        ("a.[0].b.[0].c", 1),
        ("a.[0].b.[1].c", 2),
        ("a.[1].b.[0].c", 3),
    ]


def test_iter_values_ragged_nesting():
    data = {"a": [{"b": []}, {"b": [{"c": 1}, {"c": 2}, {"c": 3}]}, {"b": [{"c": 4}]}]}
    assert list(iter_values(data, "a.[].b.[].c")) == [
        ("a.[1].b.[0].c", 1),
        ("a.[1].b.[1].c", 2),
        ("a.[1].b.[2].c", 3),
        ("a.[2].b.[0].c", 4),
    ]


def test_iter_values_empty_list():
    assert list(iter_values({"measurements": []}, "measurements.[].thickness")) == []


def test_iter_values_wildcard_on_dict_raises():
    data = {"measurements": {"thickness": 12.5}}
    with pytest.raises(JqPathError) as exc:
        list(iter_values(data, "measurements.[].thickness"))
    assert "measurements" in str(exc.value)
    assert "dict" in str(exc.value)


def test_iter_values_wildcard_on_scalar_raises():
    with pytest.raises(JqPathError) as exc:
        list(iter_values({"measurements": 3}, "measurements.[].thickness"))
    assert "measurements" in str(exc.value)
    assert "int" in str(exc.value)


def test_iter_values_wildcard_on_root_scalar_names_root():
    with pytest.raises(JqPathError) as exc:
        list(iter_values("nope", "[].thickness"))
    assert "<root>" in str(exc.value)


def test_iter_values_explicit_index_out_of_range(measurements):
    assert list(iter_values(measurements, "measurements.[9].thickness")) == []


def test_iter_values_explicit_index_matches_wildcard():
    data = {"measurements": [{"thickness": 12.5}]}
    assert list(iter_values(data, "measurements.[0].thickness")) == list(
        iter_values(data, "measurements.[].thickness")
    )


def test_iter_values_root_level_wildcard():
    data = [{"c": 1}, {"c": 2}]
    assert list(iter_values(data, "[].c")) == [("[0].c", 1), ("[1].c", 2)]
