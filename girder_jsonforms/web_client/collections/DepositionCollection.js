import DepositionModel from '../models/DepositionModel';

const _ = girder._;
const Collection = girder.collections.Collection;
const { restRequest } = girder.rest;

var DepositionCollection = Collection.extend({
    resourceName: 'deposition',
    model: DepositionModel,
    pageLimit: 16,
    sortField: 'igsn',
    sortDir: 1,
    level: 2,

    updateFromSession: function () {
        if (window.sessionStorage.getItem(`${this.resourceName}.sortField`) !== null) {
            this.sortField = window.sessionStorage.getItem(`${this.resourceName}.sortField`);
        }
        if (window.sessionStorage.getItem(`${this.resourceName}.sortDir`) !== null) {
            this.sortDir = parseInt(window.sessionStorage.getItem(`${this.resourceName}.sortDir`), 10);
        }
        if (window.sessionStorage.getItem(`${this.resourceName}.level`) !== null) {
            this.level = parseInt(window.sessionStorage.getItem(`${this.resourceName}.level`), 10);
        }
        if (window.sessionStorage.getItem(`${this.resourceName}.offset`) !== null) {
            this.offset = parseInt(window.sessionStorage.getItem(`${this.resourceName}.offset`), 10);
        }
    },

    fetch: function (params, reset) {
        if (this.altUrl === null && this.resourceName === null) {
            throw new Error('An altUrl or resourceName must be set on the Collection.');
        }

        if (this.filterFunc && !this.append) {
            this.pageOffsetStack = this.pageOffsetStack || [];
        }

        if (reset) {
            if (this.filterFunc && !this.append) {
                this.pageOffsetStack = [];
            }
            this.offset = 0;
        } else {
            this.params = params || {};
        }

        if (this.filterFunc && !this.append) {
            this.pageOffsetStack.push(this.offset);
        }

        var limit = this.pageLimit > 0 ? this.pageLimit + 1 : 0;

        var finalList = []; /* will be built up in pieces */

        function fetchListFragment() {
            var xhr = restRequest({
                url: this.altUrl || this.resourceName,
                data: _.extend({
                    limit: limit,
                    offset: this.offset,
                    sort: this.sortField,
                    sortdir: this.sortDir,
                    level: this.level
                }, this.params)
            });

            var result = xhr.then((list) => {
                if (this.pageLimit > 0 && list.length > this.pageLimit) {
                    // This means we have more pages to display still. Pop off
                    // the extra that we fetched.
                    list.pop();
                    this._totalCount = xhr.getResponseHeader('girder-total-count');
                    this._hasMorePages = true;
                } else {
                    this._hasMorePages = false;
                }

                var offsetDelta = list.length;

                /*
                 * If filtering, decorate the list with their pre-filtered
                 * indexes.  The index will be needed when adjusting the offset.
                 */
                if (this.filterFunc) {
                    var filter = this.filterFunc;
                    list = (
                        list
                            .map(function (x, index) { return [index, x]; })
                            .filter(function (tuple) {
                                return filter(tuple[1]);
                            })
                    );
                }

                var numUsed = list.length;
                var wantMorePages = (
                    (this.pageLimit === 0) ||
                    (finalList.length + numUsed < this.pageLimit)
                );

                /* page is complete */
                if (!wantMorePages && this.pageLimit > 0) {
                    /*
                     * If we fetched more data than we needed to complete the
                     * page, then newNumUsed will be < numUsed ...
                     */
                    var newNumUsed = this.pageLimit - finalList.length;
                    if (numUsed > newNumUsed) {
                        /*
                         * ...therefore, entries are being left out at the end,
                         * so they necessarily remain to be fetched.
                         */
                        this._hasMorePages = true;
                        numUsed = newNumUsed;
                    }

                    /*
                     * correct the offset: it must be advanced beyond the
                     * last element that got used.
                     */
                    if (this.filterFunc) {
                        /*
                         * If filtering, consult the index for the last element
                         * to be featured on this page.
                         */
                        offsetDelta = list[numUsed - 1][0] + 1;
                    } else {
                        /*
                         * Otherwise, the first numUsed elements will be
                         * unconditionally featured.
                         */
                        offsetDelta = numUsed;
                    }
                }

                list = list.slice(0, numUsed);
                /* If filtering, undecorate the list. */
                if (this.filterFunc) {
                    list = list.map(function (tuple) { return tuple[1]; });
                }

                finalList = finalList.concat(list);
                this.offset += offsetDelta;

                if (wantMorePages && this._hasMorePages) {
                    return fetchListFragment.apply(this);
                } else {
                    if (finalList.length > 0 || reset) {
                        if (this.append && !reset) {
                            this.add(finalList);
                        } else {
                            this.reset(finalList);
                        }
                    }

                    this.trigger('g:changed');
                }
                return undefined;
            });
            xhr.girder = { fetch: true };
            return result;
        }

        return fetchListFragment.apply(this);
    }
});

export default DepositionCollection;
