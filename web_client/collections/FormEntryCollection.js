import Collection from 'girder/collections/Collection';

import FormEntryModel from '../models/FormEntryModel';

var FormEntryCollection = Collection.extend({
    resourceName: 'entry',
    model: FormEntryModel,
    pageLimit: 16,
    sortField: 'data.sampleId',
    sortDir: -1
});

export default FormEntryCollection;
