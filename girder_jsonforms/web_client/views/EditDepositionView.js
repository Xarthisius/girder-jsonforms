import $ from 'jquery';

const { restRequest } = girder.rest;
const View = girder.views.View;

import AddCreatorDialog from './widgets/AddCreatorDialog';
import CreatorsWidget from './widgets/CreatorsWidget';
import IdentifiersWidget from './widgets/IdentifiersWidget';
import '../stylesheets/editDepositionView.styl';
import template from '../templates/editDepositionView.pug';

function isDefined(value) {
  return value !== null && value !== undefined && value !== '';
}

const EditDepositionView = View.extend({
  events: {
    'dragstart .g-creators-list li': 'addDragging',
    'dragend .g-creators-list li': 'removeDragging',
    'dragover .g-creators-list': 'dragOver',
    'drop .g-creators-list': function (event) {
        this.drop(event, '.g-creators-list');
        this._updateCreators();
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
      this.identifiersWidget._updateIdentifiers();  // Saves state
      const alternateIdentifiers = this.identifiersWidget.identifiers.map((item) => {
        return { alternateIdentifier: item.value, alternateIdentifierType: item.type };
      });
      const data = {
        metadata: JSON.stringify({
          creators: this.creators,
          titles: [{title: metadata.title}],
          description: metadata.description,
          attributes: {alternateIdentifiers: alternateIdentifiers},
        }),
      };
      if (this.model) {
        this.updateDeposition(data);
      } else {
        data.prefix = `${metadata.governor}${metadata.governorLab}${metadata.material}${metadata.materialSubtype}`;
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
      }
    },
    'click #g-deposition-addCreator': function () {
      new AddCreatorDialog({
        el: $('#g-dialog-container'),
        parentView: this,
        creators: this.creators,
      }).on('g:creatorAdded', function (params) {
        //this.creatorsWidget.creators.push(params.creator);
        this.creatorsWidget.render();
      }, this).render();
    },
    'change #g-deposition-governor': function (event) {
      const selectedInstitution = event.target.value;
      this.$('#g-deposition-governorLab').empty();
      this.$('#g-deposition-governorLab').append($('<option>', {
        value: 'X',
        text: 'Select a lab (or leave blank)',
      }));
      let currentChar = 64;
      Object.entries(this.igsnInstitutions[selectedInstitution].labs).forEach(([labCode, labName]) => {
        this.$('#g-deposition-governorLab').append($('<option>', {
          value: labCode,
          text: labName,
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
    this.form = null;
    this.model = settings && settings.model ? settings.model : null;
    this.creators = settings && settings.model ? settings.model.getFormCreators() : [];
    this.identifiers = settings && settings.model ? settings.model.getFormIdentifiers() : [];
    this.creatorsWidget = new CreatorsWidget({creators: this.creators, parentView: this})
    this.identifiersWidget = new IdentifiersWidget({parentView: this, identifiers: this.identifiers});
    restRequest({
      method: 'GET',
      url: 'deposition/settings'
    }).done((resp) => {
      this.igsnInstitutions = resp['igsn_institutions'];
      this.igsnMaterials = resp['igsn_materials'];
      this.render();
    });
  },
  render: function () {
    if (this.model) {
      this.form = this.$el.html(template({
        igsn: this.model.get('igsn'),
        institutions: [],
        materials: [],
      }));
      this.$('#g-deposition-title').val(this.model.get('metadata').titles[0].title);
      this.$('#g-deposition-description').val(this.model.get('metadata').description);
    } else {
      this.form = this.$el.html(template({
        igsn: null,
        institutions: this.igsnInstitutions,
        materials: Object.entries(this.igsnMaterials),
      }));
    }
    this.creatorsWidget.setElement(this.$('.g-creators-container')).render();
    this.identifiersWidget.setElement(this.$('.g-identifiers-container')).render();
    return this;
  },
  updateDeposition: function(data) {
      this.model.set({ metadata: data.metadata }).save().done(() => {
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
  _updateCreators: function () {
      let items = this.$('.g-creators-list li').toArray();
      this.creators = items.map((item) => {
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
