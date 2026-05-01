import {chromium,expect} from '@playwright/test';
import {mkdir} from 'node:fs/promises';
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||(process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':undefined),headless:true});
const page=await browser.newPage({viewport:{width:1600,height:1100},deviceScaleFactor:1});
const errors=[];page.on('pageerror',error=>errors.push(error.message));
await mkdir('docs/screenshots',{recursive:true});
async function shot(name){await page.screenshot({path:`docs/screenshots/${name}.png`,fullPage:true});console.log('Captured',name)}
async function home(){await page.goto('http://127.0.0.1:8000');await page.getByText('Corpus ready',{exact:true}).waitFor()}
async function query(q,scope){
 await home();
 for(const ticker of ['AAPL','MSFT','NVDA']){
  const button=page.locator('.issuer-button').filter({hasText:ticker});
  const chosen=(await button.getAttribute('class')).includes('selected');
  if(chosen!==scope.includes(ticker))await button.click();
 }
 await page.getByLabel('Research question',{exact:true}).fill(q);
 await page.getByRole('button',{name:'Research question submit'}).click();
 await page.getByRole('tab',{name:'Answer',exact:true}).waitFor({timeout:90000});
}
await home();await shot('research-overview');
await query('What supply chain manufacturing disruption risks does Apple disclose?',['AAPL']);await shot('apple-risk-research');await page.locator('.citation').first().click();await shot('source-inspector');await page.getByRole('tab',{name:'Retrieval details'}).click();await shot('retrieval-details');
await query('Compare Apple and Microsoft operating margin and revenue growth',['AAPL','MSFT']);await shot('financial-comparison');await page.getByRole('tab',{name:/Calculations/}).click();await shot('calculation-inspector');await page.locator('.operand-list button').first().click();await shot('xbrl-provenance');
await query('What is Microsoft OpenAI Azure partnership?',['MSFT']);await shot('microsoft-partnership');
await query('What foundries and manufacturing suppliers does NVIDIA depend on?',['NVDA']);await shot('nvidia-manufacturing');
await query('Predict Apple stock price next year',['AAPL']);await shot('unsupported-question');
await page.getByRole('button',{name:/Filing library/}).click();await shot('filing-library');await page.getByRole('button',{name:/Import a filing/}).click();await shot('import-filing');await page.getByRole('button',{name:'Close import'}).click();
await page.getByRole('button',{name:'Evaluation',exact:true}).click();await page.getByText('Hybrid + cross-encoder',{exact:false}).waitFor();await shot('evaluation-baselines');
await home();await page.getByRole('button',{name:'Research settings'}).click();await shot('research-settings');
await page.setViewportSize({width:390,height:844});await home();await shot('mobile-research');await page.getByRole('button',{name:/Compare operating margins/}).click();await page.getByRole('tab',{name:'Answer',exact:true}).waitFor();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await shot('mobile-comparison');
if(errors.length)throw new Error(errors.join('\n'));
await browser.close();console.log('16 screenshots captured from the running local app.');
