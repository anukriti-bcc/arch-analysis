// Layout for the evolution timeline: places history events along a horizontal
// axis in proportion to their dates, keeps neighbouring labels from colliding,
// and alternates labels above/below the line.

const DAY_MS = 86400000;
const PAD = 7; // percent kept free at each end of the track

export function toTime(iso) {
  return new Date(iso).getTime();
}

export function daysBetween(a, b) {
  return Math.round((toTime(b) - toTime(a)) / DAY_MS);
}

export const EVENT_META = {
  introduced: { label: "Introduced", tone: "violation" },
  reintroduced: { label: "Reintroduced", tone: "violation" },
  removed: { label: "Removed", tone: "conformant" },
  snapshot: { label: "Snapshot (HEAD)", tone: "neutral" },
};

export function layoutTimeline(timeline, snapshotDate) {
  const points = [...(timeline || [])]
    .filter((e) => e && e.date && !Number.isNaN(toTime(e.date)))
    .map((e) => ({ kind: e.change, date: e.date, short: e.short, subject: e.subject, author: e.author }))
    .sort((a, b) => toTime(a.date) - toTime(b.date));

  if (snapshotDate && !Number.isNaN(toTime(snapshotDate))) {
    points.push({ kind: "snapshot", date: snapshotDate });
  }
  if (points.length === 0) return [];
  if (points.length === 1) return [{ ...points[0], x: 50, row: "above" }];

  const t0 = toTime(points[0].date);
  const t1 = toTime(points[points.length - 1].date);
  const span = t1 - t0;
  const lo = PAD;
  const hi = 100 - PAD;
  const minGap = Math.min(14, (hi - lo) / (points.length - 1));

  let xs = points.map((p, i) =>
    span === 0 ? lo + ((hi - lo) * i) / (points.length - 1) : lo + ((toTime(p.date) - t0) / span) * (hi - lo)
  );
  // push right to keep a minimum gap, then compress back if we ran past the end
  for (let i = 1; i < xs.length; i++) xs[i] = Math.max(xs[i], xs[i - 1] + minGap);
  const overflow = xs[xs.length - 1] - hi;
  if (overflow > 0) {
    const scale = (hi - xs[0]) / (xs[xs.length - 1] - xs[0]);
    xs = xs.map((x) => xs[0] + (x - xs[0]) * scale);
  }
  return points.map((p, i) => ({ ...p, x: Math.round(xs[i] * 100) / 100, row: i % 2 === 0 ? "above" : "below" }));
}
