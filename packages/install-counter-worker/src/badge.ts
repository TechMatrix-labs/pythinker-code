export function installsJson(count: number | null) {
  return { installs: count };
}

export function badgeJson(count: number | null) {
  if (count == null) {
    return { schemaVersion: 1, label: "installs", message: "unknown", color: "lightgrey" };
  }
  return {
    schemaVersion: 1,
    label: "installs",
    message: count.toLocaleString("en-US"),
    color: "blue",
  };
}
