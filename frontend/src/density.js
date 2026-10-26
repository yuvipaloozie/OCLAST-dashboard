const quantile = (sorted, p) => {
  const i = (sorted.length - 1) * p;
  return sorted[Math.floor(i)] + (sorted[Math.ceil(i)] - sorted[Math.floor(i)]) * (i % 1);
};

function niceCeiling(value) {
  const step = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / step) * step;
}

// Gaussian KDE with reflected kernels at physical bounds. Every valid object
// contributes, even when the display focuses on the central 95% of observations.
export function estimateDensity(input, bounded = false, focused = false) {
  const values = input.filter(v => Number.isFinite(v) && v >= 0 && (!bounded || v <= 1)).sort((a, b) => a - b);
  if (!values.length) return {points: [], min: 0, max: bounded ? 1 : 100, count: 0, outside: 0};
  const n = values.length;
  const mean = values.reduce((sum, v) => sum + v, 0) / n;
  const sd = Math.sqrt(values.reduce((sum, v) => sum + (v - mean) ** 2, 0) / Math.max(1, n - 1));
  const iqrScale = (quantile(values, .75) - quantile(values, .25)) / 1.34;
  const scale = Math.min(...[sd, iqrScale].filter(v => v > 0));
  let bandwidth = Number.isFinite(scale) ? .9 * scale * n ** (-.2) : (bounded ? .03 : Math.max(mean * .1, 1));
  bandwidth = Math.max(bandwidth, bounded ? .005 : 1);
  let min = 0;
  let max = bounded ? 1 : niceCeiling(values[n - 1] + 3 * bandwidth);
  if (focused) {
    // Robust display limits avoid a few extreme objects compressing the curve.
    // A small smoothing margin and rounded limits keep the plot readable.
    const low = quantile(values, .025);
    const high = quantile(values, .975);
    const padding = Math.max(bandwidth * .5, (3 * bandwidth - (high - low)) / 2);
    const step = 10 ** Math.floor(Math.log10((high - low + 2 * padding) / 5));
    min = Math.max(0, Math.floor((low - padding) / step) * step);
    max = Math.ceil((high + padding) / step) * step;
    if (bounded) max = Math.min(1, max);
  }
  const outside = values.filter(v => v < min || v > max).length;
  const gaussian = z => Math.exp(-.5 * z * z);
  const points = Array.from({length: 513}, (_, i) => {
    const x = min + (max - min) * i / 512;
    const sum = values.reduce((total, v) => total + gaussian((x - v) / bandwidth)
      + gaussian((x + v) / bandwidth)
      + (bounded ? gaussian((x - (2 - v)) / bandwidth) : 0), 0);
    return {x, y: sum / (n * bandwidth * Math.sqrt(2 * Math.PI))};
  });
  return {points, min, max, count: n, bandwidth, outside};
}
