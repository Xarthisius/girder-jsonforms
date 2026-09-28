import $ from 'jquery';
import 'bootstrap-autocomplete';

import FormCollection from '../../collections/FormCollection';
import LinkEntryToDepositionTemplate from '../../templates/linkEntryToDeposition.pug';

const View = girder.views.View;
const { handleClose, handleOpen } = girder.dialog;
const { restRequest } = girder.rest;


var LinkEntryToDepositionWidget = View.extend({
  events: {
      'submit #g-link-entry-form': function (e) {
          e.preventDefault();
          this.$('button#submit-link-btn').girderEnable(false);
          this.$('.g-validation-failed-message').empty();
          this.linkEntryToDepositions();
      },
  },

  initialize: function (settings) {
    this.depositionIds = settings.depositionIds || [];
    this.formCollection = settings.formCollection || new FormCollection();
    this.currentLocationHash = window.location.hash;
    this.formCollection.fetch().done(() => {
      this.render();
    });
  },

  render: function () {
    const depositionCount = this.depositionIds.length;
    const view = this;
    var modal = this.$el.html(
      LinkEntryToDepositionTemplate({
          forms: this.formCollection.toArray(),
          depositionCount: depositionCount
      })
    ).girderModal(this).on('hidden.bs.modal', function () {
      window.location.hash = view.currentLocationHash;
      handleClose('entryLink');
      modal.trigger('g:hidden');
    });
    $('.g-entry-autocomplete').autoComplete({
      bootstrapVersion: "3",
      minChars: 2,
      resolver: 'custom',
      formatResult: function (item) {
        const parts = item.split(';');
        return {
          value: parts[0],
          text: parts[1],
          html: `${parts[1]} <span class="text-muted">(${parts[0]})</span>`,
        };
      },
      events: {
        search: function (qry, callback) {
          const cid = view.$('select#g-form-select').find('option:selected').attr('g-form-cid');
          const form = view.formCollection.get(cid);
          restRequest({
            method: 'GET',
            url: 'entry/search',
            data: { query: qry, formId: form.id, field: form.get('uniqueField'), limit: 10 },
            error: null,
          }).done((results) => {
            callback(results);
          });
        },
        searchPost: function (resultsFromServer, origJQElement) {
          $('ul.bootstrap-autocomplete').css("display", "block");
          return resultsFromServer;
        }
      }
    });
    $('.g-entry-autocomplete').on('autocomplete.select', function (event, item) {
        $('ul.bootstrap-autocomplete').css("display", "none");
        event.preventDefault();
    });
    modal.trigger($.Event('ready.girder.modal', { relatedTarget: modal }));
    handleOpen('entryLink');
    return this;
  },

  linkEntryToDepositions: function () {
    const entryId = this.$el.find('input[name="entryId"]').val();
    const depositionIds = Object.keys(this.parentView.depositionCheckedStates);
    const action = this.$('select#g-link-action').val();
    if (depositionIds.length === 0) {
      this.$('.g-validation-failed-message').text('Please select at least one deposition to link.');
      this.$('button#submit-link-btn').girderEnable(true);
      return;
    }
    restRequest({
      type: 'POST',
      url: 'deposition/relation?entryId=' + entryId + '&action=' + action,
      data: JSON.stringify(depositionIds),
      contentType: 'application/json',
      error: null,
    }).done(() => {
      this.$el.modal('hide');
      girder.events.trigger('g:alert', {
        icon: 'ok',
        text: 'Entry successfully linked to selected depositions.',
        type: 'success',
        timeout: 4000,
      });
    }).fail((err) => {
      this.$('.g-validation-failed-message').text(err.responseJSON.message);
      this.$('button#submit-link-btn').girderEnable(true);
    });
  }
});

export default LinkEntryToDepositionWidget;
