import Collection from 'girder/collections/Collection';

import FormEntryModel from '../models/FormEntryModel';

var FormEntryCollection = Collection.extend({
    resourceName: 'entry',
    model: FormEntryModel,
    pageLimit: 100
});

export default FormEntryCollection;
