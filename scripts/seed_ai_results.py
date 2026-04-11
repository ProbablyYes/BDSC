"""Fetch AI results for each plan and save them into the plan data."""
import json, requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API = "http://127.0.0.1:8037"
UID = "12345678"

PLANS = {
    "e7e9b80a": {
        "name": "NoteMind MVP资金估算",
        "chats": [
            "我这个 MVP 阶段资金预算合理吗？有没有什么遗漏的开销？",
            "如果要申请学校创业孵化资金，我需要怎么准备预算说明？",
        ]
    },
    "6378cb0e": {
        "name": "互联网+省赛参赛预算",
        "chats": [
            "省赛的预算安排有没有遗漏？评委会关注哪些财务问题？",
            "如果进入国赛，预算大概还需要追加多少？",
            "差旅报销需要注意什么？学校一般怎么审批？",
        ]
    },
    "9dfb00e8": {
        "name": "NoteMind 商业计划书财务模型",
        "chats": [
            "我的收入模型是否合理？个人Pro会员6%的付费转化率高不高？",
            "如果要向投资人路演，我的财务数据有哪些薄弱点需要加强？",
            "B端高校定制这条收入线风险大吗？如何降低依赖？",
            "三档情景分析的参数设置是否合理？如何向评委解释？",
        ]
    },
    "64e09f91": {
        "name": "创业基础课财务分析报告",
        "chats": [
            "作为课程作业，我的财务分析还需要补充哪些内容？",
            "老师可能会问哪些关于财务的问题？我该怎么回答？",
            "盈亏平衡分析怎么写比较专业？",
        ]
    },
}

for plan_id, info in PLANS.items():
    print(f"\n=== Processing: {info['name']} ({plan_id}) ===")

    # 1. Call AI suggest
    print("  Fetching AI diagnosis...")
    try:
        r = requests.post(f"{API}/api/budget/{UID}/{plan_id}/ai-suggest",
                          json={"project_description": "", "project_type": ""}, timeout=60)
        ai_result = r.json().get("suggestions", {})
        print(f"  -> Got keys: {list(ai_result.keys())}")
    except Exception as e:
        print(f"  -> Error: {e}")
        ai_result = {}

    # 2. Call AI chats
    chat_history = []
    for q in info["chats"]:
        print(f"  Chat: '{q[:40]}...'")
        try:
            r = requests.post(f"{API}/api/budget/{UID}/{plan_id}/ai-chat",
                              json={"question": q}, timeout=60)
            reply = r.json().get("reply", "暂无回复")
            chat_history.append({"q": q, "a": reply})
            print(f"    -> {len(reply)} chars")
        except Exception as e:
            chat_history.append({"q": q, "a": f"请求失败: {e}"})
            print(f"    -> Error: {e}")

    # 3. Save AI data into the plan via PUT
    print("  Saving AI data to plan...")
    try:
        r = requests.put(f"{API}/api/budget/{UID}/{plan_id}",
                         json={"ai_result": ai_result, "ai_chat_history": chat_history},
                         timeout=10)
        d = r.json()
        print(f"  -> Saved! Status: {d.get('status')}")
    except Exception as e:
        print(f"  -> Save error: {e}")

print("\n=== All AI results saved! ===")
