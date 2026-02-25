/**
 * health-dashboard.js — Health & wellness dashboard (workouts, nutrition, glossary)
 */
import { API, escapeHtml } from './app.js';


let workoutsData = null;
let nutritionData = null;
let glossaryData = null;

export async function openHealthWindow() {
    const win = document.getElementById('health-window');
    if (!win) return;
    win.open();
    if (typeof lucide !== 'undefined') lucide.createIcons();
    if (!workoutsData) await loadWorkouts();
    if (!nutritionData) await loadNutrition();
}

export function closeHealthWindow() {
    const win = document.getElementById('health-window');
    if (win) win.close();
}

async function loadWorkouts() {
    const bodyEl = document.getElementById('workouts-body');
    try {
        const res = await fetch(`${API}/api/health/workouts/hybrid_home_program.md`);
        const data = await res.json();
        workoutsData = data;
        renderWorkouts(data);
    } catch (e) { bodyEl.innerHTML = `<div class="health-error">Failed to load workouts: ${e.message}</div>`; }
}

function renderWorkouts(data) {
    const bodyEl = document.getElementById('workouts-body');
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

async function loadNutrition() {
    const bodyEl = document.getElementById('nutrition-body');
    try {
        const res = await fetch(`${API}/api/health/nutrition`);
        const data = await res.json();
        nutritionData = data;
        renderNutrition(data);
    } catch (e) { bodyEl.innerHTML = `<div class="health-error">Failed to load nutrition: ${e.message}</div>`; }
}

function renderNutrition(data) {
    const bodyEl = document.getElementById('nutrition-body');
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

export function toggleHealthDay(dayId) {
    const content = document.getElementById(dayId);
    const icon = document.getElementById(dayId + '-icon');
    if (content.style.display === 'none') { content.style.display = 'block'; icon.textContent = '▲'; }
    else { content.style.display = 'none'; icon.textContent = '▼'; }
}

async function loadGlossary() {
    const bodyEl = document.getElementById('glossary-body');
    try {
        const res = await fetch(`${API}/api/health/glossary`);
        const data = await res.json();
        glossaryData = data;
        renderGlossary(data);
    } catch (e) { bodyEl.innerHTML = `<div class="health-error">Failed to load glossary: ${e.message}</div>`; }
}

function renderGlossary(data) {
    const bodyEl = document.getElementById('glossary-body');
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

// Event delegation for health day toggles
export function initHealthEvents() {
    const win = document.getElementById('health-window');
    if (!win) return;

    const tabs = win.querySelector('ihim-tabs');
    if (tabs) {
        tabs.addEventListener('tab:change', (e) => {
            const tabName = e.detail.tab?.dataset?.tab;
            if (tabName === 'glossary' && !glossaryData) loadGlossary();
        });
    }

    win.addEventListener('click', (e) => {
        const header = e.target.closest('[data-day-id]');
        if (header) toggleHealthDay(header.dataset.dayId);
    });
}
