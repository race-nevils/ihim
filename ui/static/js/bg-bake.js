/* Background bake — renders the dashboard backdrop (vertical fade + ember
   corners) into a full-viewport canvas with float-precision math and
   per-pixel dithering, instead of letting the browser engine rasterize CSS
   gradients.

   Why: engine-rasterized gradients quantize to 8-bit with no dithering, and
   HOW they band varies with the rendering pipeline (GPU raster path, color
   profile transform at composite) — the same CSS showed a visible contour
   line in the desktop shell that the plain browser smoothed. Baking the
   pixels ourselves removes the engine from the equation: the math runs in
   float, the falloff eases into its endpoints with zero slope (no terminal
   kink for the eye to catch), and triangular dither breaks quantization
   steps apart before they can align into a line. Every surface that shows
   this page renders identical pixels.

   The CSS background on <body> (style.css) is the same composition and
   stays as the first-paint fallback; this canvas sits at z-index -1 —
   above the propagated document background, below all content — and covers
   it once baked. */
(function () {
    'use strict';

    var canvas = document.createElement('canvas');
    canvas.id = 'bg-bake';
    canvas.setAttribute('aria-hidden', 'true');
    var cs = canvas.style;
    cs.position = 'fixed';
    cs.inset = '0';
    cs.width = '100%';
    cs.height = '100%';
    cs.zIndex = '-1';
    cs.pointerEvents = 'none';
    document.body.prepend(canvas);

    /* Composition constants — keep in lockstep with the body background in
       style.css (the fallback must match what the bake paints over it). */
    var EMBER_R = 220, EMBER_G = 20, EMBER_B = 60; /* crimson */
    var EMBER_PEAK = 0.12;   /* corner alpha at the gradient origin — the
                                ember is a tint over the fade, never a wash */
    var EMBER_END = 0.45;    /* where the ember reaches zero, as a fraction
                                of the gradient run */
    var EMBER_ANGLES = [145, 215];   /* CSS gradient angles: top-left, top-right */
    /* Vertical fade stops (grayscale): #121212 -> #0a0a0a at 45% -> #060606 */
    var BASE_STOPS = [[0, 18], [0.45, 10], [1, 6]];

    function bake() {
        var dpr = window.devicePixelRatio || 1;
        var w = Math.max(1, Math.round(window.innerWidth * dpr));
        var h = Math.max(1, Math.round(window.innerHeight * dpr));
        canvas.width = w;
        canvas.height = h;
        var ctx = canvas.getContext('2d');
        var img = ctx.createImageData(w, h);
        var px = img.data;

        /* Base fade lookup, one entry per row. */
        var baseLUT = new Float32Array(h);
        for (var y = 0; y < h; y++) {
            var t = h > 1 ? y / (h - 1) : 0;
            var s0 = BASE_STOPS[0], s1 = BASE_STOPS[1];
            if (t > BASE_STOPS[1][0]) { s0 = BASE_STOPS[1]; s1 = BASE_STOPS[2]; }
            var f = (t - s0[0]) / (s1[0] - s0[0]);
            baseLUT[y] = s0[1] + (s1[1] - s0[1]) * f;
        }

        /* Ember alpha lookups, one entry per pixel of travel along each
           gradient axis. CSS angle convention: 0deg points up, clockwise;
           the 0% end sits at the corner the direction vector points away
           from. Raised-cosine falloff — flat at the peak, flat again at
           the landing, zero from EMBER_END on: the ember tints its own
           corner and is mathematically gone everywhere else, so the
           vertical fade owns the middle of the screen. No kink at either
           end for the eye to catch (Mach banding). */
        var axes = [];
        for (var a = 0; a < EMBER_ANGLES.length; a++) {
            var rad = EMBER_ANGLES[a] * Math.PI / 180;
            var gx = Math.sin(rad), gy = -Math.cos(rad);
            var L = Math.abs(w * gx) + Math.abs(h * gy);
            var lut = new Float32Array(Math.ceil(L) + 2);
            for (var i = 0; i < lut.length; i++) {
                var u = (i / L) / EMBER_END;
                lut[i] = u >= 1 ? 0 :
                    EMBER_PEAK * 0.5 * (1 + Math.cos(Math.PI * u));
            }
            axes.push({ gx: gx, gy: gy, half: L / 2, cx: w / 2, cy: h / 2, lut: lut });
        }

        var A = axes[0], B = axes[1];
        var o = 0;
        for (y = 0; y < h; y++) {
            var base = baseLUT[y];
            /* Row-incremental projection onto each gradient axis. */
            var pa = (0 - A.cx) * A.gx + (y - A.cy) * A.gy + A.half;
            var pb = (0 - B.cx) * B.gx + (y - B.cy) * B.gy + B.half;
            for (var x = 0; x < w; x++, pa += A.gx, pb += B.gx) {
                var r = base, g = base, b = base;

                /* Ember corners, composited in the same order as the CSS
                   layer list (145deg under 215deg). */
                var ia = pa < 0 ? 0 : pa | 0;
                var al = A.lut[ia] || 0;
                if (al > 0) {
                    r += (EMBER_R - r) * al;
                    g += (EMBER_G - g) * al;
                    b += (EMBER_B - b) * al;
                }
                var ib = pb < 0 ? 0 : pb | 0;
                al = B.lut[ib] || 0;
                if (al > 0) {
                    r += (EMBER_R - r) * al;
                    g += (EMBER_G - g) * al;
                    b += (EMBER_B - b) * al;
                }

                /* Triangular-PDF dither, shared across channels so the
                   noise stays luminance-only. ±1 level — invisible as
                   texture, but it makes 8-bit quantization steps
                   physically unable to line up into a contour. No grain
                   layer: grain only ever existed to hide banding, and
                   dither does that job without reading as static. */
                var dd = Math.random() + Math.random() - 1;
                px[o++] = r + dd;
                px[o++] = g + dd;
                px[o++] = b + dd;
                px[o++] = 255;
            }
        }
        ctx.putImageData(img, 0, 0);
    }

    /* First bake AFTER first paint — a rAF callback runs before the paint
       it precedes, so the bake itself rides a timeout queued from one (the
       CSS fallback owns that first frame). Re-bake on resize, debounced;
       dither must live at native pixels. */
    requestAnimationFrame(function () { setTimeout(bake, 0); });
    var timer;
    window.addEventListener('resize', function () {
        clearTimeout(timer);
        timer = setTimeout(bake, 150);
    });
})();
