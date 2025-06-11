import DepositionModel from '../../models/DepositionModel';
import ImportToFormDialogTemplate from '../../templates/widgets/importToFormDialog.pug';
import '@girder/core/utilities/jquery/girderModal';

const FolderModel = girder.models.FolderModel;
const View = girder.views.View;
const UploadWidget = girder.views.widgets.UploadWidget;
const SearchFieldWidget = girder.views.widgets.SearchFieldWidget;
const { getCurrentUser } = girder.auth;
const { restRequest } = girder.rest;

function makeid(length) {
    let result = '';
    const characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    const charactersLength = characters.length;
    let counter = 0;
    while (counter < length) {
        result += characters.charAt(Math.floor(Math.random() * charactersLength));
        counter += 1;
    }
    return result;
}

var ImportToFormDialog = View.extend({
  events: {
    'submit #g-import-form': function (event) {
        event.preventDefault();
        console.log('Selected deposition:', this.deposition);
        console.log('Temp folder:', this.tempFolder);
        restRequest({
            method: 'POST',
            url: `form/${this.model.id}/ingest`,
            data: {
              folderId: this.tempFolder.id,
              depositionId: this.deposition.id,
              progress: true // enable progress updates
            }
        }).done((resp) => {
            this.trigger('g:alert', {
              text: "Files imported to form successfully",
              type: 'success',
            });
        }).fail((err) => {
            this.trigger('g:alert', {
              text: err.responseJSON.message || 'Error importing files to form',
              type: 'danger',
            });
        });
        this.$el.modal('hide');
    }
  },

  initialize: function (settings) {
    this.settings = settings;
    this.currentUser = getCurrentUser();
    this.tempFolder = new FolderModel({
      name: `ImportToForm_${this.model.id}_${makeid(5)}`,
      parentType: 'user',
      parentId: this.currentUser.get('_id')
    });
    const view = this;
    this.deposition = new DepositionModel();
    this.searchWidget = new SearchFieldWidget({
        placeholder: 'Select IGSN',
        types: ['deposition'],
        parentView: this,
        modes: ['igsnText'],
        getInfoCallback: this._getInfoCallback,
        noResultsPage: false,
    }).on('g:resultClicked', this._igsnSelected, this);
    this.tempFolder.save().done(() => {
      console.log('Temp folder created:', this.tempFolder);
      view.fileUploader = new UploadWidget({
        parent: view.tempFolder,
        parentType: "folder",
        title: "Files for processing",
        modal: false,
        multiFile: true,
        parentView: this,
      });
      this.listenTo(view.fileUploader, 'g:uploadFinished', view._onUploadFinished);
      this.render();
    });
  },

  render: function () {
    if (!this.fileUploader) {
      return this;
    }
    this.$el.html(ImportToFormDialogTemplate({
      settings: this.settings
    })).girderModal(this);

    this.searchWidget.setElement(this.$('.g-deposition-search-container')).render();
    this.fileUploader
        .render()
        .$el.appendTo(this.$('.g-form-upload-container'));
    //this.$('#g-import-form').on('submit', this._onSubmit.bind(this));
    return this;
  },

  _igsnSelected: function (result) {
    const view = this;
    this.deposition.set({_id: result.id, igsn: result.igsn}).once('g:fetched', function() {
        view.searchWidget.hideResults();
        view.searchWidget.clearText();
        view.searchWidget.$('.g-search-field').value = view.deposition.attributes.igsn;
        console.log('Selected deposition:', view.deposition);
        view.$('.g-selected-deposition-container span.g-info-type').text(view.deposition.attributes.igsn);
        view.$('.g-selected-deposition-container').removeClass('hide');
        view.setSubmitEnabled(true);
    }, this).fetch();
  },

  _getInfoCallback: function (type, result) {
    // returns {icon: , text: } for every result
    if (result.metadata && result.metadata.attributes && result.metadata.attributes.alternateIdentifiers) {
      var id = result.metadata.attributes.alternateIdentifiers.find(
        (id) => id.alternateIdentifierType.toLowerCase() === 'local'
      );
      if (id) {
        return {
          icon: 'barcode',
          text: `${result.igsn} (${id.alternateIdentifier}) - ${result.metadata.titles[0].title}`
        };
      }
    }
    return {
        icon: 'barcode',
        text: `${result.igsn} - ${result.metadata.titles[0].title}`
    };

  },

  setSubmitEnabled: function (state) {
    this.$('.g-import-form-btn').girderEnable(state);
  },

  _onUploadFinished: function (event) {
    console.log('Upload finished:', event.files);
    //this.$('.g-form-upload-container').addClass('hide');
    //this.$('.g-form-processing-container').removeClass('hide');
  }

});

export default ImportToFormDialog;
