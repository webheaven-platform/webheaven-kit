// Compare versions like "1.2.0", "v1.3.0-rc.1". Returns <0, 0 or >0. A pre-release sorts before its release.
const parse = v => {
  const [core, pre] = String(v).trim().replace(/^v/i, "").split("-", 2);
  return { nums: core.split(".").map(n => parseInt(n, 10) || 0), pre: pre ?? null };
};

export function compareVersions(a, b) {
  const pa = parse(a), pb = parse(b);
  for (let i = 0; i < 3; i++) {
    const d = (pa.nums[i] ?? 0) - (pb.nums[i] ?? 0);
    if (d) return d;
  }
  if (pa.pre === pb.pre) return 0;
  if (pa.pre === null) return 1;
  if (pb.pre === null) return -1;
  return pa.pre < pb.pre ? -1 : 1;
}
