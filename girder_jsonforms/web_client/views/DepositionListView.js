import DepositionModel from '../models/DepositionModel';
import DepositionCollection from '../collections/DepositionCollection';
import template from '../templates/depositionList.pug';
import '../stylesheets/depositionList.styl';

const View = girder.views.View;
const router = girder.router;
const { cancelRestRequests } = girder.rest;
const SearchFieldWidget = girder.views.widgets.SearchFieldWidget;
const PaginateWidget = girder.views.widgets.PaginateWidget;

var DepositionListView = View.extend({
    events: {
        'click button.g-deposition-create-button': function (event) {
            router.navigate('newdeposition', {trigger: true});
        },
        'input .g-filter-field': 'filter'
    },

    initialize: function () {
        cancelRestRequests('fetch');
        this.collection = new DepositionCollection();
        this.collection.on('g:changed', () => {
            this.render();
        }, this).fetch();

        this.paginateWidget = new PaginateWidget({
            parentView: this,
            collection: this.collection,
            depositionUrlFunc: (deposition) => { return `#deposition/${deposition.id}`; }
        });

        this.searchWidget = new SearchFieldWidget({
            placeholder: 'Search IGSNs...',
            types: ['deposition'],
            parentView: this,
            modes: ['igsnText'],
            getInfoCallback: this._getInfoCallback,
            noResultsPage: true
        }).on('g:resultClicked', this._gotoDeposition, this);
    },

    render: function () {
        this.$el.html(template({
            depositions: this.collection.toArray(),
            depositionUrlFunc: this.depositionUrlFunc
        }));

        this.paginateWidget.setElement(this.$('.g-deposition-pagination')).render();
        this.searchWidget.setElement(this.$('.g-deposition-search-container')).render();
        return this;
    },

    _gotoDeposition: function (result) {
        var deposition = new DepositionModel();
        deposition.set('_id', result.id).on('g:fetched', function () {
            router.navigate(`deposition/${deposition.get('_id')}`, {trigger: true});
        }, this).fetch();
    },
    _sanitizeRegex: function (q) {
        return q.replaceAll(/[&/\\#,+()$~%.^'":*?<>{}]/g, '');
    },

    _getInfoCallback: function (type, result) {
        // returns {icon: , text: } for every result
        if (result.metadata && result.metadata.attributes && result.metadata.attributes.alternateIdentifiers) {
            var alternateIdentifier = result.metadata.attributes.alternateIdentifiers.find((id) => id.type === 'local');
            if (alternateIdentifier) {
                return {
                    icon: 'barcode',
                    text: `${result.igsn} (${alternateIdentifier.value}) - ${result.metadata.titles[0].title}`
                };
            }
        }
        return {
            icon: 'barcode',
            text: `${result.igsn} - ${result.metadata.titles[0].title}`
        };
    },

    filter: function () {
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

export default DepositionListView;
