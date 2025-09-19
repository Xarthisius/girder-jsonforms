import DepositionCollection from '../../collections/DepositionCollection';
import DepositionListWidgetTemplate from '../../templates/depositionListWidget.pug';
import '../../stylesheets/depositionListWidget.styl';
import DepositionListTemplate from '../../templates/depositionCheckboxList.pug';
import LinkEntryToDepositionWidget from './LinkEntryToDepositionWidget';

const PaginateWidget = girder.views.widgets.PaginateWidget;
const View = girder.views.View;
const router = girder.router;
const events = girder.events;
const { restRequest } = girder.rest;
const { defineFlags, formatDate, DATE_SECOND, _whenAll } = girder.misc;
const eventStream = girder.utilities.eventStream;
const { getCurrentUser } = girder.auth;
const { SORT_ASC, SORT_DESC } = girder.constants;

const { _, $ } = girder;

var DepositionListWidget = View.extend({
    events: {
        'click .g-deposition-trigger-link': function (e) {
            var cid = $(e.currentTarget).attr('cid');
            this.trigger('g:depositionClicked', this.collection.get(cid));
        },
        'click button.g-deposition-create-button': function (e) {
            router.navigate('newdeposition', {trigger: true});
        },
        'change select.g-page-size': function (e) {
            this.collection.pageLimit = parseInt($(e.currentTarget).val());
            window.sessionStorage.setItem(`${this.collection.resourceName}.pageLimit`, this.collection.pageLimit);
            this.collection.fetch({}, true);
        },
        'click .btn-group[data-toggle="buttons-radio"] .btn': function (event) {
            $(event.currentTarget).addClass("active").siblings().removeClass("active");
            const accessLevel = $(event.currentTarget).attr('data-value');
            this.collection.level = accessLevel;
            window.sessionStorage.setItem(`${this.collection.resourceName}.level`, this.collection.level);
            this.collection.fetch({}, true);
        },
        'change input.g-deposition-checkbox': function (e) {
            var depositionId = $(e.currentTarget).closest('tr').attr('g-deposition-id');
            if ($(e.currentTarget).is(':checked')) {
                this.depositionCheckedStates[depositionId] = true;
            } else {
                delete this.depositionCheckedStates[depositionId];
            }
            this._renderData();
        },
        'click input.g-deposition-checkbox-all': function (e) {
            e.stopPropagation();
        },
        'click .check-menu-dropdown a.g-depositions-list-link': function (e) {
            var widget = new LinkEntryToDepositionWidget({
                el: $('#g-dialog-container'),
                parentView: this,
                depositionIds: Object.keys(this.depositionCheckedStates),
            }).on('g:hidden', function () {
                widget.destroy();
            });
        },
        'change input.g-deposition-checkbox-all': function (e) {
            if ($(e.currentTarget).is(':checked')) {
                this.collection.forEach((deposition) => { this.depositionCheckedStates[deposition.id] = true; });
            } else {
                this.depositionCheckedStates = {};
            }
            this._renderData();
        },
        'input .g-deposition-regex': 'filterDepositions',
        'click a.g-column-sortable': function (e) {
            e.preventDefault();
            var field = e.currentTarget.attributes["data-sort-by"].value
            if (this.collection.sortField === field) {
                this.collection.sortDir = this.collection.sortDir === SORT_DESC ? SORT_ASC : SORT_DESC;
            } else {
                this.collection.sortField = field;
                this.collection.sortDir = SORT_DESC;
            }
            window.sessionStorage.setItem(`${this.collection.resourceName}.sortField`, this.collection.sortField);
            window.sessionStorage.setItem(`${this.collection.resourceName}.sortDir`, this.collection.sortDir);
            this.collection.fetch({}, true);
        }
    },

    setSortIcons: function() {
        this.$('a.g-column-sortable i').removeClass("icon-sort-up icon-sort-down").addClass("icon-sort");
        if (this.collection.sortDir === SORT_DESC) {
            this.$(`a[data-sort-by="${this.collection.sortField}"]`).find('i').removeClass("icon-sort").addClass("icon-sort-down");
        } else {
            this.$(`a[data-sort-by="${this.collection.sortField}"]`).find('i').removeClass("icon-sort").addClass("icon-sort-up");
        }
    },

    initialize: function (settings) {
        var currentUser = getCurrentUser();
        this.columns = settings.columns || this.columnEnum.COLUMN_ALL;
        this.userId = (settings.filter && !settings.allDepositionsMode) ? (settings.filter.userId ? settings.filter.userId : currentUser.id) : null;
        this.showPageSizeSelector = settings.showPageSizeSelector;
        this.showFilters = settings.showFilters;
        this.depositionCheckedStates = {};
        this.depositionHighlightStates = {};

        this.pageSizes = [25, 50, 100, 250, 500, 1000];
        this.regexFilterRequest = null;

        this.collection = new DepositionCollection();
        this.collection.updateFromSession();
        console.log(this.collection);
        //this.collection.sortField = settings.sortField || 'created';
        //this.collection.sortDir = settings.sortDir || SORT_DESC;
        //this.collection.pageLimit = settings.pageLimit || this.collection.pageLimit;

        this.listenTo(this.collection, 'update reset', this._onDataChange);

        this._fetchWithFilter();

        this.currentView = settings.view ? settings.view : 'list';

        this.showHeader = _.has(settings, 'showHeader') ? settings.showHeader : true;
        this.showPaging = _.has(settings, 'showPaging') ? settings.showPaging : true;
        this.linkToDeposition = _.has(settings, 'linkToDeposition') ? settings.linkToDeposition : true;
        this.triggerDepositionClick = _.has(settings, 'triggerDepositionClick') ? settings.triggerDepositionClick : false;

        this.paginateWidget = new PaginateWidget({
            collection: this.collection,
            parentView: this
        });

        this.listenTo(eventStream, 'g:eventStream.start', this._fetchWithFilter);
        const statusTextToStatusCode = {};
        this.render();
    },

    columnEnum: defineFlags([
        'COLUMN_ACTION_CHECKBOX',
        'COLUMN_IGSN',
        'COLUMN_TITLE',
        'COLUMN_LOCAL_ID',
        'COLUMN_CREATED',
        'COLUMN_UPDATED',
        'COLUMN_STATUS'
    ], 'COLUMN_ALL'),

    render: function () {
        this.$el.html(DepositionListWidgetTemplate({
            currentView: this.currentView,
            pageSize: this.collection.pageLimit,
            pageSizes: this.pageSizes,
            showFilters: this.showFilters,
            showPageSizeSelector: this.showPageSizeSelector
        }));
        this._renderData();

        return this;
    },

    _onDataChange: function () {
        this.depositionCheckedStates = {};
        this._renderData();
    },

    _renderData: function () {
        if (!this.$('.g-main-content').length) {
            // Do nothing until render has been called
            return;
        }

        if (this.collection.isEmpty()) {
            this.$('.g-main-content,.g-deposition-pagination').hide();
            this.$('.g-no-deposition-record').show();
            return;
        } else {
            this.$('.g-main-content,.g-deposition-pagination').show();
            this.$('.g-no-deposition-record').hide();
        }

        if (this.currentView === 'list') {
            this.$('.g-main-content').html(DepositionListTemplate({
                depositions: this.collection.toArray(),
                showHeader: this.showHeader,
                columns: this.columns,
                columnEnum: this.columnEnum,
                linkToDeposition: this.linkToDeposition,
                triggerDepositionClick: this.triggerDepositionClick,
                formatDate: formatDate,
                DATE_SECOND: DATE_SECOND,
                depositionCheckedStates: this.depositionCheckedStates,
                depositionHighlightStates: this.depositionHighlightStates,
                anyDepositionChecked: _.find(this.depositionCheckedStates, (status) => status === true),
                allDepositionChecked: this.collection.every((deposition) => this.depositionCheckedStates[deposition.id]),
            }));
        }
        this.setSortIcons();
        // find the current access level button and set it to active
        this.$(`.btn-group[data-toggle="buttons-radio"] .btn[data-value="${this.collection.level}"]`)
          .addClass("active").siblings().removeClass("active");

        if (this.showPaging) {
            this.paginateWidget.setElement(this.$('.g-deposition-pagination')).render();
        }
    },

    filterDepositions: function () {
        if (this.regexFilterRequest) {
            clearTimeout(this.regexFilterRequest);
        }

        this.regexFilterRequest = setTimeout(() => {
            const regex = this.$('.g-deposition-regex-field').val();
            this._fetchWithFilter(regex);
            this.regexFilterRequest = null;
        }, 500);
    },

    _fetchWithFilter(regex) {
        var filter = {};
        if (this.userId) {
            filter.userId = this.userId;
        }
        if (regex) {
            filter.q = regex;
        } else {
            filter.q = null;
        }
        
        this.collection.params = filter;

        return this.collection.fetch({}, true);
    }
});

export default DepositionListWidget;
