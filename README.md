### Girder JSONForms Plugin

This plugin provides a JSON Forms support for Girder. It is based on the [json-editor](https://github.com/json-editor/json-editor) library. The plugin allows to create JSON forms for data input and editing.

## Usage

The plugin extends girder with two models: `Form` and `FormEntry` (with REST routes `/form` and `/entry` respectively). The `Form` model is used to define the form schema and the `FormEntry` model is used to store the form data. `FormEntries` are primarily kept in girder's mongo database, but can also be stored as JSON dumps in girder hierarchy and/or in Google Drive. The plugin provides a REST API to create, update, delete and retrieve forms and form entries. The plugin also provides a web UI component to fill and view form entries. Form schema is expected to have a single unique key field, which is used to identify the form entry (`uniqueField` key on a Form).
