/**
 * <ihim-agentnode-bar> — agent node bottom-bar status chip Web Component.
 * Click opens the agent node panel (<ihim-panel id="agentnode-window">).
 *
 * Usage:
 *   <ihim-agentnode-bar class="bar-widget" title="agent node Agent Node"></ihim-agentnode-bar>
 */

class IhimAgentNodeBar extends HTMLElement {
    connectedCallback() {
        this.innerHTML = `
            <span class="status-dot inactive"></span>
            <span class="bar-label">K8+</span>
            <span class="bar-value">OFF</span>
        `;
        this.style.cursor = 'pointer';
        this.addEventListener('click', () => {
            document.getElementById('agentnode-window')?.open();
        });
    }
}

customElements.define('ihim-agentnode-bar', IhimAgentNodeBar);
