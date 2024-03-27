import Model from 'girder/models/Model';
import { restRequest } from 'girder/rest';

var FormModel = Model.extend({
    resourceName: 'form',
});

export default FormModel;
