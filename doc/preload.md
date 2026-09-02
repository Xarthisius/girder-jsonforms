# Technical Documentation: Preload Field in JSON Schema

---

## 1. Introduction

This document describes the `preload` field within the root of a JSON schema, its specified format, and its resulting impact on the materialization of a form, specifically regarding the "dependencies" key.

## 2. Preload Field Definition

The `preload` field is an optional field located at the root level of a JSON schema. Its primary purpose is to define a mechanism for pre-populating data within a form's materialized dependencies.

## 3. Preload Field Format

The `preload` field adheres to a specific string format:

`girder.formId:<formId>:<field1>:<field2>...`

### 3.1. Format Components:

* **`girder.formId`**: A literal string prefix indicating the type of preload operation, specifically targeting a Girder form.
* **`<formId>`**: A unique identifier corresponding to the target form. This ID links the preload configuration to a specific form definition.
* **`<field1>:<field2>...`**: A colon-separated list of field names. These field names correspond to specific fields within the form identified by `<formId>` whose values are intended to be preloaded.

## 4. Impact on Form Materialization: "dependencies" Key

When a form is materialized, the presence and proper configuration of the `preload` field result in the addition or modification of a "dependencies" key within the form's materialized structure.

### 4.1. "dependencies" Key Structure:

The "dependencies" key will contain a map where:

* **`<entryId>`**: Represents a unique identifier for a data entry or record that is being preloaded. The specific generation or source of this `entryId` is context-dependent but typically relates to an existing data record that the form is intended to interact with.
* **`{data.<field1>: value1, data.<field2>: value2, ...}`**: This is an object that maps the specified preload fields to their corresponding values for the given `<entryId>`.
    * **`data.<fieldN>`**: Represents the full path to the field within the preloaded data structure. The `data.` prefix indicates that these fields are part of the core data payload for the entry.
    * **`valueN`**: The actual value to be preloaded for `data.<fieldN>`. These values are typically retrieved from an external data source based on the `<entryId>` and the specified field names.

## 5. Example

Consider the following `preload` field in a JSON schema:

```json
{
  "preload": "girder.formId:myAwesomeForm:firstName:lastName:email"
}
```

Upon materialization of the myAwesomeForm, and assuming a preloaded entry with entryId "user123", the "dependencies" key within the form's materialized structure might appear as follows:

```json
{
  "dependencies": {
    "user123": {
      "data.firstName": "John",
      "data.lastName": "Doe",
      "data.email": "john.doe@example.com"
    },
    "user124": {
      "data.firstName": "Jane",
      "data.lastName": "Smith",
      "data.email": "jane.smith@example.com"
    }
  }
}
```

## 6. Conclusion

The `preload` field in a JSON schema serves as a powerful tool for pre-populating form data, enhancing user experience by reducing manual input requirements. By adhering to the specified format and understanding its impact on the "dependencies" key, developers can effectively implement this feature in their applications.
