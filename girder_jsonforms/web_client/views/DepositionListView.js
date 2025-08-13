import DepositionModel from '../models/DepositionModel';
import DepositionCollection from '../collections/DepositionCollection';
import template from '../templates/depositionList.pug';
import '../stylesheets/depositionList.styl';

const View = girder.views.View;
const router = girder.router;
const { cancelRestRequests } = girder.rest;
const SearchFieldWidget = girder.views.widgets.SearchFieldWidget;
const SortCollectionWidget = girder.views.widgets.SortCollectionWidget;
const PaginateWidget = girder.views.widgets.PaginateWidget;

var DepositionListView = View.extend({
    events: {
        'click a.g-deposition-link': function (event) {
            var cid = $(event.currentTarget).attr('g-deposition-cid');
            router.navigate(`deposition/${this.collection.get(cid).id}`, {trigger: true});
        },
        'click button.g-deposition-create-button': function (event) {
            router.navigate('newdeposition', {trigger: true});
        },
        'click .btn-group[data-toggle="buttons-radio"] .btn': function (event) {
            $(event.currentTarget).addClass("active").siblings().removeClass("active");
            const accessLevel = $(event.currentTarget).attr('data-value');
            this.collection.level = accessLevel;
            this.collection.fetch({}, true);
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

        this.sortCollectionWidget = new SortCollectionWidget({
            collection: this.collection,
            parentView: this,
            fields: {
                igsn: 'IGSN',
                created: 'Created Date',
                updated: 'Updated Date',
                title: 'Title'
            },
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
        this.sortCollectionWidget.setElement(this.$('.g-deposition-sort')).render();
        this.searchWidget.setElement(this.$('.g-deposition-search-container')).render();
        // find the current access level button and set it to active
        this.$(`.btn-group[data-toggle="buttons-radio"] .btn[data-value="${this.collection.level}"]`)
          .addClass("active").siblings().removeClass("active");
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
        if (result.metadata && result.metadata.alternateIdentifiers) {
            var id = result.metadata.alternateIdentifiers.find(
              (id) => id.alternateIdentifierType.toLowerCase() === 'local'
            );
            if (id) {
                return {
                    icon: 'barcode',
                    text: `${result.igsn} (${id.alternateIdentifier}) - ${result.metadata.titles[0].title}`
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
