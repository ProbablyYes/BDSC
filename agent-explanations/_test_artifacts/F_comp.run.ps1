[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue

. (Join-Path $PSScriptRoot '_helpers.ps1')

# ───── 场景参数 ─────
# 沿用测试 F 的 3D 打印儿童假肢项目，但把它挂到默认项目目录下，
# 这样前端账号 654321 / uid=0cfb36f4-... 打开"我的项目"就能直接看到。
$projectId = 'project-0cfb36f4-db33-4cab-b7cb-6258204c454e'
$convId    = '886072db-9c29-42d6-9484-bd3d80467c9b'   # 之前 7 轮项目教练对话的 conv_id
$sid       = $global:SID                              # 1120233400
$compType  = 'challenge_cup'                          # 挑战杯
$label     = 'F_comp'

function Invoke-JsonPost {
  param([string]$Url, [hashtable]$Body, [int]$TimeoutSec = 600)
  $json = $Body | ConvertTo-Json -Depth 8 -Compress
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
  $client = [System.Net.Http.HttpClient]::new()
  $client.Timeout = [System.TimeSpan]::FromSeconds($TimeoutSec)
  $content = [System.Net.Http.ByteArrayContent]::new($bytes)
  $content.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::new('application/json')
  $content.Headers.ContentType.CharSet = 'utf-8'
  $task = $client.PostAsync($Url, $content)
  $res = $task.Result
  $rb = $res.Content.ReadAsByteArrayAsync().Result
  $client.Dispose()
  $code = [int]$res.StatusCode
  $txt = [System.Text.Encoding]::UTF8.GetString($rb)
  return @{ code = $code; body = $txt }
}

function Invoke-JsonPatch {
  param([string]$Url, [hashtable]$Body, [int]$TimeoutSec = 120)
  $json = $Body | ConvertTo-Json -Depth 6 -Compress
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
  $req = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::new('PATCH'), $Url)
  $req.Content = [System.Net.Http.ByteArrayContent]::new($bytes)
  $req.Content.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::new('application/json')
  $req.Content.Headers.ContentType.CharSet = 'utf-8'
  $client = [System.Net.Http.HttpClient]::new()
  $client.Timeout = [System.TimeSpan]::FromSeconds($TimeoutSec)
  $task = $client.SendAsync($req)
  $res = $task.Result
  $rb = $res.Content.ReadAsByteArrayAsync().Result
  $client.Dispose()
  return @{ code = [int]$res.StatusCode; body = [System.Text.Encoding]::UTF8.GetString($rb) }
}

function Invoke-JsonGet {
  param([string]$Url, [int]$TimeoutSec = 60)
  $client = [System.Net.Http.HttpClient]::new()
  $client.Timeout = [System.TimeSpan]::FromSeconds($TimeoutSec)
  $res = $client.GetAsync($Url).Result
  $rb = $res.Content.ReadAsByteArrayAsync().Result
  $client.Dispose()
  return @{ code = [int]$res.StatusCode; body = [System.Text.Encoding]::UTF8.GetString($rb) }
}

# ═══════════════════════════════════════════════════════════
# Step 1: 基于已有 7 轮项目教练对话生成项目书（竞赛模式）
# ═══════════════════════════════════════════════════════════
Write-Host "`n========== [Step 1] 生成项目书（conv=$convId）=========="
$r = Invoke-JsonPost -Url "$($global:API)/api/business-plan/generate" -Body @{
  project_id           = $projectId
  student_id           = $sid
  conversation_id      = $convId
  mode                 = 'competition'
  allow_low_confidence = $true
}
Write-Host ("HTTP " + $r.code + "  len=" + $r.body.Length)
if ($r.code -ne 200) { Write-Host $r.body; exit 1 }
$planJson = $r.body | ConvertFrom-Json
$plan     = $planJson.plan
$planId   = $plan.plan_id
Write-Host "  plan_id           = $planId"
Write-Host "  maturity_tier     = $($planJson.readiness.maturity_tier)"
Write-Host "  section count     = $($plan.sections.Count)"
Write-Host "  coaching_mode     = $($plan.coaching_mode)"

# ═══════════════════════════════════════════════════════════
# Step 2: 切换计划书到"竞赛教练"模式
# ═══════════════════════════════════════════════════════════
Write-Host "`n========== [Step 2] 切换到竞赛教练模式 =========="
$r = Invoke-JsonPatch -Url "$($global:API)/api/business-plan/$planId/coaching-mode" -Body @{ mode = 'competition' }
Write-Host ("HTTP " + $r.code)
$planJson = $r.body | ConvertFrom-Json
Write-Host "  status         = $($planJson.status)"
Write-Host "  coaching_mode  = $($planJson.plan.coaching_mode)"
Write-Host "  competition_unlocked = $($planJson.plan.competition_unlocked)"
if ($planJson.status -eq 'locked') {
  Write-Host "  ⚠ 成熟度不足以解锁竞赛模式；脚本仍会继续后续步骤（但聊天抽取会被 skipped）"
}

# ═══════════════════════════════════════════════════════════
# Step 3: 竞赛冲刺模式多轮对话（每轮 assistant 回复触发 note_agenda_signal）
# ═══════════════════════════════════════════════════════════
Write-Host "`n========== [Step 3] 竞赛冲刺模式 4 轮对话 =========="
$competitionMessages = @(
  # 第 1 轮：竞赛维度定向追问（证据 / 量化）
  '现在我们要报挑战杯"揭榜挂帅"专项赛。请以评委视角看我这个项目：目前说的"单台成本 800 元以内、毛利 1100 元"只是我自己算的，评委一定会问证据。请告诉我：要让评审相信这三个数字，我必须在项目书里补上哪几类可验证的证据？每类证据应该具体到什么颗粒度？',

  # 第 2 轮：防守点 / 差异化
  '接着上一轮。赛道里已经有 e-NABLE、Limbitless Solutions 这样的开源假肢公益组织，也有国内的强脑科技、傲意信息在做智能假肢。如果评委反问："你比 e-NABLE 多了什么？比强脑便宜在哪？为什么这件事一定要由你们清华这个学生团队来做？"——我该怎么在项目书的"差异化与护城河"章节里写清楚三条可被防守的差异点？',

  # 第 3 轮：技术成熟度 / 量化
  '评委很在意 TRL（技术成熟度等级）。我现在的 MVP 是"AI 建模+打印打出了 3 例假肢"，这个 3 例能说明 TRL 几？我在项目书里应该怎么描述技术路线图，才能让评委明确看到"从实验验证到产品定型"每一阶段的量化指标（扫描误差、打印合格率、穿戴舒适度评分）？',

  # 第 4 轮：合规 / 公益+商业混合身份的赛道匹配
  '最后一轮。挑战杯的评委对"公益+商业"混合身份其实很敏感——他们怕两件事：一是"装公益骗补贴"，二是"公益拖死商业"。请帮我在项目书的"商业模式"和"社会价值"两章里设计一种清晰的写法，让评委一眼看出：我的商业部分（城市中产定制）和公益部分（山区基金会单）是"交叉补贴但财务独立核算"的，而不是左手倒右手。'
)

$i = 0
foreach ($msg in $competitionMessages) {
  $i++
  Write-Host ("=== $label turn $i (" + [DateTime]::Now.ToString('HH:mm:ss') + ") ===")
  $raw = Send-Turn -ProjectId $projectId -Message $msg -Mode 'competition' -CompetitionType $compType -ConvId $convId
  if ($null -eq $raw) { Write-Host "FAIL at turn $i"; exit 1 }
  Write-Host "  len=$($raw.Length)"
}

# 给后台议题抽取一点余量（LLM 调用是异步触发的）
Start-Sleep -Seconds 3

# ═══════════════════════════════════════════════════════════
# Step 4: 触发评委视角全书巡检
# ═══════════════════════════════════════════════════════════
Write-Host "`n========== [Step 4] 评委视角全书巡检 =========="
$r = Invoke-JsonPost -Url "$($global:API)/api/business-plan/$planId/agenda/review" -Body @{ force = $true } -TimeoutSec 900
Write-Host ("HTTP " + $r.code)
$rev = $r.body | ConvertFrom-Json
Write-Host "  status              = $($rev.status)"
Write-Host "  sections_total      = $($rev.sections_total)"
Write-Host "  sections_reviewed   = $($rev.sections_reviewed)"
Write-Host "  new_items           = $($rev.new_items.Count)"
Write-Host "  errors              = $($rev.errors.Count)"

# ═══════════════════════════════════════════════════════════
# Step 5: 拉取议题板现状
# ═══════════════════════════════════════════════════════════
Write-Host "`n========== [Step 5] 议题板列表 =========="
$r = Invoke-JsonGet -Url "$($global:API)/api/business-plan/$planId/agenda"
$a = $r.body | ConvertFrom-Json
Write-Host "  total  = $($a.items.Count)"
$byStatus = $a.items | Group-Object status | ForEach-Object { "$($_.Name)=$($_.Count)" }
Write-Host ("  by_status = " + ($byStatus -join ', '))
$bySrc = $a.items | Group-Object source_kind | ForEach-Object { "$($_.Name)=$($_.Count)" }
Write-Host ("  by_source = " + ($bySrc -join ', '))
$byPrio = $a.items | Group-Object priority | ForEach-Object { "$($_.Name)=$($_.Count)" }
Write-Host ("  by_priority = " + ($byPrio -join ', '))

# 挑 pending + priority=high/med 的议题批量应用
$target = $a.items | Where-Object { $_.status -eq 'pending' -and ($_.priority -eq 'high' -or $_.priority -eq 'med') }
if (-not $target -or $target.Count -eq 0) {
  $target = $a.items | Where-Object { $_.status -eq 'pending' } | Select-Object -First 8
}
$ids = @($target | ForEach-Object { $_.agenda_id })
Write-Host "  will_apply = $($ids.Count) items"
foreach ($it in $target | Select-Object -First 6) {
  $w = if ($it.weakness) { $it.weakness.Substring(0,[Math]::Min(60,$it.weakness.Length)) } else { '' }
  Write-Host ("    - [" + $it.priority + "/" + $it.source_kind + "] sec=" + $it.section_id + "  " + $w)
}

# ═══════════════════════════════════════════════════════════
# Step 6: 批量应用议题 → 生成真实 pending_revision（段落级 patch）
# ═══════════════════════════════════════════════════════════
if ($ids.Count -gt 0) {
  Write-Host "`n========== [Step 6] 应用议题（段落级 patch）=========="
  $r = Invoke-JsonPost -Url "$($global:API)/api/business-plan/$planId/agenda/apply" -Body @{ agenda_ids = $ids } -TimeoutSec 1200
  Write-Host ("HTTP " + $r.code)
  $applied = $r.body | ConvertFrom-Json
  Write-Host "  status              = $($applied.status)"
  $pRev = $applied.plan.pending_revisions
  Write-Host "  pending_revision数  = $($pRev.Count)"
  $i = 0
  foreach ($rev in $pRev | Select-Object -First 5) {
    $i++
    $before = if ($rev.before) { $rev.before.Substring(0,[Math]::Min(80,$rev.before.Length)) } else { '' }
    $after  = if ($rev.after)  { $rev.after.Substring(0,[Math]::Min(80,$rev.after.Length))   } else { '' }
    Write-Host ("  [" + $i + "] sec=" + $rev.section_id + "  kind=" + $rev.kind)
    Write-Host ("      before: " + $before + '...')
    Write-Host ("      after : " + $after  + '...')
  }
}

# ═══════════════════════════════════════════════════════════
# Step 7: 落档最终状态
# ═══════════════════════════════════════════════════════════
Write-Host "`n========== [Step 7] 落档最终 plan =========="
$r = Invoke-JsonGet -Url "$($global:API)/api/business-plan/$planId"
$finalPath = Join-Path $global:OUT_DIR 'F_comp.plan.final.json'
[System.IO.File]::WriteAllText($finalPath, $r.body, [System.Text.UTF8Encoding]::new($false))
Write-Host "  saved -> $finalPath"

Write-Host "`n===== Session $label 完成 ====="
Write-Host "project_id   = $projectId"
Write-Host "conv_id      = $convId"
Write-Host "plan_id      = $planId"
