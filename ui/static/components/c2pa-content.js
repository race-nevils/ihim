/**
 * <c2pa-content> - C2PA Content Authenticity Web Component
 *
 * A minimal Web Component that wraps content with C2PA-compliant JSON-LD metadata.
 * Foundation layer for content authenticity in iHIM.
 *
 * Usage:
 *   <c2pa-content creator="iHIM" action="c2pa.created">
 *     Hello World - This content has C2PA provenance!
 *   </c2pa-content>
 *
 * Attributes:
 *   - creator: The entity that created the content (default: "iHIM")
 *   - action: The C2PA action type (default: "c2pa.created")
 *   - timestamp: ISO timestamp (default: current time)
 *   - claim-id: Unique claim identifier (default: auto-generated)
 *
 * Public API:
 *   - getManifest(): Returns the JSON-LD manifest object
 *   - getManifestJSON(): Returns the manifest as formatted JSON string
 */

class C2PAContent extends HTMLElement {
    // Private fields
    #shadow;
    #manifest;

    static get observedAttributes() {
        return ['creator', 'action', 'timestamp', 'claim-id'];
    }

    constructor() {
        super();
        this.#shadow = this.attachShadow({ mode: 'open' });
        this.#manifest = this.#createManifest();
    }

    connectedCallback() {
        this.#render();
    }

    attributeChangedCallback(name, oldValue, newValue) {
        if (oldValue !== newValue) {
            this.#manifest = this.#createManifest();
            this.#render();
        }
    }

    /**
     * Create C2PA-compliant JSON-LD manifest
     * Follows C2PA 1.4+ specification patterns
     */
    #createManifest() {
        const claimId = this.getAttribute('claim-id') || this.#generateClaimId();
        const timestamp = this.getAttribute('timestamp') || new Date().toISOString();
        const creator = this.getAttribute('creator') || 'iHIM';
        const action = this.getAttribute('action') || 'c2pa.created';

        return {
            "@context": [
                "https://c2pa.org/specifications/manifest/1.0",
                "https://schema.org"
            ],
            "@type": "c2pa:Manifest",
            "@id": `urn:c2pa:${claimId}`,
            "c2pa:claim_generator": `iHIM/1.0`,
            "c2pa:title": "C2PA Content Block",
            "c2pa:assertions": [
                {
                    "@type": "c2pa:CreativeWork",
                    "stds.schema-org.CreativeWork": {
                        "@type": "CreativeWork",
                        "author": {
                            "@type": "Organization",
                            "name": creator
                        },
                        "dateCreated": timestamp
                    }
                },
                {
                    "@type": "c2pa.actions",
                    "actions": [
                        {
                            "action": action,
                            "when": timestamp,
                            "softwareAgent": "iHIM Dashboard"
                        }
                    ]
                }
            ],
            "c2pa:signature": {
                "@type": "c2pa:Signature",
                "algorithm": "POC-placeholder",
                "value": this.#generatePlaceholderSignature()
            }
        };
    }

    #generateClaimId() {
        return `ihim-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    }

    #generatePlaceholderSignature() {
        // POC: Not a real signature, just demonstrates structure
        return btoa(`poc:${Date.now()}`);
    }

    /**
     * Get manifest as object
     * @returns {Object} The JSON-LD manifest
     */
    getManifest() {
        return this.#manifest;
    }

    /**
     * Get manifest as formatted JSON string
     * @returns {string} The manifest as JSON
     */
    getManifestJSON() {
        return JSON.stringify(this.#manifest, null, 2);
    }

    #render() {
        const action = this.getAttribute('action') || 'c2pa.created';
        const creator = this.getAttribute('creator') || 'iHIM';

        // Format action for display (remove c2pa. prefix if present)
        const displayAction = action.replace('c2pa.', '');

        this.#shadow.innerHTML = `
            <style>
                :host {
                    display: block;
                    position: relative;
                }
                .c2pa-wrapper {
                    border: 1px solid var(--border-normal, #333);
                    border-radius: var(--radius-sm, 6px);
                    background: var(--bg-tertiary, #1a1a1a);
                    padding: var(--space-4, 16px);
                    position: relative;
                }
                .c2pa-badge {
                    position: absolute;
                    top: -8px;
                    right: 12px;
                    background: var(--accent-gold, #DAA520);
                    color: var(--bg-primary, #0a0a0a);
                    font-size: 10px;
                    font-weight: 600;
                    padding: 2px 8px;
                    border-radius: 4px;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                    cursor: pointer;
                    user-select: none;
                    transition: background 0.15s ease;
                }
                .c2pa-badge:hover {
                    background: var(--accent-gold-bright, #FFD700);
                }
                .c2pa-badge.active {
                    background: var(--color-safe, #10b981);
                }
                .c2pa-content {
                    color: var(--text-secondary, #e5e5e5);
                }
                .c2pa-meta-line {
                    font-size: 10px;
                    color: var(--text-muted, #666);
                    margin-top: var(--space-2, 8px);
                }
                .c2pa-manifest {
                    display: none;
                    margin-top: var(--space-3, 12px);
                    padding: var(--space-3, 12px);
                    background: var(--bg-secondary, #111);
                    border: 1px solid var(--border-dim, #222);
                    border-radius: var(--radius-sm, 6px);
                    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
                    font-size: 11px;
                    color: var(--text-tertiary, #888);
                    overflow-x: auto;
                    max-height: 300px;
                    overflow-y: auto;
                    white-space: pre;
                }
                .c2pa-manifest.visible {
                    display: block;
                }
                .c2pa-manifest::-webkit-scrollbar {
                    width: 6px;
                    height: 6px;
                }
                .c2pa-manifest::-webkit-scrollbar-track {
                    background: var(--bg-secondary, #111);
                }
                .c2pa-manifest::-webkit-scrollbar-thumb {
                    background: var(--border-normal, #333);
                    border-radius: 3px;
                }
            </style>
            <div class="c2pa-wrapper">
                <span class="c2pa-badge" title="Click to view C2PA manifest">C2PA</span>
                <div class="c2pa-content">
                    <slot></slot>
                </div>
                <div class="c2pa-meta-line">
                    ${displayAction} by ${creator}
                </div>
                <pre class="c2pa-manifest">${this.#escapeHtml(this.getManifestJSON())}</pre>
            </div>
        `;

        // Add click handler to badge
        const badge = this.#shadow.querySelector('.c2pa-badge');
        const manifest = this.#shadow.querySelector('.c2pa-manifest');

        badge.addEventListener('click', () => {
            manifest.classList.toggle('visible');
            badge.classList.toggle('active');
        });
    }

    #escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Register the custom element
customElements.define('c2pa-content', C2PAContent);
