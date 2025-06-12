import DepositionModel from '../models/DepositionModel';

const Collection = girder.collections.Collection;

var DepositionCollection = Collection.extend({
    resourceName: 'deposition',
    model: DepositionModel,
    pageLimit: 16,
    sortField: 'igsn',
    sortDir: 1
});

export default DepositionCollection;
