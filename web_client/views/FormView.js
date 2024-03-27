import ItemCollection from 'girder/collections/ItemCollection';
import FolderCollection from 'girder/collections/FolderCollection';
import FolderModel from 'girder/models/FolderModel';
import BrowserWidget from 'girder/views/widgets/BrowserWidget';
import View from 'girder/views/View';
import router from 'girder/router';
import UploadWidget from 'girder/views/widgets/UploadWidget';
import { getCurrentUser } from 'girder/auth';
import events from 'girder/events';

import { JSONEditor } from '@json-editor/json-editor';
// import { Handlebars } from 'handlebars';

import FormEntryModel from '../models/FormEntryModel';
import template from '../templates/formView.pug';
import '../stylesheets/formView.styl';


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

var lastParent = null;

const FormView = View.extend({
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
        'click a.g-cancel-form': function () {
            this.tempFolder.destroy();
            router.navigate('forms', {trigger: true});
        },
        'submit #g-form': function (event) {
            event.preventDefault();
            var errors = this.form.validate();
            if (errors.length) {
                this.form.root.showValidationErrors(errors);
                return;
            }
            new FormEntryModel({
                formId: this.model.id,
                data: JSON.stringify(this.form.getValue()),
                sourceId: this.tempFolder.id,
                destinationId: this.destFolder.id,
            }).save().done(() => {
                router.navigate('forms', {trigger: true});
            });
        }
    },


    uploadDialog: function (jseditor, field, directory) {
        var onlyFiles = true;
        var onlyFolders = false;
        if (directory === true) {
            onlyFiles = false;
            onlyFolders = true;
        }
        new UploadWidget({
            el: $('#g-dialog-container'),
            parentView: this,
            title: 'Upload a file',
            multiFile: false,
            onlyFiles: onlyFiles,
            onlyFolders: onlyFolders,
            overrideStart: false,
            overrideStartText: 'Upload',
            overrideStartIcon: 'ok',
            overrideStartClass: 'btn-primary',
            parent: this.tempFolder,
            parentType: 'folder',
        }).on('g:uploadFinished', function (info) {
            if (info.files.length === 0) {
                return;
            } else if (info.files.length === 1) {
                var ids = info.files[0].id;
            } else {
                var ids = info.files.map(function (file) {
                    return file.id;
                }).join(',');
            }
            const value = jseditor.jsoneditor.getValue();
            value[field] = ids;
            jseditor.jsoneditor.setValue(value);
        }, this).render();
    },
    
    initialize: function (settings) {
        this.schema = JSON.parse(this.model.get('schema'));
        const destFolderId = this.model.get('folderId');
        this.destFolder = null;
        if (destFolderId) {
            var folder = new FolderModel({_id: destFolderId}).once('g:fetched', function(val) {
                this.destFolder = folder;
            }, this);
            $.when(folder.fetch()).done(() => {
                this.render();
            });
        }
        this.currentUser = getCurrentUser();
        this.dataSelector = new BrowserWidget({
            parentView: this,
            showItems: false,
            selectItem: false,
            root: lastParent || this.currentUser,
            titleText: this.initialValues ? this.initialValues.data : 'Select a folder for upload',
            helpText: 'Browse to a directory to select it, then click "Save"',
            showPreview: false,
            input: this.initialValues ? {default: this.initialValues.data} : false,
            validate: _.noop
        });
        const tempName = `_temp_${this.model.id}_${makeid(5)}`;
        this.tempFolder = new FolderModel({
            parentType: 'user',
            parentId: this.currentUser.id,
            name: tempName,
        });
        this.tempFolder.save().done(() => {
            this.tempFolder.addMetadata('formId', this.model.id);
        });

        const view = this;
        window.addEventListener('beforeunload', function (e) {
            view.tempFolder.destroy();
        });

        JSONEditor.defaults.callbacks.button = {
          "button1CB" : function(jseditor, element) {
            var value = jseditor.jsoneditor.getValue();
            const field = jseditor.options.button.uploadFor;
            value[field] = 'Waiting for a file to be uploaded';
            this.uploadDialog(jseditor, field, false);
            jseditor.jsoneditor.setValue(value);
          }.bind(this),
          "button2CB" : function(jseditor,e) {
            var value = jseditor.jsoneditor.getValue();
            const field = jseditor.options.button.uploadFor;
            value[field] = 'Waiting for a directory to be uploaded';
            this.uploadDialog(jseditor, field, true);
            jseditor.jsoneditor.setValue(value);
          }.bind(this)
        }
        this.listenTo(this.dataSelector, 'g:saved', function (val) {
            this.$('#g-folder-data-id').val(val.attributes.name);
            this.$('#g-folder-data-id').attr('objId', val.id);
            this.destFolder = val;
            this.render();            
        });

        this.form = null;
    },

    render: function () {
        this.$el.html(template({
            form: this.model,
            destFolder: this.destFolder,
        }));
        const formContainer = this.$('.g-form-container');
        this.form = new JSONEditor(formContainer[0], {
            schema: this.schema,
            theme: 'bootstrap3',
            //template: 'handlebars',
            disable_edit_json: true,
            disable_properties: true,
            disable_collapse: true,
            show_errors: 'interactive',
        });
        if (this.model.get('folderId')) {
            this.$('#g-folder-data-id').attr('objId', this.model.get('folderId'));
            this.$('#g-folder-data-id').val(this.model.get('folderId'));
        }
        const view = this;
        $.when(this.form.promise).done(() => {
          if (view.destFolder === null) {
              view.form.disable();
          } else {
              view.form.enable();
          }
        })
        return this;
    }
});

export default FormView;
