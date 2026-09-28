import ProjectModel from '../models/ProjectModel';

const Collection = girder.collections.Collection;

var ProjectCollection = Collection.extend({
    resourceName: 'project',
    model: ProjectModel,
    pageLimit: 50,
    sortField: 'name',
    sortDir: 1
});

export default ProjectCollection;
