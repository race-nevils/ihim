/**
 * <c2pa-signer> - C2PA Image Signing Web Component
 *
 * A Web Component for signing images with C2PA metadata.
 * Drag-and-drop or file picker interface.
 *
 * Usage:
 *   <c2pa-signer></c2pa-signer>
 *
 * Attributes:
 *   - creator: Default creator name (default: from API)
 *   - action: C2PA action type (default: "c2pa.created")
 *
 * Events:
 *   - c2pa-signed: Fired when image is successfully signed
 *   - c2pa-error: Fired on signing error
 */

class C2PASigner extends HTMLElement {
    #shadow;
    #defaultCreator = 'the operator James [scrubbed]';
    #isUploading = false;

    static get observedAttributes() {
        return ['creator', 'action'];
    }

    constructor() {
        super();
        this.#shadow = this.attachShadow({ mode: 'open' });
    }

    async connectedCallback() {
        // Fetch default creator from API
        try {
            const response = await fetch('/api/c2pa/status');
            const data = await response.json();
            if (data.default_creator) {
                this.#defaultCreator = data.default_creator;
            }
        } catch (e) {
            console.warn('Could not fetch C2PA status:', e);
        }
        this.#render();
    }

    attributeChangedCallback(name, oldValue, newValue) {
        if (oldValue !== newValue) {
            this.#render();
        }
    }

    async #signImage(file) {
        if (this.#isUploading) return;
        this.#isUploading = true;

        const statusEl = this.#shadow.querySelector('.c2pa-status');
        const resultEl = this.#shadow.querySelector('.c2pa-result');

        statusEl.textContent = 'Signing image...';
        statusEl.className = 'c2pa-status signing';
        resultEl.innerHTML = '';

        try {
            const formData = new FormData();
            formData.append('image_file', file);

            const creator = this.getAttribute('creator') || this.#defaultCreator;
            const action = this.getAttribute('action') || 'c2pa.created';

            formData.append('creator', creator);
            formData.append('action', action);
            formData.append('title', file.name);

            const response = await fetch('/api/c2pa/sign', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (result.success) {
                statusEl.textContent = 'Image signed successfully!';
                statusEl.className = 'c2pa-status success';

                resultEl.innerHTML = `
                    <div class="result-item">
                        <span class="result-label">Output:</span>
                        <span class="result-value">${this.#escapeHtml(result.output_filename)}</span>
                    </div>
                    <div class="result-item">
                        <span class="result-label">Creator:</span>
                        <span class="result-value">${this.#escapeHtml(result.creator)}</span>
                    </div>
                    <div class="result-item">
                        <span class="result-label">Location:</span>
                        <span class="result-value path">${this.#escapeHtml(result.output_path)}</span>
                    </div>
                `;

                // Dispatch success event
                this.dispatchEvent(new CustomEvent('c2pa-signed', {
                    detail: result,
                    bubbles: true
                }));
            } else {
                throw new Error(result.error || 'Unknown error');
            }

        } catch (error) {
            statusEl.textContent = `Error: ${error.message}`;
            statusEl.className = 'c2pa-status error';

            // Dispatch error event
            this.dispatchEvent(new CustomEvent('c2pa-error', {
                detail: { error: error.message },
                bubbles: true
            }));
        } finally {
            this.#isUploading = false;
        }
    }

    #render() {
        const creator = this.getAttribute('creator') || this.#defaultCreator;

        this.#shadow.innerHTML = `
            <style>
                :host {
                    display: block;
                }
                .c2pa-signer {
                    border: 1px solid var(--border-normal, #333);
                    border-radius: var(--radius-sm, 6px);
                    background: var(--bg-tertiary, #1a1a1a);
                    padding: var(--space-4, 16px);
                }
                .c2pa-header {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    margin-bottom: 12px;
                }
                .c2pa-title {
                    font-size: 14px;
                    font-weight: 600;
                    color: var(--text-primary, #fff);
                }
                .c2pa-badge {
                    background: var(--accent-gold, #DAA520);
                    color: var(--bg-primary, #0a0a0a);
                    font-size: 10px;
                    font-weight: 600;
                    padding: 2px 8px;
                    border-radius: 4px;
                    text-transform: uppercase;
                }
                .c2pa-drop-zone {
                    border: 2px dashed var(--border-normal, #444);
                    border-radius: var(--radius-sm, 6px);
                    padding: 32px 16px;
                    text-align: center;
                    cursor: pointer;
                    transition: all 0.15s ease;
                    background: var(--bg-secondary, #111);
                }
                .c2pa-drop-zone:hover,
                .c2pa-drop-zone.dragover {
                    border-color: var(--accent-gold, #DAA520);
                    background: rgba(218, 165, 32, 0.05);
                }
                .c2pa-drop-zone.dragover {
                    border-style: solid;
                }
                .drop-icon {
                    font-size: 32px;
                    margin-bottom: 8px;
                    opacity: 0.6;
                }
                .drop-text {
                    font-size: 13px;
                    color: var(--text-secondary, #aaa);
                    margin-bottom: 4px;
                }
                .drop-hint {
                    font-size: 11px;
                    color: var(--text-muted, #666);
                }
                .c2pa-file-input {
                    display: none;
                }
                .c2pa-creator-info {
                    font-size: 11px;
                    color: var(--text-muted, #666);
                    margin-top: 12px;
                    padding-top: 12px;
                    border-top: 1px solid var(--border-dim, #222);
                }
                .c2pa-status {
                    font-size: 12px;
                    padding: 8px 12px;
                    border-radius: 4px;
                    margin-top: 12px;
                    display: none;
                }
                .c2pa-status.signing {
                    display: block;
                    background: rgba(59, 130, 246, 0.1);
                    color: #60a5fa;
                    border: 1px solid rgba(59, 130, 246, 0.3);
                }
                .c2pa-status.success {
                    display: block;
                    background: rgba(16, 185, 129, 0.1);
                    color: #34d399;
                    border: 1px solid rgba(16, 185, 129, 0.3);
                }
                .c2pa-status.error {
                    display: block;
                    background: rgba(239, 68, 68, 0.1);
                    color: #f87171;
                    border: 1px solid rgba(239, 68, 68, 0.3);
                }
                .c2pa-result {
                    margin-top: 12px;
                    font-size: 11px;
                }
                .result-item {
                    display: flex;
                    gap: 8px;
                    padding: 4px 0;
                }
                .result-label {
                    color: var(--text-muted, #666);
                    min-width: 60px;
                }
                .result-value {
                    color: var(--text-secondary, #aaa);
                    word-break: break-all;
                }
                .result-value.path {
                    font-family: monospace;
                    font-size: 10px;
                    color: var(--text-tertiary, #888);
                }
            </style>
            <div class="c2pa-signer">
                <div class="c2pa-header">
                    <span class="c2pa-badge">C2PA</span>
                    <span class="c2pa-title">Sign Image</span>
                </div>
                <div class="c2pa-drop-zone">
                    <div class="drop-icon">📷</div>
                    <div class="drop-text">Drop image here or click to select</div>
                    <div class="drop-hint">JPG, PNG, WebP, GIF, TIFF</div>
                </div>
                <input type="file" class="c2pa-file-input" accept="image/jpeg,image/png,image/webp,image/gif,image/tiff">
                <div class="c2pa-creator-info">
                    Signing as: <strong>${this.#escapeHtml(creator)}</strong>
                </div>
                <div class="c2pa-status"></div>
                <div class="c2pa-result"></div>
            </div>
        `;

        // Setup event listeners
        const dropZone = this.#shadow.querySelector('.c2pa-drop-zone');
        const fileInput = this.#shadow.querySelector('.c2pa-file-input');

        // Click to select
        dropZone.addEventListener('click', () => {
            fileInput.click();
        });

        // File selected
        fileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                this.#signImage(file);
            }
        });

        // Drag and drop
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });

        dropZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
        });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');

            const file = e.dataTransfer.files[0];
            if (file && file.type.startsWith('image/')) {
                this.#signImage(file);
            }
        });
    }

    #escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Register the custom element
customElements.define('c2pa-signer', C2PASigner);
