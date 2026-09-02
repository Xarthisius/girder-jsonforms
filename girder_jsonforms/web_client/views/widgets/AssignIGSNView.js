import assignIGSNTemplate from '../../templates/assignIgsnWidget.pug';

const $ = girder.$;
const View = girder.views.View;
const { handleOpen, handleClose } = girder.dialog;
const { restRequest } = girder.rest;

var AssignIGSNWidget = View.extend({
    events: {
        'submit #g-assign-igsn': function (event) {
            event.preventDefault();
            this.$('button.g-assign-igsn').girderEnable(false);
            restRequest({
                method: 'PUT',
                url: `folder/${this.folder.id}/assign_igsn?igsn=${this.$('#assign-igsn').val()}`,
                error: null,
            }).done(() => {
                this.$el.modal('hide');
                girder.events.trigger('g:alert', {
                    icon: 'ok',
                    text: 'IGSN assigned successfully.',
                    type: 'success',
                    timeout: 4000,
                });
            }).fail((err) => {
                this.$('.g-validation-failed-message').text(err.responseJSON.message);
                this.$('button.g-assign-igsn').girderEnable(true);
            });
        }
    },

    initialize: function (settings) {
        this.folder = settings.folder;
    },

    render: function () {
        var modal = this.$el.html(assignIGSNTemplate({
            folder: this.folder
        })).girderModal(this).on('shown.bs.modal', function () {
            handleOpen('assignigsn');
        }).on('hidden.bs.modal', function () {
            handleClose('assignigsn');
        });
        modal.trigger($.Event('ready.girder.modal', { relatedTarget: modal }));
        this.$('#assign-igsn').trigger('focus');
        return this;
    },
});

export default AssignIGSNWidget;
