/* Pixel geometry is deliberately independent of price units and ticker currency. */
function bisectLines(a, b) {
    const normal = ([p, q]) => {
        const dx = q[0] - p[0], dy = q[1] - p[1];
        const length = Math.hypot(dx, dy);
        return length < 1e-8 ? null : [-dy / length, dx / length];
    };
    const n = normal(a), m = normal(b);
    if (!n || !m) return null;
    // Orient directions consistently to select the smaller-angle bisector.
    if (n[0] * m[0] + n[1] * m[1] < 0) {
        m[0] *= -1; m[1] *= -1;
    }
    const c = n[0] * a[0][0] + n[1] * a[0][1]
            + m[0] * b[0][0] + m[1] * b[0][1];
    return [n[0] + m[0], n[1] + m[1], c];
}

function clipLine([nx, ny, c], width, height) {
    const points = [];
    const add = (x, y) => {
        if (Number.isFinite(x) && Number.isFinite(y)
            && x >= -1e-6 && x <= width + 1e-6
            && y >= -1e-6 && y <= height + 1e-6
            && !points.some(p => Math.hypot(p[0] - x, p[1] - y) < 1e-6)) {
            points.push([x, y]);
        }
    };
    if (Math.abs(ny) > 1e-10) {
        add(0, c / ny); add(width, (c - nx * width) / ny);
    }
    if (Math.abs(nx) > 1e-10) {
        add(c / nx, 0); add((c - ny * height) / nx, height);
    }
    return points.length >= 2 ? points.slice(0, 2) : null;
}

function mountReferenceLines(payload) {
    const owner = window;
    let activeWindow, state, timer, attempts = 0;
    const token = {};
    const cleanup = () => {
        clearInterval(timer);
        if (state && state.token === token) state.svg.remove();
    };
    window.addEventListener('pagehide', cleanup, {once: true});
    const tick = () => {
        if (!owner.frameElement?.isConnected) { cleanup(); return; }
        if (!activeWindow) {
            for (const frame of window.parent.document.querySelectorAll('iframe')) {
                try {
                    if (frame.contentWindow.chartApiMap?.[payload.id]) {
                        activeWindow = frame.contentWindow; break;
                    }
                } catch (_) { /* Ignore unrelated cross-origin frames. */ }
            }
        }
        const chart = activeWindow?.chartApiMap?.[payload.id];
        const candle = activeWindow?.seriesRefsMap?.[payload.id]?.[0];
        if (!chart || !candle) {
            activeWindow = null;
            if (++attempts > 100) cleanup();
            return;
        }
        const pane = chart.panes()[0];
        const element = pane?.getHTMLElement();
        if (!element) return;
        const scale = chart.timeScale();
        const size = chart.paneSize(0);
        const canvas = [...element.querySelectorAll('canvas')].find(c =>
            Math.abs(c.getBoundingClientRect().width - size.width) < 2);
        if (!canvas || size.width < 10 || size.height < 10) return;
        const project = p => [scale.logicalToCoordinate(p[0]), candle.priceToCoordinate(p[1])];
        const a = payload.openClose.map(project), b = payload.lowHigh.map(project);
        if ([...a.flat(), ...b.flat()].some(v => v === null || !Number.isFinite(v))) return;
        const key = JSON.stringify(payload);
        const existing = chart.__referenceLines;
        if (state && state !== existing) { cleanup(); return; }
        if (!state || state !== existing || state.key !== key) {
            existing?.svg.remove();
            const svg = activeWindow.document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.style.cssText = 'position:fixed;pointer-events:none;overflow:hidden;z-index:20';
            svg.setAttribute('aria-hidden', 'true');
            activeWindow.document.body.appendChild(svg);
            const equation = bisectLines(a, b);
            const endpoints = equation && clipLine(equation, size.width, size.height);
            const bisector = existing?.key === key ? existing.bisector
                : endpoints?.map(p => [scale.coordinateToLogical(p[0]), candle.coordinateToPrice(p[1])]);
            state = {key, svg, bisector, token, signature: null};
            chart.__referenceLines = state;
        } else if (state.token !== token) {
            // A newer Streamlit render owns this chart now.
            clearInterval(timer); return;
        }
        const rect = canvas.getBoundingClientRect();
        const middle = state.bisector?.map(project);
        const signature = JSON.stringify([rect.left, rect.top, size, a, b, middle]);
        if (signature === state.signature) return;
        state.signature = signature;
        Object.assign(state.svg.style, {left: `${rect.left}px`, top: `${rect.top}px`,
            width: `${size.width}px`, height: `${size.height}px`});
        state.svg.setAttribute('viewBox', `0 0 ${size.width} ${size.height}`);
        state.svg.replaceChildren();
        const draw = (points, color, dashed = false) => {
            if (!points || points.flat().some(v => v === null || !Number.isFinite(v))) return;
            const line = activeWindow.document.createElementNS('http://www.w3.org/2000/svg', 'line');
            const [p, q] = points;
            for (const [name, value] of Object.entries({x1: p[0], y1: p[1], x2: q[0], y2: q[1],
                stroke: color, 'stroke-width': dashed ? 2.5 : 2})) line.setAttribute(name, value);
            if (dashed) line.setAttribute('stroke-dasharray', '7 4');
            state.svg.appendChild(line);
        };
        draw(a, '#0891b2'); draw(b, '#d97706');
        if (middle) {
            const p = middle[0], q = middle[1];
            const nx = p[1] - q[1], ny = q[0] - p[0];
            draw(clipLine([nx, ny, nx * p[0] + ny * p[1]], size.width, size.height), '#334155', true);
        }
    };
    timer = setInterval(() => {
        try { tick(); } catch (error) {
            cleanup(); console.warn('Reference line overlay unavailable', error);
        }
    }, 100);
    tick();
}

if (typeof module !== 'undefined') module.exports = {bisectLines, clipLine};
