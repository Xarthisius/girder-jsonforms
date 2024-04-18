import router from 'girder/router';
import events from 'girder/events';

import FormModel from './models/FormModel';
import FormEntryModel from './models/FormEntryModel';
import FormListView from './views/FormListView';
import EditFormView from './views/EditFormView';

router.route('forms', 'forms', function () {
    events.trigger('g:navigateTo', FormListView);
});

router.route('form/:id/entry', 'form', function (id, params) {
    const item = new FormModel({_id: id});
    const promises = [item.fetch()];
    const entry = params && params.entryId ? new FormEntryModel({_id: params.entryId}) : null;
    if (entry) {
        promises.push(entry.fetch());
    }

    $.when(...promises).done(() => {
        if (entry && entry.get('formId') !== id) {
            // If the entry does not belong to the form, redirect to the form
            router.navigate('form/' + id + '/entry', {trigger: true, replace: true});
            return;
        }
        events.trigger('g:navigateTo', EditFormView, {
            model: item,
            initialValues: entry
        }, {
            renderNow: true
        });
    }).fail(() => {
        router.navigate('forms', {trigger: true, replace: true});
    });
});
