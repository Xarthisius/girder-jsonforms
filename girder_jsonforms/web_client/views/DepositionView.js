import DepositionModel from '../models/DepositionModel';
import DepositionTemplate from '../templates/depositionView.pug'; 

const View = girder.views.View;
const { renderMarkdown } = girder.misc;

var DepositionView = View.extend({
    initialize: function (settings) {
        if (settings.deposition) {
            this.model = settings.deposition;
            this.render();
        } else if (settings.id) {
            this.model = new DepositionModel();
            this.model.set('_id', settings.id);

            this.model.on('g:fetched', function () {
                this.render();
            }, this).fetch();
        }
    },

    render: function () {
        this.$el.html(DepositionTemplate({
            deposition: this.model,
            metadata: this.model.get("metadata"),
            renderMarkdown: renderMarkdown
        }));
        return this;
    }
});

export default DepositionView;
