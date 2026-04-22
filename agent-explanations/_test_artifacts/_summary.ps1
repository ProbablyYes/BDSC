$labels = @('A','B','C','D','E')
$lines = @()
foreach ($l in $labels) {
  $bytes = [System.IO.File]::ReadAllBytes("agent-explanations\_test_artifacts\$l.extracted.json")
  $text = [System.Text.Encoding]::UTF8.GetString($bytes)
  $obj = $text | ConvertFrom-Json
  $lines += "=== SESSION $l ==="
  $lines += "project_id = $($obj.project_id)"
  $lines += "conversation_id = $($obj.conversation_id)"
  $lines += "title = $($obj.title)"
  foreach ($t in $obj.turns) {
    $lines += "  -- turn $($t.turn_index) --"
    $lines += "  user_message_len=$($t.user_message.Length)  assistant_full_len=$($t.assistant_full_len)"
    $lines += "  intent=$($t.intent)  intent_engine=$($t.intent_engine)"
    $lines += "  pipeline=$(@($t.pipeline) -join ',')  nodes_visited=$(@($t.nodes_visited) -join ',')"
    $lines += "  category=$($t.category)  stage=$($t.project_stage)  score_band=$($t.score_band)  overall=$($t.overall_score)  bottleneck=$($t.bottleneck)"
    $lines += "  is_nonprofit=$($t.is_nonprofit)"
    $lines += "  triggered_rules=$(@($t.triggered_rule_ids) -join ',')"
    $lines += "  kg_entities=$($t.kg_entities_count)  kg_rels=$($t.kg_relationship_count)  rag_cases=$($t.rag_cases_count)  neo4j_hits=$($t.neo4j_hits_count)"
    $famLine = ''
    if ($t.hyper_family_counts) {
      $tops = @($t.hyper_family_counts.PSObject.Properties) | Sort-Object -Property Value -Descending | Select-Object -First 5
      $famLine = ($tops | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ','
    }
    $lines += "  hyper_top_families=$famLine"
    if ($t.finance_advisory) {
      $evLine = ''
      if ($t.finance_advisory.evidence) {
        $evLine = ($t.finance_advisory.evidence.PSObject.Properties | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ','
      }
      $lines += "  finance_advisory: triggered=$($t.finance_advisory.triggered)  industry=$($t.finance_advisory.industry)  cards=$($t.finance_advisory.cards_count)  verdict=$($t.finance_advisory.verdict)  evidence={$evLine}"
    }
    $lines += "  next_task_title=$($t.next_task_title)"
    $lines += "  next_task_desc_head=$(if($t.next_task_desc){$t.next_task_desc.Substring(0,[Math]::Min(200,$t.next_task_desc.Length))}else{''})"
    $lines += "  USER: $(if($t.user_message){$t.user_message.Substring(0,[Math]::Min(220,$t.user_message.Length))}else{''})"
    $lines += "  ASSISTANT_HEAD(300): $(if($t.assistant_head){$t.assistant_head.Substring(0,[Math]::Min(300,$t.assistant_head.Length))}else{''})"
    $lines += ""
  }
  $lines += ""
}
$out = $lines -join "`n"
[System.IO.File]::WriteAllText('agent-explanations\_test_artifacts\_summary.txt', $out, [System.Text.UTF8Encoding]::new($false))
"summary written len=$($out.Length)"
