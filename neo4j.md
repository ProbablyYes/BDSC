## 一、整体架构

知识库采用**三层架构**：

1. **本体层**  - 定义抽象概念、方法、交付物、指标等
2. **导入层**  - 将结构化案例数据导入Neo4j
3. **服务层**  - 提供查询和统计接口

## 二、本体设计 (kg_ontology.py)

本体是知识库的"语义坐标系"，包含100+个节点，分为7类：

- **概念** (concept): `C_problem`、`C_user_segment`、`C_solution`、`C_business_model`等
- **方法** (method): `M_user_interview`、`M_mvp`、`M_tam_sam_som`等
- **交付物** (deliverable): `D_bp`、`D_pitch_deck`、`D_interview_notes`等  
- **指标** (metric): `X_tam`、`X_cac`、`X_ltv`、`X_retention`等
- **任务** (task): `T_task_user_evidence_loop`等学习任务
- **常见坑** (pitfall): `P_no_competitor_claim`、`P_market_size_fallacy`等
- **证据原子** (evidence): `E_user_interview_raw`、`E_survey_dataset`等

关键映射：
- `RUBRIC_EVIDENCE_CHAIN` - 评分维度→所需本体节点
- `RULE_ONTOLOGY_MAP` - 风险规则→相关概念
- `RULE_TASK_MAP` - 风险规则→推荐学习任务

## 三、数据导入流程 (import_to_neo4j.py)

导入脚本从 `data/graph_seed/case_structured` 读取结构化案例JSON，执行以下步骤：

1. **加载本体节点**  - 先将所有OntologyNode写入图数据库
2. **创建项目节点** - 每个案例创建一个Project节点，包含基本信息
3. **创建关联节点**：
   - `Stakeholder` - 目标用户
   - `PainPoint` - 痛点
   - `Solution` - 解决方案
   - `InnovationPoint` - 创新点
   - `BusinessModelAspect` - 商业模式要素
   - `Market` - 市场分析
   - `ExecutionStep` - 执行步骤
   - `RiskControlPoint` - 风险控制
   - `Evidence` - 证据条目
   - `RubricItem` - 评分维度
4. **建立关系** - 使用 `HAS_*`、`BELONGS_TO`、`EVALUATED_BY` 等关系类型
5. **本体对齐** - 通过 `INSTANCE_OF` 关系将实例节点映射到本体概念
6. **元数据** - 教育层次、获奖等级、赛事分类等

## 四、节点与关系设计

核心节点类型包括：

- **Project** - 项目中心节点
- **Category** - 项目类别
- **Stakeholder** - 利益相关者
- **PainPoint/Solution/InnovationPoint** - 项目要素
- **BusinessModelAspect/Market/ExecutionStep/RiskControlPoint** - 商业要素
- **Evidence** - 证据条目
- **RubricItem** - 评分维度
- **OntologyNode** - 本体概念节点

关键关系类型：
- `BELONGS_TO` - 项目→类别
- `HAS_TARGET_USER` - 项目→目标用户
- `HAS_PAIN/HAS_SOLUTION` - 项目→痛点/方案
- `HAS_EVIDENCE` - 项目→证据
- `EVALUATED_BY` - 项目→评分维度
- `INSTANCE_OF` - 实例→本体概念

```

## 五、核心设计理念

1. **实例→概念对齐** - 具体文本通过 `INSTANCE_OF` 关系映射到抽象本体
2. **可追溯性** - 每个评分和风险发现都可追溯到明确的概念和证据
3. **教学导向** - 支持从教材本体→案例库的教学检索
4. **多维分析** - 支持按类别、目标用户、评分维度等多视角分析