const AccessControlledModel = girder.models.AccessControlledModel;
const { getApiRoot } = girder.rest;

var FormModel = AccessControlledModel.extend({
    resourceName: 'form',
    exportForm: function (format) {
      let url = `${getApiRoot()}/${this.resourceName}/${this.id}/export?exportFormat=${format}`;
      return url;
    }
});

export default FormModel;
