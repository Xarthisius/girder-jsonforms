import FormEntryModel from '../models/FormEntryModel';

const Collection = girder.collections.Collection;

var FormEntryCollection = Collection.extend({
    resourceName: 'entry',
    model: FormEntryModel,
    pageLimit: 16,
    sortField: 'data.sampleId',
    sortDir: -1
});

export default FormEntryCollection;
