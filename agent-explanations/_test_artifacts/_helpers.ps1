[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$global:API = 'http://127.0.0.1:8037'
$global:SID = '1120233400'
$global:UID = '0cfb36f4-db33-4cab-b7cb-6258204c454e'
$global:CONV_DIR = 'data\conversations'
$global:OUT_DIR  = 'agent-explanations\_test_artifacts'

function Send-Turn {
  param(
    [string]$ProjectId,
    [string]$Message,
    [string]$Mode = 'coursework',
    [string]$CompetitionType = '',
    [string]$ConvId = ''
  )
  $payload = @{
    project_id = $ProjectId
    student_id = $global:SID
    message    = $Message
    mode       = $Mode
    competition_type = $CompetitionType
  }
  if ($ConvId -ne '' -and $null -ne $ConvId) { $payload.conversation_id = $ConvId }
  $json = $payload | ConvertTo-Json -Depth 6 -Compress
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)

  Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue
  $client = [System.Net.Http.HttpClient]::new()
  $client.Timeout = [System.TimeSpan]::FromSeconds(600)
  $content = [System.Net.Http.ByteArrayContent]::new($bytes)
  $content.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::new('application/json')
  $content.Headers.ContentType.CharSet = 'utf-8'
  $task = $client.PostAsync("$($global:API)/api/dialogue/turn", $content)
  $result = $task.Result
  $rbytes = $result.Content.ReadAsByteArrayAsync().Result
  $client.Dispose()
  if ([int]$result.StatusCode -ne 200) {
    $txt = [System.Text.Encoding]::UTF8.GetString($rbytes)
    Write-Host "HTTP $([int]$result.StatusCode): $txt"
    return $null
  }
  $text = [System.Text.Encoding]::UTF8.GetString($rbytes)
  return $text  # raw UTF-8 JSON string
}

function Parse-ConvId {
  param([string]$Text)
  if (-not $Text) { return '' }
  $m = [System.Text.RegularExpressions.Regex]::Match($Text, '"conversation_id"\s*:\s*"([^"]+)"')
  if ($m.Success) { return $m.Groups[1].Value }
  return ''
}

function Save-Conversation {
  param([string]$ProjectId, [string]$Label)
  $src = Get-ChildItem (Join-Path $global:CONV_DIR $ProjectId) -Filter '*.json' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($null -eq $src) { return $null }
  $dst = Join-Path $global:OUT_DIR ("{0}.conversation.json" -f $Label)
  Copy-Item $src.FullName $dst -Force
  return $dst
}

function Invoke-SessionTurns {
  param(
    [string]$ProjectId,
    [string]$SessionLabel,
    [string]$Mode = 'coursework',
    [string]$CompetitionType = '',
    [string[]]$Messages
  )
  $convId = ''
  $i = 0
  foreach ($m in $Messages) {
    $i++
    Write-Host "=== $SessionLabel turn $i ($([DateTime]::Now.ToString('HH:mm:ss'))) ==="
    $raw = Send-Turn -ProjectId $ProjectId -Message $m -Mode $Mode -CompetitionType $CompetitionType -ConvId $convId
    if ($null -eq $raw) {
      Write-Host "FAIL at turn $i"
      return $convId
    }
    if ($convId -eq '') { $convId = Parse-ConvId -Text $raw }
    Write-Host "conv_id=$convId len=$($raw.Length)"
  }
  Save-Conversation -ProjectId $ProjectId -Label $SessionLabel | Out-Null
  return $convId
}
