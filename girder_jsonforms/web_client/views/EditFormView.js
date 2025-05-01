const $ = girder.$;
const _ = girder._;
const AccessWidget = girder.views.widgets.AccessWidget;
const FolderModel = girder.models.FolderModel;
const BrowserWidget = girder.views.widgets.BrowserWidget;
const View = girder.views.View;
const router = girder.router;
const UploadWidget = girder.views.widgets.UploadWidget;
const { getCurrentUser } = girder.auth;
const { AccessType } = girder.constants;
const { restRequest } = girder.rest;

import '../stylesheets/editFormView.styl';

import flatpickr from 'flatpickr'; // eslint-disable-line no-unused-vars
import Handlebars from 'handlebars';
import '@json-editor/json-editor';
import Autocomplete from '@trevoreyre/autocomplete-js';

import template from '../templates/editFormView.pug';
import FormEntryModel from '../models/FormEntryModel';

import 'flatpickr/dist/flatpickr.min.css';
import '@trevoreyre/autocomplete-js/dist/style.css';

function makeid(length) {
    let result = '';
    const characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    const charactersLength = characters.length;
    let counter = 0;
    while (counter < length) {
        result += characters.charAt(Math.floor(Math.random() * charactersLength));
        counter += 1;
    }
    return result;
}

// Function to access or create nested objects based on keys
function accessOrCreate(obj, keys) {
    let current = obj;
    for (let i = 0; i < keys.length - 1; i++) {
        if (!current[keys[i]]) {
            current[keys[i]] = {};
        }
        current = current[keys[i]];
    }
    return current;
}

function setField(jseditor, field, value) {
    const formValue = jseditor.jsoneditor.getValue();
    let keys = field.split('.');
    keys.shift(); // Remove the first string 'root'
    let objToUpdate = accessOrCreate(formValue, keys);
    objToUpdate[keys[keys.length - 1]] = value;
    jseditor.jsoneditor.setValue(formValue);
}

var lastParent = null;

const EditFormView = View.extend({
    events: {
        'click .g-reload-form': function (event) {
            this.model.fetch().done(() => { this.render(); });
        },
        'click .g-edit-form': function (event) {
            router.navigate('form/' + this.model.get('_id') + '/edit', {
                params: this._formSpec,
                trigger: true
            });
        },
        'click .g-open-browser': function () {
            this.dataSelector.setElement($('#g-dialog-container')).render();
        },
        'click .g-edit-access': 'editAccess',
        'click a.g-cancel-form': function () {
            this.tempFolder.destroy().done(() => {
              router.navigate('forms', {trigger: true});
            });
        },
        'submit #g-form': function (event) {
            event.preventDefault();
            this.$('.g-validation-failed-message').empty();
            var errors = this.form.validate();
            if (errors.length) {
                this.form.root.showValidationErrors(errors);
                this.$('.g-validation-failed-message').html('<ul>' + errors.map(function (err) {
                    return `<li> Path ${err.path}: ${err.message} (${err.property})</li>`;
                }).join('') + '</ul>');
                return;
            }
            var params = {
                formId: this.model.id,
                data: JSON.stringify(this.form.getValue()),
            }
            if (this.tempFolder) {
                params.sourceId = this.tempFolder.id;
            }
            if (this.destFolder) {
                params.destinationId = this.destFolder.id;
            }
            new FormEntryModel(params).save().done(() => {
                router.navigate(`form/${params.formId}`, {trigger: true});
            });
            /* if (this.initialValues) {
                this.initialValues.set('data', this.form.getValue());
                this.initialValues.save().done(() => {
                    router.navigate('forms', {trigger: true});
                });
            } else {
                new FormEntryModel({
                    formId: this.model.id,
                    data: JSON.stringify(this.form.getValue()),
                    sourceId: this.tempFolder.id,
                    destinationId: this.destFolder.id
                }).save().done(() => {
                    router.navigate('forms', {trigger: true});
                });
            } */
        }
    },

    initialize: function (settings) {
        window.Handlebars = Handlebars; // Otherwise the helper is not available in the template
        window.Autocomplete = Autocomplete; // Otherwise the helper is not available in the template
        this.otherEntries = {};
        const view = this;
        Handlebars.registerHelper('entryField', function (entryId, field) {
            const dependencies = view.model.get('dependencies');
            console.log(dependencies);
            try {
                return dependencies[entryId][`data.${field}`];
            } catch (e) {
                console.log('Error getting dependencies');
                return undefined;
            }
        });
        this.schema = this.model.get('schema');
        if (this.model.get('jsHelpers')) {
            try {
                eval(this.model.get('jsHelpers'));
                console.log('JS helpers loaded');
            } catch (e) {
                console.log('Error loading JS helpers');
            }
        }
        const destFolderId = this.model.get('folderId');
        this.serialize = this.model.get('serialize');
        this.destFolder = null;
        if (destFolderId) {
            var folder = new FolderModel({_id: destFolderId}).once('g:fetched', function (val) {
                this.destFolder = folder;
            }, this);
            $.when(folder.fetch()).done(() => {
                this._fetchFolderToRoot(this.destFolder);
            });
        }
        this.currentUser = getCurrentUser();
        this.dataSelector = new BrowserWidget({
            parentView: this,
            showItems: false,
            selectItem: false,
            root: lastParent || this.currentUser,
            titleText: 'Select a folder for upload',
            helpText: 'Browse to a directory to select it, then click "Save"',
            showPreview: false,
            input: false,
            validate: _.noop
        });
        const tempName = `_temp_${this.model.id}_${makeid(5)}`;
        this.tempFolder = new FolderModel({
            parentType: 'user',
            parentId: this.currentUser.id,
            name: tempName
        });
        this.tempFolder.save().done(() => {
            this.tempFolder.addMetadata('formId', this.model.id);
        });

        window.addEventListener('beforeunload', function (e) {
            view.tempFolder.destroy();
        });

        JSONEditor.defaults.callbacks.button = {
            'button1CB': function (jseditor, element) {
                const field = jseditor.options.path.replace(/\.button(?!.*\.button)/, '.file');
                //setField(jseditor, field, 'Waiting for a file to be uploaded');
                this.uploadDialog(jseditor, field, false, true);
            }.bind(this),
            'button2CB': function (jseditor, e) {
                const field = jseditor.options.path.replace(/\.button(?!.*\.button)/, '.file');
                //setField(jseditor, field, 'Waiting for a directory to be uploaded');
                this.uploadDialog(jseditor, field, true);
            }.bind(this),
            'buttonSample': function (jseditor, e) {
                const field = jseditor.options.path.replace(/\.button(?!.*\.button)/, '.file');
                //setField(jseditor, field, 'Waiting for a file to be uploaded');
                this.uploadDialog(jseditor, field, false, true);
            }
        };
        this.listenTo(this.dataSelector, 'g:saved', function (val) {
            this.$('#g-folder-data-id').val(val.attributes.name);
            this.$('#g-folder-data-id').attr('objId', val.id);
            // this.destFolder = val;
            this._fetchFolderToRoot(val);
        });

        this.initialValues = settings.initialValues;
        this.form = null;
    },

    _fetchFolderToRoot: function (folder) {
        folder.getRootPath().done((path) => {
            var rootType = path[0].type;
            if (rootType === 'user') {
                rootType = `/user/${path[0].object.login}/${path.slice(1).map((obj) => obj.object.name).join('/')}`.replace(/\/$/g, '');
            } else {
                rootType = `/${rootType}/${path.map((obj) => obj.object.name).join('/')}`;
            }
            this.destFolderPath = `${rootType}/${folder.name()}`;
            this.destFolder = folder;
            this.render();
        });
    },

    uploadDialog: function (jseditor, field, directory, multiFile = false) {
        var onlyFiles = true;
        var onlyFolders = false;
        if (directory === true) {
            onlyFiles = false;
            onlyFolders = true;
        }
        const value = jseditor.parent.getValue();
        const uniqueField = this.model.get('uniqueField', 'sampleId');
        var reference = {
            [uniqueField]: value[uniqueField],
            annotate: true,
            formField: field
        };
        if (value.targetPath) {
            reference.targetPath = value.targetPath;
        }
        if (this.model.get('gdriveFolderId')) {
            reference.gdriveFolderId = this.model.get('gdriveFolderId');
        }

        new UploadWidget({
            el: $('#g-dialog-container'),
            parentView: this,
            title: 'Upload a file',
            multiFile: multiFile,
            onlyFiles: onlyFiles,
            onlyFolders: onlyFolders,
            overrideStart: false,
            overrideStartText: 'Upload',
            overrideStartIcon: 'ok',
            overrideStartClass: 'btn-primary',
            parent: this.tempFolder,
            parentType: 'folder',
            otherParams: {
                reference: JSON.stringify(reference)
            }
        }).on('g:uploadFinished', function (info) {
            var ids = jseditor.jsoneditor.getEditor(field).getValue();
            if (info.files.length === 0) {
                return;
            } else if (info.files.length === 1) {
                if (ids) {
                    ids = `${ids},${info.files[0].id}`;
                } else {
                    ids = info.files[0].id;
                }
            } else {
                const newids = Array.from(info.files).map(function (file) {
                    return file.id;
                }).join(',');
                if (ids) {
                    ids = `${ids},${newids}`;
                } else {
                    ids = newids;
                }
            }
            setField(jseditor, field, ids);
        }, this).render();
    },

    render: function () {
        this.$el.html(template({
            form: this.model,
            level: this.model.getAccessLevel(),
            AccessType: AccessType,
            destFolder: this.destFolder,
            destFolderPath: this.destFolderPath,
            serialize: this.serialize,
        }));
        const formContainer = this.$('.g-form-container');
        if (this.schema) {
            this.form = new JSONEditor(formContainer[0], {
                schema: this.schema,
                theme: 'bootstrap3',
                template: 'handlebars',
                disable_edit_json: true,
                disable_properties: true,
                disable_collapse: true,
                show_errors: 'always'
            });
            if (this.model.get('folderId')) {
                this.$('#g-folder-data-id').attr('objId', this.model.get('folderId'));
                this.$('#g-folder-data-id').val(this.model.get('folderId'));
            }
            const view = this;
            $.when(this.form.promise).done(() => {
                if (view.initialValues) {
                    view.form.setValue(view.initialValues.get('data'));
                }
                if (view.destFolder === null && view.serialize) {
                    view.form.disable();
                } else {
                    view.form.enable();
                }
            });
        }
        return this;
    },

    editAccess: function () {
        new AccessWidget({
            el: $('#g-dialog-container'),
            model: this.model,
            modelType: 'form',
            parentView: this
        }).on('g:accessListSaved', function (params) {
            console.log(params);
            console.log('Should change access to folderId');
        }, this).render();
    }

});

export default EditFormView;
