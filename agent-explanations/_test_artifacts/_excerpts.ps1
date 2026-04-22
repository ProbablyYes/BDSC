$labels = @('A','B','C','D','E')
$out = @()
foreach ($l in $labels) {
  $bytes = [System.IO.File]::ReadAllBytes("agent-explanations\_test_artifacts\$l.conversation.json")
  $text = [System.Text.Encoding]::UTF8.GetString($bytes)
  $obj = $text | ConvertFrom-Json
  $turn = 0
  foreach ($m in $obj.messages) {
    if ($m.role -eq 'user') { $turn += 1; continue }
    if ($m.role -ne 'assistant') { continue }
    $content = $m.content
    $head = if ($content) { $content.Substring(0, [Math]::Min(2200, $content.Length)) } else { '' }
    $tail = ''
    if ($content -and $content.Length -gt 2200) {
      $start = [Math]::Max(0, $content.Length - 1400)
      $tail = $content.Substring($start)
    }
    $out += "=============================="
    $out += "### $l turn $turn (len=$($content.Length))"
    $out += "[HEAD]"
    $out += $head
    if ($tail) {
      $out += ""
      $out += "[TAIL]"
      $out += $tail
    }
    $out += ""
  }
}
$s = $out -join "`n"
[System.IO.File]::WriteAllText('agent-explanations\_test_artifacts\_excerpts.txt', $s, [System.Text.UTF8Encoding]::new($false))
"len=$($s.Length)"
