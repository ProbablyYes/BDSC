import urllib.request, json

r = urllib.request.urlopen("http://127.0.0.1:8037/api/teacher/team-diagnosis?teacher_id=T001")
d = json.loads(r.read())
teams = d.get("teams", [])
print(f"Teams: {len(teams)}")
for t in teams[:4]:
    syns = t.get("syndromes", [])
    pri = t.get("priority_intervention", "?")[:80]
    portraits = t.get("student_portraits", [])
    has_issues = sum(1 for p in portraits if p.get("project_issues"))
    has_advice = sum(1 for p in portraits if p.get("actionable_advice"))
    print(f"\n  {t['team_name']}: syndromes={len(syns)}, students_w_issues={has_issues}, students_w_advice={has_advice}")
    print(f"    priority: {pri}")
    for s in syns[:3]:
        print(f"    [{s['severity']}] {s['label']}: {s['affected_ratio']}% ({s['affected_student_count']} students)")
        if s.get("intervention_steps"):
            print(f"      step 1: {s['intervention_steps'][0]['title']}")
    for p in portraits[:2]:
        pi = p.get("project_issues", [])
        adv = p.get("actionable_advice", [])
        prio = p.get("teacher_intervention_priority", "?")
        if pi or adv:
            print(f"    Student {p['display_name']}: priority={prio}, issues={len(pi)}, advice={len(adv)}")
            for issue in pi[:1]:
                print(f"      issue: {issue['issue_title']} -> {issue['issue_summary'][:60]}")
            for a in adv[:1]:
                print(f"      advice: {a['title']}")
