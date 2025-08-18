const $ = girder.$;
const { wrap } = girder.utilities.PluginUtils;
const HierarchyWidget = girder.views.widgets.HierarchyWidget;
const SortCollectionWidget = girder.views.widgets.SortCollectionWidget;

import '../stylesheets/hierarchyWidget.styl';

wrap(HierarchyWidget, 'initialize', function (initialize, ...args) {
    this.sortCollectionWidget = new SortCollectionWidget({
        parentView: this,
        collection: null,
        fields: {
          lowerName: 'Name',
          created: 'Created',
          updated: 'Updated',
        },
    });
    initialize.apply(this, args);
});

wrap(HierarchyWidget, 'render', function (render) {
    this.sortCollectionWidget.collection = this.folderListView.collection;
    render.call(this);
    const folderHeader = this.$('.g-folder-header-buttons');
    const sortDiv = $('<div class="g-folder-sort">');
    folderHeader.before(sortDiv);
    this.sortCollectionWidget.setElement(sortDiv).render();
    return this;
});
