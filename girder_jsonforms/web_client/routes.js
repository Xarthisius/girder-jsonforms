import $ from 'jquery';
import DepositionModel from './models/DepositionModel';
import DepositionView from './views/DepositionView';
import DepositionListView from './views/DepositionListView';
import FormModel from './models/FormModel';
import FormEntryModel from './models/FormEntryModel';
import FormView from './views/FormView';
import FormListView from './views/FormListView';
import EditFormView from './views/EditFormView';
import EditDepositionView from './views/EditDepositionView';

const router = girder.router;
const events = girder.events;

router.route('forms', 'forms', function () {
    events.trigger('g:navigateTo', FormListView);
});

router.route('depositions', 'depositions', function () {
    events.trigger('g:navigateTo', DepositionListView);
});

router.route('newdeposition', 'deposition', function () {
    events.trigger('g:navigateTo', EditDepositionView);
});

router.route('deposition/:id', 'deposition', function (id) {
    const deposition = new DepositionModel({_id: id});
    deposition.fetch().done(() => {
      events.trigger('g:navigateTo', DepositionView, {
            model: deposition
        }, {
            renderNow: true
        });
    }).fail(() => {
        router.navigate('depositions', {trigger: true, replace: true});
    });
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

router.route('form/:id', 'form', function (id) {
    const item = new FormModel({_id: id});
    item.fetch().done(() => {
        events.trigger('g:navigateTo', FormView, {
            model: item
        }, {
            renderNow: true
        });
    }).fail(() => {
        router.navigate('forms', {trigger: true, replace: true});
    });
});
