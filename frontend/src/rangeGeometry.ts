import type { Report } from "./api";
export function rangeGeometry(test: Report["tests"][number]) {
  if (
    test.uncertain ||
    test.status === "indeterminate" ||
    !test.unit ||
    !test.value ||
    !test.reference_range
  )
    return null;
  const number = "[+-]?(?:\\d+(?:\\.\\d+)?|\\.\\d+)";
  if (!new RegExp(`^${number}$`).test(test.value)) return null;
  const match = test.reference_range.match(
    new RegExp(
      `^\\s*(${number})\\s*(?:-|–|—|to)\\s*(${number})(?:\\s+(.+))?\\s*$`,
      "i",
    ),
  );
  if (
    !match ||
    (match[3] &&
      match[3].trim().toLowerCase() !== test.unit.trim().toLowerCase())
  )
    return null;
  const value = Number(test.value),
    low = Number(match[1]),
    high = Number(match[2]),
    span = high - low;
  if (![value, low, high, span].every(Number.isFinite) || span <= 0)
    return null;
  const start = Math.min(low - span * 0.5, value - span * 0.1),
    end = Math.max(high + span * 0.5, value + span * 0.1);
  if (!Number.isFinite(end - start) || end <= start) return null;
  const position = (v: number) => (100 * (v - start)) / (end - start);
  return {
    low,
    high,
    value,
    lowPosition: position(low),
    highPosition: position(high),
    marker: position(value),
  };
}
