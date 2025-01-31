import AccessControlledModel from 'girder/models/AccessControlledModel';
import { getApiRoot } from 'girder/rest';

var FormModel = AccessControlledModel.extend({
    resourceName: 'form',
    exportForm: function (format) {
      let url = `${getApiRoot()}/${this.resourceName}/${this.id}/export?format=${format}`;
      return url;
    }
});

export default FormModel;
