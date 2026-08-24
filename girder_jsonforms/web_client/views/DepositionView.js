import QRCode from 'qrcode';

import DepositionModel from '../models/DepositionModel';
import DepositionTemplate from '../templates/depositionView.pug';
import DepositionSplitDialog from '../templates/depositionSplitDialog.pug';
import SearchResultsTypeTemplate from '../templates/searchResultsType.pug';

import '../stylesheets/depositionView.styl';

const _ = girder._;
const events = girder.events;
const router = girder.router;
const { AccessType } = girder.constants;
const { confirm, handleClose, handleOpen } = girder.dialog;
const { renderMarkdown } = girder.misc;
const { getApiRoot, getPublicSettings } = girder.rest;
const AccessWidget = girder.views.widgets.AccessWidget;
const View = girder.views.View;
const { restRequest } = girder.rest;
const SearchPaginateWidget = girder.views.widgets.SearchPaginateWidget;
const UploadWidget = girder.views.widgets.UploadWidget;
const ItemModel = girder.models.ItemModel;
const FolderModel = girder.models.FolderModel;

const QRparams = {
    'errorCorrectionLevel': 'H',
    'version': 8,
    'mode': 'alphanumeric'
};

var SplitDialog = View.extend({
    events: {
        'submit #g-split-form': function (e) {
            e.preventDefault();
            // Disable submission button to prevent multiple clicks
            this.$('#g-split-btn').girderEnable(false);
            this.$('.g-validation-failed-message').text('');

            const data = $(e.currentTarget).serializeArray();
            const params = new Map(data.map((obj) => [obj.name, obj.value]));
            const suffix = params.get('suffix') || '';
            const batch = parseInt(params.get('batch'), 10);

            // validate that batch or suffix is provided, but not both
            // if batch is provided, validate that it's a positive integer
            // if both batch and suffix are provided, or neither is provided, show an error message
            if ((!batch && !suffix) || (batch && suffix)) {
                this.$('#g-split-btn').girderEnable(true);
                this.$('.g-validation-failed-message').text('Please provide either a batch size or a suffix, but not both.');
                return;
            }
            if (batch) {
                if (isNaN(batch) || batch <= 0) {
                    this.$('#g-split-btn').girderEnable(true);
                    this.$('.g-validation-failed-message').text('Batch size must be a positive integer.');
                    return;
                }
                params.set('batch', batch);
            }
            if (suffix) {
                if (!/^[a-zA-Z0-9]+$/.test(suffix)) {
                    this.$('#g-split-btn').girderEnable(true);
                    this.$('.g-validation-failed-message').text('Suffix must be a non-empty alphanumeric string.');
                    return;
                }
            }
            restRequest({
                type: 'POST',
                url: `deposition/${this.model.id}/split`,
                data: Object.fromEntries(params),
                error: null
            }).done((resp) => {
                this.$el.modal('hide');
                router.navigate(`deposition/${resp._id}`, { trigger: true });
            }).fail((resp) => {
                this.$el.modal('hide');
                events.trigger('g:alert', {
                    text: resp.responseJSON.message || 'An error occurred while splitting the deposition.',
                    type: 'danger'
                });
            });
        }
    },

    initialize: function (settings) {
        this.model = settings.model || new DepositionModel();
        this.render();
    },

    render: function () {
        this.$el.html(DepositionSplitDialog({
            igsn: this.model.get('igsn')
        })).girderModal(this)
            .on('shown.bs.modal', () => {
                this.$('#g-split-form').focus();
            }).on('hidden.bs.modal', () => {
                handleClose('splitEvent', { replace: true });
            });
        handleOpen('splitEvent', { replace: true });
        this.$('#g-split-form').focus();
        return this;
    }
});

var DepositionView = View.extend({
    events: {
        'click .g-edit-access': 'editAccess',
        'click .g-edit-deposition': function () {
            girder.router.navigate(`deposition/${this.model.get('_id')}/edit`, { trigger: true });
        },
        'click .g-back': function () {
            girder.router.navigate('depositions', { trigger: true });
        },
        'click .g-upload-deposition-image': function () {
            var container = $('#g-dialog-container');
            restRequest({
                "type": 'GET',
                "url": `deposition/${this.model.id}/assets`,
                error: null
            }).done((resp) => {
                var folder = new FolderModel();
                folder.set(resp);
                new UploadWidget({
                    el: container,
                    parentView: this,
                    parentType: 'folder',
                    parent: folder,
                    title: 'Upload Deposition Image',
                    multiFile: false,
                    onlyFiles: true,
                    otherParams: { reference: JSON.stringify({ igsn: this.model.get('igsn'), type: 'deposition_image' }) },
                }).on('g:uploadFinished', (info) => {
                    const fileId = info.files[0].id;
                    $('.g-sample-image').attr('src', `${getApiRoot()}/file/${fileId}/download?contentDisposition=inline`);
                    handleClose('upload');
                }, this).render();
            }).fail((resp) => {
                events.trigger('g:alert', {
                    text: resp.responseJSON.message || 'An error occurred while fetching the deposition assets.',
                    type: 'danger'
                });
            });
        },
        'click .g-split-deposition': function () {
            new SplitDialog({
                el: $('#g-dialog-container'),
                model: this.model,
                parentView: this
            }).render();
        },
        'click .g-delete-deposition': function () {
            this.model.destroy({
                error: null
            }).done(() => {
                events.trigger('g:alert', {
                    icon: 'ok',
                    text: 'The deposition has been deleted.',
                    type: 'success',
                    timeout: 4000
                });
                router.navigate('depositions', { trigger: true });
            }).fail((resp) => {
                events.trigger('g:alert', {
                    text: resp.responseJSON.message || 'An error occurred while deleting the deposition.',
                    type: 'danger'
                });
            });
        },
        'click .g-register-aimd-deposition': function () {
            restRequest({
                type: 'PUT',
                url: `deposition/${this.model.id}/task`,
                data: { action: 'register_aimd' },
                error: null
            }).done((resp) => {
                events.trigger('g:alert', {
                    icon: 'ok',
                    text: 'The deposition has been registered with AIMD.',
                    type: 'success',
                    timeout: 4000
                });
                this.model.set(resp);
                this.render();
            }).fail((resp) => {
                events.trigger('g:alert', {
                    text: resp.responseJSON.message || 'An error occurred while registering the deposition with AIMD.',
                    type: 'danger'
                });
            });
        },
        'click .g-publish-deposition': function () {
            const igsn = this.model.get('igsn');
            // A DOI is world readable, so the record has to be public already.
            // Making it public is a separate, deliberate act -- publishing will
            // not do it for you, and neither will this button.
            if (!this.model.get('public')) {
                events.trigger('g:alert', {
                    text: `${igsn} is not public. Publishing mints a permanent public ` +
                        'DOI, so make it public under Access control first.',
                    type: 'warning',
                    timeout: 6000
                });
                return;
            }
            const question = `Publish ${igsn} to DataCite? This mints a permanent, public DOI ` +
                'for this sample and every sample in its batch, and cannot be undone.';
            confirm({
                text: question,
                yesText: 'Publish',
                confirmCallback: () => {
                    this._depositionTask('publish', {
                        target: 'findable',
                        recurse: true
                    }, `${igsn} has been queued for publication to DataCite.`);
                }
            });
        },
        'click .g-sync-deposition': function () {
            this._depositionTask(
                'sync', {},
                'The metadata has been queued for sync with the IGSN registry.'
            );
        }
    },

    /**
     * Kick off a deposition task and report the outcome.
     *
     * Publication is asynchronous on the registry side too, so a success here
     * means "queued", not "published" -- the status badge updates once the
     * registry has actually pushed the record.
     */
    _depositionTask: function (action, params, successText) {
        restRequest({
            type: 'PUT',
            url: `deposition/${this.model.id}/task`,
            data: _.extend({ action: action }, params),
            error: null
        }).done(() => {
            events.trigger('g:alert', {
                icon: 'ok',
                text: successText,
                type: 'success',
                timeout: 4000
            });
            this.model.fetch().done(() => this.render());
        }).fail((resp) => {
            events.trigger('g:alert', {
                text: (resp.responseJSON && resp.responseJSON.message) ||
                    `An error occurred while running the ${action} task.`,
                type: 'danger'
            });
        });
    },

    initialize: function (settings) {
        this._query = this.model.get('igsn');
        this._mode = 'igsn';
        this._subviews = {};
        this.formMap = {};
        this.entryMap = {};
        this._searchRequest = restRequest({
            url: 'resource/search',
            data: {
                q: this._query,
                mode: this._mode,
                types: JSON.stringify(['folder', 'item']),
                limit: 10,
            }
        }).done((results) => {
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
                } else {
                    this._subviews[type] = null;
                }
            });
            this.render();
        });
        this.image = new ItemModel();
        if (this.model.get('imageId')) {
            this.image.set({
                _id: this.model.get('imageId')
            }).on('g:fetched', function () {
                this.render();
            }, this).on('g:error', function () {
                this.item = null;
                this.render();
            }, this).fetch();
        }
        const relatedIdentifiers = this.model.get("metadata").relatedIdentifiers;
        this.reducedIdentifiers = this._processRelatedIdentifiers(relatedIdentifiers, 10);
        this.transformRelatedIdentifiers(this.reducedIdentifiers.reducedIdentifiers);
        // Fetch datafile counts for this IGSN and stash on the view, but only
        // if the deployment has enabled it (avoids a request that will just 404/no-op
        // on deployments without AIMD configured).
        const publicSettings = getPublicSettings() || {};
        if (publicSettings['jsonforms.aimdl_counts']) {
            restRequest({
                url: 'aimdl/count',
                method: 'GET',
                data: { igsn: this.model.get('igsn') },
                error: null
            }).done((resp) => {
                this.datafileCounts = resp;
                // Re-render to show the datafile counts when available
                this.render();
            }).fail((resp) => {
                events.trigger('g:alert', {
                    text: resp && resp.responseJSON && resp.responseJSON.message ? resp.responseJSON.message : 'Could not fetch datafile counts.',
                    type: 'warning'
                });
            });
        }
    },

    render: function () {
        this.$el.html(DepositionTemplate({
            deposition: this.model,
            metadata: this.model.get("metadata"),
            renderMarkdown: renderMarkdown,
            trackerUrl: `#sample/${this.model.get('sampleId')}`,
            AccessType: AccessType,
            relIds: this.reducedIdentifiers,
            level: this.model.getAccessLevel(),
            imageUrl: this.model.get('imageId') ? `${getApiRoot()}/item/${this.model.get('imageId')}/download?contentDisposition=inline` : null,
            datafileCounts: this.datafileCounts || null,
            // Present only when this Girder is backed by the central IGSN
            // registry; absent in local mode, which hides the publish UI.
            // Whether publishing is offered at all depends on the deployment,
            // not on whether this particular record has synced yet.
            registryEnabled: !!(getPublicSettings() || {})['jsonforms.igsn_registry_enabled'],
            serviceStatus: this.model.get('serviceStatus') || null,
            serviceError: this.model.get('serviceError') || null,
            publishedAt: this.model.get('publishedAt') || null,
        }));
        // Find all html elements with entryId and formId
        // and set the text to the name of the entry or form
        $('.g-deposition-info-line').each((index, element) => {
            if (element.attributes.entryId) {
                const entryId = element.attributes.entryId.value;
                const entry = this.entryMap[entryId];
                if (entry) {
                    $(element).find('span.g-info-type').text(`Entry for ${entry.uniqueId}`);
                }
            }
            if (element.attributes.formId) {
                const formId = element.attributes.formId.value;
                const form = this.formMap[formId];
                if (form) {
                    $(element).find('span.g-info-type').text(`Form "${form.name}"`);
                }
            }
        });
        if (this._searchRequest.state() === 'resolved') {
            this.$('.g-search-pending').hide();
            // for each subview that's not null, render it and append it to the container but make sure they are not duplicated if they already exist
            _.each(this._subviews, (subview, type) => {
                if (subview) {
                    subview.render();
                    const container = this.$(`.g-search-results-${type}`);
                    if (container.children().length === 0) {
                        subview.$el.appendTo(container);
                    }
                }
            });
            if (_.isEmpty(this._subviews)) {
                this.$('.g-search-no-results').show();
            }
        }
        if (this.model.get("sampleId")) {
            const addEventUrl = `${window.location.origin}/#sample/${this.model.get('sampleId')}/add`;
            QRCode.toCanvas(this.$('#g-qr-code')[0], addEventUrl, QRparams);
        }
        if (this.image && this.image.id && this.image.get('meta') && this.image.get('meta').shape) {
            const imageUrl = `${getApiRoot()}/item/${this.image.id}/download?contentDisposition=inline`;
            const links = this.image.get('meta').links || [];
            const shape = this.image.get('meta').shape || [1000, 1000];
            const interactiveImage = this.createInteractiveSVG(imageUrl, links, shape[0], shape[1]);
            this.$('.g-sample-image-container').html(interactiveImage);
        }

        return this;
    },
    /**
     * Processes an array of related identifiers to reduce the number of items
     * per relation type to a specified maximum, and reports on the changes.
     *
     * @param {Array<Object>} relatedIdentifiers - The input array of identifier objects.
     * Each object is expected to have a 'relationType' property.
     * @param {number} maxItemsPerType - The maximum number of items to keep for each 'relationType'.
     * @returns {{
     * originalCount: number,
     * newCount: number,
     * removedCounts: Object<string, number>,
     * reducedIdentifiers: Array<Object>
     * }} An object containing the original count, the new count,
     * the reduced array of identifiers, and a map of how many
     * items were removed per type.
     */
    _processRelatedIdentifiers: function (relatedIdentifiers, maxItemsPerType) {
        // 1. Get the total number of elements.
        const originalCount = relatedIdentifiers.length;

        if (!Array.isArray(relatedIdentifiers) || maxItemsPerType < 0) {
            console.error("Invalid input provided.");
            return {
                originalCount: 0,
                newCount: 0,
                removedCounts: {},
                reducedIdentifiers: []
            };
        }

        // Group identifiers by their 'relationType'.
        const groupedByIdentifier = relatedIdentifiers.reduce((acc, item) => {
            const { relationType } = item;
            // Initialize the array for this relationType if it doesn't exist.
            if (!acc[relationType]) {
                acc[relationType] = [];
            }
            acc[relationType].push(item);
            return acc;
        }, {});

        const reducedIdentifiers = [];
        const removedCounts = {};

        // 2. Reduce elements and 3. Track removed elements.
        for (const relationType in groupedByIdentifier) {
            const items = groupedByIdentifier[relationType];
            const itemsToRemoveCount = Math.max(0, items.length - maxItemsPerType);

            removedCounts[relationType] = itemsToRemoveCount;

            // Add the allowed number of items to the final array.
            reducedIdentifiers.push(...items.slice(0, maxItemsPerType));
        }

        const newCount = reducedIdentifiers.length;

        return {
            originalCount,
            newCount,
            removedCounts,
            reducedIdentifiers,
        };
    },

    transformRelatedIdentifiers: function (relatedIdentifiers) {
        if (!relatedIdentifiers || !Array.isArray(relatedIdentifiers)) {
            return; // nothing to transform
        }
        const apiRoot = getApiRoot();
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
            } else if (identifier.relatedIdentifierType === "IGSN") {
                relatedIdentifiers[i].relatedIdentifierTitle = identifier.relatedIdentifier;
                relatedIdentifiers[i].relatedIdentifier = `#igsn/${identifier.relatedIdentifier}`;
            }
        }
        restRequest({
            url: 'resource',
            method: 'GET',
            data: {
                resources: JSON.stringify({ "jsonforms.form": forms, "jsonforms.entry": entries }),
                filters: JSON.stringify({ "jsonforms.form": { "name": 1 }, "jsonforms.entry": { "uniqueId": 1 } })
            }
        }).done((response) => {
            // response is a dictionary with keys 'form' and 'entry' poiniting to dictionaries
            // with keys being the formId or entryId and values being the form or entry
            // convert it to map
            response["jsonforms.form"].forEach((form) => {
                this.formMap[form._id] = form;
            });
            response["jsonforms.entry"].forEach((entry) => {
                this.entryMap[entry._id] = entry;
            });
            this.render();
        });

    },

    editAccess: function () {
        new AccessWidget({
            el: $('#g-dialog-container'),
            model: this.model,
            modelType: 'deposition',
            parentView: this
        }).render();
    },

    createInteractiveSVG(imageUrl, regions, vbW, vbH) {
        const svgNS = "http://www.w3.org/2000/svg";

        const svg = document.createElementNS(svgNS, "svg");
        svg.setAttribute("viewBox", `0 0 ${vbW} ${vbH}`);
        svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

        const img = document.createElementNS(svgNS, "image");
        img.setAttributeNS(null, "href", imageUrl);
        img.setAttributeNS(null, "width", vbW);
        img.setAttributeNS(null, "height", vbH);
        svg.appendChild(img);

        regions.forEach(data => {
            const anchor = document.createElementNS(svgNS, "a");
            anchor.setAttributeNS(null, "href", data.href);
            anchor.setAttributeNS(null, "target", "_blank");

            let shape;
            if (data.shape === "rect") {
                shape = document.createElementNS(svgNS, "rect");
                shape.setAttributeNS(null, "x", data.pos[0]);
                shape.setAttributeNS(null, "y", data.pos[1]);
                shape.setAttributeNS(null, "width", data.size[0]);
                shape.setAttributeNS(null, "height", data.size[1]);
            } else if (data.shape === "circle") {
                shape = document.createElementNS(svgNS, "circle");
                shape.setAttributeNS(null, "cx", data.pos[0]);
                shape.setAttributeNS(null, "cy", data.pos[1]);
                shape.setAttributeNS(null, "r", data.radius);
            }

            if (shape) {
                // Default style: very lightly opaque
                shape.setAttributeNS(null, "fill", "white");
                shape.setAttributeNS(null, "fill-opacity", "0.1");
                shape.style.cursor = "pointer";

                anchor.appendChild(shape);
                svg.appendChild(anchor);
            }
        });

        return svg;
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
// export the view and helpers
export default DepositionView;
export { SplitDialog, SearchResultsTypeView };
