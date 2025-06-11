import EntriesWidget from './widgets/EntriesWidget';
import ImportToFormDialog from './widgets/ImportToForm';
import FormModel from '../models/FormModel';
import FormTemplate from '../templates/formTemplate.pug';

import '../stylesheets/formView.styl';

const $ = girder.$;
const View = girder.views.View;
const AccessWidget = girder.views.widgets.AccessWidget;
const router = girder.router;
const { cancelRestRequests } = girder.rest;
const { renderMarkdown } = girder.misc;

var FormView = View.extend({
    events: {
        'click .g-new-entry': function (event) {
            router.navigate('form/' + this.model.get('_id') + '/entry', {
                trigger: true
            });
        },
        'click .g-edit-access': 'editAccess',
        'click .g-import-form': 'importForm'
    },
    initialize: function (settings) {
        cancelRestRequests('fetch');

        if (settings.form) {
            this.model = settings.form;
            this.render();
        } else if (settings.id) {
            this.model = new FormModel();
            this.model.set('_id', settings.id);

            this.model.on('g:fetched', function () {
                this.render();
            }, this).fetch();
        }
    },

    render: function () {
        this.$el.html(FormTemplate({
            form: this.model,
            renderMarkdown: renderMarkdown
        }));

        if (!this.entriesView) {
            this.entriesView = new EntriesWidget({
                el: this.$('.g-form-entries-container'),
                parentView: this,
                parentModel: this.model
            });
        } else {
            this.entriesView.setElement(this.$('.g-form-entries-container')).render();
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
    },

    importForm: function () {
        new ImportToFormDialog({
            el: $('#g-dialog-container'),
            model: this.model,
            modelType: 'form',
            parentView: this
        });
    },
});

export default FormView;
