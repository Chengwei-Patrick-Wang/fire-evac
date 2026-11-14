// Headless visual QA: node scripts/qa.mjs [--open FILE]...  (run `npm run build` first; `npm run qa` does both)
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { preview } from 'vite'

// axe rules we accept as-is, one line of reason each (none yet)
const AXE_ALLOW = []

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const out = join(root, 'qa')
const opens = []
for (let i = 2; i < process.argv.length; i++) {
  if (process.argv[i] === '--open' && process.argv[i + 1]) opens.push(resolve(process.argv[++i]))
}
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
    cur = name
    try {
      await fn()
    } catch (e) {
      problems.push(`step "${name}" failed: ${String(e).split('\n')[0]}`)
    }
  }
  const shot = async (name) => {
    await page.screenshot({ path: join(out, name + '.png') })
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
  const changedShare = (b64) =>
    page.evaluate(async (b64) => {
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
  const blankCheck = async (name) => {
    const canvases = page.locator('main.center canvas')
    const n = await canvases.count()
    if (n === 0) {
      problems.push(`no canvas in ${name}`)
      lines.push(`${name}: no canvas`)
      return
    }
    for (let i = 0; i < n; i++) {
      const buf = await canvases.nth(i).screenshot()
      const share = await changedShare(buf.toString('base64'))
      lines.push(`${name}: canvas ${i} changed ${(share * 100).toFixed(1)}%`)
      if (share < 0.01) problems.push(`blank canvas in ${name}`)
    }
  }

  await step('load', async () => {
    await page.goto(`${server.resolvedUrls.local[0]}?qa`)
    await page.waitForFunction(() => window.__app?.getState().activeRunKey, null, { timeout: 60000 })
    webgl = await page.evaluate(() => !!document.createElement('canvas').getContext('webgl2'))
  })
  await step('whatif-static', async () => {
    // No VITE_API_URL here, so the app is in static mode: the Sprinklers box must be off and quote the measured what-if.
    const box = page.locator('.scenario .whatif')
    await box.scrollIntoViewIfNeeded()
    await page.waitForFunction(() => /fires:/.test(document.querySelector('.scenario .whatif .note')?.textContent ?? ''), null, { timeout: 5000 }).catch(() => {})
    const check = box.locator('label.check', { hasText: 'Sprinklers' }).locator('input[type=checkbox]')
    if ((await check.count()) === 0 || (await check.isEnabled())) problems.push('whatif-static: the Sprinklers checkbox is missing or enabled in static mode')
    const notes = box.locator('p.note')
    const note = (await notes.count()) > 0 ? ((await notes.first().textContent()) ?? '') : ''
    if (!/Sprinklers need the live backend/.test(note)) problems.push(`whatif-static: note lacks "Sprinklers need the live backend": "${note}"`)
    if (!/fires:/.test(note)) problems.push(`whatif-static: note lacks the measured "fires:" quote: "${note}"`)
    await shot('whatif-static')
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
    await page.locator('header.topbar button', { hasText: 'About' }).click()
    await page.locator('[role=dialog]').waitFor({ timeout: 10000 })
    await page.waitForTimeout(500)
    await shot('about')
    await page.keyboard.press('Escape')
  })
  await step('tracer', async () => {
    await page.locator('.topbar .tabs button', { hasText: 'Tracer' }).click()
    await page.locator('.tr-page').waitFor({ timeout: 15000 })
    await page.waitForTimeout(500)
    await shot('tracer')
    cur = 'tracer→replay'
    await page.locator('.topbar .tabs button', { hasText: 'Replay' }).click()
    await page.locator('main.center canvas').first().waitFor({ timeout: 15000 })
  })
  await step('scene4', async () => {
    await page.evaluate(() => window.__tour.getState().go(3, false))
    await page.waitForTimeout(4000)
    await shot('scene4')
    await blankCheck('scene4')
    await page.evaluate(() => window.__tour.getState().stop())
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
        return g && g.resultsTab === 'risk' && g.activeRunKey && Math.abs(window.__clock.getState().t - 42) < 0.11
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
    lines.push('deeplink ok')
  })
  await step('share', async () => {
    await page.locator('header.topbar button', { hasText: 'Share' }).click()
    await page.locator('[role=dialog][aria-label="Share this view"]').waitFor({ timeout: 10000 })
    await page.waitForTimeout(500)
    await shot('share')
    await page.keyboard.press('Escape')
  })
  await step('print', async () => {
    await page.locator('.results [role=tab]').nth(2).click()
    await page.locator('.results button', { hasText: 'Print report' }).first().click()
    await page.locator('.printreport').waitFor({ timeout: 15000 })
    await page.waitForTimeout(1000)
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
  await step('save-png', async () => {
    const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 15000 }), page.locator('.toolbar3d button', { hasText: 'Save PNG' }).click()])
    const f = join(out, 'save-3d.png')
    await dl.saveAs(f)
    const share = await changedShare(readFileSync(f).toString('base64'))
    lines.push(`save-3d.png: changed ${(share * 100).toFixed(1)}%`)
    if (share < 0.01) problems.push('blank Save PNG')
  })
  await step('a11y', async () => {
    const axePath = join(root, 'node_modules', 'axe-core', 'axe.min.js')
    let haveAxe = existsSync(axePath)
    if (haveAxe) await page.addScriptTag({ path: axePath })
    else lines.push('axe skipped: not installed')
    const runAxe = async (label, sel) => {
      if (!haveAxe) return
      const res = await page.evaluate(
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
    await page.locator('header.topbar button', { hasText: 'About' }).click()
    await page.locator('[role=dialog]').waitFor({ timeout: 10000 })
    await runAxe('about', '[role=dialog]')
    await page.keyboard.press('Escape')
    await page.locator('.results [role=tab]').first().click()

    await page.evaluate(() => document.body.focus())
    await page.evaluate(() => document.activeElement && document.activeElement.blur())
    for (let i = 1; i <= 60; i++) {
      await page.keyboard.press('Tab')
      const bad = await page.evaluate(() => {
        const el = document.activeElement
        if (!el || el === document.body) return null
        const name = (el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '').trim() || (el.labels && el.labels.length ? el.labels[0].textContent.trim() : '') || (el.getAttribute('aria-labelledby') ? 'x' : '')
        return name ? null : `${el.tagName.toLowerCase()}.${el.className}`
      })
      if (bad) problems.push(`tab ${i}: focused element has no accessible name: ${bad}`)
      if (i === 8) await shot('a11y-focus')
    }

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

    await page.locator('header.topbar button', { hasText: 'Display' }).click()
    await page.locator('#display-panel label', { hasText: 'High contrast' }).click()
    await page.waitForTimeout(500)
    await shot('contrast')
    await page.locator('#display-panel label', { hasText: 'High contrast' }).click()
    await page.keyboard.press('Escape')
  })
  for (let n = 0; n < opens.length; n++) {
    await step(`open-${n + 1}`, async () => {
      await page.locator('header.topbar label.file input').setInputFiles(opens[n])
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
      const btn = list.locator('button.spot').first()
      const id = await btn.getAttribute('data-spot')
      await btn.click()
      await page.waitForTimeout(2000)
      const st = await page.evaluate(() => ({ a: window.__app.getState().activeSpot, v: window.__app.getState().visibleFloors }))
      if (st.a !== id || !st.v || st.v.length !== 1) problems.push(`fixes: activeSpot ${st.a} (want ${id}), visibleFloors ${JSON.stringify(st.v)}`)
      await shot('fixes-fly')
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
