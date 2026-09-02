const AccessControlledModel = girder.models.AccessControlledModel;
const { restRequest } = girder.rest;

var ProjectModel = AccessControlledModel.extend({
    resourceName: 'project',

    updateSamples: function (samples) {
        return restRequest({
            method: 'PUT',
            url: `${this.resourceName}/${this.id}/samples`,
            data: JSON.stringify(samples),
            contentType: 'application/json'
        }).done((resp) => {
            this.set(resp);
            this.trigger('g:changed');
        });
    },

    updateStatus: function (status) {
        return restRequest({
            method: 'PUT',
            url: `${this.resourceName}/${this.id}`,
            data: JSON.stringify({ status: status }),
            contentType: 'application/json'
        }).done((resp) => {
            this.set(resp);
            this.trigger('g:changed');
        });
    }
});

export default ProjectModel;
