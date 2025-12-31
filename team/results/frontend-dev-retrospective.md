# Frontend Dev Retrospective: Stopwatch Widget

**Task:** Build stopwatch widget with spawn functionality
**Date:** 2025-12-27
**Status:** Complete

---

## Assumptions I Didn't Verify

### Technology Stack
- Initially assumed iHIM might use React/TypeScript based on the <business> project in the same repo
- Should have checked the file extensions first (.html, .css, .js = vanilla JavaScript)

### localStorage Availability
- Assumed localStorage is always available
- In private browsing mode or with storage disabled, the widget works but won't persist state
- Didn't add error handling for this edge case

### Timer Precision
- Assumed `setInterval` at 10ms provides smooth centisecond display
- JavaScript timers can drift under heavy CPU load, but for a stopwatch this is acceptable

### Z-index Conflicts
- Used z-index: 50 for the widget container without verifying against all modal z-indices
- Modals use z-index: 1000, so there should be no conflict, but didn't test with all modals open simultaneously

---

## Where I Wasted Time

### Over-reading the Codebase
- Read more of index.html than necessary (~1500 lines when ~200 would have sufficed)
- Could have focused on just one modal pattern and the initialization section

### Considered React Patterns First
- Spent initial time looking for React component patterns
- Should have immediately checked file extensions to determine technology

### CSS Lap Feature
- Added CSS for a lap times feature that wasn't requested
- Kept it minimal (~20 lines) but it's unused code that could be removed

---

## What I'd Do Differently

1. **Check Technology Stack Immediately**
   - Run `ls *.tsx *.jsx` or check file extensions before exploring patterns

2. **Ask About Positioning**
   - Top-right corner was an assumption
   - Should have asked: "Do you want the stopwatch as a floating widget, in a modal, or in a specific dashboard section?"

3. **Start with Minimal CSS**
   - Glassmorphism effects look nice but added complexity
   - Could have shipped faster with simpler card styling and enhanced later

4. **Add Mobile Breakpoints**
   - Didn't consider responsive design
   - Should have added a media query for smaller screens

---

## What Might Break

### Memory Leaks
- If users spawn many stopwatches without removing them, intervals accumulate
- Added interval cleanup on remove(), but not on page unload for running timers
- Running timers on closed page will be "resumed" on next load (by design) but could surprise users

### Mobile Responsiveness
- No mobile breakpoints added
- Widget positioned fixed in top-right corner may overlap content on small screens
- Touch targets might be too small on mobile

### Extreme Values
- No upper bound on timer - after 99:59.99 it will show 100:00.00 etc.
- Display could overflow its container at very large times (hours)

### Interval Cleanup on Unload
```javascript
// NOT IMPLEMENTED - timers keep "running" via startTime calculation
window.addEventListener('beforeunload', () => {
    // Could add: clear all intervals here
});
```
This is intentional (to preserve running state) but could be unexpected.

---

## What Next Agent Should Know

### No Backend Needed
- This is a purely frontend feature
- State persists via localStorage key `ihim_stopwatches`
- No API endpoints required

### CSS Variables
- All colors use existing CSS variables from `:root` in style.css
- Key variables: `--accent-cyan`, `--glass-bg`, `--glass-blur`, `--status-success`

### Widget Position
- Fixed position, top-right corner
- To move: update `.stopwatch-container` in style.css

### State Structure
```javascript
{
  nextId: 3,
  stopwatches: [
    { id: 1, elapsed: 5000, running: false },
    { id: 2, elapsed: 12345, running: true }
  ]
}
```

### Key Functions
- `stopwatchManager.spawn()` - Create new stopwatch
- `stopwatchManager.toggle(id)` - Start/stop toggle
- `stopwatchManager.reset(id)` - Reset to 00:00.00
- `stopwatchManager.remove(id)` - Delete stopwatch

---

## Files Changed

| File | Lines Added | Purpose |
|------|-------------|---------|
| `IHIM/ui/static/style.css` | ~250 | Stopwatch widget styling |
| `IHIM/ui/index.html` | ~260 | HTML container + JavaScript manager |

---

## Testing Checklist for QA

- [ ] Click + button to spawn stopwatch
- [ ] Click Start, verify timer counts up with millisecond precision
- [ ] Click Stop, verify timer pauses at current value
- [ ] Click Start again, verify timer resumes from paused time
- [ ] Click Reset, verify timer resets to 00:00.00
- [ ] Click X to remove stopwatch, verify smooth animation
- [ ] Spawn 3+ stopwatches, verify they run independently
- [ ] Refresh page, verify all stopwatches restore (with correct times)
- [ ] Start timer, close tab, reopen - verify timer "continued" running
- [ ] Test hover effects on spawn button (rotation animation)
- [ ] Verify running stopwatch has pulsing top border

---

## Summary

**What Went Well:**
- Clean implementation following existing iHIM patterns
- Full state persistence across page reloads
- Smooth animations matching the HUD aesthetic
- No backend dependencies = no coordination overhead

**What Could Improve:**
- Mobile responsiveness not addressed
- Over-read the codebase before building
- Added unused CSS for lap feature

**Lesson Learned:**
Check technology stack (React vs vanilla JS) FIRST before exploring component patterns.
