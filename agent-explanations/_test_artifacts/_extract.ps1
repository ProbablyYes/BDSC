param([string]$Label)
$path = "agent-explanations\_test_artifacts\$Label.conversation.json"
$bytes = [System.IO.File]::ReadAllBytes($path)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
$obj = $text | ConvertFrom-Json
$messages = $obj.messages

$result = [PSCustomObject]@{
  session_label   = $Label
  project_id      = $obj.project_id
  conversation_id = $obj.conversation_id
  title           = $obj.title
  summary         = $obj.summary
  turns           = @()
}

$turnIndex = 0
for ($i=0; $i -lt $messages.Count; $i++) {
  $m = $messages[$i]
  if ($m.role -eq 'user') { $turnIndex += 1; continue }
  if ($m.role -ne 'assistant') { continue }
  $prevUser = if ($i -gt 0 -and $messages[$i-1].role -eq 'user') { $messages[$i-1].content } else { '' }
  $at = $m.agent_trace
  $orc = $null
  $diag = $null
  $kg = $null
  $hyper = $null
  $fa = $null
  $nt = $null
  if ($at) {
    $orc = $at.orchestration
    $diag = $at.diagnosis
    $kg = $at.kg_analysis
    $hyper = $at.hypergraph_insight
    $fa = $at.finance_advisory
    $nt = $at.next_task
  }
  $ruleIds = @()
  $risks = @()
  if ($diag -and $diag.triggered_rules) {
    $ruleIds = @($diag.triggered_rules | ForEach-Object { $_.id })
    $risks   = @($diag.triggered_rules | ForEach-Object { [PSCustomObject]@{ id=$_.id; severity=$_.severity; title=$_.title; score_impact=$_.score_impact } })
  }
  $hyperTop = @()
  if ($hyper -and $hyper.edges) {
    $hyperTop = @($hyper.edges) | Select-Object -First 6 family_label, severity, score_impact, confidence, rules, rubrics
  }
  $hyperFamCount = $null
  if ($hyper -and $hyper.meta) { $hyperFamCount = $hyper.meta.family_counts }
  $obj_trim = [PSCustomObject]@{
    turn_index     = $turnIndex
    user_message   = $prevUser
    assistant_head = if ($m.content) { $m.content.Substring(0,[Math]::Min(1800,$m.content.Length)) } else { '' }
    assistant_full_len = if ($m.content) { $m.content.Length } else { 0 }
    pipeline       = if ($orc -and $orc.pipeline) { @($orc.pipeline) } else { @() }
    nodes_visited  = if ($orc -and $orc.nodes_visited) { @($orc.nodes_visited) } else { @() }
    intent         = if ($orc) { $orc.intent } else { '' }
    intent_reason  = if ($orc) { $orc.intent_reason } else { '' }
    intent_engine  = if ($orc) { $orc.engine } else { '' }
    category       = if ($at -and $at.category) { $at.category } elseif ($orc -and $orc.category) { $orc.category } else { '' }
    mode           = if ($diag) { $diag.mode } else { '' }
    project_stage  = if ($diag) { $diag.project_stage } else { '' }
    overall_score  = if ($diag) { $diag.overall_score } else { $null }
    bottleneck     = if ($diag) { $diag.bottleneck } else { '' }
    score_band     = if ($diag) { $diag.score_band } else { '' }
    is_nonprofit   = if ($diag) { $diag.is_nonprofit } else { $null }
    triggered_rule_ids = $ruleIds
    risks          = $risks
    next_task_title = if ($nt) { $nt.title } else { '' }
    next_task_desc  = if ($nt) { $nt.description } else { '' }
    kg_entities_count   = if ($kg -and $kg.entities) { @($kg.entities).Count } else { 0 }
    kg_relationship_count = if ($kg -and $kg.relationships) { @($kg.relationships).Count } else { 0 }
    kg_entities_sample  = if ($kg -and $kg.entities) { @($kg.entities) | Select-Object -First 10 name, type } else { @() }
    hyper_top_edges     = $hyperTop
    hyper_family_counts = $hyperFamCount
    rag_cases_count     = if ($at -and $at.rag_cases) { @($at.rag_cases).Count } else { 0 }
    neo4j_hits_count    = if ($at -and $at.neo4j_graph_hits) { @($at.neo4j_graph_hits).Count } else { 0 }
    finance_advisory = if ($fa) { @{
        triggered = $fa.triggered
        industry  = $fa.industry
        cards_count = if ($fa.cards) { @($fa.cards).Count } else { 0 }
        hits      = $fa.hits
        verdict   = $fa.verdict
        evidence  = $fa.evidence_for_diagnosis
    } } else { $null }
    competition_role = if ($at -and $at.competition) { @{
        type    = $at.competition.type
        role    = $at.competition.role
        score   = $at.competition.score
    } } else { $null }
  }
  $result.turns += ,$obj_trim
}

$outPath = "agent-explanations\_test_artifacts\$Label.extracted.json"
$json = $result | ConvertTo-Json -Depth 12
[System.IO.File]::WriteAllText($outPath, $json, [System.Text.UTF8Encoding]::new($false))
"extracted $Label -> $outPath (turns=$(@($result.turns).Count))"
