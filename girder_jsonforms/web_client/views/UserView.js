const _ = girder._;
const { getCurrentUser } = girder.auth;
const { restRequest } = girder.rest;
const UserView = girder.views.body.UserView;
const { wrap } = girder.utilities.PluginUtils;

import { SearchResultsTypeView } from './DepositionView';
import UserPageSearchTemplate from '../templates/userPageSearch.pug';
import UserPageTabsTemplate from '../templates/userPageTabs.pug'; 

var _initialize = UserView.prototype.initialize;
UserView.prototype.initialize = function (settings) {
    this.currentView = settings.currentView || 'list';
    this._searchRequest = restRequest({
        url: 'resource/search',
        data: {
          q: settings.user.id,
          mode: 'byCreator',
          types: JSON.stringify(['folder', 'item']),
          limit: 10,
        }
    });
    this._subviews = {};
    let currentUser = getCurrentUser();
    this.owner = currentUser && currentUser.id === settings.user.id;
    _initialize.apply(this, arguments);
};

wrap(UserView, 'render', function (render) {
    render.call(this);
    this.$('.g-user-header').after(
        UserPageTabsTemplate({
            currentView: this.currentView,
            owner: this.owner
        })
    );
    this.$('.g-user-hierarchy-container').after(
        UserPageSearchTemplate({
            currentView: this.currentView,
            owner: this.owner
        })
    );
    if (this.currentView === 'search') {
        this.$('.g-user-hierarchy-container').hide();
        this.$('.g-search-container').show();
    } else {
        this.$('.g-user-hierarchy-container').show();
        this.$('.g-search-container').hide();
    }
    this.$('a[data-toggle="tab"]').on('shown.bs.tab', (e) => {
        this.currentView = $(e.currentTarget).attr('name');
        this.render();
    });
    const userId = this.model.id;
    this._searchRequest.done((results) => {
        this.$('.g-search-pending').hide();

        const resultTypes =  _.keys(results);
        const orderedTypes = ["folder", "item"];
        _.each(orderedTypes, (type) => {
            if (results[type].length) {
                this._subviews[type] = new SearchResultsTypeView({
                    parentView: this,
                    query: userId,
                    mode: "byCreator",
                    type: type,
                    limit: this.pageLimit,
                    initResults: results[type],
                    sizeOneElement: this._sizeOneElement
                }).render();
                this._subviews[type].$el
                    .appendTo(this.$('.g-search-results-container'));
            }
        });

        if (_.isEmpty(this._subviews)) {
            this.$('.g-search-no-results').show();
        }
    });
    return this;
});
