/* Development-only regression checks. No browser libraries ship with the site. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const modules = process.env.QA_NODE_MODULES;
if (!modules) throw new Error('Set QA_NODE_MODULES to the development-only npm installation');
const { chromium } = require(path.join(modules, 'playwright'));
const axePath = path.join(modules, 'axe-core', 'axe.min.js');
const chartPath = path.join(modules, 'chart.js', 'dist', 'chart.umd.js');
const base = process.argv[2] || 'http://127.0.0.1:8765';
const pages = ['index','global-macro','intel-feed','ai','ct','mri','pet','xray','consultancy',
               'intel-regulatory','intel-ma','intel-funding','intel-partnerships','global-risk-report'];
const sizes = [{width:375,height:812}, {width:768,height:1024}, {width:1440,height:1000}];
const results = [], failures = [];
fs.mkdirSync('qa-results', {recursive:true});

(async () => {
 const browser = await chromium.launch();
 try {
  for (const viewport of sizes) {
   const context = await browser.newContext({viewport, reducedMotion:'reduce',
     isMobile:viewport.width===375, hasTouch:viewport.width<=768});
   // Exercise the exact runtime chart version without depending on a CDN during QA.
   await context.route('https://cdn.jsdelivr.net/npm/chart.js@4.4.8/dist/chart.umd.min.js',
     route => route.fulfill({path:chartPath,contentType:'application/javascript'}));
   context.setDefaultTimeout(10000);
   const page = await context.newPage();
   let errors = [];
   page.on('pageerror', error => errors.push(error.message));
   for (const name of pages) {
    errors = [];
    try {
     const response = await page.goto(`${base}/${name}.html`, {waitUntil:'networkidle'});
     assert.equal(response.status(),200, 'page must load');
     assert.equal(await page.locator('main').count(),1, 'one main landmark');
     const structure = await page.evaluate(() => {
      const ids = [...document.querySelectorAll('[id]')].map(e=>e.id);
      const broken = [...document.querySelectorAll('a[href^="#"]')]
       .map(a=>a.getAttribute('href')).filter(h=>h.length>1&&!document.getElementById(decodeURIComponent(h.slice(1))));
      const offscreen = [...document.querySelectorAll('nav a,select,input')]
       .filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.height&&(r.left < -1||r.right>innerWidth+1);})
       .map(e=>e.outerHTML.slice(0,160));
      return {duplicateIds:ids.filter((id,i)=>ids.indexOf(id)!==i),broken,offscreen,
        documentOverflow:document.documentElement.scrollWidth>innerWidth+1};
     });
     assert.deepEqual(structure.duplicateIds,[], 'unique element IDs');
     assert.deepEqual(structure.broken,[], 'in-page links resolve');
     assert.deepEqual(structure.offscreen,[], 'navigation and inputs remain on screen');
     assert.equal(structure.documentOverflow,false, 'no page-wide horizontal overflow');
     if (['ct','mri','pet'].includes(name)) {
      for (const region of ['europe','northAmerica','asiaPacific','global']) {
       await page.locator(`#${name}-region`).selectOption(region);
       assert.ok((await page.locator(`#${name}-stat-grid`).innerText()).trim(),'regional overview populated');
      }
     }
     if (name==='ai') {
      assert.equal(await page.locator('#dashboard-data').count(),0,'build-only evidence is not shipped');
      const source=JSON.parse(await page.locator('#ai-data').textContent());
      const fdaAvailable=source.regions.global.approvals.some(v=>typeof v==='number'&&Number.isFinite(v));
      const researchAvailable=source.registryChart.values.some(v=>typeof v==='number'&&Number.isFinite(v));
      if(fdaAvailable){
       const summary=page.getByText('View annual and year-to-date values',{exact:true});
       // Test native keyboard activation of the expandable FDA data table.
       await summary.press('Enter');
       assert.ok(await page.locator('#fda-trend-section table').isVisible(),'FDA exact values accessible');
      }
      assert.equal(await page.locator('.ai-table-scroll[tabindex="0"]').count(),
        Number(fdaAvailable)+Number(researchAvailable),'all available value tables keyboard scrollable');
     }
     if (name==='xray') {
      await page.locator('#xr-region').selectOption('northAmerica');
      assert.equal(await page.locator('#xr-sample-note').isVisible(),false,'England note hidden elsewhere');
      assert.match(await page.locator('#xr-history').innerText(),/No verified/);
      await page.locator('#xr-region').selectOption('europe');
      assert.equal(await page.locator('#xr-sample-note').isVisible(),true);
     }
     if (name==='global-macro') {
      await page.locator('#nominal-input').fill('');
      assert.equal(await page.locator('#real-output').innerText(),'Check inputs');
      await page.locator('#nominal-input').fill('0');
      await page.locator('#inflation-input').fill('0');
      assert.equal(await page.locator('#real-output').innerText(),'0%');
      await page.locator('#inflation-input').fill('-100');
      assert.equal(await page.locator('#real-output').innerText(),'Check inputs');
      await page.locator('#nominal-input').fill('5');
      await page.locator('#inflation-input').fill('3');
     }
     // Include the content exposed by expandable methodology and data tables.
     await page.locator('details').evaluateAll(es=>es.forEach(e=>e.open=true));
     await page.addScriptTag({path:axePath});
     const accessibility = await page.evaluate(async () => {
      const result=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}});
      return result.violations.map(v=>({id:v.id,impact:v.impact,help:v.help,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary})).slice(0,8)}));
     });
     assert.deepEqual(accessibility,[], 'automated WCAG A/AA checks: '+JSON.stringify(accessibility));
     assert.deepEqual(errors,[], 'no page JavaScript errors');
     if (['ai','ct','global-macro'].includes(name)&&viewport.width!==768)
      await page.screenshot({path:`qa-results/${name}-${viewport.width}.png`});
     results.push({page:name,width:viewport.width,status:'passed'});
    } catch(error) {
     const entry={page:name,width:viewport.width,status:'failed',error:error.message};
     results.push(entry);failures.push(entry);
     await page.screenshot({path:`qa-results/FAILED-${name}-${viewport.width}.png`}).catch(()=>{});
     console.error(JSON.stringify(entry));
    }
   }
   await context.close();
  }
  // Simulate CDN failure and real zero/null data without changing source files.
  const fallback=await browser.newContext({viewport:{width:375,height:812}});
  await fallback.route('**/chart.umd.min.js',r=>r.abort());
  await fallback.route(`${base}/ai.html`,async route=>{
   const response=await route.fetch();let html=await response.text();
   html=html.replace(/(<script id="ai-data" type="application\/json">)([\s\S]*?)(<\/script>)/,(_,a,raw,b)=>{
    const payload=JSON.parse(raw);payload.registryChart.values[0]=0;payload.registryChart.values[1]=null;
    payload.regions.global.years=['2025','2026 YTD'];payload.regions.global.approvals=[0,null];
    return a+JSON.stringify(payload).replace(/</g,'\\u003c')+b;
   });
   await route.fulfill({response,body:html});
  });
  const fp=await fallback.newPage();
  await fp.goto(`${base}/ai.html`,{waitUntil:'networkidle'});
  const table=await fp.locator('#ai-research-section table').innerText();
  assert.match(table,/Worldwide\s+0/,'zero retained');assert.match(table,/Unavailable/,'null is unavailable');
  assert.equal(await fp.locator('#approvalsChart').isVisible(),false,'failed CDN hides canvas');
  await fp.getByText('View annual and year-to-date values',{exact:true}).press('Enter');
  assert.ok(await fp.locator('#fda-trend-section table').isVisible(),'FDA values survive CDN failure');
  results.push({page:'ai failure/zero/null',width:375,status:'passed'});
  await fallback.close();
  const slow=await browser.newContext({viewport:{width:375,height:812},reducedMotion:'reduce'});
  await slow.route('https://cdn.jsdelivr.net/npm/chart.js@4.4.8/dist/chart.umd.min.js',
    route=>route.fulfill({path:chartPath,contentType:'application/javascript'}));
  const sp=await slow.newPage(),cdp=await slow.newCDPSession(sp);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions',{offline:false,latency:150,
    downloadThroughput:200*1024,uploadThroughput:100*1024,connectionType:'cellular3g'});
  await cdp.send('Emulation.setCPUThrottlingRate',{rate:4});
  const start=Date.now();await sp.goto(`${base}/ai.html`,{waitUntil:'networkidle'});
  assert.ok((await sp.locator('#ai-overview-section').innerText()).trim(),'slow mobile overview populated');
  const elapsed=Date.now()-start;assert.ok(elapsed<20000,'local throttled smoke-test budget');
  results.push({page:'ai throttled mobile',width:375,status:'passed',loadMs:elapsed,
    conditions:'150ms latency; 200 KiB/s download; CPU x4; local server, not field metrics'});
  await slow.close();
 } catch(error) {
  failures.push({page:'edge cases',error:error.stack});console.error(error);
 } finally {
  await browser.close();
  fs.writeFileSync('qa-results/report.json',JSON.stringify({results,failures},null,2));
 }
 console.log(`${results.filter(r=>r.status==='passed').length} browser scenarios passed; ${failures.length} failed.`);
 if(failures.length)process.exitCode=1;
})();
