import classifyEbsdTemplate from '../../templates/classifyEbsdWidget.pug';

const $ = girder.$;
const View = girder.views.View;
const { handleOpen, handleClose } = girder.dialog;
const { restRequest } = girder.rest;

var ClassifyEbsdWidget = View.extend({
    events: {
        'submit #g-classify-ebsd': function (event) {
            event.preventDefault();
            this.$('button.g-classify-ebsd').girderEnable(false);
            restRequest({
                method: 'PUT',
                url: `folder/${this.folder.id}/classify_ebsd?progress=true`,
                error: null,
            }).done(() => {
                this.$el.modal('hide');
                girder.events.trigger('g:alert', {
                    icon: 'ok',
                    text: 'EBSD classification started successfully.',
                    type: 'success',
                    timeout: 4000,
                });
            }).fail((err) => {
                this.$('.g-validation-failed-message').text((err.responseJSON && err.responseJSON.message) || 'Failed to classify folder.');
                this.$('button.g-classify-ebsd').girderEnable(true);
            });
        }
    },

    initialize: function (settings) {
        this.folder = settings.folder;
    },

    render: function () {
        var modal = this.$el.html(classifyEbsdTemplate({
            folder: this.folder
        })).girderModal(this).on('shown.bs.modal', function () {
            handleOpen('classifyebsd');
        }).on('hidden.bs.modal', function () {
            handleClose('classifyebsd');
        });
        modal.trigger($.Event('ready.girder.modal', { relatedTarget: modal }));
        return this;
    },
});

export default ClassifyEbsdWidget;
