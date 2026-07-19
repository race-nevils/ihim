/**
 * <ihim-health> — Health Dashboard window (workouts, nutrition, glossary).
 * Extends IhimPanel: IS the draggable window; renders its own chrome +
 * content, loads data on its panel:open lifecycle.
 */
import { API, escapeHtml } from '../app.js';
import { IhimPanel } from './ihim-panel.js';
import './ihim-tabs.js';

class IhimHealth extends IhimPanel {
    _workoutsData = null;
    _nutritionData = null;
    _glossaryData = null;

    connectedCallback() {
        this.innerHTML = `
            <ihim-tabs>
            <!-- Tabs -->
            <div class="health-tabs" id="health-tablist" role="tablist" aria-label="Health Dashboard">
                <button class="health-tab-btn active" data-tab="workouts" role="tab" id="health-tab-workouts-btn" aria-selected="true" aria-controls="health-tab-workouts" tabindex="0">Workouts</button>
                <button class="health-tab-btn" data-tab="nutrition" role="tab" id="health-tab-nutrition-btn" aria-selected="false" aria-controls="health-tab-nutrition" tabindex="-1">Nutrition</button>
                <button class="health-tab-btn" data-tab="glossary" role="tab" id="health-tab-glossary-btn" aria-selected="false" aria-controls="health-tab-glossary" tabindex="-1">Glossary</button>
            </div>

            <!-- Workouts Tab -->
            <div id="health-tab-workouts" class="health-tab-content active" role="tabpanel" aria-labelledby="health-tab-workouts-btn">
                <div class="health-body" id="workouts-body">
                    <div class="health-loading">Loading workouts...</div>
                </div>
            </div>

            <!-- Nutrition Tab -->
            <div id="health-tab-nutrition" class="health-tab-content" role="tabpanel" aria-labelledby="health-tab-nutrition-btn" style="display: none;">
                <div class="health-body" id="nutrition-body">
                    <div class="health-loading">Loading nutrition plan...</div>
                </div>
            </div>

            <!-- Glossary Tab -->
            <div id="health-tab-glossary" class="health-tab-content" role="tabpanel" aria-labelledby="health-tab-glossary-btn" style="display: none;">
                <div class="health-body" id="glossary-body">
                    <div class="health-loading">Loading glossary...</div>
                </div>
            </div>
            </ihim-tabs>
        `;

        // Data init on open (manual click + auto-restore on reload).
        this.addEventListener('panel:open', async () => {
            if (typeof lucide !== 'undefined') lucide.createIcons();
            if (!this._workoutsData) await this._loadWorkouts();
            if (!this._nutritionData) await this._loadNutrition();
        });

        this.querySelector('ihim-tabs').addEventListener('tab:change', (e) => {
            const tabName = e.detail.tab?.dataset?.tab;
            if (tabName === 'glossary' && !this._glossaryData) this._loadGlossary();
        });

        // Event delegation for day/category expand toggles
        this.addEventListener('click', (e) => {
            const header = e.target.closest('[data-day-id]');
            if (header) this._toggleDay(header.dataset.dayId);
        });

        super.connectedCallback();
    }

    _el(id) { return this.querySelector(`#${id}`); }

    async _loadWorkouts() {
        const bodyEl = this._el('workouts-body');
        try {
            const res = await fetch(`${API}/api/health/workouts/hybrid_home_program.md`);
            const data = await res.json();
            this._workoutsData = data;
            this._renderWorkouts(data);
        } catch (e) { bodyEl.innerHTML = `<div class="health-error">Failed to load workouts: ${e.message}</div>`; }
    }

    _renderWorkouts(data) {
        const bodyEl = this._el('workouts-body');
        let html = '<div class="health-section health-universal"><h3>Universal Rules</h3>';
        html += '<div class="health-rules-text">' + escapeHtml(data.universal_rules).replace(/\n/g, '<br>') + '</div></div>';

        data.days.forEach((day, idx) => {
            const dayId = `workout-day-${idx}`;
            html += `<div class="health-day-card">
                <div class="health-day-header" data-day-id="${dayId}">
                    <span class="health-day-name">${day.day}</span>
                    <span class="health-day-title">${escapeHtml(day.title)}</span>
                    <span class="health-expand-icon" id="${dayId}-icon">▼</span>
                </div>
                <div class="health-day-content" id="${dayId}" style="display: none;">`;
            if (day.extras) html += `<div class="health-extras">${escapeHtml(day.extras).replace(/\n/g, '<br>')}</div>`;
            html += `<div class="health-subsection"><strong>Primary Plan:</strong><br>${escapeHtml(day.primary_plan).replace(/\n/g, '<br>')}</div>`;
            html += `<div class="health-subsection health-minimum"><strong>Minimum Effective Dose:</strong><br>${escapeHtml(day.minimum_dose).replace(/\n/g, '<br>')}</div>`;
            html += `</div></div>`;
        });
        bodyEl.innerHTML = html;
    }

    async _loadNutrition() {
        const bodyEl = this._el('nutrition-body');
        try {
            const res = await fetch(`${API}/api/health/nutrition`);
            const data = await res.json();
            this._nutritionData = data;
            this._renderNutrition(data);
        } catch (e) { bodyEl.innerHTML = `<div class="health-error">Failed to load nutrition: ${e.message}</div>`; }
    }

    _renderNutrition(data) {
        const bodyEl = this._el('nutrition-body');
        let html = '<div class="health-section health-universal"><h3>Nutrition Guidelines</h3>';
        html += '<div class="health-rules-text">' + escapeHtml(data.nutrition_rules).replace(/\n/g, '<br>') + '</div>';
        html += '<h4>High-Protein Staples</h4>';
        html += '<div class="health-rules-text">' + escapeHtml(data.staples).replace(/\n/g, '<br>') + '</div></div>';

        data.days.forEach((day, idx) => {
            const dayId = `nutrition-day-${idx}`;
            html += `<div class="health-day-card">
                <div class="health-day-header" data-day-id="${dayId}">
                    <span class="health-day-name">${day.day}</span>
                    <span class="health-day-title">${escapeHtml(day.title)}</span>
                    <span class="health-expand-icon" id="${dayId}-icon">▼</span>
                </div>
                <div class="health-day-content" id="${dayId}" style="display: none;">`;
            if (day.targets) html += `<div class="health-targets"><strong>Targets:</strong> ${escapeHtml(day.targets)}</div>`;
            html += `<div class="health-meals">`;
            for (const [mealType, mealContent] of Object.entries(day.meals)) {
                html += `<div class="health-meal"><strong>${mealType.charAt(0).toUpperCase() + mealType.slice(1)}:</strong><br>${escapeHtml(mealContent).replace(/\n/g, '<br>')}</div>`;
            }
            html += `</div></div></div>`;
        });
        bodyEl.innerHTML = html;
    }

    _toggleDay(dayId) {
        const content = this._el(dayId);
        const icon = this._el(dayId + '-icon');
        if (content.style.display === 'none') { content.style.display = 'block'; icon.textContent = '▲'; }
        else { content.style.display = 'none'; icon.textContent = '▼'; }
    }

    async _loadGlossary() {
        const bodyEl = this._el('glossary-body');
        try {
            const res = await fetch(`${API}/api/health/glossary`);
            const data = await res.json();
            this._glossaryData = data;
            this._renderGlossary(data);
        } catch (e) { bodyEl.innerHTML = `<div class="health-error">Failed to load glossary: ${e.message}</div>`; }
    }

    _renderGlossary(data) {
        const bodyEl = this._el('glossary-body');
        let html = '<div class="health-section health-universal"><h3>Global Cues (use everywhere)</h3>';
        html += '<div class="health-rules-text">' + escapeHtml(data.global_cues).replace(/\n/g, '<br>') + '</div></div>';

        data.categories.forEach((category, catIdx) => {
            const categoryId = `glossary-category-${catIdx}`;
            html += `<div class="health-category-card">
                <div class="health-category-header" data-day-id="${categoryId}">
                    <span class="health-category-name">${escapeHtml(category.letter)} ${escapeHtml(category.name)}</span>
                    <span class="health-expand-icon" id="${categoryId}-icon">▼</span>
                </div>
                <div class="health-category-content" id="${categoryId}" style="display: none;">`;

            category.exercises.forEach(exercise => {
                html += `<div class="health-exercise-card">
                    <div class="health-exercise-name">${exercise.number}) ${escapeHtml(exercise.name)}</div>`;
                if (exercise.target) html += `<div class="health-exercise-field"><strong>Target:</strong> ${escapeHtml(exercise.target)}</div>`;
                if (exercise.goal) html += `<div class="health-exercise-field"><strong>Goal:</strong> ${escapeHtml(exercise.goal)}</div>`;
                if (exercise.setup) html += `<div class="health-exercise-field"><strong>Setup:</strong> ${escapeHtml(exercise.setup)}</div>`;
                if (exercise.do) html += `<div class="health-exercise-field"><strong>Do:</strong> ${escapeHtml(exercise.do)}</div>`;
                if (exercise.rule) html += `<div class="health-exercise-field"><strong>Rule:</strong> ${escapeHtml(exercise.rule)}</div>`;
                if (exercise.cues) html += `<div class="health-exercise-field"><strong>Cues:</strong> ${escapeHtml(exercise.cues)}</div>`;
                if (exercise.errors) html += `<div class="health-exercise-field health-exercise-errors"><strong>Errors:</strong> ${escapeHtml(exercise.errors)}</div>`;
                if (exercise.avoid) html += `<div class="health-exercise-field health-exercise-errors"><strong>Avoid:</strong> ${escapeHtml(exercise.avoid)}</div>`;
                if (exercise.scale) html += `<div class="health-exercise-field"><strong>Scale:</strong> ${escapeHtml(exercise.scale)}</div>`;
                html += `</div>`;
            });
            html += `</div></div>`;
        });

        html += '<div class="health-section health-substitutions"><h3>Quick Substitution Map</h3>';
        html += '<div class="health-rules-text">' + escapeHtml(data.substitution_map).replace(/\n/g, '<br>') + '</div></div>';
        html += '<div class="health-section health-checklist"><h3>10-Second Checklist</h3>';
        html += '<div class="health-rules-text">' + escapeHtml(data.checklist).replace(/\n/g, '<br>') + '</div></div>';
        bodyEl.innerHTML = html;
    }
}

customElements.define('ihim-health', IhimHealth);
