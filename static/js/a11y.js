// static/js/a11y.js
//
// App-wide dialog and keyboard behavior, applied by observing the DOM rather than by
// editing every modal template. Alpine shows dialogs with x-show (style changes) or
// mounts them with x-if (child insertions); both are picked up here.
//
//  - Escape closes the topmost open dialog (via its own × button, so each dialog's
//    cancel/guard logic still runs), or else any open dropdown menu.
//  - Opening a dialog moves focus into it, Tab is trapped inside, and focus returns
//    to the opener when it closes.
//  - Dialog windows get role="dialog"/aria-modal and a label from their heading.
//  - Icon-only buttons get an accessible name from their title (or "Close" for ×).
//  - Clickable spans used as buttons (pill toggles, filter tokens) become focusable
//    and respond to Enter/Space; pill and day toggles expose aria-pressed.

const OVERLAY_SELECTOR = '.modal-overlay, .modal-backdrop';
const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const SPAN_BUTTONS = 'span.pill-btn, span.token, b.token-remove, span.clickable';
const PRESSABLE = '.pill-btn, .day-btn';
const IGNORE_ROOT = '#log-drawer';

let openDialogs = [];          // [{ overlay, opener }] in open order
let overlayCheckQueued = false;
let dialogIdSeq = 0;

const isRendered = (el) => el.isConnected && el.getClientRects().length > 0;
const isClosingText = (text) => text === '×' || text === '✕';

function visibleOverlays() {
    return [...document.querySelectorAll(OVERLAY_SELECTOR)]
        .filter(el => el.id !== 'access-gate-overlay' && isRendered(el));
}

function topmostOverlay() {
    const overlays = visibleOverlays();
    if (!overlays.length) return null;
    // Highest z-index wins; ties go to the later element in the document.
    return overlays.reduce((top, el) => {
        const z = parseInt(getComputedStyle(el).zIndex, 10) || 0;
        const topZ = parseInt(getComputedStyle(top).zIndex, 10) || 0;
        return z >= topZ ? el : top;
    });
}

function closeControl(overlay) {
    const explicit = overlay.querySelector('[data-modal-close]');
    if (explicit) return explicit;
    const headerButtons = [...overlay.querySelectorAll('.modal-header button, .modal-header .modal-close')];
    const cross = headerButtons.find(b => isClosingText(b.textContent.trim()) || b.classList.contains('modal-close'));
    if (cross) return cross;
    const footerButtons = [...overlay.querySelectorAll('.modal-footer button')];
    return footerButtons.find(b => /^(cancel|close|done)$/i.test(b.textContent.trim())) || null;
}

function focusFirst(overlay) {
    const win = overlay.querySelector('.modal-window') || overlay;
    const preferred = win.querySelector('[autofocus]')
        || win.querySelector('.modal-body input:not([type="checkbox"]):not([type="radio"]):not([disabled]), .modal-body textarea:not([disabled]), .modal-body select:not([disabled])');
    const fallback = [...win.querySelectorAll(FOCUSABLE)].find(el => isRendered(el) && !isClosingText(el.textContent.trim()));
    const target = preferred && isRendered(preferred) ? preferred : (fallback || win);
    if (target === win && !win.hasAttribute('tabindex')) win.setAttribute('tabindex', '-1');
    target.focus({ preventScroll: true });
}

function syncOverlays() {
    overlayCheckQueued = false;
    const visible = visibleOverlays();

    // Closed dialogs: drop them and hand focus back to whatever opened them.
    const stillOpen = openDialogs.filter(d => visible.includes(d.overlay));
    const closed = openDialogs.filter(d => !visible.includes(d.overlay));
    openDialogs = stillOpen;
    if (closed.length && !openDialogs.length) {
        const opener = closed[closed.length - 1].opener;
        if (opener && opener.isConnected && isRendered(opener)) opener.focus({ preventScroll: true });
    }

    // Newly opened dialogs.
    for (const overlay of visible) {
        if (openDialogs.some(d => d.overlay === overlay)) continue;
        decorateDialog(overlay);
        openDialogs.push({ overlay, opener: document.activeElement });
        // Let Alpine finish rendering the body (x-if content, x-model values) first.
        requestAnimationFrame(() => { if (isRendered(overlay)) focusFirst(overlay); });
    }
}

function queueOverlayCheck() {
    if (overlayCheckQueued) return;
    overlayCheckQueued = true;
    requestAnimationFrame(syncOverlays);
}

function decorateDialog(overlay) {
    const win = overlay.querySelector('.modal-window');
    if (!win || win.hasAttribute('role')) return;
    win.setAttribute('role', 'dialog');
    win.setAttribute('aria-modal', 'true');
    const heading = win.querySelector('.modal-header h2, .modal-header h3, h2, h3');
    if (heading) {
        if (!heading.id) heading.id = `mb-dialog-title-${++dialogIdSeq}`;
        win.setAttribute('aria-labelledby', heading.id);
    }
}

function nameIconButton(el) {
    if (el.hasAttribute('aria-label') && !el.dataset.a11yNamed) return;
    const text = el.textContent.trim();
    if (isClosingText(text)) {
        el.setAttribute('aria-label', 'Close');
        el.dataset.a11yNamed = '1';
        return;
    }
    if (text) return;
    const title = el.getAttribute('title');
    if (title) {
        el.setAttribute('aria-label', title);
        el.dataset.a11yNamed = '1';
    }
}

const isClickable = (el) => el.hasAttribute('@click') || el.hasAttribute('x-on:click') || el.hasAttribute('@click.stop') || el.hasAttribute('@click.prevent');

function decorateSpanButton(el) {
    // Display-only tokens (e.g. curated picks) stay out of the tab order.
    if (!isClickable(el)) return;
    if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0');
    if (!el.hasAttribute('role')) el.setAttribute('role', 'button');
    if (el.matches('b.token-remove') && !el.hasAttribute('aria-label')) el.setAttribute('aria-label', 'Remove');
}

function syncPressed(el) {
    el.setAttribute('aria-pressed', el.classList.contains('active') ? 'true' : 'false');
}

function decorate(root) {
    if (!(root instanceof Element)) return;
    if (root.closest(IGNORE_ROOT)) return;
    const each = (selector, fn) => {
        if (root.matches(selector)) fn(root);
        root.querySelectorAll(selector).forEach(fn);
    };
    each('button, a.icon-btn, a.icon-only', nameIconButton);
    each(SPAN_BUTTONS, decorateSpanButton);
    each(PRESSABLE, syncPressed);
}

function onMutations(mutations) {
    let overlaysTouched = false;
    for (const m of mutations) {
        if (m.type === 'childList') {
            m.addedNodes.forEach(node => decorate(node));
            overlaysTouched = true;
        } else if (m.type === 'attributes') {
            const el = m.target;
            if (m.attributeName === 'style') overlaysTouched = true;
            else if (m.attributeName === 'class' && el.matches?.(PRESSABLE)) syncPressed(el);
            else if (m.attributeName === 'title' && el.dataset?.a11yNamed) {
                el.removeAttribute('aria-label');
                nameIconButton(el);
            }
        }
    }
    if (overlaysTouched) queueOverlayCheck();
}

function trapTab(event) {
    const top = openDialogs.length ? openDialogs[openDialogs.length - 1].overlay : null;
    if (!top || !isRendered(top)) return;
    const focusables = [...top.querySelectorAll(FOCUSABLE)].filter(isRendered);
    if (!focusables.length) { event.preventDefault(); return; }
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const active = document.activeElement;
    if (!top.contains(active)) {
        event.preventDefault();
        first.focus();
    } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
    }
}

function closeOpenMenus() {
    const menus = [...document.querySelectorAll('.dropdown-menu, .account-menu-panel')].filter(isRendered);
    if (!menus.length) return false;
    // Every menu closes through @click.outside. With a dialog open, the click lands on
    // the dialog window itself so the dialog's own @click.outside does not fire.
    const top = topmostOverlay();
    const target = top ? (top.querySelector('.modal-window') || top) : document.body;
    target.click();
    return true;
}

function onKeydown(event) {
    if (event.key === 'Escape') {
        if (closeOpenMenus()) { event.preventDefault(); return; }
        const top = topmostOverlay();
        if (!top) return;
        const control = closeControl(top);
        if (control) {
            event.preventDefault();
            control.click();
        }
        return;
    }
    if (event.key === 'Tab') {
        trapTab(event);
        return;
    }
    if ((event.key === 'Enter' || event.key === ' ') && event.target instanceof Element) {
        const el = event.target;
        if (el.getAttribute('role') === 'button' && !el.matches('button, a, input, select, textarea')) {
            event.preventDefault();
            el.click();
        }
    }
}

export function initA11y() {
    decorate(document.body);
    new MutationObserver(onMutations).observe(document.body, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ['style', 'class', 'title']
    });
    document.addEventListener('keydown', onKeydown);
    queueOverlayCheck();
}
