const $ = girder.$;
const FolderListWidget = girder.views.widgets.FolderListWidget;
const { wrap } = girder.utilities.PluginUtils;
const router = girder.router;

import '../stylesheets/folderListWidget.styl';

wrap(FolderListWidget, 'render', function (render) {
    render.call(this);

    if (this.collection.length) {
        this.$('.g-folder-list-link').each((i, el) => {
            const $el = $(el);
            const cid = $el.attr("g-folder-cid");
            const folder = this.collection.get(cid);
            // show the date as Feb 16 09:24
            const updated = new Date(folder.get('updated')).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
            // create a div with icon and updated date
            const icon = '<i class="icon-pencil"></i>';
            const updatedHtml = `<span class="g-folder-updated">${icon} ${updated}</span>`;
            $el.nextAll().last().after(updatedHtml);
        });
    }

    return this;
});
