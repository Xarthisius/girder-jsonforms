import RelatedIdentifiersWidgetTemplate from '../../templates/widgets/relatedIdentifiersWidget.pug';

const $ = girder.$;
const View = girder.views.View;

const RelatedIdentifiersWidget = View.extend({
  events: {
    'dragstart .g-related-identifiers-list li': 'addDragging',
    'dragend .g-related-identifiers-list li': 'removeDragging',
    'dragover .g-related-identifiers-list': 'dragOver',
    'click #g-deposition-addRelatedIdentifier': function () {
      this._updateIdentifiers();
      this.identifiers.push({
        relatedIdentifier: "",
        relatedIdentifierType: "", 
        relationType: ""
      });
      this.render();
    },
    'click #g-deposition-removeRelatedIdentifier': function (event) {
      this._updateIdentifiers();
      let item = $(event.currentTarget).closest('li').get(0);
      let index = this.$('.g-related-identifiers-list li').index(item);
      this.identifiers.splice(index, 1);
      this.render();
    },
    'drop .g-related-identifiers-list': function (event) {
        this.drop(event, '.g-related-identifiers-list');
        this._updateIdentifiers();
    },
    'change .g-related-identifier-relation-type': function (event) {
        console.log('Relation type changed:', event.currentTarget.value);
        this._updateIdentifiers();
        this.render();
    }
  },

  initialize: function (settings) {
    this.settings = settings;
    this.identifiers = settings.identifiers || [];  // Default to empty array if not provided
  },

  render: function () {
    this.$el.html(RelatedIdentifiersWidgetTemplate({identifiers: this.identifiers}));
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
      let items = this.$('.g-related-identifiers-list li').toArray();
      this.identifiers = items.map((item) => {
          const result = {
              relatedIdentifier: $(item).find('.g-related-identifier-value').val(),
              relatedIdentifierType: $(item).find('.g-related-identifier-type').val(),
              relationType: $(item).find('.g-related-identifier-relation-type').val(),
              // Add scheme if it exists
          };
          let scheme = $(item).find('.g-related-metadata-scheme').val();
          console.log('Scheme:', scheme);
          if (scheme) {
              result.relatedMetadataScheme = scheme;
          }
          return result;
      });
  },

});

export default RelatedIdentifiersWidget;
