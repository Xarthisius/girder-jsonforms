import DepositionModel from '../models/DepositionModel';
import DepositionTemplate from '../templates/depositionView.pug'; 

import '../stylesheets/depositionView.styl';

import QRCode from 'qrcode';

const { AccessType } = girder.constants;
const { renderMarkdown } = girder.misc;
const { getApiRoot } = girder.rest;
const AccessWidget = girder.views.widgets.AccessWidget;
const View = girder.views.View;

const QRparams = {
  'errorCorrectionLevel': 'H',
  'version': 6,
  'mode': 'alphanumeric'
};

var DepositionView = View.extend({
    events: {
        'click .g-edit-access': 'editAccess',
        'click .g-back': function () {
            girder.router.navigate('depositions', {trigger: true});
        }
    },

    initialize: function (settings) {
        if (settings.deposition) {
            this.model = settings.deposition;
            this.render();
        } else if (settings.id) {
            this.model = new DepositionModel();
            this.model.set('_id', settings.id);

            this.model.on('g:fetched', function () {
                this.render();
            }, this).fetch();
        }
    },

    render: function () {
        const relatedIdentifiers = this.model.get("metadata").relatedIdentifiers;
        this.transformRelatedIdentifiers(relatedIdentifiers);
        this.$el.html(DepositionTemplate({
            deposition: this.model,
            metadata: this.model.get("metadata"),
            renderMarkdown: renderMarkdown,
            AccessType: AccessType,
            relatedIdentifiers: relatedIdentifiers,
            level: this.model.getAccessLevel()
        }));
        console.log(this.model.get("sampleId"));
        if (this.model.get("sampleId")) {
            console.log("HERE");
            const addEventUrl = `${window.location.origin}/#sample/${this.model.get('sampleId')}/add`;
            QRCode.toCanvas(this.$('#g-qr-code')[0], addEventUrl.toUpperCase(), QRparams);
        }
        return this;
    },

    transformRelatedIdentifiers: function (relatedIdentifiers) {
        const apiRoot = getApiRoot();
        const origin = window.location.origin;
        console.log("!!!!!!!");
        const entryRegex = new RegExp(`${origin}${apiRoot}/entry/(\\w+)`);
        const formRegex = new RegExp(`${origin}${apiRoot}/form/(\\w+)/schema`);

        for (let i = 0; i < relatedIdentifiers.length; i++) {
            const identifier = relatedIdentifiers[i];
            console.log(identifier);
            if (identifier.relationType === "HasMetadata") {
                const entryMatch = identifier.relatedIdentifier.match(entryRegex);
                const formMatch = identifier.relatedMetadataScheme.match(formRegex);
                if (entryMatch && formMatch) {
                    const entryId = entryMatch[1];
                    const formId = formMatch[1];
                    relatedIdentifiers[i].relatedIdentifier = `#form/${formId}/entry?entryId=${entryId}`;
                    relatedIdentifiers[i].relatedMetadataScheme = `#form/${formId}`;
                    relatedIdentifiers[i].relatedMetadataSchemeTitle = `Form (id: ${formId})`;
                    relatedIdentifiers[i].relatedIdentifierTitle = `Entry (id: ${entryId})`;
                }
            } else if (identifier.relationType === "IsPartOf" && identifier.relatedIdentifierType === "IGSN") {
                relatedIdentifiers[i].relatedIdentifierTitle = identifier.relatedIdentifier;
                relatedIdentifiers[i].relatedIdentifier = `#igsn/${identifier.relatedIdentifier}`;
            }
        }
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

export default DepositionView;
