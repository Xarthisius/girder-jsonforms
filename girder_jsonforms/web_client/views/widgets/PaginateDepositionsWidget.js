import DepositionCollection from '../../collections/DepositionCollection';
import template from '../../templates/widgets/paginateDepositionsWidget.pug';
import '../../stylesheets/paginateDepositionsWidget.styl';

const $ = girder.$;
const View = girder.views.View;
const PaginateWidget = girder.views.widgets.PaginateWidget;
const router = girder.router;

var PaginateDepositionsWidget = View.extend({
    events: {
        'click button.g-deposition-create-button': function (event) {
            router.navigate('newdeposition', {trigger: true});
        },
        'input .g-filter-field': 'search'
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
    },

    _sanitizeRegex: function (q) {
        return q.replaceAll(/[&/\\#,+()$~%.^'":*?<>{}]/g, '');
    },

    search: function () {
        // only search when the user stops typing
        if (this.pending) {
            clearTimeout(this.pending);
        }

        this.pending = setTimeout(() => {
            var q = this.$('.g-filter-field').val();
            if (!q) {
                this.collection.filterFunc = null;
            } else {
                let regex = this._sanitizeRegex(q);
                this.collection.filterFunc = function (model) {
                    var match = model.igsn.match(new RegExp(regex, 'i'));
                    return match;
                };
            }
            this.collection.on('g:changed', function () {
                this.render();
                this.$('.g-filter-field').val(q);
                this.$('.g-filter-field').focus();
            }, this).fetch({}, true);
        }, 500);
        return this;
    }
});

export default PaginateDepositionsWidget;
