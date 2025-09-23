import DescriptionsWidgetTemplate from '../../templates/widgets/descriptionsWidget.pug';

const $ = girder.$;
const View = girder.views.View;

const DescriptionsWidget = View.extend({
  events: {
    'dragstart .g-descriptions-list li': 'addDragging',
    'dragend .g-descriptions-list li': 'removeDragging',
    'dragover .g-descriptions-list': 'dragOver',
    'click #g-deposition-addDescription': function () {
      this._updateDescriptions();
      this.descriptions.push({"type": "Abstract", "value": ""});
      this.render();
    },
    'click #g-deposition-removeDescription': function (event) {
      this._updateDescriptions();
      const item = $(event.currentTarget).closest('li').get(0);
      const index = this.$('.g-descriptions-list li').index(item);
      this.descriptions.splice(index, 1);
      this.render();
    },
    'drop .g-descriptions-list': function (event) {
        this.drop(event, '.g-descriptions-list');
        this._updateDescriptions();
    },
  },

  initialize: function (settings) {
    this.settings = settings;
    this.descriptions = settings.descriptions || [];  // Default to empty array if not provided
  },

  render: function () {
    this.$el.html(DescriptionsWidgetTemplate({descriptions: this.descriptions}));
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
        const target = event.target.closest('li');
        if (target && target !== this.draggedItem) {
            const list = $(target);
            const items = list.children("li").toArray();
            const draggedIndex = items.indexOf(this.draggedItem);
            const targetIndex = items.indexOf(target);

            if (draggedIndex < targetIndex) {
                $(target).after(this.draggedItem);
            } else {
                $(target).before(this.draggedItem);
            }
        }
    }
  },
  _updateDescriptions: function () {
      const items = this.$('.g-descriptions-list li').toArray();
      console.log(items);
      this.descriptions = items.map((item) => {
          return {
              descriptionType: $(item).find('.g-description-type').val(),
              description: $(item).find('.g-description-description').val()
          };
      });
      console.log(this.descriptions);
  },

});

export default DescriptionsWidget;
