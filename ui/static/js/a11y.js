/**
 * a11y.js — Shared accessibility utilities
 * Focus trapping, focus restoration, accessible tabs, window escape close.
 */

// =====================
// Focus Trap
// =====================

const FOCUSABLE_SELECTOR = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Trap Tab/Shift+Tab cycling within a dialog element.
 * Returns a cleanup function to remove the listener.
 */
export function trapFocus(dialogEl) {
    function handler(e) {
        if (e.key !== 'Tab') return;
        const focusable = [...dialogEl.querySelectorAll(FOCUSABLE_SELECTOR)].filter(el => el.offsetParent !== null);
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey) {
            if (document.activeElement === first) { e.preventDefault(); last.focus(); }
        } else {
            if (document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
    }
    dialogEl.addEventListener('keydown', handler);
    return () => dialogEl.removeEventListener('keydown', handler);
}

// =====================
// Focus Restore (Modal Pattern)
// =====================

const triggerMap = new WeakMap();

/**
 * Open a <dialog> modal, remember the trigger for focus return.
 * Sets up focus trap automatically.
 */
export function openWithFocusRestore(dialogEl, triggerEl) {
    if (!dialogEl) return;
    if (triggerEl) triggerMap.set(dialogEl, triggerEl);
    if (!dialogEl.open) dialogEl.showModal();
    // Focus first focusable inside
    const first = dialogEl.querySelector(FOCUSABLE_SELECTOR);
    if (first) setTimeout(() => first.focus(), 50);
    // Set up trap if not already
    if (!dialogEl._a11yTrapCleanup) {
        dialogEl._a11yTrapCleanup = trapFocus(dialogEl);
    }
}

/**
 * Close a <dialog> modal, return focus to original trigger.
 */
export function closeWithFocusRestore(dialogEl) {
    if (!dialogEl) return;
    if (dialogEl.open) dialogEl.close();
    const trigger = triggerMap.get(dialogEl);
    if (trigger && typeof trigger.focus === 'function') {
        trigger.focus();
        triggerMap.delete(dialogEl);
    }
    if (dialogEl._a11yTrapCleanup) {
        dialogEl._a11yTrapCleanup();
        dialogEl._a11yTrapCleanup = null;
    }
}

// =====================
// Accessible Tabs (WAI-ARIA Tabs Pattern)
// =====================

/**
 * Initialize accessible tab pattern on a tablist container.
 * @param {HTMLElement} tablistEl - The element containing tab buttons
 * @param {Object} options
 * @param {string} options.tabSelector - CSS selector for tab buttons (default: '[role="tab"]')
 * @param {Function} options.onActivate - Callback(tabEl) when a tab is activated
 */
export function initAccessibleTabs(tablistEl, { tabSelector = '[role="tab"]', onActivate } = {}) {
    if (!tablistEl) return;
    tablistEl.setAttribute('role', 'tablist');
    const tabs = [...tablistEl.querySelectorAll(tabSelector)];
    if (tabs.length === 0) return;

    // Set ARIA attributes on each tab
    tabs.forEach((tab, i) => {
        tab.setAttribute('role', 'tab');
        if (!tab.id) tab.id = `tab-${tablistEl.id || 'set'}-${i}`;
        const panelId = tab.getAttribute('aria-controls');
        if (panelId) {
            const panel = document.getElementById(panelId);
            if (panel) {
                panel.setAttribute('role', 'tabpanel');
                panel.setAttribute('aria-labelledby', tab.id);
            }
        }
        // Only the active tab is in tab order
        const isActive = tab.classList.contains('active') || tab.getAttribute('aria-selected') === 'true';
        tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
        tab.setAttribute('tabindex', isActive ? '0' : '-1');
    });

    // Keyboard navigation
    tablistEl.addEventListener('keydown', (e) => {
        const currentTab = e.target.closest(tabSelector);
        if (!currentTab) return;
        const currentIndex = tabs.indexOf(currentTab);
        if (currentIndex === -1) return;

        let newIndex = -1;
        switch (e.key) {
            case 'ArrowLeft':
            case 'ArrowUp':
                newIndex = currentIndex > 0 ? currentIndex - 1 : tabs.length - 1;
                break;
            case 'ArrowRight':
            case 'ArrowDown':
                newIndex = currentIndex < tabs.length - 1 ? currentIndex + 1 : 0;
                break;
            case 'Home':
                newIndex = 0;
                break;
            case 'End':
                newIndex = tabs.length - 1;
                break;
            default:
                return;
        }

        e.preventDefault();
        activateTab(tabs, newIndex, onActivate);
    });
}

function activateTab(tabs, index, onActivate) {
    tabs.forEach((tab, i) => {
        const isTarget = i === index;
        tab.setAttribute('aria-selected', isTarget ? 'true' : 'false');
        tab.setAttribute('tabindex', isTarget ? '0' : '-1');
        if (isTarget) tab.focus();
    });
    if (onActivate) onActivate(tabs[index]);
}

// =====================
// Window Escape Close (Delegated)
// =====================

const windowRegistry = new Map();

/**
 * Register a window for Escape-key closing.
 * @param {HTMLElement} windowEl - The window container element
 * @param {Function} closeFn - Function to call when Escape is pressed
 */
export function initWindowEscapeClose(windowEl, closeFn) {
    if (!windowEl || windowRegistry.has(windowEl)) return;
    windowRegistry.set(windowEl, closeFn);
}

/**
 * Initialize the global delegated Escape handler.
 * Call once at app init.
 */
export function initGlobalEscapeHandler() {
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        // Don't interfere with <dialog> (they handle their own Escape)
        if (document.querySelector('dialog[open]')) return;

        // Find the topmost visible registered window that contains focus or is "active"
        for (const [windowEl, closeFn] of windowRegistry) {
            if (windowEl.style.display === 'none') continue;
            if (windowEl.contains(document.activeElement) || windowEl.matches(':hover')) {
                closeFn();
                e.preventDefault();
                return;
            }
        }
    });
}
