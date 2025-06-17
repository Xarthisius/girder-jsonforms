import IdentifiersWidgetTemplate from '../../templates/widgets/identifiersWidget.pug';
import AddCreatorDialog from './AddCreatorDialog';

const $ = girder.$;
const View = girder.views.View;

const IdentifiersWidget = View.extend({
  events: {
    'dragstart .g-identifiers-list li': 'addDragging',
    'dragend .g-identifiers-list li': 'removeDragging',
    'dragover .g-identifiers-list': 'dragOver',
    'click #g-deposition-addIdentifier': function () {
      this._updateIdentifiers();
      this.identifiers.push({"type": "local", "value": ""});
      this.render();
    },
    'click #g-deposition-removeIdentifier': function (event) {
      this._updateIdentifiers();
      let item = $(event.currentTarget).closest('li').get(0);
      let index = this.$('.g-identifiers-list li').index(item);
      this.identifiers.splice(index, 1);
      this.render();
    },
    'drop .g-identifiers-list': function (event) {
        this.drop(event, '.g-identifiers-list');
        this._updateIdentifiers();
    },
  },

  initialize: function (settings) {
    this.settings = settings;
    this.identifiers = settings.identifiers || [];  // Default to empty array if not provided
  },

  render: function () {
    this.$el.html(IdentifiersWidgetTemplate({identifiers: this.identifiers}));
    return this;
  },

  addDragging: function (event) {
    this.draggedItem = event.currentTarget;
    $(event.currentTarget).addClass('dragging');
    event.originalEvent.dataTransfer.effectAllowed = 'move';
  },
  removeDragging: function (event) {
    $(event.currentTarget).removeClass('dragging');
  },
  dragOver: function (event) {
    event.preventDefault();
  },
  drop: function (event, target) {
    event.preventDefault();
    if (this.draggedItem) {
        let target = event.target.closest('li');
        if (target && target !== this.draggedItem) {
            let list = $(target);
            let items = list.children("li").toArray();
            let draggedIndex = items.indexOf(this.draggedItem);
            let targetIndex = items.indexOf(target);

            if (draggedIndex < targetIndex) {
                $(target).after(this.draggedItem);
            } else {
                $(target).before(this.draggedItem);
            }
        }
    }
  },
  _updateIdentifiers: function () {
      let items = this.$('.g-identifiers-list li').toArray();
      this.identifiers = items.map((item) => {
          return {
              type: $(item).find('.g-identifier-type').val(),
              value: $(item).find('.g-identifier-value').val()
          };
      });
  },

});

export default IdentifiersWidget;
