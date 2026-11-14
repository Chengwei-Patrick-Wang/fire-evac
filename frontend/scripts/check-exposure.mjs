// Checks the what-if headline wording. Usage (from frontend/): node scripts/check-exposure.mjs
let m
try {
  m = await import('../src/model/exposure.ts')
} catch (e) {
  console.log('check skipped: needs Node 22.18+')
  process.exit(0)
}
const run = (psis, smokeAt, t90) => ({
  metrics: { t90, trapped: 1, exposure: { personSecondsInSmoke: psis, stairs: [{ floor: 'F1', group: 'SA', smokeAt }] } },
})
const p = m.pairHeadline(run(1654, 93, 124.2), run(2020, 62, 124.4), 'Propping DSA1 open')
const b = m.batchHeadline({
  runs: [{ smokeSeconds: 1000 }, { smokeSeconds: 1200 }],
  whatIf: [{ id: 'proppedStairs', label: 'Stair doors propped open', why: 'x', n: 2, dT90: 0.2, slower: 1, faster: 0, dTrapped: 0, dSmokeSeconds: 242 }],
})
console.log(p)
console.log(b)
let ok = true
if (p?.main !== 'Propping DSA1 open: +22% person-seconds in smoke, Stair A on F1 fills 31 s sooner') {
  console.error('FAIL pairHeadline')
  ok = false
}
if (b?.main !== 'Stair doors propped open: +22% person-seconds in smoke') {
  console.error('FAIL batchHeadline')
  ok = false
}
process.exit(ok ? 0 : 1)
