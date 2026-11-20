import { expect, test } from '@playwright/test'

test('login, create a batch, simulate an alarm, acknowledge, trace, and export', async ({ page, request }) => {
  const username = process.env.E2E_ADMIN_USERNAME
  const password = process.env.E2E_ADMIN_PASSWORD
  if (!username || !password) {
    throw new Error('Set E2E_ADMIN_USERNAME and E2E_ADMIN_PASSWORD to a dedicated test account.')
  }

  const suffix = Date.now().toString()
  const batchCode = 'PW-' + suffix
  await page.goto('/')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByRole('heading', { name: '运行总览' })).toBeVisible()

  await page.getByRole('button', { name: '批次任务' }).click()
  await page.getByLabel('批次编号').fill(batchCode)
  await page.getByLabel('来煤来源').fill('Playwright 模拟场景')
  await page.getByRole('button', { name: '＋ 新建批次' }).click()
  const batchRow = page.locator('.batch-row').filter({ hasText: batchCode })
  await expect(batchRow).toBeVisible()
  await batchRow.getByRole('button', { name: '＋ 任务' }).click()

  const token = await page.evaluate(() => localStorage.getItem('coal-token'))
  expect(token).toBeTruthy()
  const auth = { Authorization: 'Bearer ' + token }
  const batches = await request.get('/api/v1/batches?limit=100', { headers: auth }).then(response => response.json())
  const batch = batches.find((item: { batch_code: string }) => item.batch_code === batchCode)
  await expect.poll(async () => {
    const response = await request.get('/api/v1/batches/' + batch.id + '/trace', { headers: auth })
    return (await response.json()).tasks.length
  }).toBeGreaterThan(0)
  const trace = await request.get('/api/v1/batches/' + batch.id + '/trace', { headers: auth }).then(response => response.json())
  const task = trace.tasks[0]
  expect(task).toBeTruthy()

  const deviceResponse = await request.post('/api/v1/master-data/devices', {
    headers: auth,
    data: { device_code: 'PW-DEV-' + suffix, name: 'Playwright 振动监测', device_type: 'sampler' },
  })
  expect(deviceResponse.status()).toBe(201)
  const device = await deviceResponse.json()
  const pointResponse = await request.post('/api/v1/master-data/sensor-points', {
    headers: auth,
    data: { point_code: 'PW-POINT-' + suffix, device_id: device.id, metric: 'vibration', unit: 'mm/s', threshold_max: 10 },
  })
  expect(pointResponse.status()).toBe(201)
  const point = await pointResponse.json()
  const ruleResponse = await request.post('/api/v1/master-data/alarm-rules', {
    headers: auth,
    data: { rule_code: 'PW-RULE-' + suffix, name: 'Playwright 阈值规则', condition: { kind: 'threshold', point_code: point.point_code, threshold: 10 }, severity: 'critical' },
  })
  expect(ruleResponse.status()).toBe(201)

  const sampleResponse = await request.post('/api/v1/samples', {
    headers: auth,
    data: { sample_code: 'PW-SAMPLE-' + suffix, task_id: task.id, sample_type: '原煤样' },
  })
  expect(sampleResponse.status()).toBe(201)
  const telemetryResponse = await request.post('/api/v1/ingestion/telemetry', {
    headers: auth,
    data: { message_id: 'PW-MSG-' + suffix, device_id: device.id, point_id: point.id,
      event_time: new Date().toISOString(), value: 15, unit: 'mm/s', quality: 'good', source: 'playwright' },
  })
  expect(telemetryResponse.status()).toBe(200)

  await page.getByRole('button', { name: '告警中心' }).click()
  const alarmRow = page.locator('.alarm-row').filter({ hasText: point.point_code })
  await expect(alarmRow).toBeVisible()
  await alarmRow.getByRole('button', { name: '确认' }).click()
  await alarmRow.getByRole('button', { name: '关闭' }).click()
  await page.getByRole('button', { name: '全链路追溯' }).click()
  await page.getByLabel('选择来煤批次').selectOption(batch.id)
  await expect(page.getByText('PW-SAMPLE-' + suffix, { exact: true })).toBeVisible()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '⇩ 导出 CSV' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('trace-report.csv')
})
