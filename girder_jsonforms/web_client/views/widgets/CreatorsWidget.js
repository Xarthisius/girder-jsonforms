import $ from 'jquery';

import CreatorsWidgetTemplate from '../../templates/widgets/creatorsWidget.pug';
import AddCreatorDialog from './AddCreatorDialog';

const View = girder.views.View;

const CreatorsWidget = View.extend({
  events: {
    'click #g-deposition-addCreator': function () {
      new AddCreatorDialog({
        el: this.$('#g-dialog-container'),
        parentView: this,
        creators: this.creators,
      }).render()
    },
    'click #g-deposition-removeCreator': function (event) {
      const item = $(event.currentTarget).closest('li').get(0);
      const index = this.$('.g-creators-list li').index(item);
      this.creators.splice(index, 1);
      this.render();
    },
  },

  initialize: function (settings) {
    this.settings = settings;
    this.creators = settings.creators || [];  // Expecting an array of creator objects
  },

  render: function () {
    this.$el.html(CreatorsWidgetTemplate({creators: this.creators}));
    return this;
  },


});

export default CreatorsWidget;
