import router from 'girder/router';
import events from 'girder/events';

import FormModel from './models/FormModel';
import FormListView from './views/FormListView';
import FormView from './views/FormView';

router.route('forms', 'forms', function () {
    events.trigger('g:navigateTo', FormListView);
});


router.route('form/:id', 'form', function (id, params) {
    const item = new FormModel({_id: id});
    const promises = [item.fetch()];

    $.when(...promises).done(() => {
        events.trigger('g:navigateTo', FormView, {
            model: item
        }, {
            renderNow: true
        });
    }).fail(() => {
        router.navigate('forms', {trigger: true, replace: true});
    });
});
