import DataCiteCardTemplate from '../templates/collectionLandingPage.pug';
import '../stylesheets/collectionLandingPage.styl';


const $ = girder.$;
const _ = girder._;
const View = girder.views.View;
const Model = girder.models.Model;


var DataCiteCardView = View.extend({
    className: 'doi-card-embed',

    events: {
        'click .toggle-collapse-btn': 'toggleCollapse'
    },
    
    initialize: function(options) {
        options = options || {};
        this.url = options.url || 'https://girder.local.xarthisius.xyz/api/v1/item/6a3fdf289fbbe2709f3bd0f1/download';
        this.isExpanded = true;

        // If a model wasn't passed to the view, instantiate a blank one
        if (!this.model) {
            this.model = new Model();
        }
        this.model.set({
            title: "title",
            doi: "doi",
            doiUrl: "doiUrl",
            publisher: "publisherName",
            year: "pubYear",
            creators: [],
            abstract: "abstractText",
            subjects: [],
            relatedIdentifiers: [],
            resourceType: "resourceType",
            version: "1.0",
            size: "Not specified",
            format: "Not specified",
            locationStr: "locStr",
            locationTitle: "locTitle",
            licenseStr: "All Rights Reserved",
            licenseUri: "#",
            funding: []
        });
        this.listenTo(this.model, 'change', this.render);
        this.fetchData();
    },

    toggleCollapse: function(e) {
        e.preventDefault();
        this.isExpanded = !this.isExpanded;
        
        // Toggle the wrapper class for CSS transitions
        this.$el.toggleClass('is-collapsed', !this.isExpanded);
        
        // Update accessibility attributes
        this.$('.toggle-collapse-btn').attr('aria-expanded', this.isExpanded);
    },
    
    fetchData: function() {
        var self = this;
        $.getJSON(this.url)
            .done(function(jsonData) {
                // Adapt logic from Python to handle structure variance
                var data = jsonData.data || {};
                var attributes = data.attributes ? data.attributes : (typeof data === 'object' ? data : {});
                
                self.model.set(self.parseAttributes(attributes));
            })
            .fail(function(jqXHR, textStatus, errorThrown) {
                console.error("Error fetching DataCite JSON:", textStatus, errorThrown);
            });
    },
    
    parseAttributes: function(attrs) {
        // 1. Title
        var titles = attrs.titles || [];
        var titleText = "Untitled Resource";
        if (titles.length > 0 && typeof titles[0] === 'object') {
            titleText = titles[0].title || "Untitled Resource";
        }
        
        // 2. DOI
        var doi = attrs.doi || "N/A";
        var doiUrl = doi !== "N/A" ? "https://doi.org/" + doi : "#";
        
        // 3. Authors & Affiliations Array
        var creators = attrs.creators || [];
        var processedCreators = _.map(creators, function(creator) {
            if (typeof creator !== 'object') return null;
            
            var orcidUrl = null;
            var nameIdentifiers = creator.nameIdentifiers || [];
            for (var i = 0; i < nameIdentifiers.length; i++) {
                var nid = nameIdentifiers[i];
                if (nid.nameIdentifierScheme === "ORCID" || (nid.nameIdentifier && nid.nameIdentifier.indexOf("orcid.org") !== -1)) {
                    var rawId = nid.nameIdentifier || "";
                    orcidUrl = rawId.indexOf("http") === 0 ? rawId : "https://orcid.org/" + rawId;
                    break;
                }
            }
            
            var affiliations = creator.affiliation || [];
            var processedAffs = _.map(affiliations, function(aff) {
                if (typeof aff !== 'object') return null;
                var affName = aff.name || "";
                var rorId = aff.affiliationIdentifier || "";
                var rorUrl = rorId ? (rorId.indexOf("http") === 0 ? rorId : "https://ror.org/" + rorId) : null;
                
                return { name: affName, rorUrl: rorUrl };
            }).filter(Boolean);
            
            return {
                name: creator.name || "Unknown Author",
                orcidUrl: orcidUrl,
                orcidId: orcidUrl ? orcidUrl.split("/").pop() : null,
                affiliations: processedAffs
            };
        }).filter(Boolean);
        
        // 4. Publisher & Year
        var publisherObj = attrs.publisher || {};
        var publisherName = typeof publisherObj === 'object' ? (publisherObj.name || "Unknown Publisher") : String(publisherObj);
        var pubYear = attrs.publicationYear || "N/A";
        
        // 5. Abstract
        var descriptions = attrs.descriptions || [];
        var abstractText = "No description or abstract available for this resource.";
        for (var j = 0; j < descriptions.length; j++) {
            if (typeof descriptions[j] === 'object' && descriptions[j].descriptionType === 'Abstract') {
                abstractText = descriptions[j].description || "";
                break;
            }
        }
        if (abstractText.indexOf("No description") === 0 && descriptions.length > 0) {
            abstractText = descriptions[0].description || abstractText;
        }
        
        // 6. Subjects
        var subjects = attrs.subjects || [];
        var processedSubjects = _.map(subjects, function(s) {
            if (typeof s !== 'object') return null;
            var name = s.subject || "";
            return name.indexOf("FOS: ") === 0 ? name.replace("FOS: ", "") : name;
        }).filter(Boolean);
        
        // 7. Related Identifiers
        var relatedIds = attrs.relatedIdentifiers || [];
        var processedRelatedIds = _.map(relatedIds, function(r) {
            if (typeof r !== 'object') return null;
            var relType = r.relationType || "Related";
            var relId = r.relatedIdentifier || "";
            var genType = r.resourceTypeGeneral || "Resource";
            var idType = r.relatedIdentifierType || "";
            
            var href = (relId.indexOf("http") === 0 || idType !== "DOI") ? relId : "https://doi.org/" + relId;
            var diplayId = relId.indexOf("doi.org") !== -1 ? relId.replace("https://doi.org/", "") : relId;
            if (diplayId.length > 40) {
                diplayId = diplayId.substring(0, 25) + "..." + diplayId.substring(diplayId.length - 10);
            }
            
            return { type: relType, href: href, display: diplayId, generalType: genType };
        }).filter(Boolean);
        
        // 8. Sidebar details
        var types = attrs.types || {};
        var resourceType = types.schemaOrg || "Dataset";
        if (types.resourceType) {
            resourceType += " (" + types.resourceType + ")";
        }
        if (resourceType.indexOf("(") !== -1 && resourceType.indexOf("())") !== -1) {
            resourceType = types.schemaOrg || "Dataset";
        }
        
        var sizes = attrs.sizes || [];
        var formats = attrs.formats || [];
        var locations = attrs.geoLocations || [];
        var rights = attrs.rightsList || [];
        
        var locStr = "Not Specified";
        var locTitle = "";
        if (locations.length > 0 && typeof locations[0] === 'object') {
            locStr = locations[0].geoLocationPlace || "Coordinates Provided";
            var point = locations[0].geoLocationPoint || {};
            if (point.pointLatitude) {
                locTitle = "Lat: " + point.pointLatitude + ", Long: " + point.pointLongitude;
            }
        }
        
        var fundingList = attrs.fundingReferences || [];
        var processedFunding = _.map(fundingList, function(fund) {
            if (typeof fund !== 'object') return null;
            return {
                funder: fund.funderName || "Unknown Funder",
                awardNum: fund.awardNumber || "",
                awardTitle: fund.awardTitle || ""
            };
        }).filter(Boolean);

        return {
            title: titleText,
            doi: doi,
            doiUrl: doiUrl,
            publisher: publisherName,
            year: pubYear,
            creators: processedCreators,
            abstract: abstractText,
            subjects: processedSubjects,
            relatedIdentifiers: processedRelatedIds,
            resourceType: resourceType,
            version: attrs.version || "1.0",
            size: sizes.length > 0 ? sizes[0] : "Not specified",
            format: formats.length > 0 ? formats[0] : "Not specified",
            locationStr: locStr,
            locationTitle: locTitle,
            licenseStr: rights.length > 0 ? (rights[0].rights || "Restricted Access") : "All Rights Reserved",
            licenseUri: rights.length > 0 ? (rights[0].rightsUri || "#") : "#",
            funding: processedFunding
        };
    },
    
    render: function() {
        var context = _.extend({}, this.model.toJSON(), {
            isExpanded: this.isExpanded
        });
        this.$el.html(DataCiteCardTemplate(context));

        this.$el.toggleClass('is-collapsed', !this.isExpanded);
        return this;
    }
});

export default DataCiteCardView;
