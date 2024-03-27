import Collection from 'girder/collections/Collection';

import FormModel from '../models/FormModel';

var FormCollection = Collection.extend({
    resourceName: 'form',
    model: FormModel,
    pageLimit: 100
});

export default FormCollection;
