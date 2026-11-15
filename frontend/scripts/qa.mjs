// Headless visual QA: node scripts/qa.mjs [--open FILE]... [--only=step,step]  (run `npm run build` first; `npm run qa` does both)
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { preview } from 'vite'

// axe rules we accept as-is, one line of reason each (none yet)
const AXE_ALLOW = []

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const out = join(root, 'qa')
// A11's run/v0 with fire.rooms (the room-to-room spread), kept in contracts/ and never copied into public/.
const FIXTURE = join(root, '..', 'contracts', 'run.spread.fixture.json')
const opens = []
for (let i = 2; i < process.argv.length; i++) {
  if (process.argv[i] === '--open' && process.argv[i + 1]) opens.push(resolve(process.argv[++i]))
}
// --only=a,b runs just the steps whose names start with a or b (`load` first: most steps work on its page), for trying one change.
const ONLY = (process.argv.find((a) => a.startsWith('--only='))?.slice('--only='.length) ?? '').split(',').filter(Boolean)
const FPS = process.argv.includes('--fps')
const GPU = process.argv.includes('--gpu')
rmSync(out, { recursive: true, force: true })
mkdirSync(out, { recursive: true })

const problems = []
const errors = []
let cur = 'start'
const shots = []
const lines = []
let webgl = false
let playSecs = 0

const server = await preview({ root, preview: { port: 4317 }, logLevel: 'warn' })
let browser
try {
  try {
    if (GPU) {
      try {
        browser = await chromium.launch({
          channel: 'chromium',
          headless: false,
          args: [
            '--ignore-gpu-blocklist',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-background-timer-throttling',
            '--disable-features=CalculateNativeWinOcclusion',
          ],
        })
      } catch (e) {
        lines.push('gpu: not available, SwiftShader numbers only')
        console.error(`gpu launch failed: ${String(e).split('\n')[0]}`)
      }
    }
    if (!browser)
      browser = await chromium.launch({
        channel: 'chromium',
        args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
      })
  } catch (e) {
    if (/Executable doesn't exist|executable/i.test(String(e))) console.error('Run: npx playwright install chromium')
    throw e
  }
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
  await ctx.addInitScript(() => {
    try {
      localStorage['fes.aboutSeen'] = '1'
    } catch {
      /* ignore */
    }
  })
  const page = await ctx.newPage()
  page.on('console', (m) => {
    if (m.type() !== 'error') return
    const t = m.text()
    if (/Failed to load resource/.test(t) && /calibration\.json/.test(m.location()?.url ?? t)) return
    errors.push(`[${cur}] ${t}`)
  })
  page.on('pageerror', (e) => errors.push(`[${cur}] ${String(e)}`))

  const step = async (name, fn) => {
    if (ONLY.length && !ONLY.some((o) => name.startsWith(o))) return
    cur = name
    try {
      await fn()
    } catch (e) {
      problems.push(`step "${name}" failed: ${String(e).split('\n')[0]}`)
    }
  }
  // Console and page errors of an extra page go to the report under `tag` (a missing calibration.json is allowed).
  const watchPage = (pg, tag, ignore = /calibration\.json/) => {
    pg.on('console', (m) => {
      if (m.type() === 'error' && !ignore.test(m.text() + (m.location()?.url ?? ''))) errors.push(`[${tag}] ${m.text()}`)
    })
    pg.on('pageerror', (e) => errors.push(`[${tag}] ${String(e)}`))
  }
  const shot = async (name, pg = page) => {
    await pg.screenshot({ path: join(out, name + '.png') })
    shots.push(name)
  }
  const tabShots = async (prefix) => {
    const names = ['results', 'risk', 'report', 'cred']
    for (let i = 0; i < names.length; i++) {
      await step(`${prefix}tab-${names[i]}`, async () => {
        await page.locator('.results [role=tab]').nth(i).click()
        await page.waitForTimeout(1000)
        await shot(`${prefix}tab-${names[i]}`)
      })
    }
  }
  // The nav is a drawer, collapsed by default: open it to reach a menu or the toolbar, and leave it collapsed again.
  const nav = async (pg, open) => {
    const t = pg.locator('#nav-toggle')
    if (((await t.getAttribute('aria-expanded')) === 'true') !== open) await t.click()
    await pg.waitForFunction((o) => document.getElementById('nav-toggle')?.getAttribute('aria-expanded') === String(o), open, { timeout: 5000 })
  }
  const pickMenu = async (pg, menu, item) => {
    await pg.locator('#topnav .menus').getByRole('button', { name: menu, exact: true }).click()
    await pg.locator('[role=menu] .mi-label', { hasText: new RegExp(`^${item.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`) }).first().click()
  }
  const AXE = join(root, 'node_modules', 'axe-core', 'axe.min.js')
  const axeOn = async (pg, label, sel) => {
    if (!existsSync(AXE)) return void lines.push('axe skipped: not installed')
    if (!(await pg.evaluate(() => !!window.axe))) await pg.addScriptTag({ path: AXE })
    const res = await pg.evaluate(
      async (sel) => {
        const r = await window.axe.run(document.querySelector(sel), { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } })
        return r.violations.map((v) => ({ id: v.id, impact: v.impact, target: String(v.nodes[0]?.target?.[0] ?? ''), n: v.nodes.length }))
      },
      sel,
    )
    for (const v of res) {
      if ((v.impact === 'serious' || v.impact === 'critical') && !AXE_ALLOW.includes(v.id)) problems.push(`axe ${label}: ${v.id} (${v.impact}) x${v.n}, first ${v.target}`)
      else lines.push(`axe ${label}: ${v.id} (${v.impact}) x${v.n}, first ${v.target}`)
    }
    lines.push(`axe ${label}: ${res.length} violations`)
  }
  const changedShare = (b64, pg = page) =>
    pg.evaluate(async (b64) => {
        const img = new Image()
        img.src = 'data:image/png;base64,' + b64
        await img.decode()
        const c = document.createElement('canvas')
        c.width = img.width
        c.height = img.height
        const g = c.getContext('2d')
        g.drawImage(img, 0, 0)
        const x0 = Math.floor(img.width / 4)
        const y0 = Math.floor(img.height / 4)
        const w = Math.max(1, Math.floor(img.width / 2))
        const h = Math.max(1, Math.floor(img.height / 2))
        const d = g.getImageData(x0, y0, w, h).data
        const counts = new Map()
        for (let p = 0; p < d.length; p += 4) {
          const k = (d[p] << 16) | (d[p + 1] << 8) | d[p + 2]
          counts.set(k, (counts.get(k) ?? 0) + 1)
        }
        let best = 0
        let bc = -1
        for (const [k, v] of counts) if (v > bc) ((best = k), (bc = v))
        const r = best >> 16
        const gg = (best >> 8) & 255
        const bb = best & 255
        let diff = 0
        for (let p = 0; p < d.length; p += 4) {
          if (Math.abs(d[p] - r) + Math.abs(d[p + 1] - gg) + Math.abs(d[p + 2] - bb) > 40) diff++
        }
        return diff / (d.length / 4)
    }, b64)
  const blankCheck = async (name, pg = page) => {
    const canvases = pg.locator('main.center canvas')
    const n = await canvases.count()
    if (n === 0) {
      problems.push(`no canvas in ${name}`)
      lines.push(`${name}: no canvas`)
      return
    }
    for (let i = 0; i < n; i++) {
      const buf = await canvases.nth(i).screenshot()
      const share = await changedShare(buf.toString('base64'), pg)
      lines.push(`${name}: canvas ${i} changed ${(share * 100).toFixed(1)}%`)
      if (share < 0.01) problems.push(`blank canvas in ${name}`)
    }
  }

  await step('load', async () => {
    await page.goto(`${server.resolvedUrls.local[0]}?qa`)
    await page.waitForFunction(() => window.__app?.getState().activeRunKey, null, { timeout: 60000 })
    webgl = await page.evaluate(() => !!document.createElement('canvas').getContext('webgl2'))
  })
  await step('shell', async () => {
    const bad = (m) => problems.push(`shell: ${m}`)
    const toggle = page.locator('#nav-toggle')
    // Default state: nav collapsed, analytics open, timeline in the dock.
    if ((await toggle.getAttribute('aria-label')) !== 'Expand navigation' || (await toggle.getAttribute('aria-expanded')) !== 'false') bad('#nav-toggle is not "Expand navigation" / aria-expanded=false by default')
    if (await page.locator('#topnav').isVisible()) bad('#topnav is visible by default')
    if (!(await page.getByRole('button', { name: 'Hide analytics' }).isVisible())) bad('"Hide analytics" is not visible by default')
    if (!(await page.locator('footer.dock #play').isVisible())) bad('#play is not visible inside footer.dock')
    // Speeds.
    const speeds = (await page.locator('select[aria-label="Playback speed"] option').allTextContents()).map((t) => t.trim())
    if (speeds.join(' ') !== '0.25× 0.5× 1× 2× 4× 10×') bad(`speed options read "${speeds.join(' ')}"`)
    await page.locator('select[aria-label="Playback speed"]').selectOption('4')
    if ((await page.evaluate(() => window.__clock.getState().speed)) !== 4) bad('choosing 4× did not set the clock speed to 4')
    await page.locator('select[aria-label="Playback speed"]').selectOption('1')
    if ((await page.evaluate(() => window.__clock.getState().speed)) !== 1) bad('choosing 1× did not set the clock speed to 1')
    // Floor strip and legend.
    const floors = (await page.locator('nav.floorstrip button').allInnerTexts()).map((t) => t.trim())
    if (floors.join('|') !== 'Whole building|Floor 1|Floor 2') bad(`floor strip reads "${floors.join('|')}"`)
    if ((await page.locator('nav.floorstrip button').first().getAttribute('aria-pressed')) !== 'true') bad('Whole building is not pressed by default')
    if (!(await page.locator('section.legendcard').isVisible())) bad('the legend card is not visible')
    await shot('shell')
    // Navigation drawer and menus.
    await toggle.click()
    await page.waitForFunction(() => document.getElementById('nav-toggle')?.getAttribute('aria-label') === 'Collapse navigation', null, { timeout: 5000 }).catch(() => bad('one click did not turn #nav-toggle into "Collapse navigation"'))
    const menus = (await page.locator('#topnav .menus > .menuwrap > button').allInnerTexts()).map((t) => t.trim())
    if (menus.join(' ') !== 'File Edit View Simulation Analysis Settings') bad(`menus read "${menus.join(' ')}"`)
    await page.locator('#topnav .menus').getByRole('button', { name: 'View', exact: true }).click()
    await page.locator('[role=menu][aria-label=View]').waitFor({ timeout: 5000 })
    await page.waitForTimeout(300)
    await shot('nav-view')
    await page.keyboard.press('Escape')
    if ((await page.locator('[role=menu]').count()) !== 0) bad('Escape did not close the View menu')
    if ((await page.evaluate(() => document.activeElement?.textContent?.trim())) !== 'View') bad('Escape did not put focus back on the View button')
    // Focus mode: both drawers collapsed, the viewer takes the full width, and the toggles stay.
    await pickMenu(page, 'View', 'Focus mode')
    await page.waitForTimeout(500)
    const fm = await page.evaluate(() => ({ nav: window.__app.getState().navOpen, side: window.__app.getState().sidebarOpen, w: document.querySelector('main.center').getBoundingClientRect().width, focus: document.activeElement?.id }))
    if (fm.nav || fm.side) bad(`Focus mode left navOpen=${fm.nav}, sidebarOpen=${fm.side}`)
    if (fm.w < 1400) bad(`in Focus mode main.center is ${Math.round(fm.w)} px wide, want at least 1400`)
    if (fm.focus !== 'nav-toggle') bad(`Focus mode left focus on "${fm.focus}", want nav-toggle`)
    await shot('focus-mode')
    await page.getByRole('button', { name: 'Show analytics' }).click()
    if (!(await page.evaluate(() => window.__app.getState().sidebarOpen)) || !(await page.getByRole('button', { name: 'Hide analytics' }).isVisible())) bad('"Show analytics" did not restore the sidebar')
    // Floor strip: one floor, then the whole building.
    await page.locator('nav.floorstrip button', { hasText: 'Floor 2' }).click()
    await page.waitForTimeout(2500)
    const f2 = await page.evaluate(() => ({ v: window.__app.getState().visibleFloors, p: [...document.querySelectorAll('nav.floorstrip button')].map((b) => b.getAttribute('aria-pressed')) }))
    if (JSON.stringify(f2.v) !== '["F2"]') bad(`Floor 2 set visibleFloors to ${JSON.stringify(f2.v)}`)
    if (f2.p.join() !== 'false,false,true') bad(`pressed states after Floor 2: ${f2.p.join()}`)
    await shot('floor-2')
    await blankCheck('floor-2')
    await page.locator('nav.floorstrip button', { hasText: 'Whole building' }).click()
    await page.waitForTimeout(500)
    if ((await page.evaluate(() => window.__app.getState().visibleFloors)) !== null) bad('Whole building did not set visibleFloors to null')
    // Alerts: paused, a chokepoint alert flies to its floor. (The first run may have none at 60 s: other times are tried before giving up.)
    let alerted = false
    for (const t of [60, 75, 90, 105, 120, 140]) {
      await page.evaluate((t) => {
        window.__clock.setState({ playing: false })
        window.__clock.getState().seek(t)
      }, t)
      await page.waitForTimeout(800)
      if ((await page.locator('ul.alerts button').count()) === 0) continue
      alerted = true
      await page.locator('ul.alerts button').first().click()
      await page.waitForTimeout(2500)
      const v = await page.evaluate(() => window.__app.getState().visibleFloors)
      if (!v || v.length !== 1) bad(`an alert click left visibleFloors ${JSON.stringify(v)}`)
      await shot('alert-fly')
      lines.push(`alerts: clicked the first at ${t} s`)
      await page.locator('nav.floorstrip button', { hasText: 'Whole building' }).click()
      break
    }
    if (!alerted) lines.push('alerts: none at 60 s')
    await page.evaluate(() => window.__clock.getState().seek(0))
    await nav(page, false)
  })
  await step('whatif-static', async () => {
    // No VITE_API_URL here, so the app is in static mode: the Sprinklers box must be off and quote the measured what-if.
    await page.evaluate(() => window.__app.setState({ card: 'scenario' }))
    const box = page.locator('.scenario .whatif')
    await box.scrollIntoViewIfNeeded()
    await page.waitForFunction(() => /fires:/.test(document.querySelector('.scenario .whatif .note')?.textContent ?? ''), null, { timeout: 5000 }).catch(() => {})
    const check = box.locator('label.check', { hasText: 'Sprinklers' }).locator('input[type=checkbox]')
    if ((await check.count()) === 0 || (await check.isEnabled())) problems.push('whatif-static: the Sprinklers checkbox is missing or enabled in static mode')
    const notes = box.locator('p.note')
    const note = (await notes.count()) > 0 ? ((await notes.first().textContent()) ?? '') : ''
    if (!/Sprinklers need the live backend/.test(note)) problems.push(`whatif-static: note lacks "Sprinklers need the live backend": "${note}"`)
    if (!/fires:/.test(note)) problems.push(`whatif-static: note lacks the measured "fires:" quote: "${note}"`)
    // The building material needs the live backend too: the select is off, and says so.
    const mat = page.locator('.scenario label', { hasText: 'Building material (illustrative)' }).locator('select')
    if ((await mat.count()) !== 1 || (await mat.isEnabled())) problems.push('whatif-static: the material select is missing or enabled in static mode')
    if ((await page.locator('.scenario p.note', { hasText: 'Material needs the live backend' }).count()) !== 1) problems.push('whatif-static: the note "Material needs the live backend" is missing')
    // So does the Crowd (who decides where people go): the select is off on the rules, with its three options, and says so.
    const crowd = page.locator('.scenario label', { hasText: 'Crowd' }).locator('select')
    if ((await crowd.count()) !== 1 || (await crowd.isEnabled())) problems.push('whatif-static: the Crowd select is missing or enabled in static mode')
    else {
      const opts = (await crowd.locator('option').allTextContents()).map((t) => t.trim()).join('|')
      if (opts !== 'Rules (hard-coded)|Some people ask Claude|Everyone asks Claude') problems.push(`whatif-static: the Crowd options read "${opts}"`)
      if ((await crowd.inputValue()) !== 'rules') problems.push('whatif-static: the Crowd select does not show the rules in static mode')
    }
    if ((await page.locator('.scenario p.note', { hasText: 'Claude crowds need the live backend' }).count()) !== 1) problems.push('whatif-static: the note "Claude crowds need the live backend" is missing')
    await shot('whatif-static')
    await page.evaluate(() => window.__app.setState({ card: null }))
  })
  await step('replay-60s', async () => {
    const t0 = Date.now()
    await page.evaluate(() => {
      const c = window.__clock.getState()
      c.seek(0)
      c.setSpeed(10)
      window.__clock.setState({ playing: true })
    })
    await page.waitForFunction(
      () => {
        const c = window.__clock.getState()
        return c.t >= Math.min(60, c.duration)
      },
      null,
      { timeout: 90000, polling: 250 },
    )
    playSecs = (Date.now() - t0) / 1000
    await page.evaluate(() => {
      window.__clock.setState({ playing: false })
      window.__clock.getState().seek(60)
    })
    await page.waitForTimeout(1000)
    await shot('replay-60s')
    await blankCheck('replay-60s')
  })
  await step('views', async () => {
    // The four floor views at 60 s, paused. Hiding or fading a floor is a picture change: the numbers the page reads from the run must not move.
    const bad = (m) => problems.push(`views: ${m}`)
    const read = () =>
      page.evaluate(() => {
        const a = window.__app.getState()
        return {
          visible: a.visibleFloors,
          focus: a.focusFloor,
          pressed: [...document.querySelectorAll('nav.floorstrip button')].filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.textContent.trim()),
          kpis: document.querySelector('dl.kpis')?.textContent ?? '',
          summary: document.getElementById('replay-summary')?.textContent ?? '',
        }
      })
    let ref = null
    for (const [mode, floor] of [['stacked'], ['single', 'F2'], ['side'], ['ghost', 'F2']]) {
      await page.evaluate(([m, f]) => window.__app.getState().setViewMode(m, f), [mode, floor])
      await page.waitForTimeout(1500)
      const r = await read()
      const want = mode === 'single' ? '["F2"]' : 'null'
      if (JSON.stringify(r.visible) !== want) bad(`${mode}: visibleFloors is ${JSON.stringify(r.visible)}, want ${want}`)
      if (mode === 'ghost' && r.focus !== 'F2') bad(`ghost: focusFloor is ${r.focus}, want F2`)
      const pressed = mode === 'single' || mode === 'ghost' ? 'Floor 2' : 'Whole building'
      if (r.pressed.join('|') !== pressed) bad(`${mode}: the pressed floor-strip item is "${r.pressed.join('|')}", want "${pressed}"`)
      if (!r.kpis || !/^At \d+:\d\d, /.test(r.summary)) bad(`${mode}: dl.kpis or #replay-summary is empty ("${r.summary.slice(0, 40)}")`)
      if (!ref) ref = r
      else {
        if (r.kpis !== ref.kpis) bad(`${mode}: dl.kpis changed with the view ("${r.kpis}" vs "${ref.kpis}")`)
        if (r.summary !== ref.summary) bad(`${mode}: #replay-summary changed with the view ("${r.summary}" vs "${ref.summary}")`)
      }
      await shot(`view-${mode}`)
      await blankCheck(`view-${mode}`)
    }
    // Through the UI: View > Side by side.
    await page.evaluate(() => window.__app.getState().setViewMode('stacked'))
    await nav(page, true)
    await pickMenu(page, 'View', 'Side by side')
    await page.waitForTimeout(300)
    if ((await page.evaluate(() => window.__app.getState().viewMode)) !== 'side') bad('View > Side by side did not set viewMode to side')
    await page.locator('#topnav .menus').getByRole('button', { name: 'View', exact: true }).click()
    const radio = page.locator('[role=menu][aria-label=View] [role=menuitemradio]', { hasText: 'Side by side' })
    if ((await radio.getAttribute('aria-checked')) !== 'true') bad('the View menu does not show Side by side as aria-checked=true')
    await page.keyboard.press('Escape')
    await nav(page, false)
    await page.evaluate(() => window.__app.getState().setViewMode('stacked'))
    await page.waitForTimeout(500)
  })
  await step('colors', async () => {
    const bad = (m) => problems.push(`colors: ${m}`)
    const sw = page.locator('section.legendcard button[role=switch]')
    const people = () => page.locator('section.legendcard .lc-body ul').first().locator('li').allInnerTexts().then((t) => t.map((x) => x.trim()))
    await sw.click()
    if ((await page.evaluate(() => window.__app.getState().colorBy)) !== 'type') bad('the legend switch did not set colorBy to type')
    if ((await sw.getAttribute('aria-checked')) !== 'true') bad('the switch is not aria-checked=true in type mode')
    const want = 'typical|older|visitor|cane|walker|wheelchair|Trapped (red ring)'
    const got = (await people()).join('|')
    if (got !== want) bad(`the type legend reads "${got}", want "${want}"`)
    await page.waitForTimeout(1000)
    await shot('colors-type')
    await blankCheck('colors-type')
    await sw.click()
    if ((await page.evaluate(() => window.__app.getState().colorBy)) !== 'status') bad('the legend switch did not return to status')
    if (!(await people()).includes('Delayed or waiting')) bad('the status legend lacks "Delayed or waiting"')
  })
  await step('visibility', async () => {
    const bad = (m) => problems.push(`visibility: ${m}`)
    const read = () => page.evaluate(() => ({ g: window.__app.getState().fireGlow, o: window.__app.getState().smokeOpacity }))
    await page.locator('.rail').getByRole('button', { name: 'Fire and smoke visibility', exact: true }).click()
    await page.locator('#card-visibility').waitFor({ timeout: 5000 })
    const card = page.locator('#card-visibility')
    const high = card.getByRole('button', { name: 'High visibility', exact: true })
    await high.click()
    const v = await read()
    if (v.g !== 2 || v.o !== 1.5) bad(`High visibility left fireGlow ${v.g} and smokeOpacity ${v.o}, want 2 and 1.5`)
    if ((await high.getAttribute('aria-pressed')) !== 'true') bad('High visibility is not aria-pressed=true while its values hold')
    // Close to the fire at 120 s, where a bigger glow and denser smoke show (the fly-to also isolates the fire's floor).
    await page.evaluate(() => {
      window.__clock.getState().seek(120)
      const a = window.__app.getState()
      const f = a.runs[a.activeRunKey].run.fire
      a.flyTo(f.floor, [f.x, f.y])
    })
    await page.waitForTimeout(3500)
    await shot('visibility-high')
    await card.getByRole('button', { name: 'Reset', exact: true }).click()
    const r = await read()
    if (r.g !== 1 || r.o !== 1) bad(`Reset left fireGlow ${r.g} and smokeOpacity ${r.o}, want 1 and 1`)
    if ((await high.getAttribute('aria-pressed')) !== 'false') bad('High visibility is still pressed after Reset')
    await page.evaluate(() => {
      window.__app.setState({ card: null })
      window.__app.getState().setViewMode('stacked')
      window.__clock.getState().seek(60)
    })
    await page.waitForTimeout(500)
  })
  // The room-to-room spread on screen, in a fresh page and the stacked view. The fixture is A11's run/v0 with fire.rooms: it is read from disk
  // (contracts/run.spread.fixture.json) and opened through File > Open, so it never has to be copied into public/ (which would publish it).
  await step('fire-spread', async () => {
    if (!existsSync(FIXTURE)) return void problems.push('fire-spread: fixture missing (A11 part 1)')
    const fx = JSON.parse(readFileSync(FIXTURE, 'utf8'))
    const bad = (m) => problems.push(`fire-spread: ${m}`)
    const pf = await ctx.newPage()
    pf.on('console', (m) => {
      if (m.type() === 'error' && !/calibration\.json/.test(m.text() + (m.location()?.url ?? ''))) errors.push(`[fire-spread] ${m.text()}`)
    })
    pf.on('pageerror', (e) => errors.push(`[fire-spread] ${String(e)}`))
    try {
      await pf.goto(`${server.resolvedUrls.local[0]}?qa`)
      await pf.waitForFunction(() => window.__app?.getState().activeRunKey, null, { timeout: 60000 })
      const seek = async (t) => {
        await pf.evaluate((t) => {
          window.__clock.setState({ playing: false })
          window.__clock.getState().seek(t)
        }, t)
        return pf.evaluate(() => window.__clock.getState().t)
      }
      // What the active run itself lists at t: the rooms of its fire.rooms with ignite <= t, those the building has, and per floor.
      const own = (t) =>
        pf.evaluate((t) => {
          const a = window.__app.getState()
          const run = a.runs[a.activeRunKey].run
          const has = (r) => !!a.building.floors.find((f) => f.id === r.floor)?.rooms.some((x) => x.id === r.room)
          const rooms = (run.fire.rooms ?? []).filter((r) => r.ignite <= t)
          const byFloor = {}
          for (const r of rooms) if (has(r)) byFloor[r.floor] = (byFloor[r.floor] ?? 0) + 1
          // The doors the run has closed by t, that the building has (BlockedDoors draws each once).
          const closed = new Set()
          for (const e of run.events) if (e.type === 'door_blocked' && e.t <= t && a.building.floors.some((f) => (!e.floor || f.id === e.floor) && f.doors.some((d) => d.id === e.door))) closed.add(`${e.floor}|${e.door}`)
          return { hasRooms: !!run.fire.rooms?.length, burning: rooms.length, drawn: rooms.filter(has).length, byFloor, closed: closed.size }
        }, t)
      // The frame loop writes __spread: wait for it to reach the wanted numbers (or give up), then read it.
      const spread = async (want) => {
        await pf.waitForFunction(([b, d]) => window.__spread.burning === b && window.__spread.drawn === d, [want.burning, want.drawn], { timeout: 10000 }).catch(() => {})
        return pf.evaluate(() => ({ ...window.__spread }))
      }
      const openRun = async (run, file = null) => {
        await pf.locator('#open-file').setInputFiles(file ?? { name: `${run.id}.json`, mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(run)) })
        await pf.waitForFunction((id) => {
          const a = window.__app.getState()
          return !!a.activeRunKey && a.runs[a.activeRunKey].run.id === id && a.loading === null
        }, run.id, { timeout: 60000 })
      }

      // 1. The default run, paused at 60 s: it draws exactly the rooms its own fire.rooms lists by then (none for a run without the field).
      const t60 = await seek(60)
      const w60 = await own(t60)
      const g60 = await spread(w60)
      if (g60.drawn !== w60.drawn) bad(`the default run at ${t60} s draws ${g60.drawn} burning rooms, its own fire.rooms lists ${w60.drawn}`)
      if (!w60.hasRooms) {
        if ((await pf.locator('p.spreadline').count()) !== 0) bad('a run without fire.rooms shows the spread line')
        if ((await pf.locator('section.legendcard', { hasText: 'Burning room' }).count()) !== 0) bad('a run without fire.rooms shows the burning-room legend row')
      }
      lines.push(`fire-spread: the default run has ${w60.hasRooms ? 'fire.rooms' : 'no fire.rooms'}; ${g60.drawn} rooms drawn at ${t60} s`)

      // 2. The fixture, opened through the file input in the building it was made for.
      const bid = await pf.evaluate(() => window.__app.getState().building.id)
      if (bid !== fx.buildingId) {
        await nav(pf, true)
        await pf.locator('select[aria-label="Building"]').selectOption(fx.buildingId)
        await pf.waitForFunction((id) => {
          const a = window.__app.getState()
          return a.building?.id === id && a.loading === null && !!a.activeRunKey
        }, fx.buildingId, { timeout: 60000 })
        await nav(pf, false)
      }
      await openRun(fx, FIXTURE)
      const times = (fx.fire.rooms ?? []).map((r) => r.ignite).sort((a, b) => a - b)
      const dur = await pf.evaluate(() => window.__clock.getState().duration)
      if (times.length === 0) return void bad('the fixture lists no fire.rooms')
      // The second ignition (one second past it); with one room, the first. Never past the end of the run.
      const t1 = await seek(Math.min(dur, times.length > 1 ? times[1] + 1 : times[0]))
      const want = await own(t1)
      const wantFile = times.filter((x) => x <= t1).length
      if (want.burning !== wantFile) bad(`at ${t1} s the page's run lists ${want.burning} burning rooms, the fixture file ${wantFile}`)
      const got = await spread(want)
      if (got.burning !== want.burning || got.drawn !== want.drawn) bad(`at ${t1} s __spread is ${JSON.stringify(got)}, want burning ${want.burning} and drawn ${want.drawn}`)
      const sayN = new RegExp(`\\b${want.burning} rooms? burning`)
      await pf.waitForFunction((src) => new RegExp(src).test(document.querySelector('p.spreadline')?.textContent ?? ''), sayN.source, { timeout: 8000 }).catch(() => {})
      const line = (await pf.locator('p.spreadline').allInnerTexts()).join(' | ')
      if (!sayN.test(line) || !/illustrative/.test(line)) bad(`the spread line reads "${line}", want "${want.burning} room(s) burning" and "illustrative"`)
      const matName = fx.fire.material ? fx.fire.material[0].toUpperCase() + fx.fire.material.slice(1) : null
      if (matName && !line.includes(matName)) bad(`the spread line reads "${line}", want the material ${matName}`)
      const legend = await pf.locator('section.legendcard').innerText()
      for (const row of ['Burning room (illustrative)', 'Fire marker', 'Closed door']) if (!legend.includes(row)) bad(`the legend lacks "${row}"`)
      if ((await pf.evaluate(() => window.__app.getState().viewMode)) !== 'stacked') bad('the page left the stacked view')
      // The doors the run closes show as they close: none before the first, all of them at the end.
      if (got.closed !== want.closed) bad(`at ${t1} s ${got.closed} closed doors are drawn, the run has closed ${want.closed}`)
      // The Fire layer off draws no tint.
      await pf.evaluate(() => window.__app.setState((s) => ({ layers: { ...s.layers, fire: false } })))
      await pf.waitForFunction(() => window.__spread.drawn === 0, null, { timeout: 8000 }).catch(() => {})
      const off = await pf.evaluate(() => window.__spread.drawn)
      if (off !== 0) bad(`with the Fire layer off ${off} burning rooms are still drawn`)
      await pf.evaluate(() => window.__app.setState((s) => ({ layers: { ...s.layers, fire: true } })))
      await spread(want)
      await pf.waitForTimeout(800)
      await shot('fire-spread', pf)
      await blankCheck('fire-spread', pf)
      await axeOn(pf, 'fire-spread', '.app')
      await pf.evaluate(() => window.__app.setState({ fireGlow: 2 }))
      await pf.waitForTimeout(800)
      await shot('fire-spread-high', pf)
      await pf.evaluate(() => window.__app.setState({ fireGlow: 1 }))

      // The end of the run: every burning room, and the doors closed by then.
      const tEnd = await seek(dur)
      const wEnd = await own(tEnd)
      const gEnd = await spread(wEnd)
      if (gEnd.drawn !== wEnd.drawn || gEnd.closed !== wEnd.closed) bad(`at the end (${tEnd} s) __spread is ${JSON.stringify(gEnd)}, want drawn ${wEnd.drawn} and closed ${wEnd.closed}`)
      await pf.waitForTimeout(500)
      await shot('fire-spread-end', pf)

      // 3. Hidden floors. The fixture's ignition times are halved so that every floor it lists burns within the run; then each floor view must draw
      // only the burning rooms of the floors it shows (fire on a hidden floor never shows on another one), and the tints must read on the slabs.
      const fast = { ...fx, id: `${fx.id}-fast`, fire: { ...fx.fire, rooms: fx.fire.rooms.map((r) => ({ ...r, ignite: Math.round(r.ignite / 2) })) } }
      await openRun(fast)
      const tFast = await seek(dur)
      const wFast = await own(tFast)
      const floorsBurning = Object.keys(wFast.byFloor)
      const views = [['stacked', undefined, wFast.drawn]]
      for (const f of floorsBurning) views.push(['single', f, wFast.byFloor[f]])
      views.push(['side', undefined, wFast.drawn], ['ghost', floorsBurning[0], wFast.drawn])
      for (const [mode, floor, n] of views) {
        await pf.evaluate(([m, f]) => window.__app.getState().setViewMode(m, f), [mode, floor])
        const g = await spread({ burning: wFast.burning, drawn: n })
        if (g.drawn !== n) bad(`${mode}${floor ? ' ' + floor : ''} view: ${g.drawn} burning rooms drawn, want ${n} (rooms on the floors that view shows)`)
        if (mode !== 'stacked' && !(mode === 'single' && floor !== floorsBurning[0])) {
          await pf.waitForTimeout(1500)
          await shot(`fire-spread-${mode}`, pf)
          await blankCheck(`fire-spread-${mode}`, pf)
        }
      }
      lines.push(`fire-spread: views draw ${views.map(([m, f, n]) => `${m}${f ? ' ' + f : ''} ${n}`).join(', ')} of ${wFast.drawn} burning rooms`)
      // A close-up on a burning room other than the ignition room (the fire sphere stands there): it carries the marker cone.
      const near = await pf.evaluate((rooms) => {
        const a = window.__app.getState()
        for (const r of rooms.slice(1)) {
          const room = a.building.floors.find((f) => f.id === r.floor)?.rooms.find((x) => x.id === r.room)
          if (!room || ['stair', 'corridor'].includes(room.type)) continue
          const n = room.polygon.length
          return { floor: r.floor, at: [room.polygon.reduce((s, p) => s + p[0], 0) / n, room.polygon.reduce((s, p) => s + p[1], 0) / n] }
        }
        return null
      }, fast.fire.rooms)
      if (near) {
        await pf.evaluate((t) => window.__app.getState().flyTo(t.floor, t.at), near)
        await pf.waitForTimeout(3500)
        await shot('fire-spread-close', pf)
      }
      await pf.evaluate(() => window.__app.getState().setViewMode('stacked'))

      // 4. A run without fire.rooms (an old precomputed run, an older backend) draws no spread at all, and nothing fails.
      const plain = { ...fx, id: `${fx.id}-plain`, fire: { floor: fx.fire.floor, x: fx.fire.x, y: fx.fire.y, hrr: fx.fire.hrr } }
      await openRun(plain)
      await seek(dur)
      await pf.waitForTimeout(1200)
      const none = await pf.evaluate(() => ({ ...window.__spread }))
      if (none.drawn !== 0 || none.burning !== 0 || none.closed !== 0) bad(`a run without fire.rooms reports ${JSON.stringify(none)}`)
      if ((await pf.locator('p.spreadline').count()) !== 0) bad('a run without fire.rooms shows the spread line')
      if ((await pf.locator('section.legendcard').innerText()).includes('Burning room')) bad('a run without fire.rooms shows the burning-room legend row')
      await blankCheck('fire-spread-none', pf)
    } finally {
      await pf.close()
    }
  })
  // The wood-against-drywall pair. The fixture stands in for the wood run: the index is the real one plus one entry for it, and the file is served from disk.
  await step('material-pair', async () => {
    const bad = (m) => problems.push(`material-pair: ${m}`)
    const before = problems.length
    if (!existsSync(FIXTURE)) return void problems.push('material-pair: fixture missing (A11 part 1)')
    const fx = JSON.parse(readFileSync(FIXTURE, 'utf8'))
    const realIndex = JSON.parse(readFileSync(join(root, 'dist', 'demo', 'index.json'), 'utf8'))
    const base = realIndex.runs.find((r) => r.buildingId === fx.buildingId && r.whatIf === null)
    if (!base) return void bad(`the demo index has no baseline run for building ${fx.buildingId}`)
    const entry = { id: 'qa-wood', buildingId: fx.buildingId, label: 'Wood (qa fixture)', file: 'fixtures/fire-spread.run.json', whatIf: 'material', material: 'wood', fire: base.fire, doors: {} }
    const watch = (pg, tag) => {
      pg.on('console', (m) => {
        if (m.type() === 'error' && !/calibration\.json/.test(m.text() + (m.location()?.url ?? ''))) errors.push(`[${tag}] ${m.text()}`)
      })
      pg.on('pageerror', (e) => errors.push(`[${tag}] ${String(e)}`))
    }
    // Compares in a fresh page: clicks the button, waits for the split view with `wood` active and its partner loaded, and returns the .whatif text.
    const compare = async (pg, woodId, shotName) => {
      await pg.waitForFunction(() => window.__app?.getState().activeRunKey, null, { timeout: 60000 })
      await pg.evaluate(() => {
        window.__clock.setState({ playing: false })
        window.__clock.getState().seek(30)
        window.__app.setState({ card: 'scenario' })
      })
      const before = await pg.evaluate(() => window.__clock.getState().t)
      const btn = pg.getByRole('button', { name: 'Compare wood with drywall' })
      await btn.scrollIntoViewIfNeeded()
      await btn.click()
      await pg.waitForFunction((id) => {
        const a = window.__app.getState()
        const w = a.runs[id]
        return a.split && a.activeRunKey === id && !!w?.whatIf && !!a.runs[w.whatIf.baselineKey] && a.whatIfBusy === null
      }, woodId, { timeout: 60000 })
      const s = await pg.evaluate((id) => {
        const a = window.__app.getState()
        const w = a.runs[id]
        return { keys: a.compareKeys, base: w.whatIf.baselineKey, material: w.whatIf.material, door: w.whatIf.door, t: window.__clock.getState().t, err: a.whatIfError, canvases: document.querySelectorAll('main.center canvas').length }
      }, woodId)
      if (s.err) bad(`whatIfError "${s.err}"`)
      if (s.keys.join() !== `${s.base},${woodId}`) bad(`compareKeys ${s.keys.join()}, want ${s.base},${woodId}`)
      if (s.material !== 'wood' || s.door !== '') bad(`the wood run's whatIf is ${JSON.stringify({ material: s.material, door: s.door })}`)
      if (Math.abs(s.t - before) > 0.2) bad(`the clock moved from ${before} s to ${s.t} s`)
      if (s.canvases !== 2) bad(`${s.canvases} canvases in the split view, want 2`)
      const text = await pg.locator('.scenario .whatif').innerText()
      if (!text.includes('Wood instead of drywall')) bad(`.whatif lacks "Wood instead of drywall": "${text.slice(0, 160)}"`)
      await pg.locator('.scenario .whatif .whatif-card').first().scrollIntoViewIfNeeded()
      await pg.waitForTimeout(1500)
      await shot(shotName, pg)
      await blankCheck(shotName, pg)
      await axeOn(pg, shotName, '.app')
    }
    // The real index with the material entry FIRST: it must never pass for a door what-if, wherever it stands in the list.
    const routes = async (pg) => {
      await pg.route('**/demo/index.json', async (route) => {
        const res = await route.fetch()
        const idx = await res.json()
        idx.runs = [entry, ...idx.runs]
        await route.fulfill({ response: res, json: idx })
      })
      await pg.route('**/demo/fixtures/fire-spread.run.json', (route) => route.fulfill({ path: FIXTURE, contentType: 'application/json' }))
    }
    const pm = await ctx.newPage()
    watch(pm, 'material-pair')
    try {
      await routes(pm)
      await pm.goto(`${server.resolvedUrls.local[0]}?qa&building=${fx.buildingId}`)
      await pm.waitForFunction(() => window.__app?.getState().activeRunKey, null, { timeout: 60000 })
      // The static what-if still finds the door what-if of the baseline (its propped run), not the material entry.
      const propped = realIndex.runs.find((r) => r.buildingId === fx.buildingId && r.whatIf === 'propped' && r.fire.room === base.fire.room)
      if (propped) {
        await pm.evaluate(() => window.__app.setState({ card: 'scenario' }))
        await pm.locator('.scenario .whatif button.run').click()
        await pm.waitForFunction(() => window.__app.getState().whatIfBusy === null, null, { timeout: 60000 })
        const w = await pm.evaluate(() => {
          const a = window.__app.getState()
          return { key: a.activeRunKey, material: !!a.runs['qa-wood'], err: a.whatIfError }
        })
        if (w.key !== propped.id || w.material || w.err) bad(`the static what-if loaded ${w.key} (material run loaded: ${w.material}, error "${w.err}"), want the propped run ${propped.id}`)
      }
      await compare(pm, 'qa-wood', 'material-pair')
      // The link of the pair opens the pair again: a wood entry in `r` loads its drywall partner first, and the link's split keeps the two side by side.
      await pm.waitForTimeout(1500)
      const hash = await pm.evaluate(() => location.hash)
      if (!/(^#|&)r=qa-wood(&|$)/.test(hash) || !/(^#|&)split=1(&|$)/.test(hash)) bad(`the link of the pair reads "${hash}", want r=qa-wood and split=1`)
      const pl = await ctx.newPage()
      watch(pl, 'material-pair-link')
      try {
        await routes(pl)
        await pl.goto(`${server.resolvedUrls.local[0]}?qa${hash}`)
        await pl.waitForFunction(() => {
          const a = window.__app?.getState()
          const w = a?.runs['qa-wood']
          return !!w?.whatIf && a.activeRunKey === 'qa-wood' && a.split && !!a.runs[w.whatIf.baselineKey] && a.loading === null
        }, null, { timeout: 60000 })
        const l = await pl.evaluate(() => ({ whatIf: window.__app.getState().runs['qa-wood'].whatIf, canvases: document.querySelectorAll('main.center canvas').length }))
        if (l.whatIf.material !== 'wood' || l.whatIf.door !== '' || l.canvases !== 2) bad(`the pair's link restored ${JSON.stringify(l)}, want the wood variant in a split view`)
      } catch (e) {
        bad(`the pair's link did not restore the pair: ${String(e).split('\n')[0]}`)
      } finally {
        await pl.close()
      }
    } finally {
      await pm.close()
    }
    // The main page reads the real index: the section is there exactly when the loaded building has a wood run in it.
    const loaded = await page.evaluate(() => window.__app.getState().building.id)
    const woods = realIndex.runs.filter((r) => r.whatIf === 'material' && r.material === 'wood' && realIndex.runs.some((b) => b.buildingId === r.buildingId && b.whatIf === null && b.fire.room === r.fire.room))
    await page.evaluate(() => window.__app.setState({ card: 'scenario' }))
    await page.waitForTimeout(600)
    const shown = (await page.locator('.scenario .whatif .material').count()) > 0
    const wanted = woods.some((r) => r.buildingId === loaded)
    if (shown !== wanted) bad(`the main page ${shown ? 'shows' : 'lacks'} the material section for ${loaded}, but the index ${wanted ? 'has' : 'has no'} a wood run for it`)
    await page.evaluate(() => window.__app.setState({ card: null }))
    lines.push(`material-pair: the real index has ${woods.length} wood run(s); the main page (${loaded}) ${shown ? 'shows' : 'hides'} the section`)
    if (problems.length === before) lines.push('material-pair ok: the static what-if skips the material entry, Compare splits the view at the same time, the link of the pair restores it')
    // With a real pair in the index (A11 part 2's rerun), it is compared the same way.
    if (woods[0]) {
      const pr = await ctx.newPage()
      watch(pr, 'material-pair-real')
      try {
        await pr.goto(`${server.resolvedUrls.local[0]}?qa&building=${woods[0].buildingId}`)
        await compare(pr, woods[0].id, 'material-pair-real')
      } finally {
        await pr.close()
      }
    }
  })
  // Rules against a Claude crowd. The real index has no such pair yet, so the index here is the real one plus one qa entry (whatIf 'brain', brain 'llm'), and its
  // file is a copy of the rules baseline it pairs with, carrying three of Claude's decisions for one person: two from Claude and one the rules made after Claude's
  // time ran out. The file is served from memory.
  await step('claude-pair', async () => {
    const bad = (m) => problems.push(`claude-pair: ${m}`)
    const before = problems.length
    const realIndex = JSON.parse(readFileSync(join(root, 'dist', 'demo', 'index.json'), 'utf8'))
    const base = realIndex.runs.find((r) => r.id === 'example-office-R101-base') ?? realIndex.runs.find((r) => r.whatIf === null)
    if (!base) return void bad('the demo index has no baseline run')
    const baseRun = JSON.parse(readFileSync(join(root, 'dist', 'demo', base.file), 'utf8'))
    const who = baseRun.agents[0].idx
    const floor = baseRun.agents[0].floor
    const reason = 'The east stair is clear and close, so I go there.'
    // Claude's run traps three more people than the rules' and never gets 90% out: the headline must lead with that, and put the smoke line second.
    const trappedMore = baseRun.metrics.trapped + 3
    const claudeRun = {
      ...baseRun,
      id: 'qa-claude-run',
      metrics: { ...baseRun.metrics, trapped: trappedMore, t90: null },
      agents: baseRun.agents.map((a, i) => (i < 12 ? { ...a, llm: true } : a)),
      events: [
        ...baseRun.events,
        { t: 20, type: 'llm', idx: who, floor, target: 'qa-exit', action: 'reroute', reason },
        { t: 60, type: 'llm', idx: who, floor, target: 'qa-exit', action: 'wait', reason: 'rules: keep current target', fallback: true },
      ].sort((a, b) => a.t - b.t),
    }
    const entry = { id: 'qa-claude', buildingId: base.buildingId, label: 'Kitchen, Claude (qa)', file: 'fixtures/claude-crowd.run.json', whatIf: 'brain', brain: 'llm', fire: base.fire, doors: base.doors }
    // The real index with the Claude entry FIRST: it must never pass for a door what-if, wherever it stands in the list.
    const routes = async (pg) => {
      await pg.route('**/demo/index.json', async (route) => {
        const res = await route.fetch()
        const idx = await res.json()
        idx.runs = [entry, ...idx.runs]
        await route.fulfill({ response: res, json: idx })
      })
      await pg.route('**/demo/fixtures/claude-crowd.run.json', (route) => route.fulfill({ json: claudeRun }))
    }
    // Compares in a fresh page: clicks the button, waits for the split view with the Claude run active and its rules partner loaded, and checks what the card says.
    const compare = async (pg, claudeId, shotName, headline = null) => {
      await pg.waitForFunction(() => window.__app?.getState().activeRunKey, null, { timeout: 60000 })
      await pg.evaluate(() => {
        window.__clock.setState({ playing: false })
        window.__clock.getState().seek(30)
        window.__app.setState({ card: 'scenario' })
      })
      const t0 = await pg.evaluate(() => window.__clock.getState().t)
      const btn = pg.getByRole('button', { name: 'Compare rules with Claude crowd' })
      await btn.scrollIntoViewIfNeeded()
      await btn.click()
      await pg.waitForFunction((id) => {
        const a = window.__app.getState()
        const c = a.runs[id]
        return a.split && a.activeRunKey === id && !!c?.whatIf && !!a.runs[c.whatIf.baselineKey] && a.whatIfBusy === null
      }, claudeId, { timeout: 60000 })
      const s = await pg.evaluate((id) => {
        const a = window.__app.getState()
        const c = a.runs[id]
        return { keys: a.compareKeys, base: c.whatIf.baselineKey, brain: c.whatIf.brain, material: c.whatIf.material, door: c.whatIf.door, t: window.__clock.getState().t, err: a.whatIfError, canvases: document.querySelectorAll('main.center canvas').length }
      }, claudeId)
      if (s.err) bad(`whatIfError "${s.err}"`)
      if (s.keys.join() !== `${s.base},${claudeId}`) bad(`compareKeys ${s.keys.join()}, want ${s.base},${claudeId}`)
      if (s.brain !== 'llm' || s.door !== '' || s.material !== undefined) bad(`the Claude run's whatIf is ${JSON.stringify({ brain: s.brain, door: s.door, material: s.material })}`)
      if (Math.abs(s.t - t0) > 0.2) bad(`the clock moved from ${t0} s to ${s.t} s`)
      if (s.canvases !== 2) bad(`${s.canvases} canvases in the split view, want 2`)
      const text = await pg.locator('.scenario .whatif').innerText()
      if (!text.includes('Claude crowd instead of rules')) bad(`.whatif lacks "Claude crowd instead of rules": "${text.slice(0, 200)}"`)
      if (!/t90 .*trapped \d+ → \d+/.test(text)) bad(`.whatif lacks the t90 and trapped line: "${text.slice(-200)}"`)
      // With a known difference in the people trapped, the headline leads with it, then the smoke line, then the t90 line.
      if (headline) {
        // (Each is searched for after the one before it: the card's sprinkler note above already says "person-seconds in smoke".)
        const i0 = text.indexOf(headline)
        const i1 = i0 < 0 ? -1 : text.indexOf('person-seconds in smoke', i0 + headline.length)
        const i2 = i1 < 0 ? -1 : text.indexOf('t90 ', i1)
        if (i2 < 0) bad(`.whatif does not read "${headline}", then the smoke line, then the t90 line: "${text.slice(Math.max(0, text.indexOf('Claude crowd instead') - 20))}"`)
      }
      await pg.locator('.scenario .whatif .whatif-card').first().scrollIntoViewIfNeeded()
      await pg.waitForTimeout(1500)
      await shot(shotName, pg)
      await blankCheck(shotName, pg)
      await axeOn(pg, shotName, '.app')
    }
    const pc = await ctx.newPage()
    watchPage(pc, 'claude-pair')
    try {
      await routes(pc)
      await pc.goto(`${server.resolvedUrls.local[0]}?qa&building=${base.buildingId}`)
      await pc.waitForFunction(() => window.__app?.getState().activeRunKey, null, { timeout: 60000 })
      // The static what-if still finds the door what-if of the baseline (its propped run), never the Claude entry.
      const propped = realIndex.runs.find((r) => r.buildingId === base.buildingId && r.whatIf === 'propped' && r.fire.room === base.fire.room)
      if (propped) {
        await pc.evaluate(() => window.__app.setState({ card: 'scenario' }))
        await pc.locator('.scenario .whatif button.run').click()
        await pc.waitForFunction(() => window.__app.getState().whatIfBusy === null, null, { timeout: 60000 })
        const w = await pc.evaluate(() => {
          const a = window.__app.getState()
          return { key: a.activeRunKey, claude: !!a.runs['qa-claude'], err: a.whatIfError }
        })
        if (w.key !== propped.id || w.claude || w.err) bad(`the static what-if loaded ${w.key} (Claude run loaded: ${w.claude}, error "${w.err}"), want the propped run ${propped.id}`)
        // The door pair has the same number trapped in both runs (the demo's R101 pair: none), so its headline leads with the smoke, as before.
        if (base.metrics?.trapped === propped.metrics?.trapped) {
          const doorHead = (await pc.locator('.scenario .whatif .whatif-card b').allInnerTexts()).join(' | ')
          if (/trapped instead of/.test(doorHead)) bad(`the door pair led with the trapped count though it is the same in both runs: "${doorHead}"`)
        }
      }
      await compare(pc, 'qa-claude', 'claude-pair', `Claude crowd instead of rules: ${trappedMore} people trapped instead of ${baseRun.metrics.trapped}; 90% never get out`)
      // The run is named once for who decides: the Run select, and the caption of its pane.
      const opt = ((await pc.locator('select[aria-label="Run"] option[value="qa-claude"]').textContent()) ?? '').trim()
      if (opt !== 'Kitchen, Claude (qa) · Claude crowd') bad(`the Run select names the Claude run "${opt}", want "Kitchen, Claude (qa) · Claude crowd"`)
      if (!(await pc.locator('.pane-caption').allInnerTexts()).some((t) => t.includes('Claude crowd'))) bad('no pane caption names the Claude crowd')
      // The link of the pair opens the pair again, never as a door what-if.
      await pc.waitForTimeout(1500)
      const hash = await pc.evaluate(() => location.hash)
      if (!/(^#|&)r=qa-claude(&|$)/.test(hash) || !/(^#|&)split=1(&|$)/.test(hash)) bad(`the link of the pair reads "${hash}", want r=qa-claude and split=1`)
      const pl = await ctx.newPage()
      watchPage(pl, 'claude-pair-link')
      try {
        await routes(pl)
        await pl.goto(`${server.resolvedUrls.local[0]}?qa${hash}`)
        await pl.waitForFunction(() => {
          const a = window.__app?.getState()
          const c = a?.runs['qa-claude']
          return !!c?.whatIf && a.activeRunKey === 'qa-claude' && a.split && !!a.runs[c.whatIf.baselineKey] && a.loading === null
        }, null, { timeout: 60000 })
        const l = await pl.evaluate(() => ({ whatIf: window.__app.getState().runs['qa-claude'].whatIf, canvases: document.querySelectorAll('main.center canvas').length }))
        if (l.whatIf.brain !== 'llm' || l.whatIf.door !== '' || l.canvases !== 2) bad(`the pair's link restored ${JSON.stringify(l)}, want the Claude run (brain llm, no door) in a split view`)
      } catch (e) {
        bad(`the pair's link did not restore the pair: ${String(e).split('\n')[0]}`)
      } finally {
        await pl.close()
      }
      // Claude's reasons in the readout: one person followed, in a single view, with the clock before Claude's first answer, at it, and at the rules' fallback.
      const legendHas = async () => (await pc.locator('section.legendcard').innerText()).includes('Asks Claude (pink ring)')
      if (!(await legendHas())) bad('the legend lacks the "Asks Claude" row for a run in which people ask Claude')
      await pc.evaluate((who) => {
        window.__app.setState({ split: false })
        window.__app.getState().setFollow(who)
      }, who)
      await pc.locator('.agentreadout').waitFor({ timeout: 15000 })
      // The line follows the clock within a quarter second, but a page busy drawing the first-person view can be later: wait until the wanted text is there (or
      // for ten seconds), then judge what is.
      const readoutAt = async (t, ok) => {
        await pc.evaluate((t) => window.__clock.getState().seek(t), t)
        let text = await pc.locator('.agentreadout').innerText()
        for (let i = 0; i < 50 && !ok(text); i++) {
          await pc.waitForTimeout(200)
          text = await pc.locator('.agentreadout').innerText()
        }
        return text
      }
      const none = (x) => !/Claude|Rules \(/.test(x)
      const r10 = await readoutAt(10, none)
      if (!none(r10)) bad(`the readout shows a decision at 10 s, before Claude's first: "${r10}"`)
      const r30 = await readoutAt(30, (x) => x.includes(`Claude: ${reason}`))
      if (!r30.includes(`Claude: ${reason}`) || !/\breroute\b/.test(r30)) bad(`at 30 s the readout reads "${r30}", want "Claude: ${reason}" and the action reroute`)
      await shot('claude-readout', pc)
      await axeOn(pc, 'claude-readout', '.app')
      const r70 = await readoutAt(70, (x) => x.includes("Rules (Claude didn't answer in time)"))
      if (!r70.includes("Rules (Claude didn't answer in time)") || /Claude:/.test(r70)) bad(`at 70 s the readout reads "${r70}", want "Rules (Claude didn't answer in time)" and no "Claude:"`)
      // The rules' run of the same fire has no decisions: its readout is as before.
      await pc.evaluate((k) => window.__app.getState().switchRun(k), 'example-office-R101-base')
      const rb = await readoutAt(30, none)
      if (!none(rb)) bad(`the rules run's readout mentions Claude: "${rb}"`)
      if (await legendHas()) bad('the legend shows the "Asks Claude" row for the rules run')
      // Tour scene 4 never takes the Claude entry for its what-if: with the entry first in the index it still shows the baseline's propped run.
      await pc.evaluate(() => {
        window.__app.getState().setFollow(null)
        window.__tour.getState().go(3, false)
      })
      await pc.waitForTimeout(4000)
      const tour = await pc.evaluate(() => {
        const a = window.__app.getState()
        return { active: a.activeRunKey, keys: a.compareKeys, whatIf: a.runs[a.activeRunKey]?.whatIf ?? null }
      })
      if (tour.active === 'qa-claude' || tour.keys.includes('qa-claude') || tour.whatIf?.brain) bad(`tour scene 4 took the Claude run: ${JSON.stringify(tour)}`)
      if (propped && tour.active !== propped.id) bad(`tour scene 4 shows ${tour.active}, want the propped run ${propped.id}`)
      await pc.evaluate(() => window.__tour.getState().stop())
    } finally {
      await pc.close()
    }
    // The main page reads the real index: the section is there exactly when the loaded building has a Claude pair in it (today none).
    const loaded = await page.evaluate(() => window.__app.getState().building.id)
    const claudes = realIndex.runs.filter((r) => r.whatIf === 'brain' && r.brain === 'llm' && realIndex.runs.some((b) => b.buildingId === r.buildingId && b.whatIf === null && b.fire.room === r.fire.room))
    await page.evaluate(() => window.__app.setState({ card: 'scenario' }))
    await page.waitForTimeout(600)
    const shown = (await page.locator('.scenario .whatif .claudepair').count()) > 0
    const wanted = claudes.some((r) => r.buildingId === loaded)
    if (shown !== wanted) bad(`the main page ${shown ? 'shows' : 'lacks'} the Claude crowd section for ${loaded}, but the index ${wanted ? 'has' : 'has no'} a Claude pair for it`)
    await page.evaluate(() => window.__app.setState({ card: null }))
    lines.push(`claude-pair: the real index has ${claudes.length} Claude pair(s); the main page (${loaded}) ${shown ? 'shows' : 'hides'} the section`)
    if (problems.length === before) lines.push("claude-pair ok: the static what-if and tour scene 4 skip the Claude entry, Compare splits the view, its link restores the pair, the readout carries Claude's reasons")
    // With a real pair in the index, it is compared the same way.
    if (claudes[0]) {
      const pr = await ctx.newPage()
      watchPage(pr, 'claude-pair-real')
      try {
        await pr.goto(`${server.resolvedUrls.local[0]}?qa&building=${claudes[0].buildingId}`)
        await compare(pr, claudes[0].id, 'claude-pair-real')
      } finally {
        await pr.close()
      }
    }
  })
  // The Crowd select in live mode. qa has no backend, so a fresh page is put in live mode by hand and the API answered by routes (as in live-fallback).
  await step('crowd-live', async () => {
    const bad = (m) => problems.push(`crowd-live: ${m}`)
    const before = problems.length
    const p6 = await ctx.newPage()
    watchPage(p6, 'crowd-live', /calibration\.json|status of 500|ERR_CONNECTION_REFUSED/)
    try {
      const posts = []
      let how = 'running'
      const json = (r, body, status = 200) => r.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
      await p6.route('**/runs', (r) => {
        if (r.request().method() === 'POST') posts.push(JSON.parse(r.request().postData() ?? '{}'))
        return how === 'http' ? json(r, { detail: 'qa: backend error' }, 500) : json(r, { runId: 'qa-run' })
      })
      await p6.route('**/runs/qa-run', (r) => json(r, { status: 'running' }))
      await p6.goto(`${server.resolvedUrls.local[0]}?qa`)
      await p6.waitForFunction(() => window.__app?.getState().activeRunKey, null, { timeout: 60000 })
      await p6.evaluate(() => {
        // pollRun's wait is of Date.now: this lets the page's clock jump over it
        const real = Date.now.bind(Date)
        let skew = 0
        Date.now = () => real() + skew
        window.__skew = (ms) => (skew += ms)
        window.__app.setState({ mode: 'live', card: 'scenario', notice: null })
      })
      const select = p6.locator('.scenario label', { hasText: 'Crowd' }).locator('select')
      const runButton = p6.locator('.scenario > button.run')
      const state = () =>
        p6.evaluate(() => {
          const a = window.__app.getState()
          return { running: a.running, err: a.runError, note: a.runNote, fallback: a.runFallback, brain: a.draft.brain }
        })
      const setPeople = (n) =>
        p6.evaluate((n) => {
          const a = window.__app.getState()
          a.patchDraft({ occupants: { ...a.draft.occupants, total: n } })
        }, n)
      // Live: the select is on, on the rules, and the static-mode note is gone.
      if (!(await select.isEnabled())) bad('the Crowd select is off in live mode')
      if ((await select.inputValue()) !== 'rules') bad(`the Crowd select shows "${await select.inputValue()}" at the start, want rules`)
      if ((await p6.locator('.scenario p.note', { hasText: 'Claude crowds need the live backend' }).count()) !== 0) bad('the static-mode note shows in live mode')
      // Everyone asks Claude with more than 200 people: a warning, and no way to run: the button, the nav's Run, and the store.
      await select.selectOption('llm')
      await setPeople(250)
      const warn = p6.locator('.scenario p.warn[role=alert]')
      await warn.waitFor({ timeout: 5000 })
      const w = await warn.innerText()
      if (!/200 people/.test(w) || !/\b250\b/.test(w)) bad(`the warning reads "${w}", want 200 people and 250`)
      if (!(await runButton.isDisabled())) bad('the Run button is on with 250 people and everyone asking Claude')
      await shot('crowd-limit', p6)
      await axeOn(p6, 'crowd-limit', '.app')
      await nav(p6, true)
      if (!(await p6.locator('.ctxbar').getByRole('button', { name: 'Run simulation', exact: true }).isDisabled())) bad("the nav's Run simulation button is on with 250 people and everyone asking Claude")
      await nav(p6, false)
      await p6.evaluate(() => {
        const a = window.__app.getState()
        void a.runScenario(a.draft)
      })
      await p6.waitForTimeout(500)
      const blocked = await state()
      if (posts.length !== 0 || blocked.running !== null || !/200 people/.test(blocked.err ?? '')) bad(`runScenario with 250 people sent ${posts.length} request(s), running ${blocked.running}, error "${blocked.err}"`)
      // 160 people: the warning goes, and the run is sent with brain llm, says whom Claude is deciding for, and is waited for fifteen minutes (not ten).
      await setPeople(160)
      if ((await warn.count()) !== 0) bad('the warning stays at 160 people')
      if (!(await runButton.isEnabled())) bad('the Run button stays off at 160 people')
      await runButton.click()
      await p6.waitForFunction(() => /^Claude is deciding for 160 people… \d+ s$/.test(window.__app.getState().running ?? ''), null, { timeout: 20000 })
      if (!(await runButton.innerText()).includes('Claude is deciding for 160 people…')) bad('the Run button does not show the Claude status')
      if (posts.length !== 1 || posts[0].brain !== 'llm' || posts[0].occupants?.total !== 160) bad(`the request carried ${JSON.stringify({ brain: posts[0]?.brain, people: posts[0]?.occupants?.total })}, want brain llm and 160 people`)
      await shot('crowd-live', p6)
      await p6.evaluate(() => window.__skew(200000))
      await p6.waitForFunction(() => / 2\d\d s$/.test(window.__app.getState().running ?? ''), null, { timeout: 15000 }).catch(() => bad('three minutes in, the Claude run is no longer waited for'))
      await p6.evaluate(() => window.__skew(800000))
      await p6.waitForFunction(() => window.__app.getState().running === null, null, { timeout: 30000 })
      const done = await state()
      if (!done.fallback || !/^Live run unavailable: showing the nearest precomputed fire \(room \S+\)\. That run uses the rules crowd, not Claude\.$/.test(done.note ?? '') || done.err) bad(`after six minutes the note reads "${done.note}" (error "${done.err}")`)
      // The other two crowds are sent as chosen, and only the Claude crowds say the fallback is not theirs.
      how = 'http'
      for (const [value, claude] of [['mixed', true], ['rules', false]]) {
        await select.selectOption(value)
        await runButton.click()
        await p6.waitForFunction(() => window.__app.getState().running === null, null, { timeout: 30000 })
        const sent = posts[posts.length - 1]?.brain
        const st = await state()
        if (sent !== value) bad(`choosing "${value}" sent brain ${sent}`)
        if (/rules crowd, not Claude/.test(st.note ?? '') !== claude) bad(`after a failed ${value} run the note reads "${st.note}"`)
      }
      // A door what-if is not offered against a live Claude crowd run (its scenario carries the brain): the button is off, and the card says why.
      await p6.evaluate(() => {
        const a = window.__app.getState()
        const k = a.activeRunKey
        window.__app.setState((s) => ({ runs: { ...s.runs, [k]: { ...s.runs[k], scenario: { ...a.draft, brain: 'llm' } } } }))
      })
      const wi = p6.locator('.scenario .whatif')
      await wi.scrollIntoViewIfNeeded()
      if (!(await wi.locator('button.run').isDisabled()) || (await wi.locator('p.note', { hasText: 'Door what-ifs compare against a Rules run' }).count()) !== 1) bad('a Claude crowd run still offers a door what-if')
      await p6.evaluate(() => {
        const k = window.__app.getState().activeRunKey
        window.__app.setState((s) => ({ runs: { ...s.runs, [k]: { ...s.runs[k], scenario: undefined } } }))
      })
      if (!(await wi.locator('button.run').isEnabled())) bad('the door what-if stays off for a run of the rules')
      if (problems.length === before) lines.push('crowd-live ok: the Crowd select, the 200-person block, brain in the request, the Claude status and its six minutes, the rules-crowd note, no door what-if against Claude')
    } finally {
      await p6.close()
    }
  })
  // The Fire and scenario card in plain words: the fire's size and growth in place of its type, the fire placed by clicking (with a list as the other way), the people
  // mix in percent, a hint under each field, and no door overrides. A fresh page in static mode; for what the card sends, live mode is put on by hand and the API
  // answered by a failing route (the request is all that is read).
  await step('scenario-card', async () => {
    const bad = (m) => problems.push(`scenario-card: ${m}`)
    const before = problems.length
    const p7 = await ctx.newPage()
    watchPage(p7, 'scenario-card', /calibration\.json|status of 500|ERR_CONNECTION_REFUSED/)
    try {
      const posts = []
      await p7.route('**/runs', (r) => {
        if (r.request().method() === 'POST') posts.push(JSON.parse(r.request().postData() ?? '{}'))
        return r.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'qa: backend error' }) })
      })
      await p7.goto(`${server.resolvedUrls.local[0]}?qa`)
      await p7.waitForFunction(() => window.__app?.getState().activeRunKey, null, { timeout: 60000 })
      await p7.evaluate(() => window.__app.setState({ card: 'scenario' }))
      const card = p7.locator('.scenario')
      await card.waitFor({ timeout: 10000 })
      const draft = () => p7.evaluate(() => window.__app.getState().draft)
      const placing = () => p7.evaluate(() => window.__app.getState().placing)
      const field = (label) => card.locator('label', { hasText: label })
      const size = field('Fire size').locator('select')
      const growth = field('How fast it grows').locator('select')
      const where = card.locator('.fireplace .where')
      const mover = card.locator('.fireplace button')
      const texts = async (loc) => (await loc.allTextContents()).map((t) => t.trim()).join('|')
      // Plain words, with a hint under the fields; nothing of the old labels, the fire type, the fire room list or the door overrides. (The texts a label or button
      // holds itself, not the options inside it.)
      const own = await card.evaluate((el) => [...el.querySelectorAll('label, legend, h4, summary, button')].map((n) => [...n.childNodes].filter((c) => c.nodeType === 3).map((c) => c.textContent.trim()).join(' ').trim()).filter(Boolean))
      for (const w of ['Fire size', 'How fast it grows', 'Move fire', 'Choose a room from a list', 'Room', 'Building material (illustrative)', 'Crowd', 'People in the building', 'Who is inside', 'Typical adults', 'Older adults (walk slower)', "Visitors (don't know the building)", 'Variation', 'Alarm sounds after (seconds)'])
        if (!own.includes(w)) bad(`the card lacks "${w}" (it has ${JSON.stringify(own)})`)
      for (const w of ['Occupants', 'Seed', 'Alarm time (s)', 'Fire', 'Fire room', 'Door overrides', 'Door…', 'Add', 'Click a floor to place the fire'])
        if (own.includes(w)) bad(`the card still has "${w}"`)
      const all = await card.innerText()
      for (const w of ['Fire in:', 'How big the fire gets.', 'How quickly it reaches its full size.', 'How fast the fire spreads from room to room.', 'Who decides where people go.', 'How many people are inside when the fire starts.', 'Same number, same run; change it to see another possible night.', 'Seconds after the fire starts.'])
        if (!all.includes(w)) bad(`the card lacks the text "${w}"`)
      if ((await card.locator('select[aria-label="Door to override"], select option[value="liquid"], select option[value="battery"]').count()) !== 0) bad('the card still has a door override or a fire type select')
      if ((await texts(size.locator('option'))) !== 'Small, like a wastebasket|Medium, like a kitchen fire|Large, like a burning room') bad(`the Fire size options read "${await texts(size.locator('option'))}"`)
      if ((await texts(growth.locator('option'))) !== 'Slow|Medium|Fast|Very fast') bad(`the growth options read "${await texts(growth.locator('option'))}"`)
      // The defaults are today's: a medium (kitchen) fire that grows fast, 160 people in the 85, 10 and 5 percent mix.
      if ((await size.inputValue()) !== 'medium' || (await growth.inputValue()) !== 'fast') bad(`the fire shows ${await size.inputValue()} and ${await growth.inputValue()}, want medium and fast`)
      const pct = async () => [await field('Typical adults').locator('input').inputValue(), await field('Older adults').locator('input').inputValue(), await field('Visitors').locator('input').inputValue()].join(',')
      if ((await pct()) !== '85,10,5' || (await card.locator('fieldset.mix .note').count()) !== 0) bad(`the mix shows ${await pct()} with ${await card.locator('fieldset.mix .note').count()} note(s), want 85,10,5 and none`)
      // The fire placed by clicking: it says where, "Move fire" turns placing on (and "Cancel" off), and the room list is a collapsed disclosure.
      if (!/^Fire in: \S.*, Floor \d+/.test(await where.innerText())) bad(`the card says "${await where.innerText()}", want "Fire in: <room>, Floor N"`)
      if ((await placing()) !== false || (await mover.innerText()) !== 'Move fire') bad(`with a fire placed, placing is ${await placing()} and the button reads "${await mover.innerText()}", want false and "Move fire"`)
      await mover.click()
      if ((await placing()) !== true || (await mover.innerText()) !== 'Cancel' || !/Click a room in the building to move the fire\./.test(await where.innerText())) bad(`after "Move fire", placing is ${await placing()}, the button reads "${await mover.innerText()}" and the card says "${await where.innerText()}"`)
      await mover.click()
      if ((await placing()) !== false) bad('Cancel did not turn placing off')
      const disclosure = card.locator('details.roompick')
      const summary = disclosure.locator('summary')
      if ((await summary.innerText()) !== 'Choose a room from a list' || (await disclosure.evaluate((d) => d.open)) || (await disclosure.locator('select').isVisible())) bad('the room list is not a collapsed "Choose a room from a list"')
      await summary.focus()
      await p7.keyboard.press('Enter')
      if (!(await disclosure.evaluate((d) => d.open)) || !(await disclosure.locator('select').isVisible())) bad('Enter on the disclosure does not open the room list')
      const rooms = disclosure.locator('select')
      const was = (await draft()).fire.room
      const pick = (await rooms.locator('option').evaluateAll((os) => os.map((o) => o.value))).find((v) => v.includes('|') && v.split('|')[1] !== was)
      if (!pick) bad('the room list offers no other room')
      else {
        await rooms.selectOption(pick)
        const f = (await draft()).fire
        if (f.floor !== pick.split('|')[0] || f.room !== pick.split('|')[1] || typeof f.x !== 'number' || typeof f.y !== 'number' || (await placing()) !== false) bad(`choosing ${pick} from the list left the fire at ${JSON.stringify(f)} (placing ${await placing()})`)
        if (!(await where.innerText()).includes('Fire in:')) bad(`after the list, the card says "${await where.innerText()}"`)
      }
      // No fire yet: the card says so and starts placing by itself, also when it is opened that way.
      await p7.evaluate(() => {
        const a = window.__app.getState()
        a.patchDraft({ fire: { type: a.draft.fire.type, start: 0 } })
      })
      await p7.waitForFunction(() => window.__app.getState().placing === true, null, { timeout: 5000 }).catch(() => bad('a draft with no fire did not turn placing on'))
      if (!/^No fire placed yet\./.test(await where.innerText()) || !/Click a room in the building to place the fire\./.test(await where.innerText()) || (await mover.innerText()) !== 'Cancel') bad(`with no fire the card says "${await where.innerText()}" and the button reads "${await mover.innerText()}"`)
      await p7.evaluate(() => window.__app.setState({ card: null, placing: false }))
      await p7.evaluate(() => window.__app.setState({ card: 'scenario' }))
      await p7.waitForFunction(() => window.__app.getState().placing === true, null, { timeout: 5000 }).catch(() => bad('opening the card with no fire did not turn placing on'))
      await card.locator('details.roompick summary').click()
      await rooms.selectOption(pick ?? '')
      if ((await placing()) !== false || !(await where.innerText()).startsWith('Fire in:')) bad('a room chosen from the list did not place the fire and end placing')
      // The fire as the card shows it: the presets the card does not offer, a growth in the backend's other spellings, and a type it has never seen (nothing throws).
      const shows = async (fire) => {
        await p7.evaluate((f) => {
          const a = window.__app.getState()
          a.patchDraft({ fire: { ...a.draft.fire, ...f } })
        }, fire)
        return `${await size.inputValue()}/${await growth.inputValue()}`
      }
      for (const [fire, want] of [
        [{ type: 'battery', growth: undefined }, 'small/ultra-fast'],
        [{ type: 'liquid', growth: undefined }, 'medium/ultra-fast'],
        [{ type: 'trash', growth: undefined }, 'small/fast'],
        [{ type: 'bedroom', growth: undefined }, 'large/medium'],
        [{ type: 'kitchen', growth: 'instant' }, 'medium/ultra-fast'],
        [{ type: 'Kitchen', growth: 'Ultra_Fast' }, 'medium/ultra-fast'],
        [{ type: 'no-such-fire', growth: 'no-such-growth' }, 'medium/fast'],
        [{ type: 'kitchen', growth: undefined }, 'medium/fast'],
      ]) {
        const got = await shows(fire)
        if (got !== want) bad(`a fire of ${JSON.stringify(fire)} shows ${got}, want ${want}`)
      }
      // The people mix: percent on the card, fractions in the scenario, and a note when it does not add up to 100%.
      const typical = field('Typical adults').locator('input')
      await typical.fill('60')
      const mix = (await draft()).occupants.mix
      if (mix.typical !== 0.6 || mix.older !== 0.1 || mix.visitor !== 0.05) bad(`typing 60 left the mix at ${JSON.stringify(mix)}, want 0.6, 0.1 and 0.05`)
      const note = (await card.locator('fieldset.mix .note').allInnerTexts()).join(' ')
      if (note !== 'These add up to 75%. They are scaled to 100% when you run.') bad(`the mix note reads "${note}"`)
      await typical.fill('85')
      if ((await card.locator('fieldset.mix .note').count()) !== 0) bad('the mix note stays at 100%')
      await field('People in the building').locator('input').fill('120')
      await field('Variation').locator('input').fill('7')
      await field('Alarm sounds after').locator('input').fill('45')
      const d = await draft()
      if (d.occupants.total !== 120 || d.seed !== 7 || d.alarmTime !== 45) bad(`the people, variation and alarm fields wrote ${JSON.stringify({ total: d.occupants.total, seed: d.seed, alarm: d.alarmTime })}, want 120, 7 and 45`)
      await shot('scenario-card', p7)
      await axeOn(p7, 'scenario-card', '.app')
      // What goes to the backend (live mode by hand). Untouched, the fire is today's: kitchen, no growth written. Size and growth write the type and the growth; the
      // doors the draft carries go with the run though the card no longer shows them.
      await p7.evaluate(() => {
        const a = window.__app.getState()
        a.patchDraft({ fire: { type: 'kitchen', floor: a.draft.fire.floor, room: a.draft.fire.room, x: a.draft.fire.x, y: a.draft.fire.y, start: 0 }, doors: { DSA1: 'propped' } })
        window.__app.setState({ mode: 'live' })
      })
      const run = async () => {
        const n = posts.length
        await p7.locator('.scenario > button.run').click()
        await p7.waitForFunction(() => window.__app.getState().running === null, null, { timeout: 30000 })
        return posts.length > n ? posts[posts.length - 1] : null
      }
      let sent = await run()
      if (!sent || sent.fire.type !== 'kitchen' || 'growth' in sent.fire || JSON.stringify(sent.doors) !== '{"DSA1":"propped"}') bad(`an untouched card sent ${JSON.stringify({ type: sent?.fire.type, growth: sent?.fire.growth, doors: sent?.doors })}, want kitchen, no growth and its doors`)
      await size.selectOption('small')
      await growth.selectOption('ultra-fast')
      sent = await run()
      if (!sent || sent.fire.type !== 'trash' || sent.fire.growth !== 'ultra-fast') bad(`Small and Very fast sent ${JSON.stringify({ type: sent?.fire.type, growth: sent?.fire.growth })}, want trash and ultra-fast`)
      await size.selectOption('large')
      sent = await run()
      if (!sent || sent.fire.type !== 'bedroom' || sent.fire.growth !== 'ultra-fast') bad(`Large sent ${JSON.stringify({ type: sent?.fire.type, growth: sent?.fire.growth })}, want bedroom and the growth kept (ultra-fast)`)
      await growth.selectOption('slow')
      await size.selectOption('medium')
      sent = await run()
      if (!sent || sent.fire.type !== 'kitchen' || sent.fire.growth !== 'slow') bad(`Slow and Medium sent ${JSON.stringify({ type: sent?.fire.type, growth: sent?.fire.growth })}, want kitchen and slow`)
      if (problems.length === before) lines.push('scenario-card ok: plain labels and hints, fire size and growth, placing and the room list, the percent mix, no door overrides')
    } finally {
      await p7.close()
    }
  })
  await tabShots('')
  await step('cred', async () => {
    await page.locator('.results [role=tab]').nth(3).click()
    await page.waitForTimeout(800)
    const t = await page.locator('#results-panel').innerText()
    if (!/0\.8 m door/.test(t) || !/Corridor/.test(t) || /EXAMPLE VALUES/.test(t)) problems.push('cred: calibration panel missing 0.8 m door / Corridor, or shows EXAMPLE VALUES')
    await page.getByText('Known limits').first().scrollIntoViewIfNeeded()
    await shot('cred-limits')
  })
  await step('about', async () => {
    await nav(page, true)
    await page.locator('#topnav .menubar').getByRole('button', { name: 'About', exact: true }).click()
    await page.locator('[role=dialog]').waitFor({ timeout: 10000 })
    await page.waitForTimeout(500)
    await shot('about')
    await page.keyboard.press('Escape')
    await nav(page, false)
  })
  await step('tracer', async () => {
    await nav(page, true)
    await pickMenu(page, 'File', 'Trace a floor plan')
    await page.locator('.tr-page').waitFor({ timeout: 15000 })
    await page.waitForTimeout(500)
    await shot('tracer')
    cur = 'tracer→replay'
    await page.locator('header.topbar button', { hasText: 'Back to 3D replay' }).click()
    await page.locator('main.center canvas').first().waitFor({ timeout: 15000 })
    await nav(page, false)
  })
  await step('scene4', async () => {
    await page.evaluate(() => window.__tour.getState().go(3, false))
    await page.waitForTimeout(4000)
    await shot('scene4')
    await blankCheck('scene4')
    await page.evaluate(() => window.__tour.getState().stop())
  })
  await step('tour', async () => {
    // The whole demo, in a fresh page, with timers of 10 s or more shortened tenfold so six scenes take about 20 s. Every scene must find its
    // panel and tab on the new layout: the sidebar open, the nav and cards closed, and scenes 5 and 6 on their tabs.
    const p4 = await ctx.newPage()
    p4.on('console', (m) => {
      if (m.type() === 'error' && !/calibration\.json/.test(m.text() + (m.location()?.url ?? ''))) errors.push(`[tour] ${m.text()}`)
    })
    p4.on('pageerror', (e) => errors.push(`[tour] ${String(e)}`))
    await p4.addInitScript(() => {
      const real = window.setTimeout.bind(window)
      window.setTimeout = (fn, ms, ...a) => real(fn, typeof ms === 'number' && ms >= 10000 ? ms / 10 : ms, ...a)
    })
    try {
      await p4.goto(`${server.resolvedUrls.local[0]}?qa&demo`)
      // Each poll records what the page shows while a scene is current. resetStage runs in the same tick that the scene starts, so the first
      // poll of a scene already sees the nav, cards and sidebar as the scene left them.
      const rec = new Map()
      const t0 = Date.now()
      let settled = 0
      while (Date.now() - t0 < 90000) {
        const s = await p4.evaluate(() => {
          const a = window.__app.getState()
          return {
            scene: window.__tour.getState().scene,
            tab: a.resultsTab,
            nav: a.navOpen,
            card: a.card,
            side: a.sidebarOpen,
            tabSel: document.querySelector('.results [role=tab][aria-selected=true]')?.textContent ?? null,
            sideVisible: !!document.querySelector('#analytics')?.offsetParent,
            cap: !!document.querySelector('.tourcap'),
          }
        })
        if (s.scene !== null) {
          const r = rec.get(s.scene) ?? { first: s, tabs: new Set(), caps: 0, polls: 0 }
          r.tabs.add(`${s.tab}/${s.tabSel}`)
          r.caps += s.cap ? 1 : 0
          r.polls++
          rec.set(s.scene, r)
          if ((s.scene === 4 || s.scene === 5) && r.polls === 3) await p4.screenshot({ path: join(out, `tour-scene${s.scene + 1}.png`) })
          if (s.scene === 5 && r.polls >= 4) break
        }
        await p4.waitForTimeout(400)
        settled++
      }
      for (let i = 0; i < 6; i++) {
        const r = rec.get(i)
        if (!r) {
          problems.push(`tour: scene ${i + 1} never ran (ran: ${[...rec.keys()].map((k) => k + 1).join(', ') || 'none'})`)
          continue
        }
        if (r.caps === 0) problems.push(`tour: scene ${i + 1} shows no caption`)
        if (r.first.nav || r.first.card) problems.push(`tour: scene ${i + 1} started with navOpen=${r.first.nav}, card=${r.first.card}`)
        if (!r.first.side || !r.first.sideVisible) problems.push(`tour: scene ${i + 1} has no visible analytics sidebar`)
      }
      const tabs = (i) => [...(rec.get(i)?.tabs ?? [])].join(', ')
      if (rec.get(4) && !rec.get(4).tabs.has('risk/Risk')) problems.push(`tour: scene 5 never showed the Risk tab (saw ${tabs(4)})`)
      if (rec.get(5) && !rec.get(5).tabs.has('cred/Credibility')) problems.push(`tour: scene 6 never showed the Credibility tab (saw ${tabs(5)})`)
      lines.push(`tour: scenes ${[...rec.keys()].map((k) => k + 1).join(', ')} ran (${settled} polls)`)
    } finally {
      await p4.close()
    }
  })
  await step('deeplink', async () => {
    await page.evaluate(() => {
      window.__tour.getState().stop()
      const a = window.__app
      a.setState({ split: false, resultsTab: 'risk', explode: 0.5, topView: a.getState().topView + 1 })
      a.setState({ layers: { ...a.getState().layers, heatmap: true, labels: false } })
      window.__clock.setState({ playing: false })
      window.__clock.getState().seek(42)
    })
    await page.waitForTimeout(2500)
    const hash = await page.evaluate(() => location.hash)
    if (!hash.includes('t=42')) problems.push(`deeplink: hash lacks t=42: ${hash}`)
    const a = await page.evaluate(() => ({ pose: { p: [...window.__pose.p], t: [...window.__pose.t] }, explode: window.__app.getState().explode, heat: window.__app.getState().layers.heatmap, labels: window.__app.getState().layers.labels }))
    await shot('deeplink-a')
    const url = page.url().split('#')[0].split('?')[0] + '?qa' + hash
    const p2 = await ctx.newPage()
    p2.on('console', (m) => {
      if (m.type() === 'error' && !/calibration\.json/.test(m.text() + (m.location()?.url ?? ''))) errors.push(`[deeplink-b] ${m.text()}`)
    })
    p2.on('pageerror', (e) => errors.push(`[deeplink-b] ${String(e)}`))
    try {
      await p2.goto(url)
      await p2.waitForFunction(() => {
        const g = window.__app?.getState()
        return g && g.resultsTab === 'risk' && g.sidebarOpen === true && g.activeRunKey && Math.abs(window.__clock.getState().t - 42) < 0.11
      }, null, { timeout: 30000, polling: 250 })
      await p2.waitForTimeout(2000)
      const b = await p2.evaluate(() => ({ pose: { p: [...window.__pose.p], t: [...window.__pose.t] }, explode: window.__app.getState().explode, heat: window.__app.getState().layers.heatmap, labels: window.__app.getState().layers.labels }))
      if (a.explode !== b.explode) problems.push(`deeplink: explode ${a.explode} vs ${b.explode}`)
      if (a.heat !== b.heat || a.labels !== b.labels) problems.push('deeplink: layers differ')
      for (const k of ['p', 't']) for (let i = 0; i < 3; i++) if (Math.abs(a.pose[k][i] - b.pose[k][i]) > 0.5) problems.push(`deeplink: pose ${k}${i} ${a.pose[k][i]} vs ${b.pose[k][i]}`)
      await p2.screenshot({ path: join(out, 'deeplink-b.png') })
      shots.push('deeplink-b')
    } finally {
      await p2.close()
    }
    // The floor view travels in the link: v=side, v=ghost with the focus floor f, and f alone for one floor.
    const bid = await page.evaluate(() => window.__app.getState().building.id)
    const base = page.url().split('#')[0].split('?')[0] + '?qa#b=' + bid
    for (const [tail, mode, focus] of [['&v=side', 'side', null], ['&v=ghost&f=F2', 'ghost', 'F2'], ['&f=F2', 'single', 'F2']]) {
      const pv = await ctx.newPage()
      pv.on('console', (m) => {
        if (m.type() === 'error' && !/calibration\.json/.test(m.text() + (m.location()?.url ?? ''))) errors.push(`[deeplink-view] ${m.text()}`)
      })
      pv.on('pageerror', (e) => errors.push(`[deeplink-view] ${String(e)}`))
      try {
        await pv.goto(base + tail)
        await pv.waitForFunction((m) => window.__app?.getState().viewMode === m, mode, { timeout: 45000, polling: 250 })
        const got = await pv.evaluate(() => ({ mode: window.__app.getState().viewMode, focus: window.__app.getState().focusFloor }))
        if (got.focus !== focus) problems.push(`deeplink: ${tail} restored focusFloor ${got.focus}, want ${focus}`)
        await pv.waitForTimeout(1500)
        if (mode !== 'single') {
          await pv.screenshot({ path: join(out, `deeplink-${mode}.png`) })
          shots.push(`deeplink-${mode}`)
        }
      } catch (e) {
        problems.push(`deeplink: opening ${tail} did not restore the ${mode} view: ${String(e).split('\n')[0]}`)
      } finally {
        await pv.close()
      }
    }
    lines.push('deeplink ok')
  })
  await step('share', async () => {
    await nav(page, true)
    await page.locator('.ctxbar').getByRole('button', { name: 'Share', exact: true }).click()
    await page.locator('[role=dialog][aria-label="Share this view"]').waitFor({ timeout: 10000 })
    await page.waitForTimeout(500)
    await shot('share')
    await page.keyboard.press('Escape')
    await nav(page, false)
  })
  await step('print', async () => {
    await page.locator('.results [role=tab]').nth(2).click()
    await page.locator('.results button', { hasText: 'Print report' }).first().click()
    await page.locator('.printreport').waitFor({ timeout: 15000 })
    await page.waitForTimeout(1000)
    // The demo card of the main page has an AI summary only when its markdown does.
    const demoCard = readFileSync(join(root, 'dist', 'demo', 'report-example-office.md'), 'utf8')
    const hasSummary = /^#{2,3}[ \t]+AI summary \(Claude\)/m.test(demoCard)
    if (((await page.locator('.printreport .aisummary').count()) > 0) !== hasSummary) problems.push(`print: the printed card ${hasSummary ? 'lacks' : 'shows'} an AI summary, its markdown ${hasSummary ? 'has' : 'has no'} one`)
    await shot('print-view')
    await page.emulateMedia({ media: 'print' })
    await page.waitForTimeout(500)
    await page.screenshot({ path: join(out, 'print-media.png'), fullPage: true })
    shots.push('print-media')
    if (!GPU || lines.includes('gpu: not available, SwiftShader numbers only')) await page.pdf({ path: join(out, 'report.pdf'), format: 'Letter', printBackground: true })
    await page.emulateMedia({ media: 'screen' })
    await page.keyboard.press('Escape')
    await page.waitForFunction(() => !document.querySelector('.printreport'), null, { timeout: 10000 })
  })
  // The report card's AI summary: a card whose markdown begins with "## AI summary (Claude)" shows it set apart (heading, the text, an "AI-written" note) in the Report
  // tab and in the printed report. The card of the main page (a template) has none, and prints as before (the print step above checks that).
  await step('ai-summary', async () => {
    const bad = (m) => problems.push(`ai-summary: ${m}`)
    const para = 'The lobby and the east stair exit are where the queues form. Claude wrote this from the simulation numbers. It is three sentences long.'
    const pa = await ctx.newPage()
    watchPage(pa, 'ai-summary')
    try {
      await pa.route('**/demo/report-example-office.md', async (route) => {
        const res = await route.fetch()
        await route.fulfill({ status: 200, contentType: 'text/markdown; charset=utf-8', body: `## AI summary (Claude)\n\n${para}\n\n${await res.text()}` })
      })
      await pa.goto(`${server.resolvedUrls.local[0]}?qa`)
      await pa.waitForFunction(() => window.__app?.getState().activeRunKey, null, { timeout: 60000 })
      await pa.locator('.results [role=tab]').nth(2).click()
      const box = pa.locator('.results .aisummary')
      await box.waitFor({ timeout: 15000 })
      if ((await box.locator('h4').allInnerTexts()).join('|') !== 'AI summary (Claude)') bad('the Report tab heading is not an h4 "AI summary (Claude)"')
      if ((await box.locator('p').first().innerText()) !== para) bad(`the Report tab paragraph reads "${await box.locator('p').first().innerText()}"`)
      if (!/AI-written/.test(await box.locator('.aisummary-note').innerText())) bad('the Report tab summary lacks the "AI-written" note')
      if (!(await pa.locator('.results .report').innerText()).includes('Report card: Example office')) bad('the card below the AI summary is gone')
      await box.scrollIntoViewIfNeeded()
      await shot('ai-summary', pa)
      await axeOn(pa, 'ai-summary', '.app')
      await pa.locator('.results button', { hasText: 'Print report' }).first().click()
      const pbox = pa.locator('.printreport .aisummary')
      await pbox.waitFor({ timeout: 15000 })
      if ((await pbox.locator('h3').allInnerTexts()).join('|') !== 'AI summary (Claude)') bad('the printed heading is not an h3 "AI summary (Claude)"')
      if ((await pbox.locator('p').first().innerText()) !== para) bad(`the printed paragraph reads "${await pbox.locator('p').first().innerText()}"`)
      if (!/AI-written/.test(await pbox.locator('.aisummary-note').innerText())) bad('the printed summary lacks the "AI-written" note')
      await pbox.scrollIntoViewIfNeeded()
      await shot('ai-summary-print', pa)
      await axeOn(pa, 'ai-summary-print', '.printreport')
    } finally {
      await pa.close()
    }
  })
  await step('save-png', async () => {
    await nav(page, true)
    const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 15000 }), page.locator('.ctxbar').getByRole('button', { name: 'Save PNG', exact: true }).click()])
    await nav(page, false)
    const f = join(out, 'save-3d.png')
    await dl.saveAs(f)
    const share = await changedShare(readFileSync(f).toString('base64'))
    lines.push(`save-3d.png: changed ${(share * 100).toFixed(1)}%`)
    if (share < 0.01) problems.push('blank Save PNG')
  })
  await step('a11y', async () => {
    const runAxe = (label, sel) => axeOn(page, label, sel)
    await page.evaluate(() => {
      window.__tour.getState().stop()
      window.__clock.setState({ playing: false })
    })
    const names = ['results', 'risk', 'report', 'cred']
    for (let i = 0; i < names.length; i++) {
      await page.locator('.results [role=tab]').nth(i).click()
      await page.waitForTimeout(600)
      await runAxe(`tab ${names[i]}`, '.app')
    }
    await nav(page, true)
    await page.locator('#topnav .menubar').getByRole('button', { name: 'About', exact: true }).click()
    await page.locator('[role=dialog]').waitFor({ timeout: 10000 })
    await runAxe('about', '[role=dialog]')
    await page.keyboard.press('Escape')
    await page.locator('.results [role=tab]').first().click()
    // The new surfaces: the nav, two menus, the two cards and Focus mode.
    await runAxe('nav open', '.app')
    for (const menu of ['View', 'Simulation']) {
      await page.locator('#topnav .menus').getByRole('button', { name: menu, exact: true }).click()
      await page.locator(`[role=menu][aria-label=${menu}]`).waitFor({ timeout: 5000 })
      await runAxe(`${menu} menu`, '.app')
      await page.keyboard.press('Escape')
    }
    await nav(page, false)
    for (const card of ['scenario', 'layers', 'visibility']) {
      await page.evaluate((c) => window.__app.setState({ card: c }), card)
      await page.waitForTimeout(400)
      await runAxe(`card ${card}`, '.app')
    }
    await page.evaluate(() => window.__app.setState({ card: null, colorBy: 'type' }))
    await page.waitForTimeout(400)
    await runAxe('colors by type', '.app')
    await page.evaluate(() => window.__app.setState({ colorBy: 'status' }))
    await page.evaluate(() => window.__app.setState({ card: null, navOpen: false, sidebarOpen: false }))
    await page.waitForTimeout(300)
    await runAxe('focus mode', '.app')
    await page.evaluate(() => window.__app.setState({ sidebarOpen: true }))
    await page.waitForTimeout(300)

    await page.evaluate(() => document.body.focus())
    await page.evaluate(() => document.activeElement && document.activeElement.blur())
    const unnamed = () =>
      page.evaluate(() => {
        const el = document.activeElement
        if (!el || el === document.body) return null
        const name = (el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '').trim() || (el.labels && el.labels.length ? el.labels[0].textContent.trim() : '') || (el.getAttribute('aria-labelledby') ? 'x' : '')
        return name ? null : `${el.tagName.toLowerCase()}.${el.className}`
      })
    for (let i = 1; i <= 60; i++) {
      await page.keyboard.press('Tab')
      const bad = await unnamed()
      if (bad) problems.push(`tab ${i}: focused element has no accessible name: ${bad}`)
      if (i === 8) await shot('a11y-focus')
    }
    // And through the open nav: the menu buttons, the building select and every toolbar button need names too.
    await nav(page, true)
    await page.evaluate(() => document.getElementById('nav-toggle').focus())
    for (let i = 1; i <= 26; i++) {
      await page.keyboard.press('Tab')
      const bad = await unnamed()
      if (bad) problems.push(`nav tab ${i}: focused element has no accessible name: ${bad}`)
    }
    await nav(page, false)

    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.reload()
    await page.waitForFunction(() => window.__app?.getState().activeRunKey, null, { timeout: 60000 })
    await page.evaluate(() => window.__tour.getState().go(0, false))
    await page.waitForTimeout(3000)
    const c = page.locator('main.center canvas').first()
    const a = await c.screenshot()
    await page.waitForTimeout(1000)
    const b = await c.screenshot()
    if (!a.equals(b)) problems.push('motion despite reduced motion')
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.evaluate(() => {
      window.__tour.getState().stop()
      window.__app.setState({ autoRotate: false })
    })

    // High contrast through Settings; the shot is of the collapsed layout.
    await nav(page, true)
    await pickMenu(page, 'Settings', 'High contrast')
    await nav(page, false)
    await page.waitForTimeout(500)
    await shot('contrast')
    await runAxe('high contrast', '.app')
    await nav(page, true)
    await pickMenu(page, 'Settings', 'High contrast')
    await nav(page, false)
    if ((await page.evaluate(() => document.documentElement.dataset.contrast)) === 'high') problems.push('High contrast did not turn off')
  })
  await step('phone', async () => {
    // A 390 x 844 phone with the same init script: panels overlay the viewer, the floor strip scrolls, the timeline stays usable.
    const pctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 })
    await pctx.addInitScript(() => {
      try {
        localStorage['fes.aboutSeen'] = '1'
      } catch {
        /* ignore */
      }
    })
    const ph = await pctx.newPage()
    ph.on('console', (m) => {
      if (m.type() === 'error' && !/calibration\.json/.test(m.text() + (m.location()?.url ?? ''))) errors.push(`[phone] ${m.text()}`)
    })
    ph.on('pageerror', (e) => errors.push(`[phone] ${String(e)}`))
    try {
      await ph.goto(`${server.resolvedUrls.local[0]}?qa`)
      await ph.waitForFunction(() => window.__app?.getState().activeRunKey, null, { timeout: 60000 })
      await ph.waitForTimeout(2000)
      const bad = (m) => problems.push(`phone: ${m}`)
      if (!(await ph.getByRole('button', { name: 'Show analytics' }).isVisible())) bad('the sidebar does not start collapsed ("Show analytics" is missing)')
      if (!(await ph.locator('#play').isVisible())) bad('#play is not visible')
      const strip = await ph.locator('nav.floorstrip').evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth, shown: el.getBoundingClientRect().height > 0 }))
      if (!strip.shown) bad('the floor strip is not visible')
      if (strip.sw < strip.cw) bad(`the floor strip's scrollWidth ${strip.sw} is under its clientWidth ${strip.cw}`)
      const tl = await ph.locator('.timeline').evaluate((el) => ({ right: el.getBoundingClientRect().right, w: window.innerWidth, scroll: document.documentElement.scrollWidth }))
      if (tl.right > tl.w + 1 || tl.scroll > tl.w + 1) bad(`the timeline or page overflows sideways (timeline right ${Math.round(tl.right)}, page scrollWidth ${tl.scroll}, window ${tl.w})`)
      await ph.screenshot({ path: join(out, 'phone.png') })
      shots.push('phone')
      const before = await ph.locator('main.center').boundingBox()
      await ph.getByRole('button', { name: 'Show analytics' }).click()
      await ph.waitForTimeout(1500)
      const after = await ph.locator('main.center').boundingBox()
      const side = await ph.locator('#analytics').boundingBox()
      if (!before || !after || !side) bad('could not measure main.center and the sidebar')
      else {
        if (Math.abs(after.width - before.width) > 1 || Math.abs(after.height - before.height) > 1) bad(`opening the sidebar resized the viewer (${Math.round(before.width)}x${Math.round(before.height)} to ${Math.round(after.width)}x${Math.round(after.height)})`)
        if (side.x < after.x - 1 || side.x + side.width > after.x + after.width + 1 || side.y + side.height > after.y + after.height + 1) bad('the open sidebar is not inside the viewer box')
      }
      await ph.screenshot({ path: join(out, 'phone-sidebar.png') })
      shots.push('phone-sidebar')
      await axeOn(ph, 'phone', '.app')
      await ph.evaluate(() => window.__app.setState({ sidebarOpen: false }))
      await ph.locator('#nav-toggle').click()
      await ph.waitForTimeout(400)
      await ph.screenshot({ path: join(out, 'phone-nav.png') })
      shots.push('phone-nav')
      await axeOn(ph, 'phone nav', '.app')
    } finally {
      await pctx.close()
    }
  })
  for (let n = 0; n < opens.length; n++) {
    await step(`open-${n + 1}`, async () => {
      await page.locator('#open-file').setInputFiles(opens[n])
      await page.waitForTimeout(500)
      await page.waitForFunction(() => window.__app.getState().loading === null, null, { timeout: 60000 })
    })
    await tabShots(`open-${n + 1}-`)
  }
  if (await page.evaluate(() => !!window.__app.getState().headlines)) {
    await step('headlines-about', async () => {
      await page.evaluate(() => window.__app.getState().setAbout(true))
      await page.waitForTimeout(500)
      await shot('open-about')
      await page.keyboard.press('Escape')
    })
    for (const [scene, name] of [[3, 'open-scene4'], [4, 'open-scene5']])
      await step(name, async () => {
        await page.evaluate((i) => window.__tour.getState().go(i, false), scene)
        await page.waitForTimeout(3000)
        await shot(name)
      })
    await page.evaluate(() => window.__tour.getState().stop())
  }
  if (opens.length > 0)
    await step('fixes', async () => {
      await page.locator('.results [role=tab]').nth(1).click()
      await page.waitForTimeout(500)
      const list = page.locator('.results .fixes')
      if ((await list.count()) === 0) return
      await list.first().scrollIntoViewIfNeeded()
      await shot('fixes-list')
      if ((await page.evaluate(() => window.__app.getState().batch?.id)) === 'fixes') {
        // The fixture holds one trade-off judged from its numbers and one the batch flags (D22): both badged, costs after "; but",
        // and no spot named by its raw id. Demo batches skip the id check: their D-written labels keep IFC ids until D23 and the precompute rerun.
        const trades = await list.first().locator('.badge.trade').allTextContents()
        if (trades.length !== 2 || trades.some((t) => t.trim() !== 'trade-off')) problems.push(`fixes: want two "trade-off" badges, got ${JSON.stringify(trades)}`)
        if (!(await list.first().innerText()).includes('; but +1.3 trapped per fire')) problems.push('fixes: the list lacks "; but +1.3 trapped per fire"')
        const named = await page.locator('.fixes .target, .spots button b').allInnerTexts()
        for (const w of ['DSB2', 'DSA2', 'DSA1', 'E1', 'E2'])
          if (named.some((t) => new RegExp(`\\b${w}\\b`).test(t))) problems.push(`fixes: raw id ${w} in a fix target or weak-spot heading`)
      }
      const btn = list.locator('button.spot').first()
      const id = await btn.getAttribute('data-spot')
      await btn.click()
      await page.waitForTimeout(2000)
      const st = await page.evaluate(() => ({ a: window.__app.getState().activeSpot, v: window.__app.getState().visibleFloors }))
      if (st.a !== id || !st.v || st.v.length !== 1) problems.push(`fixes: activeSpot ${st.a} (want ${id}), visibleFloors ${JSON.stringify(st.v)}`)
      await shot('fixes-fly')
    })
  await step('live-fallback', async () => {
    // qa has no backend, so a fresh page (the main page's runs stay as they are) is put in live mode by hand and the API answered by routes.
    // Every way a live run can fail must end on the nearest precomputed fire with the note; with none for the building, the live error stays.
    const p3 = await ctx.newPage()
    const before = problems.length
    p3.on('console', (m) => {
      if (m.type() === 'error' && !/calibration\.json|status of 500|ERR_CONNECTION_REFUSED/.test(m.text() + (m.location()?.url ?? ''))) errors.push(`[live-fallback] ${m.text()}`)
    })
    p3.on('pageerror', (e) => errors.push(`[live-fallback] ${String(e)}`))
    try {
      let how = 'http'
      const json = (r, body, status = 200) => r.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
      await p3.route('**/runs', (r) => (how === 'down' ? r.abort('connectionrefused') : how === 'http' ? json(r, { detail: 'qa: backend error' }, 500) : json(r, { runId: 'qa-run' })))
      await p3.route('**/runs/qa-run', (r) => json(r, how === 'failed' ? { status: 'error', error: 'qa: run failed' } : { status: 'running' }))
      await p3.goto(`${server.resolvedUrls.local[0]}?qa`)
      await p3.waitForFunction(() => window.__app?.getState().activeRunKey, null, { timeout: 60000 })
      const first = await p3.evaluate(() => {
        // pollRun's wait is 600 s of Date.now: this lets the page's clock jump over it
        const real = Date.now.bind(Date)
        let skew = 0
        Date.now = () => real() + skew
        window.__skew = (ms) => (skew += ms)
        return window.__app.getState().activeRunKey
      })
      // A precomputed fire other than the one on screen: the last run of this building (no what-if) whose spot no other run shares.
      const t = await p3.evaluate(async (first) => {
        const st = window.__app.getState()
        const idx = await (await fetch('demo/index.json')).json()
        const base = idx.runs.filter((r) => r.buildingId === st.building.id && r.whatIf === null)
        const lone = base.filter((r) => r.id !== first && base.filter((o) => o.fire.x === r.fire.x && o.fire.y === r.fire.y).length === 1)
        return lone.length ? lone[lone.length - 1] : null
      }, first)
      if (!t) return void problems.push('live-fallback: no second precomputed fire to fall back to in the demo index')
      await p3.evaluate((fire) => {
        const d = window.__app.getState().draft
        window.__app.getState().patchDraft({ fire: { ...d.fire, floor: fire.floor, room: fire.room, x: fire.x, y: fire.y } })
      }, t.fire)
      await p3.evaluate(() => window.__app.setState({ card: 'scenario' }))
      const runButton = p3.locator('.scenario > button.run')
      const read = () =>
        p3.evaluate(() => {
          const a = window.__app.getState()
          return { key: a.activeRunKey, note: a.runNote, fallback: a.runFallback, err: a.runError, mode: a.mode, notice: a.notice, running: a.running }
        })
      const settle = () => p3.waitForFunction(() => window.__app.getState().running === null, null, { timeout: 30000 })
      const note = `Live run unavailable: showing the nearest precomputed fire (room ${t.fire.room}).`
      for (const name of ['http', 'failed', 'slow', 'down']) {
        how = name
        await p3.evaluate((first) => {
          window.__app.getState().switchRun(first)
          window.__app.setState({ mode: 'live', notice: null })
        }, first)
        await runButton.click()
        if (name === 'slow') {
          await p3.waitForFunction(() => /Running… \d+ s/.test(window.__app.getState().running ?? ''), null, { timeout: 15000 })
          await p3.evaluate(() => window.__skew(700000))
        }
        await settle()
        const s = await read()
        const dom = await p3.locator('.scenario p.warn').allInnerTexts()
        const wantMode = name === 'down' ? 'static' : 'live'
        if (s.key !== t.id) problems.push(`live-fallback (${name}): active run ${s.key}, want ${t.id}`)
        if (s.note !== note || !s.fallback || dom.length !== 1 || dom[0] !== note) problems.push(`live-fallback (${name}): note "${s.note}", on screen ${JSON.stringify(dom)}, want "${note}"`)
        if (s.err) problems.push(`live-fallback (${name}): runError "${s.err}" beside a precomputed run`)
        if (s.mode !== wantMode) problems.push(`live-fallback (${name}): mode ${s.mode}, want ${wantMode}`)
        if (name === 'down' && s.notice !== 'Backend unreachable: precomputed runs only') problems.push(`live-fallback (down): notice "${s.notice}"`)
        if (name === 'http') {
          await p3.locator('.scenario p.warn').scrollIntoViewIfNeeded()
          await p3.screenshot({ path: join(out, 'live-fallback.png') })
          shots.push('live-fallback')
        }
      }
      // No precomputed run for the building: today's error, and no note.
      how = 'http'
      await p3.evaluate(() => {
        const a = window.__app
        a.setState({ mode: 'live', notice: null, building: { ...a.getState().building, id: 'qa-none' } })
      })
      await runButton.click()
      await settle()
      const s = await read()
      if (s.err !== 'Request failed (500): qa: backend error' || s.note || s.fallback) problems.push(`live-fallback (none): runError "${s.err}", note "${s.note}"`)
      if (!(await p3.locator('.scenario p.err').allInnerTexts()).includes('Request failed (500): qa: backend error')) problems.push('live-fallback (none): the error is not on screen')
      if (problems.length === before) lines.push('live-fallback ok: http, failed, slow and down end on the nearest precomputed fire; none keeps the error')
    } finally {
      await p3.close()
    }
  })
  await step('whatif-fallback', async () => {
    // As live-fallback, for what-ifs, in a fresh page with the same routes: every way a live what-if can fail must end on the baseline's precomputed
    // propped-door run with an amber note (and live mode kept, unless the connection itself was refused); with none for the building, the live error stays.
    const p5 = await ctx.newPage()
    const before = problems.length
    p5.on('console', (m) => {
      if (m.type() === 'error' && !/calibration\.json|status of 500|ERR_CONNECTION_REFUSED/.test(m.text() + (m.location()?.url ?? ''))) errors.push(`[whatif-fallback] ${m.text()}`)
    })
    p5.on('pageerror', (e) => errors.push(`[whatif-fallback] ${String(e)}`))
    try {
      let how = 'http'
      const json = (r, body, status = 200) => r.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
      await p5.route('**/runs', (r) => (how === 'down' ? r.abort('connectionrefused') : how === 'http' ? json(r, { detail: 'qa: backend error' }, 500) : json(r, { runId: 'qa-run' })))
      await p5.route('**/runs/qa-run', (r) => json(r, how === 'failed' ? { status: 'error', error: 'qa: run failed' } : { status: 'running' }))
      await p5.goto(`${server.resolvedUrls.local[0]}?qa`)
      await p5.waitForFunction(() => window.__app?.getState().activeRunKey, null, { timeout: 60000 })
      const first = await p5.evaluate(() => {
        // pollRun's wait is 600 s of Date.now: this lets the page's clock jump over it
        const real = Date.now.bind(Date)
        let skew = 0
        Date.now = () => real() + skew
        window.__skew = (ms) => (skew += ms)
        return window.__app.getState().activeRunKey
      })
      // The baseline's own precomputed what-if: the propped-door entry of the same fire in the index.
      const want = await p5.evaluate(async (first) => {
        const idx = await (await fetch('demo/index.json')).json()
        const st = window.__app.getState()
        const baseline = idx.runs.find((r) => r.id === first)
        return idx.runs.find((r) => r.buildingId === st.building.id && r.whatIf === 'propped' && r.fire.room === baseline?.fire.room) ?? null
      }, first)
      if (!want) return void problems.push('whatif-fallback: the first baseline has no propped what-if in the demo index')
      await p5.evaluate(() => window.__app.setState({ card: 'scenario' }))
      const runButton = p5.locator('.whatif button.run')
      const read = () =>
        p5.evaluate(() => {
          const a = window.__app.getState()
          return { key: a.activeRunKey, note: a.whatIfNote, fallback: a.whatIfFallback, err: a.whatIfError, mode: a.mode, notice: a.notice, busy: a.whatIfBusy }
        })
      const settle = () => p5.waitForFunction(() => window.__app.getState().whatIfBusy === null, null, { timeout: 30000 })
      const prefix = 'Live what-if unavailable: showing the precomputed what-if'
      for (const name of ['http', 'failed', 'slow', 'down']) {
        how = name
        await p5.evaluate((first) => {
          window.__app.getState().switchRun(first)
          window.__app.setState({ mode: 'live', notice: null })
        }, first)
        await runButton.click()
        if (name === 'slow') {
          await p5.waitForFunction(() => /Running… \d+ s/.test(window.__app.getState().whatIfBusy ?? ''), null, { timeout: 15000 })
          await p5.evaluate(() => window.__skew(700000))
        }
        await settle()
        const s = await read()
        const dom = await p5.locator('.whatif p.warn').allInnerTexts()
        const wantMode = name === 'down' ? 'static' : 'live'
        if (s.key !== want.id) problems.push(`whatif-fallback (${name}): active run ${s.key}, want ${want.id}`)
        if (!s.note?.startsWith(prefix) || !s.fallback) problems.push(`whatif-fallback (${name}): note "${s.note}", fallback ${s.fallback}, want a note starting "${prefix}"`)
        if (dom.length !== 1 || dom[0] !== s.note) problems.push(`whatif-fallback (${name}): the note is on screen as ${JSON.stringify(dom)}, want "${s.note}"`)
        if ((await p5.locator('.whatif p.warn[role=status]').count()) !== 1) problems.push(`whatif-fallback (${name}): the note is not a p.warn[role=status]`)
        if (s.err) problems.push(`whatif-fallback (${name}): whatIfError "${s.err}" beside a precomputed what-if`)
        if (s.mode !== wantMode) problems.push(`whatif-fallback (${name}): mode ${s.mode}, want ${wantMode}`)
        if (name === 'down' && s.notice !== 'Backend unreachable: precomputed runs only') problems.push(`whatif-fallback (down): notice "${s.notice}"`)
        if (name === 'http') {
          await p5.locator('.whatif p.warn').scrollIntoViewIfNeeded()
          await p5.screenshot({ path: join(out, 'whatif-fallback.png') })
          shots.push('whatif-fallback')
          await axeOn(p5, 'whatif-fallback', '.app')
        }
      }
      // No precomputed what-if for the building: today's error, and no note.
      how = 'http'
      await p5.evaluate(() => {
        const a = window.__app
        a.setState({ mode: 'live', notice: null, building: { ...a.getState().building, id: 'qa-none' } })
      })
      await runButton.click()
      await settle()
      const s = await read()
      if (s.err !== 'Request failed (500): qa: backend error' || s.note || s.fallback) problems.push(`whatif-fallback (none): whatIfError "${s.err}", note "${s.note}", fallback ${s.fallback}`)
      if (!(await p5.locator('.whatif p.err').allInnerTexts()).includes('Request failed (500): qa: backend error')) problems.push('whatif-fallback (none): the error is not on screen')
      if (problems.length === before) lines.push('whatif-fallback ok: http, failed, slow and down end on the precomputed what-if; none keeps the error')
    } finally {
      await p5.close()
    }
  })
  if (FPS && opens.length > 0)
    await step('fps', async () => {
      await page.locator('.results [role=tab]').first().click()
      const cases = [
        ['default', { autoRotate: false, trails: false }],
        ['rotate', { autoRotate: true, trails: false }],
        ['trails', { autoRotate: false, trails: true }],
      ]
      for (const [name, flags] of cases) {
        await page.evaluate((f) => {
          window.__app.setState(f)
          window.__tour?.getState().stop()
          window.__app.setState(f)
          window.__clock.getState().seek?.(0)
          window.__clock.setState({ t: 0, speed: 10, playing: true })
        }, flags)
        await page.waitForTimeout(2000)
        const r = await page.evaluate(async () => ({ f: await window.__fps(10), p: window.__perf() }))
        lines.push(
          `fps ${name}: avg ${r.f.avg.toFixed(1)}, 1% low ${r.f.low1.toFixed(1)}, calls ${r.p.calls}, triangles ${r.p.triangles > 1000 ? Math.round(r.p.triangles / 1000) + 'k' : r.p.triangles}, html ${r.p.html}, renderer ${r.p.renderer}`,
        )
        await page.evaluate(() => {
          window.__app.setState({ autoRotate: false, trails: false })
          window.__clock.setState({ playing: false })
        })
      }
    })
} finally {
  if (browser) await browser.close()
  await server.close()
}

const summary = [
  `shots (${shots.length}): ${shots.join(', ')}`,
  `webgl: ${webgl ? 'yes' : 'no'}`,
  `playback to 60 s took ${playSecs.toFixed(1)} real seconds`,
  ...lines,
  ...problems.map((p) => `PROBLEM: ${p}`),
  ...errors.map((e) => `CONSOLE ERROR: ${e}`),
].join('\n')
writeFileSync(join(out, 'summary.txt'), summary + '\n')
console.log(summary)
if (problems.length || errors.length) process.exit(1)
console.log(`qa ok: ${shots.length} screenshots in frontend/qa/`)
