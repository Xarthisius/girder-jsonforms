import pytest

from ..lib.jq import (
    convert_to_jq_notation,
    find_key_paths,
    get_value,
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
