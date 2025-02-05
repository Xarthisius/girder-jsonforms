import FormModel from '../models/FormModel';

const Collection = girder.collections.Collection;

var FormCollection = Collection.extend({
    resourceName: 'form',
    model: FormModel,
    pageLimit: 100
});

export default FormCollection;
