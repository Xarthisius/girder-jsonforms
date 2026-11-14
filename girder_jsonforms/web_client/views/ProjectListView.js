import ProjectCollection from '../collections/ProjectCollection';
import template from '../templates/projectListView.pug';
import '../stylesheets/projectStatus.styl';
import '../stylesheets/projectListView.styl';
import labels from './projectLabels.js';

const View = girder.views.View;
const PaginateWidget = girder.views.widgets.PaginateWidget;
const router = girder.router;
const { DATE_DAY, formatDate } = girder.misc;

var ProjectListView = View.extend({
    events: {
        'click .g-project-link': function (event) {
            event.preventDefault();
            const projectId = this.$(event.currentTarget).data('projectId');
            router.navigate(`project/${projectId}`, { trigger: true });
        },
        // The whole row opens the project; the link inside it stays a real link so
        // middle-click and "open in new tab" still work.
        'click .g-project-row': function (event) {
            if (event.target.closest('a')) {
                return;
            }
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
            projects: this.collection.toArray(),
            labels: labels,
            formatDate: formatDate,
            DATE_DAY: DATE_DAY
        }));

        this.paginateWidget.setElement(this.$('.g-project-pagination')).render();
        return this;
    }
});

export default ProjectListView;
