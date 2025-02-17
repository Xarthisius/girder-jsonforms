import PaginateDepositionsWidget from './widgets/PaginateDepositionsWidget';

const View = girder.views.View;

var DepositionListView = View.extend({
    initialize: function () {
        this.paginateDepositionsWidget = new PaginateDepositionsWidget({
            el: this.$el,
            parentView: this,
            depositionUrlFunc: (deposition) => { return `#deposition/${deposition.id}`; }
        });
    }
});

export default DepositionListView;
