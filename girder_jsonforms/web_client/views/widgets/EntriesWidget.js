// Description: This file contains the EntriesWidget class.
// This class is responsible for rendering the entries widget.
import FormEntryCollection from '../../collections/FormEntryCollection';
import EntriesWidgetTemplate from '../../templates/entriesWidgetTemplate.pug';

import '../../stylesheets/entriesWidget.styl';

const $ = girder.$; // Import jQuery from girder
const View = girder.views.View;
const router = girder.router;
const PaginateWidget = girder.views.widgets.PaginateWidget;
const { formatDate, DATE_DAY } = girder.misc;

var EntriesWidget = View.extend({
    events: {
        'click a.g-edit-entry': function (event) {
            const entryId = this.collection.get($(event.currentTarget).attr('cid')).id;
            router.navigate('form/' + this.parentModel.id + '/entry?entryId=' + entryId, {trigger: true});
        }
    },
    initialize: function (settings) {
        this.parentView = settings.parentView;
        this.parentModel = settings.parentModel;
        this.collection = new FormEntryCollection();
        this.collection.params = {formId: this.parentModel.id};
        this.collection.sortField = `data.${this.parentModel.get('uniqueField', 'sampleId')}`;
        this.collection.on('g:changed', function () {
            this.render();
        }, this).fetch({}, true);
        this.paginateWidget = new PaginateWidget({
            collection: this.collection,
            parentView: this
        });
    },

    render: function () {
        const uniqueField = this.parentModel.get('uniqueField', 'sampleId');
        this.$el.html(EntriesWidgetTemplate({
            entries: this.collection.toArray(),
            parentModel: this.parentModel,
            uniqueField: uniqueField,
            formatDate: formatDate,
            DATE_DAY: DATE_DAY
        }));

        if (this.collection.isEmpty()) {
            this.$('.g-main-content,.g-entries-pagination').hide();
            this.$('.g-no-entries').show();
            return;
        } else {
            this.$('.g-main-content,.g-entries-pagination').show();
            this.$('.g-no-entries').hide();
        }
        this.paginateWidget.setElement(this.$('.g-entries-pagination')).render();
        return this;
    }
});

export default EntriesWidget;
