const AccessControlledModel = girder.models.AccessControlledModel;
const { getApiRoot } = girder.rest;

var DepositionModel = AccessControlledModel.extend({
    resourceName: 'deposition',

    getFormCreators: function () {
        const metadata = this.get('metadata');
        if (metadata && metadata.creators) {
            return metadata.creators;
        }
        return [];
    },

    getFormIdentifiers: function () {
        const metadata = this.get('metadata');
        if (metadata && metadata.attributes && metadata.attributes.alternateIdentifiers) {
            return metadata.attributes.alternateIdentifiers.map(identifier => ({
                type: identifier.alternateIdentifierType,
                value: identifier.alternateIdentifier
            }));
        }
        return [];
    }
});

export default DepositionModel;
