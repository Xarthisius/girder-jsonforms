import $ from 'jquery';
import 'bootstrap-autocomplete';

import template from '../templates/projectView.pug';

const events = girder.events;
const router = girder.router;
const { restRequest } = girder.rest;
const View = girder.views.View;

var ProjectView = View.extend({
    events: {
        'click .g-back-to-projects': function (event) {
            router.navigate('projects', { trigger: true });
        },
        'submit .g-add-sample-form': function (event) {
            event.preventDefault();
            const igsn = this.$el.find('input[name="sampleIgsn"]').val().trim();
            if (!igsn) {
                return;
            }
            const samples = this.model.get('samples') || [];
            if (samples.includes(igsn)) {
                return;
            }
            this._updateSamples(samples.concat([igsn]));
        },
        'click .g-remove-sample': function (event) {
            const igsn = this.$(event.currentTarget).data('igsn');
            const samples = (this.model.get('samples') || []).filter((s) => s !== igsn);
            this._updateSamples(samples);
        }
    },

    initialize: function (settings) {
        this.model = settings.model;
        this.render();
    },

    _updateSamples: function (samples) {
        this.model.updateSamples(samples).done(() => {
            this.render();
        }).fail((resp) => {
            events.trigger('g:alert', {
                text: (resp.responseJSON && resp.responseJSON.message) || 'Failed to update samples.',
                type: 'danger'
            });
        });
    },

    render: function () {
        this.$el.html(template({
            project: this.model
        }));

        $('.g-add-sample-field', this.el).autoComplete({
            bootstrapVersion: '3',
            minChars: 2,
            resolver: 'custom',
            events: {
                search: (query, callback) => {
                    restRequest({
                        method: 'GET',
                        url: 'deposition',
                        data: { igsnPrefix: query, limit: 10 },
                        error: null
                    }).done((results) => {
                        callback(results);
                    });
                },
                searchPost: (resultsFromServer) => {
                    $('ul.bootstrap-autocomplete').css('display', 'block');
                    return resultsFromServer;
                }
            },
            formatResult: (item) => {
                return {
                    value: item.igsn,
                    text: item.igsn,
                    html: item.igsn
                };
            }
        });
        $('.g-add-sample-field', this.el).on('autocomplete.select', (event) => {
            $('ul.bootstrap-autocomplete').css('display', 'none');
        });
        return this;
    }
});

export default ProjectView;
