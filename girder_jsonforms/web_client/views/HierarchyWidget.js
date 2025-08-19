const $ = girder.$;
const { wrap } = girder.utilities.PluginUtils;
const HierarchyWidget = girder.views.widgets.HierarchyWidget;

import NamedSortCollectionWidget from './widgets/NamedSortCollectionWidget';
import '../stylesheets/hierarchyWidget.styl';

wrap(HierarchyWidget, 'initialize', function (initialize, ...args) {
    this.sortCollectionWidget = null;
    initialize.apply(this, args);
    this.sortCollectionWidget = new NamedSortCollectionWidget({
        name: "HierarchyFolderSort",
        parentView: this,
        collection: this.folderListView.collection,
        fields: {
          lowerName: 'Name',
          created: 'Created',
          updated: 'Updated',
        },
    });
    this.render();
});

wrap(HierarchyWidget, 'render', function (render) {
    render.call(this);

    if (this.sortCollectionWidget) {
        const folderHeader = this.$('.g-folder-header-buttons');
        const sortDiv = $('<div class="g-folder-sort">');
        folderHeader.before(sortDiv);
        this.sortCollectionWidget.setElement(sortDiv).render();
    }
    return this;
});
