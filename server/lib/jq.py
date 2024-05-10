# find all occurences of a key in a nested json
def find_key_paths(json_data, key, path=""):
    results = []
    # Check if the input is a dictionary
    if isinstance(json_data, dict):
        # If the key is found, return the path to it
        if key in json_data:
            results.append(path + key)
        # Recursively search through each value in the dictionary
        for k, v in json_data.items():
            results.extend(find_key_paths(v, key, path + k + "."))
    # Check if the input is a list
    elif isinstance(json_data, list):
        # Recursively search through each item in the list
        for i, item in enumerate(json_data):
            if isinstance(item, dict):
                results.extend(find_key_paths(item, key, path + f"[{i}]."))
            elif isinstance(item, list):
                for j, sub_item in enumerate(item):
                    results.extend(find_key_paths(sub_item, key, path + f"[{i}][{j}]."))
    # Return None if the key is not found
    return results


# method to change the value of the key using key notation .[]
def get_value(json_data, key):
    for path in key.split("."):
        if path.startswith("["):
            index = int(path[1:-1])
            json_data = json_data[index]
        else:
            json_data = json_data[path]
    return json_data


def set_value(json_data, key, value):
    for path in key.split(".")[:-1]:
        if path.startswith("["):
            index = int(path[1:-1])
            json_data = json_data[index]
        else:
            json_data = json_data[path]
    path = key.split(".")[-1]
    json_data[path] = value


if __name__ == "__main__":
    nested_json = {
        "key1": "value1",
        "key2": {
            "key3": "value3",
            "key4": [{"key5": "value5"}, {"keyname": "target_value"}],
        },
        "key3": {"key4": [{"key5": "value5"}, {"keyname": "target_value"}]},
        "key4": {"keyname": "target_value"},
    }

    key_to_find = "keyname"
    result = find_key_paths(nested_json, key_to_find)
    print(result)
    for path in result:
        value = get_value(nested_json, path)
        print(f"{path}: {value}")

    set_value(nested_json, "key2.key4.[1].keyname", "new_value")
    for path in result:
        value = get_value(nested_json, path)
        print(f"{path}: {value}")
