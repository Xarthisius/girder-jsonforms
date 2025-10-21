import SortCollectionWidgetTemplate from '@girder/core/templates/widgets/sortCollectionWidget.pug';

const $ = girder.$;
const { SORT_ASC, SORT_DESC } = girder.constants;
const { cancelRestRequests } = girder.rest;
const View = girder.views.View;

// import 'bootstrap/js/dropdown';


var NamedSortCollectionWidget = View.extend({
    events: {
        'click a.g-collection-sort-link': function (event) {
            cancelRestRequests('fetch');
            var sortField = $(event.currentTarget).attr('g-sort');
            this.collections.forEach(function (collection) {
                collection.sortField = sortField;
                collection.fetch({}, true);
                window.sessionStorage.setItem(`${collection.resourceName}.sortField`, sortField);
            });
        },
        'click a.g-sort-order-button': function (event) {
            cancelRestRequests('fetch');
            this.collections.forEach((collection) => {
                if (collection.sortDir === SORT_ASC) {
                    collection.sortDir = SORT_DESC;
                    this.$('.g-up').removeClass('hide');
                    this.$('.g-down').addClass('hide');
                } else {
                    collection.sortDir = SORT_ASC;
                    this.$('.g-down').removeClass('hide');
                    this.$('.g-up').addClass('hide');
                }
                collection.fetch({}, true);
                window.sessionStorage.setItem(`${collection.resourceName}.sortDir`, collection.sortDir);
            });
        }
    },
    initialize: function (settings) {
        this.collections = settings.collections;
        this.fields = settings.fields;
    },

    render: function () {
        const collection = this.collections[0];
        this.$el.html(SortCollectionWidgetTemplate({
            collection: this.collections[0],
            fields: this.fields
        }));
        this.collections.forEach((collection) => {
            const sortField = window.sessionStorage.getItem(`${collection.resourceName}.sortField`);
            var fetchNeeded = false;
            if (sortField && sortField !== collection.sortField) {
                collection.sortField = sortField;
                fetchNeeded = true;
            }
            const sortDir = window.sessionStorage.getItem(`${collection.resourceName}.sortDir`);
            if (sortDir && parseInt(sortDir, 10) !== collection.sortDir) {
                collection.sortDir = sortDir;
                fetchNeeded = true;
            }
            if (fetchNeeded) {
                collection.fetch({}, true);
            }
        });
        if (this.collections[0].sortDir === SORT_ASC) {
            this.$('.g-up').addClass('hide');
        } else {
            this.$('.g-down').addClass('hide');
        }
        return this;
    }
});

export default NamedSortCollectionWidget;
