// Extends and overrides API
import './routes';
import './views/ItemView';
import './views/UserView';
import './views/HierarchyWidget';
import './views/ItemListWidget';
import './views/FolderListWidget';
import './views/widgets/DepositionListWidget';
import AssignIGSNWidget from './views/widgets/AssignIGSNView';
import DataCiteCardView from './views/CollectionLandingPage';
import folderActionsTemplate from './templates/folderActions.pug';

const { getCurrentUser } = girder.auth;
const { AccessType } = girder.constants;
const SearchFieldWidget = girder.views.widgets.SearchFieldWidget;
const CollectionView = girder.views.body.CollectionView;
const GlobalNavView = girder.views.layout.GlobalNavView;
const HierarchyWidget = girder.views.widgets.HierarchyWidget;
const { wrap } = girder.utilities.PluginUtils;

function createNavItem(navItem) {
    // Create the <li> element
    const li = document.createElement('li');
    li.classList.add('g-global-nav-li');

    // Create the <a> element
    const a = document.createElement('a');
    a.classList.add('g-nav-link');
    a.setAttribute('g-target', navItem.target);
    a.setAttribute('g-name', navItem.name);
    a.href = `#${navItem.target}`;

    // Create the <i> element
    const i = document.createElement('i');
    i.classList.add(navItem.icon);

    // Create the <span> element and set its text
    const span = document.createElement('span');
    span.textContent = navItem.name;

    // Append <i> and <span> to <a>
    a.appendChild(i);
    a.appendChild(span);

    // Append <a> to <li>
    li.appendChild(a);

    return li;
}

wrap(CollectionView, 'render', function (render) {
    render.call(this);
    const meta = this.model.get("meta");
    if (meta && meta.datacite) {
        var landingPage = new DataCiteCardView({parentView: this, url: meta.datacite}).render()
        const collectionHeader = document.querySelector('.g-collection-header');
        collectionHeader.append(landingPage.el);
    }
});

wrap(GlobalNavView, 'render', function (render) {
    render.call(this);
    const navList = document.querySelector('.g-global-nav-li:last-of-type');
    if (getCurrentUser()) {
        const formsNav = createNavItem({
            name: 'Forms',
            icon: 'icon-doc',
            target: 'forms'
        });
        if (navList) {
            navList.parentElement.appendChild(formsNav);
        } else {
            console.warn('No existing .g-global-nav-li elements found.');
        }
    }
    const depositionsNav = createNavItem({
        name: 'IGSN',
        icon: 'icon-barcode',
        target: 'depositions'
    });
    if (navList) {
        navList.parentElement.appendChild(depositionsNav);
    } else {
        console.warn('No existing .g-global-nav-li elements found.');
    }
});

// Add an entry to assign IGSN recursively in the hierarchy widget folder menu
wrap(HierarchyWidget, 'render', function (render) {
    render.call(this);

    if (this.parentModel.resourceName === 'folder' &&
            this.parentModel.getAccessLevel() >= AccessType.WRITE) {
        this.$('.g-folder-actions-menu a.g-edit-folder').parent().after(folderActionsTemplate({
            folder: this.parentModel
        }));
    }
    return this;
});

HierarchyWidget.prototype.events['click a.g-assign-igsn-recursively'] = function (event) {
    event.preventDefault();
    new AssignIGSNWidget({
        el: $('#g-dialog-container'),
        parentView: this,
        folder: this.parentModel,
    }).render();
};

// Add search field to the global nav
SearchFieldWidget.addMode(
    'igsn',
    ['item', 'folder'],
    'Search by IGSN',
    'You are searching for all data associated with a given IGSN. (e.g. JHAMAA00001)'
);
SearchFieldWidget.addMode(
    'igsnText',
    ['deposition'],
    'Search IGSN by text',
    'You are searching'
);
SearchFieldWidget.addMode(
    'byCreator',
    ['item', 'folder', 'deposition'],
    'Search by Creator Id',
    'You are searching for all data associated with a given Creator Id'
);
