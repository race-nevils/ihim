/**
 * slash-commands.js — Slash Command Center (API-backed)
 */
import { API, escapeHtml, showStatus, formatTimestamp } from './app.js';

let slashCommands = [];
let slashIdeas = [];

async function loadSlashCommands() {
    try {
        const res = await fetch(`${API}/api/slash-commands`);
        const data = await res.json();
        slashCommands = (data.commands || []).map(cmd => ({
            id: cmd.id, name: `/${cmd.id}`, title: cmd.name || cmd.id,
            description: cmd.description || cmd.shortDesc || '',
            category: cmd.category || 'other',
            autoTrigger: cmd.auto_invoke || false,
            tags: cmd.tags || []
        }));
    } catch (err) {
        console.error('Failed to load commands:', err);
        slashCommands = [];
    }
}

async function loadSlashIdeas() {
    try {
        const res = await fetch(`${API}/api/slash-commands/ideas/all`);
        const data = await res.json();
        slashIdeas = (data.ideas || []).map(idea => ({
            id: idea.id, text: idea.description || idea.text,
            timestamp: idea.created_at ? new Date(idea.created_at).getTime() : Date.now()
        }));
    } catch (err) {
        console.error('Failed to load slash ideas:', err);
        slashIdeas = [];
    }
}

export async function openSlashModal() {
    document.getElementById('slash-modal').classList.add('active');
    await Promise.all([loadSlashCommands(), loadSlashIdeas()]);
    renderSlashCommands();
    renderSlashIdeas();
    document.getElementById('slash-search').value = '';
    setTimeout(() => document.getElementById('slash-search').focus(), 100);
}

export function closeSlashModal() {
    document.getElementById('slash-modal').classList.remove('active');
}

function getCategoryIcon(category) {
    return { session: '💾', quality: '🔍', git: '🚀', productivity: '📋', dev: '💻', other: '⚡' }[category] || '⚡';
}

function getCategoryColor(category) {
    return { session: '#3d6f9a', quality: '#f97316', git: '#22c55e', productivity: '#8b5cf6', dev: '#06b6d4', other: '#888' }[category] || '#888';
}

function renderSlashCommands(filter = '') {
    const list = document.getElementById('slash-list');
    const countEl = document.getElementById('slash-count');
    const filtered = slashCommands.filter(cmd => {
        if (!filter) return true;
        const s = filter.toLowerCase();
        return cmd.name.toLowerCase().includes(s) || cmd.title.toLowerCase().includes(s) ||
            cmd.description.toLowerCase().includes(s) || cmd.tags.some(t => t.toLowerCase().includes(s));
    });
    if (filtered.length === 0) {
        list.innerHTML = '<div class="no-slash">No commands match your search</div>';
        countEl.textContent = '0 commands'; return;
    }
    const grouped = {};
    filtered.forEach(cmd => { if (!grouped[cmd.category]) grouped[cmd.category] = []; grouped[cmd.category].push(cmd); });

    let html = '';
    for (const [category, commands] of Object.entries(grouped)) {
        html += `<div class="slash-category"><div class="slash-category-header">
            <span class="slash-category-icon">${getCategoryIcon(category)}</span>
            <span class="slash-category-name">${category.toUpperCase()}</span>
        </div><div class="slash-category-items">`;
        commands.forEach(cmd => {
            html += `<div class="slash-item" data-slash-name="${escapeHtml(cmd.name)}" style="border-left-color: ${getCategoryColor(cmd.category)}">
                <div class="slash-item-header">
                    <span class="slash-name">${escapeHtml(cmd.name)}</span>
                    ${cmd.autoTrigger ? '<span class="slash-auto-badge">Auto</span>' : ''}
                </div>
                <div class="slash-title">${escapeHtml(cmd.title)}</div>
                <div class="slash-desc">${escapeHtml(cmd.description)}</div>
                <div class="slash-tags">${cmd.tags.map(t => `<span class="slash-tag">${escapeHtml(t)}</span>`).join('')}</div>
            </div>`;
        });
        html += '</div></div>';
    }
    list.innerHTML = html;
    countEl.textContent = `${filtered.length} command${filtered.length !== 1 ? 's' : ''}`;
}

export function filterSlashCommands() {
    renderSlashCommands(document.getElementById('slash-search').value);
}

function copySlashCommand(command) {
    navigator.clipboard.writeText(command).then(() => showStatus(`Copied ${command} to clipboard`, 'success'))
        .catch(err => { console.error('Failed to copy:', err); showStatus('Failed to copy', 'error'); });
}

function renderSlashIdeas() {
    const container = document.getElementById('slash-ideas');
    if (slashIdeas.length === 0) { container.innerHTML = '<div class="no-ideas">No ideas yet. Brainstorm above!</div>'; return; }
    const sorted = [...slashIdeas].sort((a, b) => b.timestamp - a.timestamp);
    container.innerHTML = sorted.map(idea => `
        <div class="slash-idea-item" data-idea-id="${idea.id}">
            <div class="idea-content">${escapeHtml(idea.text)}</div>
            <div class="idea-meta">
                <span class="idea-timestamp">${formatTimestamp(idea.timestamp)}</span>
                <button class="delete-idea-btn" data-delete-idea="${idea.id}" title="Delete">×</button>
            </div>
        </div>
    `).join('');
}

async function saveSlashIdea() {
    const input = document.getElementById('brainstorm-input');
    const text = input.value.trim();
    if (!text) { showStatus('Please enter an idea', 'error'); return; }
    try {
        const res = await fetch(`${API}/api/slash-commands/ideas`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ description: text })
        });
        const data = await res.json();
        if (data.success) {
            slashIdeas.unshift({ id: data.idea.id, text: data.idea.description, timestamp: Date.now() });
            renderSlashIdeas(); input.value = '';
            showStatus('Idea saved', 'success');
        }
    } catch (err) { console.error('Failed to save idea:', err); showStatus('Failed to save idea', 'error'); }
}

async function deleteSlashIdea(ideaId) {
    try {
        await fetch(`${API}/api/slash-commands/ideas/${ideaId}`, { method: 'DELETE' });
        slashIdeas = slashIdeas.filter(i => i.id !== ideaId);
        renderSlashIdeas(); showStatus('Idea deleted', 'success');
    } catch (err) { console.error('Failed to delete idea:', err); showStatus('Failed to delete idea', 'error'); }
}

// Event initialization
export function initSlashEvents() {
    // Slash modal outside-click
    document.getElementById('slash-modal')?.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal')) closeSlashModal();
    });

    // Search input
    document.getElementById('slash-search')?.addEventListener('input', filterSlashCommands);

    // Brainstorm Ctrl+Enter
    document.getElementById('brainstorm-input')?.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') saveSlashIdea();
    });

    // Save idea button
    document.querySelector('.save-idea-btn')?.addEventListener('click', saveSlashIdea);

    // Event delegation for slash list (copy command) and ideas (delete)
    document.getElementById('slash-list')?.addEventListener('click', (e) => {
        const item = e.target.closest('[data-slash-name]');
        if (item) copySlashCommand(item.dataset.slashName);
    });

    document.getElementById('slash-ideas')?.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-delete-idea]');
        if (btn) deleteSlashIdea(btn.dataset.deleteIdea);
    });
}
