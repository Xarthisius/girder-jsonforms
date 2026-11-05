import refreshDataCiteTemplate from '../../templates/refreshDataCiteDialog.pug';

const $ = girder.$;
const View = girder.views.View;
const FileModel = girder.models.FileModel;
const { handleOpen, handleClose } = girder.dialog;
const { getApiRoot } = girder.rest;

const DATACITE_APIS = [
    { label: 'Production', url: 'https://api.datacite.org' },
    { label: 'Test', url: 'https://api.test.datacite.org' }
];

function normalizeDoi(doi) {
    return doi.trim().replace(/^(https?:\/\/(dx\.)?doi\.org\/|doi:)/i, '');
}

// btoa() only takes Latin-1, so encode credentials as UTF-8 first.
function basicAuth(user, password) {
    const bytes = new TextEncoder().encode(`${user}:${password}`);
    return 'Basic ' + btoa(String.fromCharCode.apply(null, bytes));
}

/**
 * The id of the Girder file `url` downloads, provided it belongs to this
 * instance's API; null for anything else, which this dialog cannot replace.
 */
function localFileId(url) {
    const apiRoot = new URL(getApiRoot(), window.location.href).href.replace(/\/$/, '');
    if (!url || url.indexOf(apiRoot + '/') !== 0) {
        return null;
    }
    const match = url.slice(apiRoot.length).match(/^\/file\/([0-9a-f]{24})(\/download)?\/?(\?|$)/);
    return match ? match[1] : null;
}

/**
 * Pulls a DOI's record from the DataCite REST API and uploads it over the
 * file a collection's `meta.datacite` points at. Registered (not findable)
 * DOIs are only visible with the repository's credentials, which are asked
 * for every time and go straight from the browser to DataCite.
 */
var RefreshDataCiteDialog = View.extend({
    events: {
        'submit #g-refresh-datacite': function (event) {
            event.preventDefault();
            this.$('.g-validation-failed-message').empty();

            const fileId = localFileId(this.collection.get('meta').datacite);
            if (!fileId) {
                return this._fail(
                    'This collection\'s "datacite" metadata does not point to a file on this ' +
                    'Girder instance, so there is nothing here to replace.');
            }

            const doi = normalizeDoi(this.$('#g-datacite-doi').val());
            const api = this.$('#g-datacite-api').val();
            const auth = basicAuth(this.$('#g-datacite-user').val(), this.$('#g-datacite-password').val());

            this.$('button.g-refresh-datacite-submit').girderEnable(false);
            // fetch() rather than $.ajax so no Girder headers ride along to DataCite.
            fetch(`${api}/dois/${doi}`, {
                headers: { Accept: 'application/vnd.api+json', Authorization: auth },
                credentials: 'omit'
            }).catch(() => {
                throw new Error(`Could not reach ${api}.`);
            }).then((resp) => {
                if (resp.status === 401 || resp.status === 403) {
                    throw new Error('DataCite rejected these credentials.');
                }
                if (resp.status === 404) {
                    throw new Error(`DOI ${doi} was not found at ${api} for this repository.`);
                }
                if (!resp.ok) {
                    throw new Error(`DataCite responded with ${resp.status} ${resp.statusText}.`);
                }
                return resp.json();
            }).then((record) => {
                if (!record.data || !record.data.attributes) {
                    throw new Error('DataCite returned a response without a DOI record.');
                }
                // The base64 XML duplicates the JSON and roughly doubles the file.
                delete record.data.attributes.xml;
                return this._upload(fileId, record);
            }).then((record) => {
                this.$el.modal('hide');
                if (this.card) {
                    this.card.model.set(this.card.parseAttributes(record.data.attributes));
                }
                girder.events.trigger('g:alert', {
                    icon: 'ok',
                    text: `DataCite metadata for ${doi} updated.`,
                    type: 'success',
                    timeout: 4000
                });
            }).catch((err) => {
                this._fail(err.message);
            });
        }
    },

    initialize: function (settings) {
        this.collection = settings.collection;
        this.card = settings.card;
    },

    render: function () {
        const cardDoi = this.card ? this.card.model.get('doi') : '';
        var modal = this.$el.html(refreshDataCiteTemplate({
            doi: /^10\./.test(cardDoi || '') ? cardDoi : '',
            apis: DATACITE_APIS
        })).girderModal(this).on('shown.bs.modal', function () {
            handleOpen('refreshdatacite');
        }).on('hidden.bs.modal', function () {
            handleClose('refreshdatacite');
        });
        modal.trigger($.Event('ready.girder.modal', { relatedTarget: modal }));
        this.$(this.$('#g-datacite-doi').val() ? '#g-datacite-user' : '#g-datacite-doi').trigger('focus');
        return this;
    },

    _upload: function (fileId, record) {
        return new Promise((resolve, reject) => {
            const file = new FileModel({ _id: fileId });
            const failed = (params) => reject(new Error(
                (params && params.message) || 'Uploading the metadata file to Girder failed.'));
            file.on('g:upload.complete', () => resolve(record));
            file.on('g:upload.error', failed);
            file.on('g:upload.errorStarting', failed);
            file.updateContents(new Blob([JSON.stringify(record)], { type: 'application/json' }));
        });
    },

    _fail: function (message) {
        this.$('.g-validation-failed-message').text(message);
        this.$('button.g-refresh-datacite-submit').girderEnable(true);
    }
});

export default RefreshDataCiteDialog;
