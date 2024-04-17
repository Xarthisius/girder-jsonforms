import View from 'girder/views/View';

import PaginateFormsWidget from './PaginateFormsWidget';

var FormListView = View.extend({
    initialize: function () {
        this.paginateFormsWidget = new PaginateFormsWidget({
            el: this.$el,
            parentView: this,
            formUrlFunc: (form) => { return `#form/${form.id}/entry`; }
        });
    }
});

export default FormListView;
