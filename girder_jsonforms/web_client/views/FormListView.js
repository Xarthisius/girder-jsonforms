import PaginateFormsWidget from './PaginateFormsWidget';

const View = girder.views.View;

var FormListView = View.extend({
    initialize: function () {
        this.paginateFormsWidget = new PaginateFormsWidget({
            el: this.$el,
            parentView: this,
            formUrlFunc: (form) => { return `#form/${form.id}`; }
        });
    }
});

export default FormListView;
