import $ from 'jquery';

const { restRequest } = girder.rest;
const View = girder.views.View;

import AddCreatorDialog from './widgets/AddCreatorDialog';
import '../stylesheets/editDepositionView.styl';
import template from '../templates/editDepositionView.pug';

const EditDepositionView = View.extend({
  events: {
    'submit #g-deposition-form': function (event) {
        console.log('submitted !!!!!');
    },
    'click #g-deposition-addCreator': function () {
      console.log('add creator');
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
      this.render();
    });
  },
  render: function () {
    this.$el.html(template({
      institutions: this.igsnInstitutions,
      materials: Object.entries(this.igsnMaterials),
      creators: this.creators
    }));
    return this;
  },
});

export default EditDepositionView;
