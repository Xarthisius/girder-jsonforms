import View from 'girder/views/View';
import PaginateWidget from 'girder/views/widgets/PaginateWidget';
import router from 'girder/router';

import FormCollection from '../collections/FormCollection';
import template from '../templates/paginateFormsWidget.pug';
import '../stylesheets/paginateFormsWidget.styl';

var PaginateFormsWidget = View.extend({
    events: {
        'click .g-execute-form-link': function (event) {
            const formId = $(event.currentTarget).data('formId');
            const form = this.collection.get(formId);
            this.trigger('g:selected', {
                form: form
            });
        },
        'click button.g-form-create-button': function (event) {
            router.navigate('newform', {trigger: true});
        }
    },
    /**
     * @param {Function} [settings.formUrlFunc] A callback function, which if provided,
     *        will be called with a single ItemModel argument and should return a string
     *        URL to be used as the form link href.
     * @param {FormCollection} [settings.collection] An FormCollection for the widget
     *        to display. If no collection is provided, a new FormCollection is used.
     */
    initialize: function (settings) {
        this.formUrlFunc = settings.formUrlFunc || null;
        this.collection = settings.collection || new FormCollection();
        this.paginateWidget = new PaginateWidget({
            collection: this.collection,
            parentView: this.parentView
        });

        this.listenTo(this.collection, 'g:changed', () => {
            this.render();
        });

        if (settings.collection) {
            this.render();
        } else {
            this.collection.fetch(this.params);
        }
    },

    render: function () {
        this.$el.html(template({
            forms: this.collection.toArray(),
            formUrlFunc: this.formUrlFunc
        }));

        this.paginateWidget.setElement(this.$('.g-form-pagination')).render();
        return this;
    }
});

export default PaginateFormsWidget;
