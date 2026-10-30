const assert = require('node:assert/strict');
const {bisectLines, clipLine} = require('../screening/chart_reference_lines.js');
const distance = (p, a, b) => Math.abs((b[1]-a[1])*p[0] - (b[0]-a[0])*p[1]
    + b[0]*a[1]-b[1]*a[0]) / Math.hypot(b[0]-a[0], b[1]-a[1]);
for (const [a, b] of [
    [[[0, 100], [200, 50]], [[30, 0], [80, 150]]],
    [[[0, 100], [200, 50]], [[80, 150], [30, 0]]],
    [[[40, 0], [40, 200]], [[0, 100], [200, 100]]],
    [[[0, 50], [200, 50]], [[0, 150], [200, 150]]],
    [[[0, 50], [200, 50]], [[0, 50], [200, 50]]],
]) {
    const equation = bisectLines(a, b);
    const points = clipLine(equation, 200, 200);
    assert.ok(points);
    for (const p of points) assert.ok(Math.abs(distance(p, ...a) - distance(p, ...b)) < 1e-7);
}
assert.equal(bisectLines([[1, 1], [1, 1]], [[0, 0], [2, 2]]), null);
assert.equal(clipLine([0, 1, -5], 200, 200), null);
console.log('Angle bisector: equal-distance, reversed, vertical, parallel, coincident and degenerate cases passed');
