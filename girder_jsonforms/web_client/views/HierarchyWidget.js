import NamedSortCollectionWidget from './widgets/NamedSortCollectionWidget';
import '../stylesheets/hierarchyWidget.styl';

const $ = girder.$;
const { wrap } = girder.utilities.PluginUtils;
const HierarchyWidget = girder.views.widgets.HierarchyWidget;

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

wrap(HierarchyWidget, 'updateChecked', function (updateChecked) {
    // This is called when descends/ascends the hierarchy. We need to update the collection
    updateChecked.call(this);
    this.sortCollectionWidget.collection = this.folderListView.collection;
    return this;
});
