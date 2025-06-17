import DepositionModel from '../models/DepositionModel';
import DepositionTemplate from '../templates/depositionView.pug'; 

import '../stylesheets/depositionView.styl';

import QRCode from 'qrcode';

const _ = girder._;
const { AccessType } = girder.constants;
const { renderMarkdown } = girder.misc;
const { getApiRoot } = girder.rest;
const AccessWidget = girder.views.widgets.AccessWidget;
const View = girder.views.View;
const { restRequest } = girder.rest;
const SearchPaginateWidget = girder.views.widgets.SearchPaginateWidget;

import SearchResultsTypeTemplate from '@girder/core/templates/body/searchResultsType.pug';


const QRparams = {
  'errorCorrectionLevel': 'H',
  'version': 6,
  'mode': 'alphanumeric'
};

var DepositionView = View.extend({
    events: {
        'click .g-edit-access': 'editAccess',
        'click .g-edit-deposition': function () {
            girder.router.navigate(`deposition/${this.model.get('_id')}/edit`, {trigger: true});
        },
        'click .g-back': function () {
            girder.router.navigate('depositions', {trigger: true});
        }
    },

    initialize: function (settings) {
        this._query = this.model.get('igsn');
        this._mode = 'igsn';
        this._searchRequest = restRequest({
            url: 'resource/search',
            data: {
                q: this._query,
                mode: this._mode,
                types: JSON.stringify(['folder', 'item']),
                limit: 10,
            }
        });
    },

    render: function () {
        const relatedIdentifiers = this.model.get("metadata").relatedIdentifiers;
        this.transformRelatedIdentifiers(relatedIdentifiers);
        this.$el.html(DepositionTemplate({
            deposition: this.model,
            metadata: this.model.get("metadata"),
            renderMarkdown: renderMarkdown,
            trackerUrl: `#sample/${this.model.get('sampleId')}`,
            AccessType: AccessType,
            relatedIdentifiers: relatedIdentifiers,
            level: this.model.getAccessLevel()
        }));
        this._subviews = {};
        this._searchRequest.done((results) => {
            this.$('.g-search-pending').hide();

            const resultTypes =  _.keys(results);
            const orderedTypes = ["folder", "item"];
            _.each(orderedTypes, (type) => {
                if (results[type].length) {
                    this._subviews[type] = new SearchResultsTypeView({

                        parentView: this,
                        query: this._query,
                        mode: this._mode,
                        type: type,
                        limit: this.pageLimit,
                        initResults: results[type],
                        sizeOneElement: this._sizeOneElement
                    })
                        .render();
                    this._subviews[type].$el
                        .appendTo(this.$('.g-search-results-container'));
                }
            });

            if (_.isEmpty(this._subviews)) {
                this.$('.g-search-no-results').show();
            }
        });
        if (this.model.get("sampleId")) {
            const addEventUrl = `${window.location.origin}/#sample/${this.model.get('sampleId')}/add`;
            QRCode.toCanvas(this.$('#g-qr-code')[0], addEventUrl.toUpperCase(), QRparams);
        }
        return this;
    },

    transformRelatedIdentifiers: function (relatedIdentifiers) {
        if (!relatedIdentifiers || !Array.isArray(relatedIdentifiers)) {
           return; // nothing to transform
        }
        const apiRoot = getApiRoot();
        const origin = window.location.origin;
        const entryRegex = new RegExp(`${apiRoot}/entry/(\\w+)`);
        const formRegex = new RegExp(`${apiRoot}/form/(\\w+)/schema`);
        const entries = [];
        const forms = [];

        for (let i = 0; i < relatedIdentifiers.length; i++) {
            const identifier = relatedIdentifiers[i];
            if (identifier.relationType === "HasMetadata") {
                const entryMatch = identifier.relatedIdentifier.match(entryRegex);
                const formMatch = identifier.relatedMetadataScheme.match(formRegex);
                if (entryMatch && formMatch) {
                    const entryId = entryMatch[1];
                    const formId = formMatch[1];
                    relatedIdentifiers[i].relatedIdentifier = `#form/${formId}/entry?entryId=${entryId}`;
                    relatedIdentifiers[i].entryId = entryId;
                    relatedIdentifiers[i].formId = formId;
                    relatedIdentifiers[i].relatedMetadataScheme = `#form/${formId}`;
                    relatedIdentifiers[i].relatedMetadataSchemeTitle = `Form (id: ${formId})`;
                    relatedIdentifiers[i].relatedIdentifierTitle = `Entry (id: ${entryId})`;
                    forms.push(formId);
                    entries.push(entryId);
                }
            } else if (identifier.relationType === "IsPartOf" && identifier.relatedIdentifierType === "IGSN") {
                relatedIdentifiers[i].relatedIdentifierTitle = identifier.relatedIdentifier;
                relatedIdentifiers[i].relatedIdentifier = `#igsn/${identifier.relatedIdentifier}`;
            }
        }
        restRequest({
            url: 'resource',
            method: 'GET',
            data: {
                resources: JSON.stringify({"jsonforms.form": forms, "jsonforms.entry": entries}),
                filters: JSON.stringify({"jsonforms.form": {"name": 1}, "jsonforms.entry": {"uniqueId": 1}})
            }
        }).done((response) => {
            // response is a dictionary with keys 'form' and 'entry' poiniting to dictionaries
            // with keys being the formId or entryId and values being the form or entry
            // convert it to map
            const formMap = {};
            const entryMap = {};
            response["jsonforms.form"].forEach((form) => {
                formMap[form._id] = form;
            });
            response["jsonforms.entry"].forEach((entry) => {
                entryMap[entry._id] = entry;
            });

            // Find all html elements with entryId and formId
            // and set the text to the name of the entry or form
            $('.g-deposition-info-line').each((index, element) => {
                if (element.attributes.entryId) {
                    const entryId = element.attributes.entryId.value;
                    const entry = entryMap[entryId];
                    if (entry) {
                        $(element).find('span.g-info-type').text(`Entry for ${entry.uniqueId}`);
                    }
                }
                if (element.attributes.formId) {
                    const formId = element.attributes.formId.value;
                    const form = formMap[formId];
                    if (form) {
                        $(element).find('span.g-info-type').text(`Form "${form.name}"`);
                    }
                }
            });
        });
    },

    editAccess: function () {
        new AccessWidget({
            el: $('#g-dialog-container'),
            model: this.model,
            modelType: 'deposition',
            parentView: this
        }).render();
    }
});

var SearchResultsTypeView = View.extend({
    className: 'g-search-results-type-container',

    initialize: function (settings) {
        this._query = settings.query;
        this._mode = settings.mode;
        this._type = settings.type;
        this._initResults = settings.initResults || [];
        this._pageLimit = settings.limit || 10;
        this._sizeOneElement = settings.sizeOneElement || 30;

        this._paginateWidget = new SearchPaginateWidget({
            parentView: this,
            type: this._type,
            query: this._query,
            mode: this._mode,
            limit: this._pageLimit
        })
            .on('g:changed', () => {
                this._results = this._paginateWidget.results;
                this.render();
            });

        this._results = this._initResults;
    },

    _getTypeName: function (type) {
        const names = {
            collection: 'Collections',
            group: 'Groups',
            user: 'Users',
            folder: 'Folders',
            item: 'Items'
        };
        return names[type] || type;
    },

    _getTypeIcon: function (type) {
        const icons = {
            user: 'user',
            group: 'users',
            collection: 'sitemap',
            folder: 'folder',
            item: 'doc-text-inv'
        };
        return icons[type] || 'icon-attention-alt';
    },

    render: function () {
        this.$el.html(SearchResultsTypeTemplate({
            results: this._results,
            collectionName: this._getTypeName(this._type),
            type: this._type,
            icon: this._getTypeIcon(this._type)
        }));

        /* This size of the results list cannot be known until after the fetch completes. And we don't want to set
        the 'min-height' to the max results size, because we'd frequently have lots of whitespace for short result
        lists. Do not try to move that set in stylesheet.
        */
        this.$('.g-search-results-type').css('min-height', `${this._initResults.length * this._sizeOneElement}px`);
        this._paginateWidget
            .setElement(this.$(`#${this._type}Paginate`))
            .render();

        return this;
    }
});

export default DepositionView;
