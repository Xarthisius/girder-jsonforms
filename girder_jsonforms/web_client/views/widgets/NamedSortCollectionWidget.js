const $ = girder.$;
const { wrap } = girder.utilities.PluginUtils;
const SortCollectionWidget = girder.views.widgets.SortCollectionWidget;

var NamedSortCollectionWidget = SortCollectionWidget.extend({
    events: {
        'click a.g-collection-sort-link': function (event) {
            SortCollectionWidget.prototype.events['click a.g-collection-sort-link'].call(this, event);
            window.sessionStorage.setItem(`${this.collection.resourceName}.sortField`, this.collection.sortField);
        },
        'click a.g-sort-order-button': function (event) {
            SortCollectionWidget.prototype.events['click a.g-sort-order-button'].call(this, event);
            window.sessionStorage.setItem(`${this.collection.resourceName}.sortDir`, this.collection.sortDir);
        }
    },
});

export default NamedSortCollectionWidget;
