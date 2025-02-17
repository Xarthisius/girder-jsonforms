import $ from 'jquery';

import '@girder/core/utilities/jquery/girderModal';
import AddCreatorDialogTemplate from '../../templates/widgets/addCreatorDialog.pug';

import '../../stylesheets/addCreatorDialog.styl';

const View = girder.views.View;

var AddCreatorDialog = View.extend({
  events: {
    'submit #g-add-creator': function (event) {
      event.preventDefault();
      this._addCreator();
    }
  },

  initialize: function (settings) {
    this.settings = settings;
    this.creators = settings.creators || [];
  },

  render: function () {
    this.$el.html(AddCreatorDialogTemplate({})).girderModal(this);

    //this.$('#creator').val(this.settings.creators[0]);

    return this;
  },

  _addCreator: function () {
    const creator = this.$('#creator').val();
    if (creator) {
      this.creators.push(creator);
      this.settings.parentView.render();
      this.$el.modal('hide');
    }
  },
});

export default AddCreatorDialog;
