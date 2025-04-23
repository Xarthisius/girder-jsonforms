const $ = girder.$;
const ItemView = girder.views.body.ItemView;
const { wrap } = girder.utilities.PluginUtils;

wrap(ItemView, 'render', function (render) {
  this.once('g:rendered', () => {
    if (this.model.get('meta') && this.model.get('meta')['igsn']) {
      var object = $(
        '<div class="g-item-igsn g-info-list-entry"><i class="icon-barcode"></i> IGSN: <a href="#igsn/'
        + encodeURIComponent(this.model.get('meta')['igsn']) + '">' + this.model.get('meta')['igsn'] + '</a></div>'
      );
      this.$('.g-item-info').append(object);
    }
  });
  return render.call(this);
});
