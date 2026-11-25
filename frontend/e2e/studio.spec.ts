import { expect, test, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

const root = process.env.MOMENTRIX_E2E_ROOT
const url = process.env.MOMENTRIX_E2E_URL
const video = process.env.MOMENTRIX_E2E_VIDEO
const liveAutomation = process.env.MOMENTRIX_E2E_LIVE_AUTOMATION === '1'
const preset = process.env.MOMENTRIX_E2E_PRESET || 'balanced'
const verifyTracking = process.env.MOMENTRIX_E2E_TRACKING === '1'
const verifyMetadata = process.env.MOMENTRIX_E2E_METADATA === '1'
const metadataClip = process.env.MOMENTRIX_E2E_METADATA_CLIP
test.use({channel:'msedge',headless:true,viewport:{width:1280,height:850}})
test.skip(!root||!url,'Set MOMENTRIX_E2E_ROOT and MOMENTRIX_E2E_URL to an isolated local studio.')
test.beforeEach(async ({page})=>{
  await page.goto(url!)
  await expect(page.getByRole('heading',{name:'Open your studio'})).toBeVisible()
  const key=(await readFile(join(root!,'data','studio.key'),'utf8')).trim()
  await page.getByLabel('Studio access key').fill(key)
  await page.getByRole('button',{name:'Open workspace'}).click()
  await expect(page.getByRole('heading',{name:'Studio dashboard'})).toBeVisible()
})
test('navigates database-backed desktop and mobile views',async({page})=>{
  if (liveAutomation) test.setTimeout(55_000)
  const errors:string[]=[]
  page.on('pageerror',error=>errors.push(error.message))
  for (const [link,heading] of [['My Projects','My projects'],['Clip Library','Clip library'],['Campaigns','Campaigns'],['Automation','Automation'],['Analytics','Workspace analytics'],['Settings','Workspace settings']]){
    await page.getByRole('navigation').getByRole('link',{name:link,exact:true}).click()
    await expect(page.getByRole('heading',{name:heading,exact:true})).toBeVisible()
    if (liveAutomation && link === 'Automation') {
      const result = page.waitForResponse(r => r.url().endsWith('/system/test-n8n'), {timeout: 15_000})
      await page.getByRole('button',{name:'Test n8n connection'}).click()
      expect(await (await result).json()).toMatchObject({verified: true})
      await expect(page.getByText('The authenticated production webhook reached FastAPI.')).toBeVisible()
    }
  }
  await page.setViewportSize({width:390,height:844})
  await page.getByRole('button',{name:'Open menu'}).click()
  await page.getByRole('navigation').getByRole('link',{name:'New Project',exact:true}).click()
  await expect(page.getByRole('heading',{name:'New project',exact:true})).toBeVisible()
  await expect(page.locator('body')).toHaveJSProperty('scrollWidth',390)
  expect(errors).toEqual([])
})
test('uploads an authorized sample and persists the automation handoff',async({page})=>{
  test.skip(!video,'Set MOMENTRIX_E2E_VIDEO to a sample you have authorization to process.')
  test.setTimeout(verifyMetadata ? 600_000 : liveAutomation ? 420_000 : 100_000)
  await page.getByRole('navigation').getByRole('link',{name:'New Project',exact:true}).click()
  await page.getByLabel('Select source video').setInputFiles(video!)
  const name='Website integration '+Date.now()
  await page.getByLabel('Project name').fill(name)
  await page.getByLabel('I have permission').check()
  const next=page.getByRole('button',{name:'Continue'})
  await next.click()
  await page.getByLabel('Content type').selectOption('educational')
  await next.click()
  await next.click()
  await page.getByLabel('Desired clip count').fill('1')
  await expect(page.getByLabel('Processing preset')).toHaveValue('balanced')
  await page.getByLabel('Processing preset').selectOption(preset)
  await next.click()
  await next.click()
  const receipt=page.waitForResponse(r=>r.url().endsWith('/generate')&&r.request().method()==='POST')
  await page.getByRole('button',{name:'Start automation'}).click()
  const response=await receipt
  expect(response.status()).toBe(202)
  const run=await response.json()
  expect(run.id).toBeTruthy()
  expect(run.processing_preset).toBe(preset)
  await expect(page.getByRole('heading',{name})).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading',{name})).toBeVisible()
  await expect(page.getByText('Run '+run.id.slice(0,10))).toBeVisible()
  if(run.status==='dispatch_failed')await expect(page.getByRole('button',{name:'Retry run'})).toBeVisible()
  console.log('Website generation receipt',JSON.stringify({project:run.project_id,run:run.id,status:run.status}))
  if (!liveAutomation) return

  let executionId: string | undefined
  await expect.poll(async () => {
    const response = await page.request.get('/api/v2/runs/'+run.id)
    const current = await response.json()
    executionId = current.execution_id
    if (['failed','dispatch_failed','cancelled','completed','completed_with_warnings'].includes(current.status)) {
      throw new Error(current.error || JSON.stringify(current.warnings))
    }
    return current.status
  }, {timeout: 280_000, intervals: [2_000, 4_000]}).toBe('awaiting_review')
  expect(executionId).toBeTruthy()
  console.log('n8n generation execution', executionId)
  const clipList = await page.request.get('/api/v2/projects/'+run.project_id+'/clips')
  const [clip] = await clipList.json()
  await page.getByRole('link').filter({hasText: clip.title}).click({timeout: 20_000})
  if (verifyTracking) {
    const follow = page.getByRole('option',{name:'Follow tracked face'})
    await expect(follow).toBeEnabled({timeout: 20_000})
    await page.getByLabel('Vertical layout').selectOption('track')
    await page.getByLabel('Caption style').selectOption('karaoke')
    const save = page.waitForResponse(r=>r.request().method()==='PATCH' && r.url().endsWith('/clips/'+clip.id))
    await page.getByRole('button',{name:'Save draft'}).click()
    expect((await save).ok()).toBe(true)
    await expect(page.getByText('Revision 2',{exact:false})).toBeVisible()
    await page.getByRole('button',{name:'Render preview'}).click()
    await expect.poll(async () => {
      const response = await page.request.get('/api/v2/clips/'+clip.id)
      return (await response.json()).rendered_layout
    },{timeout:60_000}).toBe('track')
    await page.getByRole('button',{name:'Rendered preview',exact:true}).click()
    await expect(page.getByText('Server-rendered preview of the saved revision.')).toBeVisible()
  }
  if (verifyMetadata) await regenerateMetadata(page, clip.id)
  await approveAndDownload(page, clip.id)
})

async function regenerateMetadata(page: Page, clipId: string) {
  await page.getByText('Publishing metadata',{exact:true}).click()
  const clipPath = '/api/v2/clips/' + clipId
  const metadataPath = clipPath + '/metadata/suggestion'
  const request = page.waitForResponse(r=>r.request().method()==='POST' && r.url().endsWith(metadataPath))
  await page.getByRole('button',{name:'Regenerate metadata'}).click()
  expect((await request).status()).toBe(202)
  await expect.poll(async () => {
    const response = await page.request.get(metadataPath)
    const task = await response.json()
    if (task?.status === 'failed') throw new Error(task.error)
    return task?.status
  },{timeout: 210_000,intervals:[2000,4000]}).toBe('completed')
  await page.getByRole('button',{name:'Use suggestion'}).click()
  const suggestedTitle = await page.getByLabel('YouTube Shorts title').inputValue()
  expect(suggestedTitle.trim()).not.toBe('')
  const revisedTitle = 'Local QA: ' + suggestedTitle.slice(0,85)
  await page.getByLabel('YouTube Shorts title').fill(revisedTitle)
  await page.getByRole('button',{name:'Save draft'}).click()
  await expect(page.getByRole('heading',{name:revisedTitle})).toBeVisible()
  await page.getByRole('button',{name:'Render preview'}).click()
  await expect.poll(async () => {
    const response = await page.request.get(clipPath)
    return Boolean((await response.json()).rendered_preview)
  },{timeout:70_000}).toBe(true)
}

async function approveAndDownload(page: Page, clipId: string) {
  await expect(page.getByRole('button',{name:'Export final'})).toBeDisabled()
  expect((await page.request.get('/api/v2/clips/'+clipId+'/download')).status()).toBe(409)
  await page.getByRole('button',{name:'Approve',exact:true}).click()
  const exportReceipt = page.waitForResponse(r=>r.url().endsWith('/render') && r.request().method()==='POST')
  await page.getByRole('button',{name:'Export final'}).click()
  const exportResponse = await exportReceipt
  expect(exportResponse.status()).toBe(202)
  const task = await exportResponse.json()
  console.log('Website export receipt',JSON.stringify({clip:clipId,task:task.id}))
  await expect(page.getByRole('link',{name:'Download final MP4'})).toBeVisible({timeout: 100_000})
  const mp4 = await page.request.get('/api/v2/clips/'+clipId+'/download',{headers:{Range:'bytes=0-31'}})
  expect(mp4.status()).toBe(206)
}

test('regenerates publishing metadata for a saved authorized sample', async ({page}) => {
  test.skip(!metadataClip,'Set MOMENTRIX_E2E_METADATA_CLIP to an authorized test clip ID.')
  test.setTimeout(380_000)
  await page.goto(url! + '#/editor/' + metadataClip)
  await regenerateMetadata(page, metadataClip!)
  await approveAndDownload(page, metadataClip!)
})

