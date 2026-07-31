/**
 * <ihim-travel> — Travel window: the two legs of a drive trip on one tile.
 *   Leaving   → POST /api/system/travel         (refresh the drive mirror, then eject)
 *   Returning → POST /api/system/travel/return  (pull Mac work + transcripts back in)
 *
 * Each action launches its script in its own console — that console IS the
 * feedback, so the window closes on a successful launch and the API response
 * only carries errors (shown inline when a launch is refused).
 */
import { IhimPanel } from './ihim-panel.js';

class IhimTravel extends IhimPanel {
    connectedCallback() {
        this.innerHTML = `
            <div class="travel-body">
                <button type="button" class="travel-action" data-endpoint="/api/system/travel">
                    <span class="travel-action-name">Leaving</span>
                    <span class="travel-action-desc">Refresh the drive mirror, then eject</span>
                </button>
                <button type="button" class="travel-action" data-endpoint="/api/system/travel/return">
                    <span class="travel-action-name">Returning</span>
                    <span class="travel-action-desc">Pull Mac work + transcripts back in</span>
                </button>
                <div class="travel-error" role="alert" hidden></div>
            </div>`;
        this.addEventListener('click', (e) => {
            const btn = e.target.closest('.travel-action');
            if (btn) this._launch(btn.dataset.endpoint);
        });
        super.connectedCallback();
    }

    async _launch(endpoint) {
        const errBox = this.querySelector('.travel-error');
        errBox.hidden = true;
        try {
            const r = await fetch(endpoint, { method: 'POST' });
            if (!r.ok) {
                const doc = await r.json().catch(() => ({}));
                errBox.textContent = doc.detail || `Launch failed (${r.status})`;
                errBox.hidden = false;
                return;
            }
            this.close();   // the spawned console takes over as the feedback
        } catch (err) {
            errBox.textContent = String(err);
            errBox.hidden = false;
        }
    }
}

customElements.define('ihim-travel', IhimTravel);
