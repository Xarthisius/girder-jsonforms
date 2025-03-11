import $ from 'jquery';
import DepositionCollection from '../../collections/DepositionCollection';
import template from '../../templates/widgets/paginateDepositionsWidget.pug';
import '../../stylesheets/paginateDepositionsWidget.styl';

const View = girder.views.View;
const PaginateWidget = girder.views.widgets.PaginateWidget;
const router = girder.router;

var PaginateDepositionsWidget = View.extend({
    events: {
        'click button.g-deposition-create-button': function (event) {
            router.navigate('newdeposition', {trigger: true});
        }
    },

    initialize: function (settings) {
        this.depositionUrlFunc = settings.depositionUrlFunc || null;
        this.collection = settings.collection || new DepositionCollection();
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
            depositions: this.collection.toArray(),
            depositionUrlFunc: this.depositionUrlFunc
        }));

        this.paginateWidget.setElement(this.$('.g-deposition-pagination')).render();
        return this;
    }
});

export default PaginateDepositionsWidget;
