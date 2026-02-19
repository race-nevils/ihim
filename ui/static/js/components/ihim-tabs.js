/**
 * <ihim-tabs> — Accessible tab system Web Component
 * Thin delegation layer over Phase 3 a11y.js initAccessibleTabs().
 *
 * Usage:
 *   <ihim-tabs>
 *     <div role="tablist">
 *       <button role="tab" aria-controls="panel-1">Tab 1</button>
 *       <button role="tab" aria-controls="panel-2">Tab 2</button>
 *     </div>
 *     <div id="panel-1" role="tabpanel">Content 1</div>
 *     <div id="panel-2" role="tabpanel">Content 2</div>
 *   </ihim-tabs>
 *
 * Uses display:contents — invisible to layout and accessibility tree.
 * Panel show/hide driven by aria-controls on tabs.
 * Public API: activate(tabName)
 * Events: tab:change (bubbles) — detail: { tab, panelId }
 */

import { initAccessibleTabs } from '../a11y.js';

class IhimTabs extends HTMLElement {
    connectedCallback() {
        queueMicrotask(() => this._setup());
    }

    _setup() {
        if (this._initialized) return;
        this._initialized = true;

        const tablist = this.querySelector('[role="tablist"]');
        if (!tablist) return;
        this._tablist = tablist;

        // Delegate keyboard navigation to Phase 3 a11y.js
        initAccessibleTabs(tablist, {
            onActivate: (tab) => this._onTabActivate(tab)
        });

        // Handle click activation (initAccessibleTabs handles keyboard only)
        tablist.addEventListener('click', (e) => {
            const tab = e.target.closest('[role="tab"]');
            if (tab) this._onTabActivate(tab);
        });
    }

    _onTabActivate(tab) {
        const panelId = tab.getAttribute('aria-controls');

        // Hide all panels within this tab group
        for (const panel of this.querySelectorAll('[role="tabpanel"]')) {
            panel.style.display = 'none';
            panel.classList.remove('active');
        }

        // Show the target panel
        if (panelId) {
            const target = document.getElementById(panelId);
            if (target) {
                target.style.display = '';
                target.classList.add('active');
            }
        }

        // Update tab active states
        for (const t of this._tablist.querySelectorAll('[role="tab"]')) {
            t.classList.toggle('active', t === tab);
            t.setAttribute('aria-selected', t === tab ? 'true' : 'false');
            t.setAttribute('tabindex', t === tab ? '0' : '-1');
        }

        // Reflect current tab and fire event
        this.setAttribute('active', tab.getAttribute('data-tab') || tab.getAttribute('data-section') || '');
        this.dispatchEvent(new CustomEvent('tab:change', {
            bubbles: true,
            detail: { tab, panelId }
        }));
    }

    activate(tabName) {
        if (!this._tablist) return;
        const tab = this._tablist.querySelector(
            `[role="tab"][data-tab="${tabName}"], [role="tab"][data-section="${tabName}"]`
        );
        if (tab) this._onTabActivate(tab);
    }
}

customElements.define('ihim-tabs', IhimTabs);
