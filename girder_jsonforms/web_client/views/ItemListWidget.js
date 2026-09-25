import '../stylesheets/itemListWidget.styl';

const $ = girder.$;
const ItemListWidget = girder.views.widgets.ItemListWidget;
const { wrap } = girder.utilities.PluginUtils;

wrap(ItemListWidget, 'render', function (render) {
    render.call(this);

    if (this.collection.length) {
        this.$('.g-item-list-link').each((i, el) => {
            const $el = $(el);
            const cid = $el.attr("g-item-cid");
            const item = this.collection.get(cid);
            // show the date as Feb 16 2024, 09:24
            const options = { month: 'short', day: 'numeric', year: 'numeric',  hour: '2-digit', minute: '2-digit' };
            const updated = new Date(item.get('updated')).toLocaleString('en-US', options);
            // create a div with icon and updated date
            const icon = '<i class="icon-pencil"></i>';
            const updatedHtml = `<span class="g-item-updated">${icon} ${updated}</span>`;
            $el.nextAll().last().after(updatedHtml);
        });
    }

    return this;
});
