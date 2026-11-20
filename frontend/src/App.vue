<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import * as THREE from 'three'

echarts.use([LineChart, GridComponent, MarkLineComponent, TooltipComponent, CanvasRenderer])

type Alarm = { id: string; source_type: string; severity: string; status: string; first_triggered_at: string; trigger_condition: Record<string, unknown>; suggested_action: string }
type Batch = { id: string; batch_code: string; source?: string; status: string; arrived_at?: string }
type Device = { id: string; device_code: string; name: string; twin_object_key?: string; status: string; alarm: boolean }
type Trace = { batch: Batch; tasks: Array<Record<string, unknown>>; samples: Array<Record<string, unknown>>; events: Array<Record<string, unknown>>; alarms: Alarm[]; missing_links: string[] }
type Overview = { devices: Device[]; current_batch: Batch | null; samples: Array<{ sample_code: string; location?: string; status: string }>; open_alarms: number }

const token = ref(localStorage.getItem('coal-token') ?? '')
const username = ref(localStorage.getItem('coal-user') ?? '')
const roleNames = ref<string[]>([])
const loginName = ref('admin')
const password = ref('')
const page = ref('overview')
const busy = ref(false)
const message = ref('')
const batches = ref<Batch[]>([])
const alarms = ref<Alarm[]>([])
const devices = ref<Device[]>([])
const overview = ref<Overview | null>(null)
const trace = ref<Trace | null>(null)
const auditRows = ref<Array<Record<string, unknown>>>([])
const selectedBatch = ref('')
const batchCode = ref('')
const batchSource = ref('')
const deviceCode = ref('')
const deviceName = ref('')
const twinKey = ref('')
const pointCode = ref('')
const pointDeviceId = ref('')
const pointMetric = ref('')
const pointUnit = ref('')
const canOperate = computed(() => roleNames.value.some(role => ['administrator', 'operator'].includes(role)))
const isAdmin = computed(() => roleNames.value.includes('administrator'))
const navigation = computed(() => [
  { id: 'overview', label: '运行总览' }, { id: 'batches', label: '批次任务' },
  { id: 'alarms', label: '告警中心', count: alarms.value.filter(alarm => alarm.status !== 'closed').length },
  { id: 'trace', label: '全链路追溯' }, { id: 'twin', label: '数字孪生' },
  ...(isAdmin.value ? [{ id: 'devices', label: '设备台账' }, { id: 'audit', label: '审计日志' }] : []),
])

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(token.value ? { Authorization: 'Bearer ' + token.value } : {}), ...options.headers },
  })
  if (response.status === 401) { logout(); throw new Error('登录状态已失效，请重新登录') }
  if (!response.ok) {
    const result = await response.json().catch(() => ({}))
    throw new Error(result.message ?? '请求失败 (' + response.status + ')')
  }
  return response.json() as Promise<T>
}

async function login() {
  busy.value = true
  message.value = ''
  try {
    const body = new URLSearchParams({ username: loginName.value, password: password.value })
    const response = await fetch('/api/v1/auth/login', { method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body })
    const result = await response.json()
    if (!response.ok) throw new Error(result.message ?? '用户名或密码错误')
    token.value = result.access_token
    username.value = result.username
    localStorage.setItem('coal-token', token.value)
    localStorage.setItem('coal-user', username.value)
    await loadData()
    connectUpdates()
  } catch (reason) {
    message.value = reason instanceof Error ? reason.message : '登录失败'
  } finally { busy.value = false }
}

function logout() {
  token.value = ''
  username.value = ''
  roleNames.value = []
  localStorage.removeItem('coal-token')
  localStorage.removeItem('coal-user')
  if (socket) socket.close()
}

async function loadData() {
  if (!token.value) return
  const [batchResult, alarmResult, stateResult, me] = await Promise.all([
    api<Batch[]>('/api/v1/batches?limit=50'),
    api<{ items: Alarm[] }>('/api/v1/alarms?limit=50'),
    api<Overview>('/api/v1/twin/state'),
    api<{ roles: string[] }>('/api/v1/auth/me'),
  ])
  batches.value = batchResult
  alarms.value = alarmResult.items
  overview.value = stateResult
  devices.value = stateResult.devices
  roleNames.value = me.roles
  if (!selectedBatch.value && batchResult.length) selectedBatch.value = batchResult[0].id
}

async function refresh() {
  busy.value = true
  try {
    await loadData()
    if (page.value === 'trace') await loadTrace()
    message.value = ''
  } catch (reason) { message.value = reason instanceof Error ? reason.message : '刷新失败' }
  finally { busy.value = false }
}

async function createBatch() {
  try {
    const batch = await api<Batch>('/api/v1/batches', { method: 'POST',
      body: JSON.stringify({ batch_code: batchCode.value, source: batchSource.value }) })
    batchCode.value = ''
    batchSource.value = ''
    selectedBatch.value = batch.id
    message.value = '批次 ' + batch.batch_code + ' 已创建'
    await refresh()
  } catch (reason) { message.value = reason instanceof Error ? reason.message : '创建失败' }
}

async function createTask(batch: Batch) {
  try {
    await api('/api/v1/sampling-tasks', {
      method: 'POST',
      body: JSON.stringify({
        batch_id: batch.id,
        task_code: 'T-' + Date.now(),
        strategy_version: 'demo-v1',
      }),
    })
    selectedBatch.value = batch.id
    message.value = '已为批次 ' + batch.batch_code + ' 创建采样任务'
    await refresh()
  } catch (reason) {
    message.value = reason instanceof Error ? reason.message : '任务创建失败'
  }
}

async function advanceTask(task: Record<string, unknown>) {
  const next = task.status === 'planned' ? 'running' : task.status === 'running' ? 'completed' : null
  if (!next) return
  try {
    await api('/api/v1/sampling-tasks/' + task.id + '/status', {
      method: 'PATCH', body: JSON.stringify({ status: next }),
    })
    await refresh()
  } catch (reason) {
    message.value = reason instanceof Error ? reason.message : '任务状态更新失败'
  }
}

async function advanceSample(sample: Record<string, unknown>) {
  const transitions: Record<string, string> = { created: 'collected', collected: 'prepared', prepared: 'sealed' }
  const next = transitions[String(sample.status)]
  if (!next) return
  try {
    await api('/api/v1/samples/' + sample.id + '/status', {
      method: 'PATCH', body: JSON.stringify({ status: next }),
    })
    await refresh()
  } catch (reason) {
    message.value = reason instanceof Error ? reason.message : '样品状态更新失败'
  }
}

async function createDevice() {
  try {
    await api('/api/v1/master-data/devices', {
      method: 'POST',
      body: JSON.stringify({
        device_code: deviceCode.value,
        name: deviceName.value,
        device_type: 'sampler',
        twin_object_key: twinKey.value || null,
      }),
    })
    deviceCode.value = ''
    deviceName.value = ''
    twinKey.value = ''
    await refresh()
  } catch (reason) {
    message.value = reason instanceof Error ? reason.message : '设备登记失败'
  }
}

async function createSensorPoint() {
  try {
    await api('/api/v1/master-data/sensor-points', {
      method: 'POST',
      body: JSON.stringify({
        point_code: pointCode.value,
        device_id: pointDeviceId.value,
        metric: pointMetric.value,
        unit: pointUnit.value,
      }),
    })
    pointCode.value = ''
    pointMetric.value = ''
    pointUnit.value = ''
    message.value = '测点已登记'
  } catch (reason) {
    message.value = reason instanceof Error ? reason.message : '测点登记失败'
  }
}

async function loadTrace() {
  if (!selectedBatch.value) { trace.value = null; return }
  trace.value = await api<Trace>('/api/v1/batches/' + selectedBatch.value + '/trace')
}

async function loadAudit() {
  auditRows.value = (await api<{ items: Array<Record<string, unknown>> }>('/api/v1/audit/logs?limit=100')).items
}

async function alarmAction(alarm: Alarm, action: 'confirm' | 'close') {
  try {
    await api('/api/v1/alarms/' + alarm.id + '/actions', { method: 'POST', body: JSON.stringify({ action }) })
    await refresh()
  } catch (reason) { message.value = reason instanceof Error ? reason.message : '处置失败' }
}

async function exportCsv() {
  const query = selectedBatch.value ? '?batch_id=' + selectedBatch.value : ''
  const response = await fetch('/api/v1/reports/trace.csv' + query, {
    headers: { Authorization: 'Bearer ' + token.value },
  })
  if (!response.ok) { message.value = '导出失败'; return }
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = 'trace-report.csv'
  link.click()
  URL.revokeObjectURL(url)
}

let socket: WebSocket | null = null
let reconnectTimer = 0
function connectUpdates() {
  if (!token.value) return
  socket?.close()
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:'
  socket = new WebSocket(scheme + '//' + location.host + '/api/v1/twin/updates?token=' + encodeURIComponent(token.value))
  socket.onmessage = () => void refresh()
  socket.onclose = () => { if (token.value) reconnectTimer = window.setTimeout(connectUpdates, 2500) }
}

const chartElement = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
async function drawTrend() {
  if (!chartElement.value) return
  const points = await api<Array<{ id: string; point_code: string }>>('/api/v1/master-data/sensor-points?limit=1')
  if (!points[0]) return
  const trend = await api<{ items: Array<{ time: string; value: number }>; point_code: string; unit: string; threshold_max: number | null }>(
    '/api/v1/twin/trends?point_id=' + points[0].id)
  chart ??= echarts.init(chartElement.value)
  chart.setOption({
    animation: false, grid: { left: 42, right: 18, top: 16, bottom: 28 }, tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: trend.items.map(item => new Date(item.time).toLocaleTimeString()), axisLabel: { color: '#72807a' }, axisLine: { lineStyle: { color: '#dce5df' } } },
    yAxis: { type: 'value', name: trend.unit, splitLine: { lineStyle: { color: '#edf1ee' } } },
    series: [{ name: trend.point_code, type: 'line', smooth: 0.22, showSymbol: false, data: trend.items.map(item => item.value), lineStyle: { color: '#18866d', width: 2 }, areaStyle: { color: 'rgba(24, 134, 109, .08)' }, markLine: trend.threshold_max == null ? undefined : { symbol: 'none', lineStyle: { color: '#d19a36', type: 'dashed' }, data: [{ yAxis: trend.threshold_max }] } }],
  })
}

const sceneElement = ref<HTMLDivElement | null>(null)
let renderer: THREE.WebGLRenderer | null = null
let observer: ResizeObserver | null = null
function disposeScene() {
  observer?.disconnect()
  renderer?.dispose()
  renderer?.domElement.remove()
  renderer = null
}
function drawScene() {
  if (!sceneElement.value || renderer) return
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
    renderer.setSize(sceneElement.value.clientWidth, sceneElement.value.clientHeight)
    renderer.setClearColor(0xffffff, 0)
    sceneElement.value.append(renderer.domElement)
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(34, sceneElement.value.clientWidth / sceneElement.value.clientHeight, 0.1, 100)
    camera.position.set(7, 7, 10)
    camera.lookAt(0, 0, 0)
    scene.add(new THREE.HemisphereLight(0xffffff, 0x6d7771, 2.2))
    const light = new THREE.DirectionalLight(0xffffff, 2)
    light.position.set(4, 8, 5)
    scene.add(light)
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(14, 8), new THREE.MeshStandardMaterial({ color: 0xe9efeb, roughness: 1 }))
    floor.rotation.x = -Math.PI / 2
    floor.position.y = -0.55
    scene.add(floor)
    const nodes = [
      { key: 'sampling_head', label: '采样头', x: -4 },
      { key: 'feeder', label: '给料输送', x: -2 },
      { key: 'crusher', label: '破碎单元', x: 0 },
      { key: 'splitter', label: '缩分单元', x: 2 },
      { key: 'collector', label: '集样单元', x: 4 },
    ]
    nodes.forEach(({ key, label, x }) => {
      const device = devices.value.find(item => item.twin_object_key === key)
      const material = new THREE.MeshStandardMaterial({ color: device?.alarm ? 0xc45145 : device?.status === 'running' ? 0x1b9470 : 0x74827b, roughness: 0.6 })
      const machine = new THREE.Group()
      machine.add(new THREE.Mesh(new THREE.BoxGeometry(1.15, 0.72, 0.9), material))
      const cap = new THREE.Mesh(new THREE.BoxGeometry(0.65, 0.32, 0.6), new THREE.MeshStandardMaterial({ color: 0xd5ddd8, roughness: 0.8 }))
      cap.position.set(0.12, 0.5, 0)
      machine.add(cap)
      machine.position.x = x
      scene.add(machine)
      const canvas = document.createElement('canvas')
      canvas.width = 256
      canvas.height = 64
      const context = canvas.getContext('2d')
      if (context) {
        context.fillStyle = '#24302c'
        context.font = '24px Microsoft YaHei'
        context.textAlign = 'center'
        context.fillText(label, 128, 40)
        const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true }))
        sprite.position.set(x, 1.25, 0)
        sprite.scale.set(1.8, 0.45, 1)
        scene.add(sprite)
      }
    })
    for (let x = -3; x < 4; x += 2) {
      const belt = new THREE.Mesh(new THREE.BoxGeometry(0.95, 0.08, 0.5), new THREE.MeshStandardMaterial({ color: 0x477a70 }))
      belt.position.set(x, -0.28, 0)
      scene.add(belt)
    }
    renderer.render(scene, camera)
    observer = new ResizeObserver(() => {
      if (!sceneElement.value || !renderer) return
      camera.aspect = sceneElement.value.clientWidth / sceneElement.value.clientHeight
      camera.updateProjectionMatrix()
      renderer.setSize(sceneElement.value.clientWidth, sceneElement.value.clientHeight)
      renderer.render(scene, camera)
    })
    observer.observe(sceneElement.value)
  } catch { disposeScene() }
}

watch(page, async selected => {
  if (selected === 'trace') {
    try { await loadTrace() } catch (reason) { message.value = reason instanceof Error ? reason.message : '追溯查询失败' }
  }
  if (selected === 'overview') {
    await new Promise(resolve => requestAnimationFrame(resolve))
    void drawTrend().catch(() => undefined)
  }
  if (selected === 'twin') {
    await new Promise(resolve => requestAnimationFrame(resolve))
    drawScene()
  } else disposeScene()
  if (selected === 'audit') {
    try { await loadAudit() } catch (reason) { message.value = reason instanceof Error ? reason.message : '审计日志查询失败' }
  }
})
watch(selectedBatch, () => { if (page.value === 'trace') void loadTrace().catch(() => undefined) })
watch(devices, () => {
  if (page.value === 'twin') { disposeScene(); requestAnimationFrame(drawScene) }
})
onMounted(async () => {
  if (!token.value) return
  try { await loadData(); connectUpdates() }
  catch (reason) { message.value = reason instanceof Error ? reason.message : '无法载入数据' }
})
onBeforeUnmount(() => {
  socket?.close()
  clearTimeout(reconnectTimer)
  chart?.dispose()
  disposeScene()
})
</script>

<template>
  <main v-if="!token" class="login-screen"><form class="login-panel" @submit.prevent="login">
    <div class="brand-lockup"><span class="brand-mark">CS</span><span>输煤取样系统</span></div>
    <p class="eyebrow">DIGITAL TWIN CONSOLE</p><h1>登录系统</h1>
    <label>用户名<input v-model="loginName" autocomplete="username" required /></label>
    <label>密码<input v-model="password" type="password" autocomplete="current-password" required /></label>
    <p v-if="message" class="feedback error" role="alert">{{ message }}</p>
    <button class="primary-button" :disabled="busy" type="submit">{{ busy ? '登录中' : '登录' }}</button>
  </form></main>
  <div v-else class="app-shell">
    <aside class="sidebar"><a class="brand-lockup" href="/" aria-label="返回运行总览"><span class="brand-mark">CS</span><span>输煤取样</span></a>
      <p class="nav-caption">工作台</p><nav aria-label="主导航">
        <button v-for="item in navigation" :key="item.id" class="nav-item" :class="{ active: page === item.id }" @click="page = item.id"><span class="nav-indicator"></span><span>{{ item.label }}</span><span v-if="item.count" class="nav-count">{{ item.count }}</span></button>
      </nav><div class="sidebar-bottom"><span class="live-mark"><i></i>模拟数据</span><span class="account-name">{{ username }}</span><button class="logout-button" @click="logout">退出</button></div>
    </aside>
    <section class="content"><header class="page-bar"><div class="breadcrumbs"><span>输煤取样</span><span>/</span><strong>{{ navigation.find(item => item.id === page)?.label }}</strong></div><div class="page-actions"><span class="role-label">{{ roleNames.join(' / ') }}</span><button class="icon-button" aria-label="刷新数据" title="刷新数据" @click="refresh">↻</button></div></header>
      <div v-if="message" class="feedback" role="status"><span>{{ message }}</span><button aria-label="关闭提示" @click="message = ''">×</button></div>
      <main v-if="page === 'overview'" class="page-content"><div class="title-row"><div><p class="eyebrow">SYSTEM OVERVIEW</p><h1>运行总览</h1></div><span class="updated-at">服务端实时聚合</span></div>
        <div class="metric-strip"><div><span>当前批次</span><strong>{{ overview?.current_batch?.batch_code ?? '暂无批次' }}</strong><small>{{ overview?.current_batch ? '正在跟踪' : '等待建档' }}</small></div><div><span>在册设备</span><strong>{{ devices.length.toString().padStart(2, '0') }}</strong><small>已完成映射 {{ devices.filter(device => device.twin_object_key).length }}</small></div><div><span>未关闭告警</span><strong :class="{ danger: (overview?.open_alarms ?? 0) > 0 }">{{ overview?.open_alarms ?? 0 }}</strong><small>需要人工复核</small></div><div><span>关联样品</span><strong>{{ overview?.samples.length ?? 0 }}</strong><small>当前批次样品</small></div></div>
        <div class="section-title"><h2>测点趋势</h2><span>最近采集值</span></div><div v-if="devices.length" ref="chartElement" class="trend-chart"></div><div v-else class="empty-state">登记设备并接入测点数据后显示趋势</div>
        <div class="section-title"><h2>设备状态</h2><button class="text-button" @click="page = 'devices'">查看台账 →</button></div><div class="data-table"><div class="table-head"><span>设备编号</span><span>名称</span><span>三维映射</span><span>状态</span><span>告警</span></div><div v-for="device in devices.slice(0, 6)" :key="device.id" class="table-row"><span class="mono">{{ device.device_code }}</span><span>{{ device.name }}</span><span>{{ device.twin_object_key ?? '未映射' }}</span><span class="state"><i :class="device.status"></i>{{ device.status === 'running' ? '运行' : '待机' }}</span><span :class="device.alarm ? 'tag tag-danger' : 'muted'">{{ device.alarm ? '需核查' : '正常' }}</span></div><div v-if="!devices.length" class="empty-state compact">暂无设备记录</div></div>
      </main>
      <main v-else-if="page === 'batches'" class="page-content"><div class="title-row"><div><p class="eyebrow">BATCH REGISTER</p><h1>批次任务</h1></div></div><form v-if="canOperate" class="inline-form" @submit.prevent="createBatch"><label>批次编号<input v-model="batchCode" required maxlength="80" placeholder="例如 B-20261120-01" /></label><label>来煤来源<input v-model="batchSource" maxlength="160" placeholder="来源煤场或矿点" /></label><button class="primary-button" type="submit">＋ 新建批次</button></form>
        <div class="data-table"><div class="table-head batch-head"><span>批次编号</span><span>来源</span><span>状态</span><span>到达时间</span><span>操作</span></div><div v-for="batch in batches" :key="batch.id" class="table-row batch-row"><span class="mono">{{ batch.batch_code }}</span><span>{{ batch.source ?? '—' }}</span><span>{{ batch.status }}</span><span>{{ batch.arrived_at ? new Date(batch.arrived_at).toLocaleString() : '—' }}</span><span class="row-actions"><button v-if="canOperate" class="text-button" @click="createTask(batch)">＋ 任务</button><button class="text-button" @click="selectedBatch = batch.id; page = 'trace'">追溯</button></span></div><div v-if="!batches.length" class="empty-state compact">暂无来煤批次</div></div>
      </main>
      <main v-else-if="page === 'alarms'" class="page-content"><div class="title-row"><div><p class="eyebrow">ALARM CENTER</p><h1>告警中心</h1></div><span class="updated-at">{{ alarms.filter(alarm => alarm.status !== 'closed').length }} 条待处置</span></div>
        <div class="alarm-list"><article v-for="alarm in alarms" :key="alarm.id" class="alarm-row"><span class="severity-mark" :class="alarm.severity"></span><div class="alarm-main"><div class="alarm-heading"><strong>{{ String(alarm.trigger_condition.point_code ?? alarm.source_type) }}</strong><span class="tag" :class="alarm.severity === 'critical' ? 'tag-danger' : 'tag-warn'">{{ alarm.severity }}</span><span class="tag tag-neutral">{{ alarm.status }}</span></div><p>{{ JSON.stringify(alarm.trigger_condition) }}</p><small>{{ new Date(alarm.first_triggered_at).toLocaleString() }} · {{ alarm.suggested_action }}</small></div><div v-if="canOperate && alarm.status !== 'closed'" class="alarm-actions"><button v-if="alarm.status === 'open'" class="small-button" @click="alarmAction(alarm, 'confirm')">确认</button><button class="small-button" @click="alarmAction(alarm, 'close')">关闭</button></div></article><div v-if="!alarms.length" class="empty-state">当前没有告警记录</div></div>
      </main>
      <main v-else-if="page === 'trace'" class="page-content"><div class="title-row"><div><p class="eyebrow">TRACEABILITY</p><h1>全链路追溯</h1></div><button class="secondary-button" @click="exportCsv">⇩ 导出 CSV</button></div><div class="trace-toolbar"><label>选择来煤批次<select v-model="selectedBatch"><option value="">选择批次</option><option v-for="batch in batches" :key="batch.id" :value="batch.id">{{ batch.batch_code }}</option></select></label><button class="secondary-button" @click="loadTrace">查询</button></div>
        <template v-if="trace"><div class="trace-summary"><span><small>批次</small><strong>{{ trace.batch.batch_code }}</strong></span><span><small>任务</small><strong>{{ trace.tasks.length }}</strong></span><span><small>样品</small><strong>{{ trace.samples.length }}</strong></span><span><small>事件</small><strong>{{ trace.events.length }}</strong></span></div><div v-if="trace.missing_links.length" class="missing-links"><strong>流程缺口</strong><span v-for="item in trace.missing_links" :key="item">{{ item }}</span></div>
          <div class="section-title"><h2>采样任务</h2></div><div class="data-table"><div class="table-head task-head"><span>任务编号</span><span>状态</span><span>策略版本</span><span>计划时间</span><span></span></div><div v-for="task in trace.tasks" :key="String(task.id)" class="table-row task-row"><span class="mono">{{ task.task_code }}</span><span>{{ task.status }}</span><span>{{ task.strategy_version ?? '—' }}</span><span>{{ task.planned_at ? new Date(String(task.planned_at)).toLocaleString() : '—' }}</span><button v-if="canOperate && task.status !== 'completed' && task.status !== 'cancelled'" class="text-button" @click="advanceTask(task)">推进状态 →</button></div><div v-if="canOperate" class="task-create"><button class="secondary-button" @click="createTask(trace.batch)">＋ 新建采样任务</button><button v-if="trace.tasks.length" class="secondary-button" @click="api('/api/v1/samples', { method: 'POST', body: JSON.stringify({ task_id: trace.tasks[trace.tasks.length - 1].id, sample_code: 'S-' + Date.now(), sample_type: '原煤样', current_location: '集样器' }) }).then(loadTrace).catch(reason => message = reason.message)">＋ 添加样品</button></div></div>
          <div class="section-title"><h2>事件时间线</h2><span>按发生时间排序</span></div><ol class="timeline"><li v-for="event in trace.events" :key="String(event.event_id)"><i></i><time>{{ new Date(String(event.occurred_at)).toLocaleString() }}</time><strong>{{ event.event_type }}</strong><span>{{ JSON.stringify(event.payload) }}</span></li></ol>
          <div class="section-title"><h2>样品流转</h2></div><div class="data-table"><div class="table-head sample-head"><span>样品编号</span><span>类型</span><span>位置</span><span>状态</span><span></span></div><div v-for="sample in trace.samples" :key="String(sample.id)" class="table-row sample-row"><span class="mono">{{ sample.sample_code }}</span><span>{{ sample.sample_type }}</span><span>{{ sample.current_location ?? '—' }}</span><span>{{ sample.status }}</span><button v-if="canOperate && sample.status !== 'sealed'" class="text-button" @click="advanceSample(sample)">推进流转 →</button></div></div></template><div v-else class="empty-state">选择批次查看追溯链</div>
      </main>
      <main v-else-if="page === 'twin'" class="page-content"><div class="title-row"><div><p class="eyebrow">TWIN SCENE</p><h1>数字孪生</h1></div><span class="updated-at">只读设备状态 · {{ overview?.current_batch?.batch_code ?? '暂无活动批次' }}</span></div><div class="twin-layout"><div class="scene-wrap"><div ref="sceneElement" class="scene-canvas"></div><div v-if="!devices.length" class="flow-view"><div v-for="item in ['采样头','给料输送','破碎单元','缩分单元','集样单元']" :key="item"><i></i><strong>{{ item }}</strong></div></div><div class="scene-legend"><span><i class="ok"></i>正常/待机</span><span><i class="running"></i>运行</span><span><i class="alarm"></i>告警</span></div></div><aside class="scene-details"><div class="section-title"><h2>设备映射</h2><span>{{ devices.length }} 台</span></div><div v-for="device in devices" :key="device.id" class="device-line"><i class="device-light" :class="{ alarm: device.alarm, running: device.status === 'running' }"></i><span><strong>{{ device.name }}</strong><small>{{ device.twin_object_key ?? device.device_code }}</small></span><em>{{ device.alarm ? '告警' : device.status === 'running' ? '运行' : '待机' }}</em></div><div class="section-title sample-title"><h2>样品位置</h2></div><div v-for="sample in overview?.samples ?? []" :key="sample.sample_code" class="device-line"><span class="sample-icon">S</span><span><strong>{{ sample.sample_code }}</strong><small>{{ sample.status }}</small></span><em>{{ sample.location ?? '未登记' }}</em></div></aside></div>
      </main>
      <main v-else-if="page === 'devices'" class="page-content"><div class="title-row"><div><p class="eyebrow">MASTER DATA</p><h1>设备台账</h1></div></div>
        <form v-if="isAdmin" class="inline-form" @submit.prevent="createDevice"><label>设备编号<input v-model="deviceCode" required /></label><label>设备名称<input v-model="deviceName" required /></label><label>孪生映射键<input v-model="twinKey" placeholder="feeder / crusher" /></label><button class="primary-button">登记设备</button></form>
        <form v-if="isAdmin && devices.length" class="inline-form" @submit.prevent="createSensorPoint"><label>点位编号<input v-model="pointCode" required /></label><label>设备<select v-model="pointDeviceId" required><option value="" disabled>选择设备</option><option v-for="device in devices" :key="device.id" :value="device.id">{{ device.device_code }}</option></select></label><label>指标<input v-model="pointMetric" required /></label><label>单位<input v-model="pointUnit" required /></label><button class="secondary-button">登记点位</button></form>
        <div class="data-table"><div class="table-head"><span>设备编号</span><span>名称</span><span>状态</span><span>孪生映射键</span></div><div v-for="device in devices" :key="device.id" class="table-row"><span class="mono">{{ device.device_code }}</span><span>{{ device.name }}</span><span>{{ device.status }}</span><span class="mono">{{ device.twin_object_key ?? '—' }}</span></div></div></main>
      <main v-else class="page-content"><div class="title-row"><div><p class="eyebrow">AUDIT TRAIL</p><h1>审计日志</h1></div></div>
        <div class="data-table"><div class="table-head audit-head"><span>时间</span><span>操作者</span><span>操作</span><span>目标</span><span>结果</span></div>
          <div v-for="row in auditRows" :key="String(row.id)" class="table-row audit-row"><span>{{ new Date(String(row.occurred_at)).toLocaleString() }}</span><span>{{ row.actor_id ?? '系统' }}</span><span>{{ row.action }}</span><span>{{ row.target_type }} {{ row.target_id ?? '' }}</span><span>{{ row.outcome }}</span></div>
          <div v-if="!auditRows.length" class="empty-state compact">暂无审计记录</div></div>
      </main>
    </section>
  </div>
</template>

