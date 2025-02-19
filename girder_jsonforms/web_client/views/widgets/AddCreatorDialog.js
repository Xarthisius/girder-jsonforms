import $ from 'jquery';

import '@girder/core/utilities/jquery/girderModal';
import AddCreatorDialogTemplate from '../../templates/widgets/addCreatorDialog.pug';

import '../../stylesheets/addCreatorDialog.styl';

const View = girder.views.View;

var AddCreatorDialog = View.extend({
  events: {
    'click .g-add-creator-btn': function (event) {
      event.preventDefault();
      this._addCreator();
    },
    'change input[name="creatorType"]': function (event) {
      let creatorType = event.target.value;
      $('#g-add-creator-form').find('.person-fields').attr('hidden', creatorType !== 'person');
      $('#g-add-creator-form').find('.org-fields').attr('hidden', creatorType !== 'organization');
    },
  },

  initialize: function (settings) {
    this.settings = settings;
    this.creators = settings.creators || [];
    this.creatorType = settings.creatorType || 'person';
  },

  render: function () {
    this.$el.html(AddCreatorDialogTemplate({creatorType: this.creatorType})).girderModal(this);
    return this;
  },

  _addCreator: function () {
    const creator = $('#g-add-creator-form').serializeArray();
    if (creator) {
      this.creators.push(creator);
      this.settings.parentView.render();
    }
    this.$el.modal('hide');
  },
});

export default AddCreatorDialog;
