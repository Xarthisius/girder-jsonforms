const PaginateWidget = girder.views.widgets.PaginateWidget;

var NamedPaginateWidget = PaginateWidget.extend({
    events: {
        'click .g-page-next:not(.disabled)': function (event) {
            PaginateWidget.prototype.events['click .g-page-next:not(.disabled)'].call(this, event);
            window.sessionStorage.setItem(`${this.collection.resourceName}.offset`, this.collection.offset);
        },
        'click .g-page-prev:not(.disabled)': function (event) {
            PaginateWidget.prototype.events['click .g-page-prev:not(.disabled)'].call(this, event);
            window.sessionStorage.setItem(`${this.collection.resourceName}.offset`, this.collection.offset);
        },
    },
});

export default NamedPaginateWidget;
