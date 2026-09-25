const AccessControlledModel = girder.models.AccessControlledModel;
const { getApiRoot } = girder.rest;

var FormModel = AccessControlledModel.extend({
    resourceName: 'form',
    exportForm: function (format) {
      return `${getApiRoot()}/${this.resourceName}/${this.id}/export?exportFormat=${format}`;
    }
});

export default FormModel;
