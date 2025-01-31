from typing import Any

# find all occurences of a key in a nested json
def find_key_paths(json_data: dict, key: str, path: str = "") -> list[str]:
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
def get_value(json_data: dict, key: str) -> dict:
    for path in key.split("."):
        if path.startswith("["):
            index = int(path[1:-1])
            json_data = json_data[index]
        else:
            json_data = json_data[path]
    return json_data


def set_value(json_data: dict, key: str, value: Any) -> None:
    for path in key.split(".")[:-1]:
        if path.startswith("["):
            index = int(path[1:-1])
            json_data = json_data[index]
        else:
            json_data = json_data[path]
    path = key.split(".")[-1]
    json_data[path] = value


def convert_to_jq_notation(data: dict, parent_key: str = "", sep: str = ".") -> dict:
    """
    Convert a nested dictionary or list into a flat dictionary with jq-style keys.

    Args:
        data (dict or list): The nested dictionary or list to flatten.
        parent_key (str): The base key for recursion (used internally).
        sep (str): The separator to use for keys (default is ".").

    Returns:
        dict: A flattened dictionary with jq-like notation keys.
    """
    items = []

    if isinstance(data, dict):
        for key, value in data.items():
            new_key = f"{parent_key}{sep}{key}" if parent_key else key
            items.extend(convert_to_jq_notation(value, new_key, sep).items())
    elif isinstance(data, list):
        for index, value in enumerate(data):
            new_key = f"{parent_key}{sep}[{index}]"
            items.extend(convert_to_jq_notation(value, new_key, sep).items())
    else:
        items.append((parent_key, data))

    return dict(items)


def parse_jq_notation(input_dict: dict) -> dict:
    """
    Convert a dictionary with jq-style keys into a nested dictionary.

    Args:
        input_dict (dict): The dictionary with jq-style keys.

    Returns:
        dict: A nested dictionary.
    """

    def is_array_index(key):
        return key.startswith("[") and key.endswith("]") and key[1:-1].isdigit()

    output = {}

    for key, value in input_dict.items():
        keys = key.split(".")
        current = output

        for i, part in enumerate(keys[:-1]):
            if is_array_index(part):
                # Convert string digits to integers for lists
                part = int(part.strip("[]"))

            if "nestedlist" in key:
                print(current, key, part)
            if isinstance(part, int):
                # If current is not a list, convert it into one
                if not isinstance(current, list):
                    current[keys[i - 1]] = []
                    current = current[keys[i - 1]]
                # Extend the list to ensure the index exists

                if i + 1 <= len(keys[:-1]) and is_array_index(keys[i+1]):
                    append_object = []
                else:
                    append_object = {}

                while len(current) <= part:
                    # It has to be a placeholder for dictionary or list
                    current.append(append_object)
                current = current[part]
            else:
                if part not in current:
                    # Create a list if the next key is a digit
                    next_part = keys[i + 1]
                    current[part] = [] if is_array_index(next_part) else {}
                current = current[part]

        # Handle the last key
        last_key = keys[-1]
        if is_array_index(last_key):
            current.append(value)
        else:
            current[last_key] = value

    return output
