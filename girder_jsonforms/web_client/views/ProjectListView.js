import ProjectCollection from '../collections/ProjectCollection';
import template from '../templates/projectListView.pug';

const View = girder.views.View;
const PaginateWidget = girder.views.widgets.PaginateWidget;
const router = girder.router;

var ProjectListView = View.extend({
    events: {
        'click .g-project-link': function (event) {
            event.preventDefault();
            const projectId = this.$(event.currentTarget).data('projectId');
            router.navigate(`project/${projectId}`, { trigger: true });
        }
    },

    initialize: function () {
        this.collection = new ProjectCollection();
        this.collection.on('g:changed', () => {
            this.render();
        });
        this.paginateWidget = new PaginateWidget({
            collection: this.collection,
            parentView: this
        });
        this.collection.fetch();
    },

    render: function () {
        this.$el.html(template({
            projects: this.collection.toArray()
        }));

        this.paginateWidget.setElement(this.$('.g-project-pagination')).render();
        return this;
    }
});

export default ProjectListView;
