import $ from 'jquery';

const { restRequest } = girder.rest;
const View = girder.views.View;

import AddCreatorDialog from './widgets/AddCreatorDialog';
import '../stylesheets/editDepositionView.styl';
import template from '../templates/editDepositionView.pug';

function isDefined(value) {
  return value !== null && value !== undefined && value !== '';
}

const EditDepositionView = View.extend({
  events: {
    'dragstart .g-identifiers-list li': 'addDragging',
    'dragend .g-identifiers-list li': 'removeDragging',
    'dragover .g-identifiers-list': 'dragOver',
    'dragstart .g-creators-list li': 'addDragging',
    'dragend .g-creators-list li': 'removeDragging',
    'dragover .g-creators-list': 'dragOver',
    'drop .g-identifiers-list': function (event) {
        this.drop(event, '.g-identifiers-list');
        this._updateIdentifiers();
    },
    'drop .g-creators-list': function (event) {
        this.drop(event, '.g-creators-list');
        this._updateCreators();
    },
    'click #g-deposition-addIdentifier': function () {
      this.identifiers.push({"type": "local", "value": ""});
      this.render();
    },
    'click #g-deposition-removeIdentifier': function (event) {
      let item = $(event.currentTarget).closest('li').get(0);
      let index = this.$('.g-identifiers-list li').index(item);
      this.identifiers.splice(index, 1);
      this.render();
    },
    'click #g-deposition-cancel': function () {
      girder.router.navigate(`depositions`, { trigger: true });
    },
    'submit #g-deposition-form': function (event) {
      event.preventDefault();
      const formData = $(event.currentTarget).serializeArray();
      const metadata = {};
      formData.forEach((item) => {
        metadata[item.name] = item.value;
      });
      metadata["materialSubtype"] = isDefined(metadata["materialSubtype"]) ? metadata["materialSubtype"] : 'X';
      metadata["governorLab"] = isDefined(metadata["governorLab"]) ? metadata["governorLab"] : 'X';
      const data = {
        prefix: `${metadata.governor}${metadata.governorLab}${metadata.material}${metadata.materialSubtype}`,
        metadata: JSON.stringify({
          title: metadata.title,
          description: metadata.description,
          creators: this.creators,
        })
      };
      restRequest({
        method: 'POST',
        url: 'deposition',
        data: data,
      }).done((resp) => {
        this.trigger('g:alert', {
          text: 'Deposition updated successfully',
          type: 'success',
        });
        girder.router.navigate('depositions', { trigger: true });
      }).fail((resp) => {
        this.trigger('g:alert', {
          text: resp.responseJSON.message,
          type: 'danger',
        });
      });
    },
    'click #g-deposition-addCreator': function () {
      new AddCreatorDialog({
        el: $('#g-dialog-container'),
        parentView: this,
        creators: this.creators,
      }).render();
    },
    'change #g-deposition-governor': function (event) {
      const selectedInstitution = $(event.currentTarget).val();
      this.$('#g-deposition-governorLab').empty();
      this.$('#g-deposition-governorLab').append($('<option>', {
        value: 'X',
        text: 'Select a lab (or leave blank)',
      }));
      let currentChar = 64;
      this.igsnInstitutions[selectedInstitution].labs.forEach((lab) => {
        currentChar += 1;
        this.$('#g-deposition-governorLab').append($('<option>', {
          value: String.fromCharCode(currentChar),
          text: lab,
        }));
      });
    },
    'change #g-deposition-material': function (event) {
      const selectedMaterial = $(event.currentTarget).val();
      this.$('#g-deposition-materialType').empty();
      const subcategories = this.igsnMaterials[selectedMaterial].subcategories || {};
      const subcategoriesExists = !$.isEmptyObject(subcategories);
      if (subcategoriesExists) {
        this.$('#g-deposition-materialType').append($('<option>', {
          value: 'X',
          text: 'Select a subcategory (or leave blank)',
        }));
        Object.entries(subcategories).forEach(([materialCode, materialType]) => {
          this.$('#g-deposition-materialType').append($('<option>', {
            value: materialCode,
            text: materialType,
          }));
        });
      } else {
        this.$('#g-deposition-materialType').append($('<option>', {
          value: 'X',
          text: 'No subcategories',
        }));
      }
      this.$('#g-deposition-materialType').girderEnable(subcategoriesExists);
    },
  },
  initialize: function (settings) {
    this.draggedItem = null;
    restRequest({
      method: 'GET',
      url: 'system/setting',
      data: {
        list: JSON.stringify(['jsonforms.igsn_institutions', 'jsonforms.igsn_materials'])
      }
    }).done((resp) => {
      this.igsnInstitutions = resp['jsonforms.igsn_institutions'];

      this.igsnMaterials = resp['jsonforms.igsn_materials'];
      this.settings = settings;
      this.creators = settings.creators || [];
      this.identifiers = settings.identifiers || [];
      this.render();
    });
  },
  render: function () {
    this.$el.html(template({
      institutions: this.igsnInstitutions,
      identifiers: this.identifiers,
      materials: Object.entries(this.igsnMaterials),
      creators: this.creators
    }));
    return this;
  },
  _updateIdentifiers: function () {
      let items = this.$('.g-identifiers-list li').toArray();
      this.identifiers = items.map((item) => {
          return {
              type: $(item).find('.g-identifier-type').val(),
              value: $(item).find('.g-identifier-value').val()
          };
      });
      this.render();
  },
  _updateCreators: function () {
      console.log("Updating creators");
      let items = this.$('.g-creators-list li').toArray();
      this.creators = items.map((item) => {
          console.log("Item", item.attributes );
          const creator = {};
          for (let i = 0; i < item.attributes.length; i++) {
              const attribute = item.attributes[i];
              if (attribute.name.startsWith('data-creator')) {
                  const key = attribute.name.replace('data-creator-', '').replace('name', 'Name');
                  creator[key] = attribute.value;
              }
          }
          return creator;
      });
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
});

export default EditDepositionView;
