import Model from 'girder/models/Model';
import { restRequest } from 'girder/rest';

var FormEntryModel = Model.extend({
    resourceName: 'entry',
});

export default FormEntryModel;
