import $ from 'jquery';

import '@girder/core/utilities/jquery/girderModal';
import AddCreatorDialogTemplate from '../../templates/widgets/addCreatorDialog.pug';

import '../../stylesheets/addCreatorDialog.styl';

import 'bootstrap-autocomplete';

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
    'autocomplete.select input#autocomplete': function (event, ui) {
      console.log('Selected: ' + ui.item.value);
    },
  },

  initialize: function (settings) {
    this.settings = settings;
    this.creators = settings.creators || [];
    this.creatorType = settings.creatorType || 'person';
  },

  render: function () {
    this.$el.html(AddCreatorDialogTemplate({creatorType: this.creatorType})).girderModal(this);
    const view = this;
    $('.basicModalAutoSelect').autoComplete(
      {
        bootstrapVersion: "3" ,
        minChars: 4,
        resolverSettings: {
          url: '/api/v1/deposition/autocomplete',
          queryKey: 'query'
        },
        formatResult: function (item) {
          // Extract the text from the item: last name, first name (orcid) - institution
          const data = view._parseAutocomplete(item);

          return {
            value: item.id,
            text: item.text,
            html: `${data.firstName} ${data.lastName} <span class="text-muted">(${data.orcid})</span><p><span class="text-muted,small">${data.institution}</span></p>`,
          };
        },
        events: {
          searchPost: function (resultsFromServer, origJQElement) {
            $('ul.bootstrap-autocomplete').css("display", "block");
            return resultsFromServer;
          }
        }
      }
    );
    $('.basicModalAutoSelect').on('autocomplete.select', function (event, item) {
        const data = view._parseAutocomplete(item);
        view.$el.find('input[name="firstName"]').val(data.firstName);
        view.$el.find('input[name="lastName"]').val(data.lastName);
        view.$el.find('input[name="identifiers"]').val(`orcid:${data.orcid}`);
        view.$el.find('input[name="affiliations"]').val(data.institution);
        $('.basicModalAutoSelectSelected').html(JSON.stringify(item, null, 2));
        $('ul.bootstrap-autocomplete').css("display", "none");
    });
    return this;
  },

  _parseAutocomplete: function (item) {
    let text = item.text;
    let parts = text.split(' - ');
    let institution = parts[1];
    let namesId = parts[0].split(' (');
    let orcid = namesId[1].replace(')', '');
    let names = namesId[0].split(', ');
    let lastName = names[0];
    let firstName = names[1];

    return {
      firstName: firstName,
      lastName: lastName,
      orcid: orcid,
      institution: institution,
    }
  },

  _addCreator: function () {
    const formEntry = $('#g-add-creator-form').serializeArray();
    const creator = formEntry.reduce((obj, item) => {
      obj[item.name] = item.value;
      return obj;
    }, {});
    if (creator) {
      this.creators.push(creator);
      this.trigger('g:creatorAdded', {creator: creator});
      this.settings.parentView.trigger('g:creatorAdded', {creator: creator});
      // this.settings.parentView.render();
    }
    this.$el.modal('hide');
  },
});

export default AddCreatorDialog;
