const AccessControlledModel = girder.models.AccessControlledModel;
const { getApiRoot } = girder.rest;

var DepositionModel = AccessControlledModel.extend({
    resourceName: 'deposition'
});

export default DepositionModel;
