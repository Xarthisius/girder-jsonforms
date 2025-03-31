// Extends and overrides API
import './routes';

const { wrap } = girder.utilities.PluginUtils;
const GlobalNavView = girder.views.layout.GlobalNavView;
const { getCurrentUser } = girder.auth;
const eventStream = girder.utilities.eventStream;


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


wrap(GlobalNavView, 'render', function (render) {
    render.call(this);
    if (getCurrentUser()) {
        const formsNav = createNavItem({
            name: 'Forms',
            icon: 'icon-doc',
            target: 'forms'
        });
        const depositionsNav = createNavItem({
            name: 'IGSN',
            icon: 'icon-barcode',
            target: 'depositions'
        });
        const navList = document.querySelector('.g-global-nav-li:last-of-type');
        if (navList) {
              navList.parentElement.appendChild(formsNav);
              navList.parentElement.appendChild(depositionsNav);
        } else {
              console.warn('No existing .g-global-nav-li elements found.');
        }
    }
});
