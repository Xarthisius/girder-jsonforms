const AccessControlledModel = girder.models.AccessControlledModel;

var DepositionModel = AccessControlledModel.extend({
    resourceName: 'deposition',

    getFormCreators: function () {
        const metadata = this.get('metadata');
        if (metadata && metadata.creators) {
            return metadata.creators.map(function (creator) {
              const orcid = creator.nameIdentifiers && creator.nameIdentifiers.length > 0 ? creator.nameIdentifiers[0].nameIdentifier.match(/orcid.org\/(\d{4}-\d{4}-\d{4}-\d{3}[0-9X])/)[1] : '';
              let affiliation = '';
              if (creator.affiliation && creator.affiliation.length > 0) {
                 const aff = creator.affiliation[0];
                 affiliation = `${aff.name} - ${aff.affiliationIdentifier}`
              }
              return {
                givenName: creator.givenName || '',
                familyName: creator.familyName || '',
                identifiers: `orcid:${orcid || ''}`,
                nameType: creator.nameType || 'Personal',
                affiliations: affiliation
              }
          });
        }
        return [];
    },

    getFormIdentifiers: function () {
        const metadata = this.get('metadata');
        if (metadata && metadata.alternateIdentifiers) {
            return metadata.alternateIdentifiers.map(identifier => ({
                type: identifier.alternateIdentifierType,
                value: identifier.alternateIdentifier
            }));
        }
        return [];
    },

    getFormRelatedIdentifiers: function () {
        const metadata = this.get('metadata');
        if (metadata && metadata.relatedIdentifiers) {
            return metadata.relatedIdentifiers
        }
        return [];
    }
});

export default DepositionModel;
