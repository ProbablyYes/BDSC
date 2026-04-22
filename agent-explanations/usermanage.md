# BDSC 创新创业智能体平台 - 用户管理、角色身份与权限管理功能说明文档

## 一、系统概述

BDSC 平台采用**基于角色的访问控制（RBAC）**模型，支持三种用户角色：**学生**、**教师**、**管理员**。系统提供完整的用户生命周期管理功能，包括注册、登录、权限控制、批量导入和团队管理等。

### 1.1 技术架构

- **前端**：Next.js + React + TypeScript
- **后端**：FastAPI + Python
- **数据存储**：JSON 文件存储（data/users/users.json、data/teams/teams.json）
- **认证方式**：基于 Token 的本地存储认证
- **密码加密**：PBKDF2-SHA256 哈希算法

### 1.2 功能概述

#### 1.2.1. 用户注册（register 页面）

- **角色选择**：注册时可选“学生”、“教师”、“管理员”，角色信息随表单提交。
- **注册表单**：填写昵称、邮箱/账号、密码、确认密码。
- **注册流程**：
  - 前端提交注册信息到 `/api/auth/register`。
  - 后端校验账号唯一性，创建用户，分配角色。
  - 注册成功后自动登录，跳转到对应角色首页（如 /student、/teacher、/admin）。
  - 注册失败（如账号重复）有明确错误提示。

#### 1.2.2. 管理员后台（admin 页面）用户管理

##### 1.2.2.1 用户列表与筛选

- 展示所有用户，字段包括账号、姓名、角色、邮箱、团队、状态、上次登录等。
- 支持按角色、团队、关键词筛选。

##### 1.2.2.2 用户增删改

- **新增用户**：弹窗表单填写信息，支持直接创建。
- **编辑角色/信息**：可在表格中直接修改用户角色、团队等。
- **删除用户**：支持单个或批量删除，教师用户删除时会同步删除其团队。

##### 1.2.2.3 批量导入用户

- 支持 CSV/Excel 文件批量导入，字段包括账号、姓名、角色、邮箱、团队名、密码等。
- 前端解析文件并预览，确认后上传。
- 后端支持自动生成账号、密码，批量分配团队。

##### 1.2.2.4 团队管理

- 展示所有团队，包含团队名、教师、邀请码、成员列表等。
- 支持创建、删除团队，教师可管理团队成员。
- 用户可通过邀请码加入团队，教师可移除成员。

#### 1.2.3. 角色与权限体系

- **角色类型**：student（学生）、teacher（教师）、admin（管理员）。
- **权限控制**：
  - 注册、登录、页面访问、接口操作均有角色校验。
  - 仅管理员可批量导入用户、管理所有团队。
  - 教师可创建和管理自己的团队，学生可加入团队。
---

## 二、用户角色与权限体系

### 2.1 角色定义

系统定义三种核心角色，每种角色具有不同的权限和访问范围：

| 角色 |  主要权限 | 
|------|---------|
| 学生 | 创建项目、参与对话、查看个人数据 |
| 教师 | 管理团队、查看学生数据、创建干预、订正 AI 结论 |
| 管理员 | 用户管理、团队管理、系统监控、批量操作 |

### 2.2 权限矩阵

| 功能模块 | 学生 | 教师 | 管理员 |
|---------|------|------|--------|
| 用户注册 | ✓ | ✓ | ✓ |
| 项目创建与编辑 | ✓ | - | - |
| 查看个人数据 | ✓ | ✓ | ✓ |
| 团队管理 | - | ✓ | ✓ |
| 用户 CRUD | - | - | ✓ |
| 批量导入用户 | - | - | ✓ |
| 系统健康监控 | - | - | ✓ |
| 教学干预 | - | ✓ | ✓ |
| AI 结论订正 | - | ✓ | - |

### 2.3 认证机制

系统使用客户端认证 Hook（[useAuth.ts]）进行权限验证：

```typescript
export function useAuth(requiredRole?: string): VaUser | null {
  // 从 localStorage 读取用户信息
  const raw = localStorage.getItem("va_user");
  const u: VaUser = JSON.parse(raw);
  
  // 角色匹配验证
  if (requiredRole && u.role !== requiredRole) {
    logUnauthorizedAttempt(u, "role_mismatch");
    router.replace("/auth/login");
    return null;
  }
  
  return u;
}
```

**代码说明**：
- 这是一个 React Hook，用于在组件中验证用户身份和角色权限
- 从浏览器 localStorage 读取之前保存的用户信息（登录时存入）
- 如果页面要求特定角色（如教师端要求 teacher 角色），则检查当前用户角色是否匹配
- 角色不匹配时，记录未授权访问日志并强制跳转到登录页
- 返回用户对象供组件使用，如果验证失败返回 null

**逻辑解释**：
- 前端没有后端 API 验证，完全依赖 localStorage 中的数据
- 这种方式适合小型应用，但安全性有限（用户可以手动修改 localStorage）
- 真正的权限验证在后端 API 中进行
- logUnauthorizedAttempt 用于安全审计，记录谁试图访问无权页面

**关键特性**：
- 基于 localStorage 的会话管理
- 角色不匹配时自动重定向到登录页
- 记录未授权访问日志到 `/api/admin/logs/unauthorized`
- 支持可选的角色参数进行精细权限控制

---

## 三、用户注册功能

### 3.1 注册页面

#### 3.1.1 注册流程

1. **角色选择**：用户从三个角色卡片中选择身份
2. **基本信息填写**：
   - 昵称（display_name）：最少 2 个字符
   - 账号/邮箱（email）：作为登录账号使用
   - 密码（password）：最少 6 位
   - 确认密码：必须与密码一致
3. **表单提交**：调用 `/api/auth/register` API
4. **自动跳转**：注册成功后根据角色跳转到对应工作台

#### 3.1.2 角色选择界面

每个角色卡片包含：
- 角色图标和标签
- 选中状态的高亮效果
- 点击切换角色

#### 3.1.3 错误处理

系统处理以下错误情况：
- **账号重复**：提示"该账号名已存在"
- **昵称重复**：提示"用户名已存在"
- **密码不一致**：提示"两次输入的密码不一致"
- **网络错误**：提示"注册失败"

#### 3.1.4 注册后引导

页面左侧显示注册后的使用流程：
```
1. 选择角色并填写基本信息
2. 自动进入对应工作台
3. 在个人中心完善学号与班级
```

### 3.2 后端注册 API

#### 3.2.1 API 端点

```python
@app.post("/api/auth/register", response_model=AuthUserResponse)
def auth_register(payload: AuthRegisterPayload) -> AuthUserResponse:
    user = user_store.create_user(payload.model_dump())
    return AuthUserResponse(status="ok", user=user)
```

**代码说明**：
- 这是用户注册的后端 API 端点，接收 POST 请求
- payload.model_dump() 将 Pydantic 模型转换为字典，传给存储层
- 调用 user_store.create_user() 实际创建用户并保存到 JSON 文件
- 返回注册成功的响应，包含用户信息

**逻辑解释**：
- FastAPI 的 @app.post 装饰器定义路由和 HTTP 方法
- response_model 指定返回数据的结构，自动验证和序列化
- 实际的业务逻辑（校验、哈希、存储）都在 storage.py 中处理
- API 层只负责接收请求、调用服务层、返回响应

#### 3.2.2 数据模型

```python
class AuthRegisterPayload(BaseModel):
    role: Literal["student", "teacher", "admin"] = "student"
    display_name: str = Field(min_length=2, max_length=50)
    email: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=6, max_length=64)
    student_id: str | None = None
    class_id: str | None = None
    cohort_id: str | None = None
    bio: str | None = ""
```

**代码说明**：
- Pydantic BaseModel 定义注册请求的数据结构
- Literal 限制 role 只能是三个值之一，防止传入无效角色
- Field 定义字段验证规则（最小长度、最大长度等）
- 带 | None 的字段表示可选，不传则为 None

**逻辑解释**：
- Pydantic 自动验证请求数据，不符合规则直接返回 400 错误
- 前端传来的 JSON 会被自动解析并填充到这个模型
- 验证通过后，model_dump() 将其转换为字典供后续处理
- 这种方式比手动解析 JSON 更安全、更规范

#### 3.2.3 存储逻辑

**文件位置**：[apps/backend/app/services/storage.py]

```python
def create_user(self, payload: dict) -> dict:
    # 1. 邮箱唯一性校验
    email = str(payload.get("email", "")).strip().lower()
    if any(user.get("email") == email for user in users):
        raise ValueError("该账号名已存在")
    
    # 2. 昵称唯一性校验
    display_name = str(payload.get("display_name", "")).strip()
    if display_name and any(user.get("display_name") == display_name for user in users):
        raise ValueError("用户名已存在")
    
    # 3. 学号唯一性校验（如果提供）
    raw_sid = str(payload.get("student_id", "")).strip() or None
    if raw_sid and any(u.get("student_id") == raw_sid for u in users):
        raise ValueError("学号已被占用")
    
    # 4. 密码哈希
    salt, password_hash = self._hash_password(str(payload.get("password", "")))
    
    # 5. 创建用户记录
    user = {
        "user_id": str(uuid4()),
        "role": payload.get("role", "student"),
        "display_name": display_name or email.split("@")[0],
        "email": email,
        "student_id": raw_sid,
        "class_id": str(payload.get("class_id", "")).strip() or None,
        "cohort_id": str(payload.get("cohort_id", "")).strip() or None,
        "bio": str(payload.get("bio", "")).strip(),
        "password_salt": salt,
        "password_hash": password_hash,
        "status": "active",
        "last_login": "",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "project_serial_counter": 0,
    }
    
    users.append(user)
    self._save(users)
    return self._public_user(user)
```

**代码说明**：
- 这是用户存储层的核心方法，负责创建新用户并保存到 JSON 文件
- 先进行三重唯一性校验：邮箱、昵称、学号
- 密码不直接存储，而是哈希后存储哈希值和盐值
- 生成 UUID 作为用户唯一标识
- 最后调用 _public_user 返回脱敏后的用户信息（不包含密码）

**逻辑解释**：
- 邮箱转小写是为了避免大小写导致的重复（如 Test@test.com 和 test@test.com）
- strip() 去除首尾空格，防止用户误输入空格
- 如果用户没填昵称，就用邮箱 @ 符号前的部分作为昵称
- project_serial_counter 用于给用户的项目编号（如 P-001, P-002）
- _public_user 方法会隐藏 password_salt 和 password_hash，防止泄露

#### 3.2.4 密码哈希算法

```python
def _hash_password(self, password: str, salt: str | None = None) -> tuple[str, str]:
    real_salt = salt or secrets.token_hex(16)
    password_hash = pbkdf2_hmac(
        "sha256", 
        password.encode("utf-8"), 
        real_salt.encode("utf-8"), 
        120000
    ).hex()
    return real_salt, password_hash
```

**代码说明**：
- PBKDF2 是密码学安全的密钥派生函数，专门用于密码哈希
- 每个用户有独立的随机盐值，即使密码相同，哈希值也不同
- 120000 次迭代让暴力破解变得极其困难
- 返回盐值和哈希值，验证时需要两者结合

**逻辑解释**：
- salt 参数为 None 时自动生成 16 字节随机盐
- pbkdf2_hmac 是 Python 标准库 hashlib 中的函数
- encode("utf-8") 将字符串转为字节，哈希函数需要字节输入
- .hex() 将二进制哈希值转为十六进制字符串存储
- 验证密码时，用相同盐值和密码重新计算哈希，比对结果

**安全特性**：
- 使用 PBKDF2-SHA256 算法
- 120,000 次迭代计算
- 随机 16 字节盐值
- 符合现代密码安全标准

---

## 四、用户登录功能

### 4.1 登录页面

**文件位置**：[apps/web/app/auth/login/page.tsx]
#### 4.1.1 登录流程

1. **输入账号密码**：邮箱/账号 + 密码
2. **表单提交**：调用 `/api/auth/login` API
3. **加载状态**：显示"正在登陆，请稍后"遮罩层
4. **自动跳转**：根据用户角色跳转到对应工作台
5. **会话存储**：用户信息保存到 localStorage

#### 4.1.2 登录 API 调用

```typescript
const res = await fetch(`${API}/api/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email: email.trim(), password }),
});

if (!res.ok) throw new Error(data?.detail ?? "登录失败");

localStorage.setItem("va_user", JSON.stringify(data.user));

const role = data.user?.role ?? "student";
router.push(
  role === "teacher" ? "/teacher" : 
  role === "admin" ? "/admin" : 
  "/student"
);
```

**代码说明**：
- 前端调用登录 API，发送邮箱和密码
- 登录成功后将用户信息存入 localStorage，实现会话保持
- 根据用户角色自动跳转到对应的工作台页面
- ?? 是空值合并运算符，如果 role 为空则默认为 student

**逻辑解释**：
- email.trim() 去除用户输入的首尾空格
- fetch 返回的 res.ok 为 false 时表示 HTTP 状态码非 2xx，登录失败
- localStorage 存储的是 JSON 字符串，需要 JSON.stringify 转换
- router.push 是 Next.js 的路由跳转方法，会改变浏览器 URL

#### 4.1.3 加载提示层

```tsx
{showLoginOverlay && (
  <div className="loading-overlay">
    <span className="auth-spinner" />
    <div>
      <span>正在登陆，请稍后</span>
      <span>系统正在为你加载工作台...</span>
    </div>
  </div>
)}
```

**代码说明**：
- 这是 React 条件渲染，只有 showLoginOverlay 为 true 时才显示加载遮罩
- auth-spinner 是旋转动画，给用户视觉反馈
- 双层文字提示：主标题 + 副标题，让用户知道系统在做什么

**逻辑解释**：
- showLoginOverlay 在提交登录表单时设为 true，跳转完成后设为 false
- loading-overlay 是全屏遮罩，防止用户重复点击
- 这种 UX 设计能减少用户焦虑，提升体验

### 4.2 后端登录 API
#### 4.2.1 API 端点

```python
@app.post("/api/auth/login", response_model=AuthUserResponse)
def auth_login(payload: AuthLoginPayload) -> AuthUserResponse:
    user = user_store.authenticate(payload.email, payload.password)
    if not user:
        # 记录登录失败日志
        _append_access_log({...})
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    
    # 记录登录成功日志
    _append_access_log({...})
    return AuthUserResponse(status="ok", user=user)
```

**代码说明**：
- 后端登录 API，调用存储层的 authenticate 方法验证用户
- 验证失败返回 401 状态码，成功返回用户信息
- 无论成功失败都记录日志，用于安全审计

**逻辑解释**：
- HTTP 401 是标准的未授权状态码
- _append_access_log 记录登录时间、IP、用户等信息
- 日志文件存储在 data/logs/access_logs.json
- 记录失败日志可以检测暴力破解攻击

#### 4.2.2 认证逻辑

```python
def authenticate(self, email: str, password: str) -> dict | None:
    users = self._load()
    email_key = email.strip().lower()
    
    for user in users:
        if str(user.get("email", "")).strip().lower() != email_key:
            continue
        
        salt = str(user.get("password_salt", ""))
        _, password_hash = self._hash_password(password, salt)
        
        if password_hash != user.get("password_hash"):
            return None
        
        # 更新最后登录时间
        user["last_login"] = _now_iso()
        user["updated_at"] = _now_iso()
        self._save(users)
        return self._public_user(user)
    
    return None
```

**代码说明**：
- 从 JSON 文件加载所有用户，遍历查找匹配的邮箱
- 找到用户后，用存储的盐值对输入密码重新哈希
- 比对哈希值，一致则验证成功，不一致则失败
- 验证成功后更新最后登录时间并返回用户信息

**逻辑解释**：
- email 转小写和注册时保持一致，确保匹配
- 密码验证不比较明文，而是比较哈希值，更安全
- 验证成功必须更新 last_login，用于统计活跃用户
- _public_user 隐藏密码相关字段，防止返回给前端

#### 4.2.3 访问日志记录

系统记录所有登录尝试（成功和失败）到 `data/logs/access_logs.json`

---

## 五、管理员用户管理功能

### 5.1 管理员控制台

**文件位置**：[apps/web/app/admin/page.tsx]

#### 5.1.1 控制台结构

管理员控制台包含以下标签页：

| 标签页 | 功能 |
|--------|------|
| 全局大盘 | 系统整体数据统计 |
| 教师表现 | 教师绩效排名 |
| 教学干预 | 干预记录统计 |
| **用户管理** | 用户 CRUD 操作 |
| 项目总览 | 所有项目列表 |
| 漏洞看板 | 风险规则统计 |
| 访问日志 | 系统访问记录 |

#### 5.1.2 用户管理功能

用户管理标签页提供以下功能：

1. **用户列表展示**
   - 用户 ID、昵称、角色、邮箱
   - 所属团队、状态、最后登录时间
   - 项目数量统计

2. **筛选和搜索**
   - 角色筛选（学生/教师/管理员）
   - 团队筛选
   - 关键词搜索（昵称/ID/邮箱）
   - 按团队分组显示

3. **用户操作**
   - 修改角色
   - 启用/禁用账户
   - 重置密码
   - 删除用户
   - 管理教师团队

4. **批量操作**
   - 批量创建用户
   - CSV/Excel 导入
   - 批量创建教师及团队
### 5.2 用户 CRUD 操作

#### 5.2.1 查询用户列表

```typescript
async function loadUsers() {
  const r = await fetch(`${API}/api/admin/users`);
  const d = await r.json();
  const rows = (d.users ?? []).map((u: any): UserRecord => ({
    id: u.user_id,
    name: u.display_name ?? u.email ?? u.user_id,
    role: u.role as UserRole,
    email: u.email,
    teams: Array.isArray(u.team_names) ? u.team_names.filter(Boolean) : [],
    status: (u.status as "active" | "disabled") ?? "active",
    last_login: u.last_login || "",
    project_count: typeof u.project_count === "number" ? u.project_count : 0,
  }));
  setUsers(rows);
}
```

**代码说明**：
- 调用后端 API 获取所有用户列表
- 将后端返回的用户数据转换为前端需要的格式
- 处理可能缺失的字段，提供默认值
- 更新 React 状态，触发界面重新渲染

**逻辑解释**：
- ?? 空值合并运算符，如果 d.users 为空则使用空数组
- ?? 也是链式判断，优先用 display_name，没有则用 email，再没有则用 user_id
- filter(Boolean) 过滤掉空字符串、null、undefined 等假值
- typeof 检查确保 project_count 是数字类型，避免显示错误

#### 5.2.2 创建单个用户

```typescript
async function addUser() {
  const payload = {
    role: newUser.role,
    display_name: newUser.name,
    email: newUser.email || `${newUser.id}@local`,
    student_id: newUser.id,
    password: newUser.password || undefined,
  };
  
  const r = await fetch(`${API}/api/admin/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  
  const d = await r.json();
  setUsers((prev) => [...prev, record]);
}
```

**代码说明**：
- 管理员手动创建单个用户
- 如果没填邮箱，用用户 ID 拼接 @local 作为默认邮箱
- 密码不填则由后端自动生成
- 创建成功后将新用户添加到列表中

**逻辑解释**：
- || 或运算符，左边为假值时使用右边
- password 传 undefined 而不传空字符串，让后端知道需要自动生成
- setUsers 使用函数式更新，确保拿到最新的 prev 状态
- [...prev, record] 展开运算符创建新数组，不修改原数组（React 不可变数据原则）

#### 5.2.3 修改用户角色

```typescript
async function changeUserRole(userId: string, newRole: UserRole) {
  const r = await fetch(`${API}/api/admin/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role: newRole }),
  });
  
  const d = await r.json();
  setUsers((prev) => prev.map((row) => row.id === userId ? {...row, role: newRole} : row));
}
```

**代码说明**：
- 使用 PATCH 方法部分更新用户信息（只改角色）
- URL 中包含用户 ID，标识要修改哪个用户
- 前端先更新本地状态，提升响应速度（乐观更新）

**逻辑解释**：
- PATCH 比 PUT 更适合部分更新，PUT 通常需要提供完整数据
- prev.map 遍历所有用户，找到匹配的 ID 就更新角色
- 三元运算符：匹配则返回更新后的对象，不匹配则返回原对象
- {...row, role: newRole} 展开运算符创建新对象，只覆盖 role 字段

#### 5.2.4 切换用户状态

```typescript
async function toggleUserStatus(userId: string) {
  const target = users.find((u) => u.id === userId);
  const nextStatus: "active" | "disabled" = target?.status === "active" ? "disabled" : "active";
  
  await fetch(`${API}/api/admin/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: nextStatus }),
  });
  
  setUsers((prev) => prev.map((u) => u.id === userId ? { ...u, status: nextStatus } : u));
}
```

**代码说明**：
- 切换用户的启用/禁用状态
- 先找到当前用户，判断当前状态，然后取反
- 调用 API 更新后端，再更新前端状态

**逻辑解释**：
- target?.status 可选链，防止 target 为 undefined 时报错
- 状态只有两种值，用三元运算符切换很简洁
- 先调用 API 确保后端更新成功，再更新前端（悲观更新）
- 禁用的用户无法登录，系统在登录时会检查 status 字段

#### 5.2.5 重置密码

```typescript
async function resetPassword(userId: string) {
  const pwd = window.prompt("请输入新密码（至少6位）", "");
  if (!pwd || pwd.length < 6) return;
  
  await fetch(`${API}/api/admin/users/${userId}/password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_password: pwd }),
  });
  
  window.alert("密码已更新");
}
```

**代码说明**：
- 使用浏览器原生 prompt 弹窗让管理员输入新密码
- 验证密码长度，不符合则直接返回
- 调用专用密码重置 API
- 成功后用 alert 提示管理员

**逻辑解释**：
- window.prompt 是同步阻塞的，用户必须输入或取消
- 这种方式简单但不够美观，实际项目中常用模态框替代
- 密码重置是敏感操作，通常需要二次确认
- alert 会阻塞页面，但用于简单提示可以接受

#### 5.2.6 删除用户

```typescript
async function deleteUser(userId: string) {
  await fetch(`${API}/api/admin/users/${userId}`, { method: "DELETE" });
  setUsers((prev) => prev.filter((u) => u.id !== userId));
}
```

**代码说明**：
- 调用 DELETE API 删除用户
- 前端从列表中移除该用户
- filter 创建新数组，只保留 ID 不匹配的用户

**逻辑解释**：
- DELETE 方法不需要请求体，URL 中的 userId 已足够标识资源
- filter 不修改原数组，符合 React 不可变数据原则
- 删除是危险操作，实际项目中通常需要确认弹窗
- 后端删除教师时会级联删除其创建的团队

**注意**：删除教师时会自动删除其所有团队。

### 5.3 后端用户管理 API

#### 5.3.1 查询用户列表

```python
@app.get("/api/admin/users")
def admin_list_users(role: str = "", class_id: str = "", keyword: str = "") -> dict:
    users = user_store.list_users(role=role or None, class_id=class_id or None, keyword=keyword or None)
    
    # 构建用户到团队的映射
    all_teams = team_store.list_all()
    user_team_names: dict[str, list[str]] = {}
    for team in all_teams:
        team_name = team.get("team_name", "")
        teacher_uid = team.get("teacher_id", "")
        if teacher_uid:
            user_team_names.setdefault(teacher_uid, []).append(team_name)
        for member in team.get("members", []):
            uid = member.get("user_id")
            if uid:
                user_team_names.setdefault(uid, []).append(team_name)
    
    # 丰富用户数据
    enriched = []
    for u in users:
        uid = u.get("user_id", "")
        stats = _aggregate_student_data(uid, include_detail=False) if uid else {
            "project_count": 0,
            "last_active": "",
        }
        team_names = user_team_names.get(uid, [])
        enriched.append({
            **u,
            "status": u.get("status", "active"),
            "last_login": u.get("last_login") or stats.get("last_active", ""),
            "project_count": stats.get("project_count", 0),
            "team_names": team_names,
        })
    
    return {"count": len(enriched), "users": enriched}
```

**代码说明**：
- 后端查询用户列表 API，支持按角色、班级、关键词筛选
- 需要关联团队信息，所以先查询所有团队建立映射
- 统计每个用户的项目数量和活跃时间
- 将所有数据合并后返回

**逻辑解释**：
- role or None：空字符串转为 None，存储层用 None 表示不筛选
- user_team_names 字典：键是用户 ID，值是该用户所在的团队名称列表
- setdefault：如果键不存在则创建空列表，避免 KeyError
- **u 展开运算符复制用户所有字段，再覆盖特定字段
- last_login 优先用登录时间，没有则用项目活跃时间

#### 5.3.2 创建用户

```python
@app.post("/api/admin/users")
def admin_create_user(payload: AdminUserCreatePayload) -> dict:
    user, temp_password = user_store.admin_create_user(payload.model_dump())
    
    # 如果未提供密码，自动生成随机密码
    if not temp_password:
        alphabet = string.ascii_letters + string.digits
        temp_password = "".join(secrets.choice(alphabet) for _ in range(10))
    
    # 返回用户信息和临时密码
    return {"user": user_out, "temp_password": temp_password}
```

**代码说明**:
- 管理员创建用户的后端 API
- 调用存储层创建用户，返回用户和临时密码
- 如果前端没提供密码，后端自动生成 10 位随机密码
- 将临时密码返回给前端，方便管理员告知用户

**逻辑解释**:
- admin_create_user 和普通 create_user 的区别是允许不提供密码
- secrets.choice 从字母数字表中随机选择，确保密码安全性
- 生成的密码包含大小写字母和数字，增加复杂度
- temp_password 只在创建时返回一次，之后无法再获取

#### 5.3.3 更新用户

```python
@app.patch("/api/admin/users/{user_id}")
def admin_update_user(user_id: str, payload: AdminUserUpdatePayload) -> dict:
    user = user_store.update_user(user_id, payload.model_dump(exclude_unset=True))
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 重新计算团队信息
    teams = []
    if uid:
        teams.extend(team_store.list_by_member(uid))
        teams.extend(team_store.list_by_teacher(uid))
    team_names = [t.get("team_name", "") for t in teams if t.get("team_name", "")]
    
    return {"user": {**user, "team_names": team_names}}
```

**代码说明**:
- 部分更新用户信息，只更新前端传来的字段
- 更新后重新查询用户的团队信息，因为可能修改了角色
- 将用户作为成员的团队和作为教师的团队都合并返回

**逻辑解释**:
- exclude_unset=True 只包含前端实际传的字段，未传的不更新
- 用户角色改变后，其团队关系可能变化，所以需要重新查询
- list_by_member：用户作为成员加入的团队
- list_by_teacher：用户作为教师创建的团队
- team_names 去重后返回，方便前端显示

#### 5.3.4 删除用户

---

## 六、批量创建用户功能

### 6.1 管理员批量创建

#### 6.1.1 前端批量创建界面

管理员控制台提供：

**规则化批量创建**

```typescript
const payload = {
  role: batchRole,  // "student" 或 "teacher"
  prefix: batchPrefix.trim(),  // 账号前缀，如 "stu"
  start_index: batchStartIndex || 1,  // 起始序号
  count: batchCount,  // 创建数量
  password_suffix: batchPasswordSuffix || "123",  // 密码后缀
};

// 学生可选：加入现有团队
if (payload.role === "student" && batchInviteCode.trim()) {
  payload.invite_code = batchInviteCode.trim().toUpperCase();
}

// 教师可选：创建团队
if (payload.role === "teacher" && teamName) {
  payload.team_name = teamName;
  payload.team_invite_code = teamInviteCode;
}
```

**账号生成规则**：
- 账号格式：`{prefix}{序号:03d}`，例如 `stu001`, `stu002`
- 默认密码：`账号 + 密码后缀`，例如 `stu001123`
- 昵称：与账号相同

**教师下属的团队信息自定义的批量创建**

```typescript
const teachersPayload = batchTeachers.map(t => ({
  account: t.account,
  name: t.name,
  password: `${t.account}${batchPasswordSuffix || "123"}`,
  teams: t.teams.map(tm => ({
    team_name: tm.teamName,
    invite_code: tm.inviteCode
  }))
}));
```

每个教师可以创建多个团队，每个团队有独立的名称和邀请码。

#### 6.1.2 批量创建 API 调用

```typescript
// 规则化批量创建
const r = await fetch(`${API}/api/admin/users/batch`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});

// 自定义教师批量创建
const r = await fetch(`${API}/api/admin/teachers/batch_with_teams`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ teachers: teachersPayload }),
});
```

#### 6.1.3 批量创建结果处理

```typescript
const d = await r.json();

// 处理重复账号
if (Array.isArray(d.duplicates) && d.duplicates.length > 0) {
  window.alert(`账号名已存在：${d.duplicates.join(", ")}`);
}

// 处理重复昵称
if (Array.isArray(d.duplicate_names) && d.duplicate_names.length > 0) {
  window.alert(`用户名已存在：${d.duplicate_names.join(", ")}`);
}

// 显示成功创建数量
window.alert(`已创建 ${d.count} 个账号`);
```

### 6.2 CSV/Excel 导入功能

#### 6.2.1 导入界面

```typescript
// 文件上传处理
function handleImportFile(file: File) {
  const ext = file.name.split(".").pop()?.toLowerCase();
  
  if (ext === "csv") {
    Papa.parse(text, {
      header: true,
      skipEmptyLines: true,
      complete: (res) => {
        setImportData(res.data);
        setImportPreview(res.data.slice(0, 20));
      },
    });
  } else if (ext === "xlsx") {
    const wb = XLSX.read(e.target.result, { type: "array" });
    const ws = wb.Sheets[wb.SheetNames[0]];
    const rows = XLSX.utils.sheet_to_json(ws, { defval: "" });
    setImportData(rows);
    setImportPreview(rows.slice(0, 20));
  }
}

// 提交导入
async function handleImportSubmit() {
  const form = new FormData();
  form.append("file", importFile);
  form.append("meta", JSON.stringify({ filename: importFile.name, time: Date.now() }));
  form.append("data", JSON.stringify(importData));
  
  const r = await fetch(`${API}/api/admin/users/import_csv`, {
    method: "POST",
    body: form,
  });
  
  const d = await r.json();
  // 刷新用户和团队列表
  await Promise.all([loadUsers(), loadTeams()]);
}
```

#### 6.2.2 导入字段说明

支持的 CSV/Excel 字段：

| 字段名 | 必填 | 说明 |
|--------|------|------|
| account | 是 | 登录账号 |
| name | 是 | 用户昵称 |
| role | 是 | 角色（student/teacher/admin） |
| email | 否 | 邮箱 |
| team_name | 否 | 所属团队名称 |
| invite_code | 否 | 团队邀请码 | 
| password | 否 | 密码（不填则自动生成） |

#### 6.2.3 拖拽上传

```tsx
<div 
  onDrop={(e) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleImportFile(e.dataTransfer.files[0]);
    }
  }}
  onDragOver={(e) => e.preventDefault()}
>
  <input 
    type="file" 
    ref={fileInputRef}
    onChange={(e) => {
      if (e.target.files && e.target.files[0]) {
        handleImportFile(e.target.files[0]);
      }
    }}
    accept=".csv,.xlsx"
  />
</div>
```

### 6.3 后端批量导入 API

#### 6.3.1 规则化批量创建

```python
@app.post("/api/admin/users/batch")
def admin_batch_create_users(payload: AdminBatchCreateUsersPayload) -> dict:
    role = payload.role
    prefix = payload.prefix.strip()
    start_index = int(payload.start_index or 1)
    count = int(payload.count or 1)
    password_suffix = str(payload.password_suffix or "123")
    
    # 验证学生邀请码
    target_team = None
    if role == "student" and payload.invite_code:
        target_team = team_store.find_by_invite_code(payload.invite_code)
        if not target_team:
            raise HTTPException(status_code=400, detail="邀请码无效或团队不存在")
    
    created_users = []
    password_list = []
    duplicate_accounts = []
    duplicate_names = []
    
    for i in range(count):
        seq = start_index + i
        account = f"{prefix}{seq:03d}"
        email = account
        
        # 检查账号重复
        if user_store.get_by_email(email):
            duplicate_accounts.append(account)
            continue
        
        # 检查昵称重复
        if any(u.get("display_name") == account for u in users):
            duplicate_names.append(account)
            continue
        
        # 创建用户
        raw_password = f"{account}{password_suffix}"
        user, _ = user_store.admin_create_user({
            "role": role,
            "display_name": account,
            "email": email,
            "student_id": account if role == "student" else None,
            "password": raw_password,
        })
        
        # 学生加入团队
        if role == "student" and target_team and uid:
            team_store.add_member(target_team["team_id"], uid)
        
        # 教师创建团队
        if role == "teacher" and payload.team_name and uid:
            final_team_name = payload.team_name
            if count > 1:
                final_team_name = f"{team_name}-{i + 1}"
            team_store.create_team_with_custom_code(
                teacher_id=uid,
                teacher_name=user.get("display_name"),
                team_name=final_team_name,
                invite_code=payload.team_invite_code if i == 0 else None,
            )
    
    return {
        "status": "ok",
        "count": len(created_users),
        "users": created_users,
        "passwords": password_list,
        "duplicates": duplicate_accounts,
        "duplicate_names": duplicate_names,
    }
```

#### 6.3.2 自定义教师批量创建

```python
@app.post("/api/admin/teachers/batch_with_teams")
def admin_batch_create_teachers_with_teams(payload: dict = Body(...)):
    teachers = payload.get("teachers")
    results = []
    
    for t in teachers:
        account = str(t.get("account", "")).strip()
        name = str(t.get("name", "")).strip()
        password = str(t.get("password", "")).strip()
        teams = t.get("teams", [])
        
        # 检查账号是否存在
        if user_store.get_by_email(account):
            results.append({"account": account, "success": False, "reason": "账号已存在"})
            continue
        
        # 创建教师账号
        user, _ = user_store.admin_create_user({
            "role": "teacher",
            "display_name": name,
            "email": account,
            "password": password,
        })
        
        # 创建团队
        for tm in teams:
            team_name = tm.get("team_name", "").strip()
            invite_code = tm.get("invite_code", "").strip().upper()
            
            team_store.create_team_with_custom_code(
                teacher_id=user["user_id"],
                teacher_name=name,
                team_name=team_name,
                invite_code=invite_code,
            )
        
        results.append({"account": account, "success": True})
    
    return {"results": results}
```

#### 6.3.3 CSV/Excel 导入

```python
@app.post("/api/admin/users/import_csv")
async def admin_import_users_csv(
    file: UploadFile = File(...),
    meta: str = Form(None),
    data: str = Form(None),
    request: Request = None
):
    # 1. 解析文件
    rows = []
    if file:
        content = await file.read()
        if file.filename.endswith(".csv"):
            rows = parse_csv(content)
        elif file.filename.endswith(".xlsx"):
            rows = parse_excel(content)
    
    if data:
        rows = json.loads(data)
    
    # 2. 校验字段
    required_fields = ["account", "name", "role"]
    for row in rows:
        for field in required_fields:
            if not row.get(field):
                errors.append({"row": row, "field": field, "reason": "必填字段缺失"})
    
    # 3. 创建用户和团队
    new_users = []
    new_teams = []
    for row in rows:
        # 创建用户
        user = user_store.admin_create_user({...})
        new_users.append(user)
        
        # 创建/加入团队
        if row.get("team_name"):
            team = team_store.create_team_with_custom_code(...)
            new_teams.append(team)
    
    # 4. 生成导入日志
    log_path = logs_dir / f"import_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}.json"
    log_path.write_text(json.dumps(log_obj, ensure_ascii=False, indent=2))
    
    return {
        "status": "ok",
        "total": len(rows),
        "success": success,
        "failed": failed,
        "errors": errors,
        "new_users": [u["user_id"] for u in new_users],
        "new_teams": [t["team_id"] for t in new_teams],
        "log": str(log_path.name),
    }
```

---

## 七、团队管理功能

### 7.1 团队数据模型

**文件位置**：[apps/backend/app/services/storage.py]

```python
class TeamStorage:
    def create_team(self, teacher_id: str, teacher_name: str, team_name: str) -> dict:
        team = {
            "team_id": str(uuid4()),
            "team_name": team_name.strip(),
            "invite_code": self._gen_invite_code(),  # 6位随机大写字母数字
            "teacher_id": teacher_id,
            "teacher_name": teacher_name,
            "members": [],  # 成员列表
            "created_at": _now_iso(),
        }
        teams.append(team)
        self._save(teams)
        return team
```

**团队字段说明**：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| team_id | string | 团队唯一标识（UUID） |
| team_name | string | 团队名称 |
| invite_code | string | 邀请码（4-10位大写字母数字） |
| teacher_id | string | 教师用户 ID |
| teacher_name | string | 教师姓名 |
| members | array | 成员列表 [{user_id, joined_at}] |
| created_at | string | 创建时间（ISO 8601） |

### 7.2 团队管理 API

#### 7.2.1 创建团队

```python
@app.post("/api/teams")
def create_team(payload: TeamCreatePayload) -> TeamResponse:
    user = user_store.get_by_id(payload.teacher_id)
    if not user or user.get("role") != "teacher":
        raise HTTPException(status_code=403, detail="仅教师可创建团队")
    
    team = team_store.create_team_with_custom_code(
        teacher_id=payload.teacher_id,
        teacher_name=payload.teacher_name,
        team_name=payload.team_name,
        invite_code=payload.invite_code,
    )
    return TeamResponse(team=team)
```

#### 7.2.2 查询团队列表

```python
@app.get("/api/teams")
def list_teams(role: str = "", user_id: str = "") -> dict:
    if role == "teacher" and user_id:
        teams = team_store.list_by_teacher(user_id)
    elif role == "student" and user_id:
        teams = team_store.list_by_member(user_id)
    else:
        teams = team_store.list_all()
    
    for t in teams:
        t["member_count"] = len(t.get("members", []))
    
    return {"teams": teams}
```

#### 7.2.3 加入团队

```python
@app.post("/api/teams/join")
def join_team(payload: TeamJoinPayload) -> TeamResponse:
    team = team_store.find_by_invite_code(payload.invite_code)
    if not team:
        raise HTTPException(status_code=404, detail="邀请码无效或团队不存在")
    
    updated = team_store.add_member(team["team_id"], payload.user_id)
    return TeamResponse(team=updated or team)
```

#### 7.2.4 删除团队成员

```python
@app.delete("/api/teams/{team_id}/members/{user_id}")
def remove_team_member(team_id: str, user_id: str, teacher_id: str = "") -> TeamResponse:
    team = team_store.get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="团队不存在")
    
    if team.get("teacher_id") != teacher_id:
        raise HTTPException(status_code=403, detail="无权操作")
    
    updated = team_store.remove_member(team_id, user_id)
    return TeamResponse(team=updated)
```

#### 7.2.5 删除团队

```python
@app.delete("/api/teams/{team_id}")
def delete_team(team_id: str, teacher_id: str = "") -> dict:
    if not teacher_id:
        raise HTTPException(status_code=400, detail="需提供 teacher_id")
    
    ok = team_store.delete_team(team_id, teacher_id)
    if not ok:
        raise HTTPException(status_code=404, detail="团队不存在或无权删除")
    
    return {"status": "ok"}
```

### 7.3 管理员团队管理

#### 7.3.1 教师团队管理界面

管理员可以为教师管理团队：

```typescript
// 打开教师团队管理器
function openTeacherTeamManager(teacherId: string, teacherName: string) {
  setManageTeacherId(teacherId);
  setManageTeacherName(teacherName);
  setShowTeamManager(true);
}

// 创建教师团队
async function createTeacherTeam() {
  const payload = {
    teacher_id: manageTeacherId,
    teacher_name: manageTeacherName,
    team_name: newTeamName.trim(),
    invite_code: newTeamInviteCode.trim().toUpperCase(),
  };
  
  const r = await fetch(`${API}/api/teams`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  
  await Promise.all([loadTeams(), loadUsers()]);
}

// 删除教师团队
async function deleteTeacherTeam(teamId: string, teacherId: string) {
  const url = `${API}/api/teams/${teamId}?teacher_id=${encodeURIComponent(teacherId)}`;
  const r = await fetch(url, { method: "DELETE" });
  
  await Promise.all([loadTeams(), loadUsers()]);
}
```

#### 7.3.2 团队成员管理

```typescript
// 添加成员到团队
async function addMemberToTeam() {
  const payload = {
    user_id: newMemberUserId.trim(),
    invite_code: String(team.invite_code).toUpperCase(),
  };
  
  const r = await fetch(`${API}/api/teams/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  
  await Promise.all([loadTeams(), loadUsers()]);
}

// 从团队移除成员
async function removeMemberFromTeam(teamId: string, teacherId: string, userId: string) {
  const url = `${API}/api/teams/${teamId}/members/${userId}?teacher_id=${encodeURIComponent(teacherId)}`;
  const r = await fetch(url, { method: "DELETE" });
  
  await Promise.all([loadTeams(), loadUsers()]);
}
```

### 7.4 邀请码机制

#### 7.4.1 邀请码生成

```python
@staticmethod
def _gen_invite_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(6))
```

**特性**：
- 6 位随机大写字母和数字
- 使用 `secrets` 模块确保密码学安全
- 自动检测并避免重复

#### 7.4.2 自定义邀请码

```python
def create_team_with_custom_code(
    self,
    teacher_id: str,
    teacher_name: str,
    team_name: str,
    invite_code: str | None = None,
) -> dict:
    if invite_code:
        code = invite_code.strip().upper()
        if len(code) < 4 or len(code) > 10:
            raise ValueError("邀请码长度需在 4-10 位之间")
        if any(t.get("invite_code") == code for t in teams):
            raise ValueError("邀请码已存在，请更换")
    else:
        code = self._gen_invite_code()
        while any(t.get("invite_code") == code for t in teams):
            code = self._gen_invite_code()
    
    # 创建团队...
```

**自定义邀请码规则**：
- 长度：4-10 位
- 格式：大写字母和数字
- 唯一性：系统全局唯一

---

## 八、数据模型定义

### 8.1 用户相关模型

**文件位置**：[apps/backend/app/schemas.py]

#### 8.1.1 用户注册模型

```python
class AuthRegisterPayload(BaseModel):
    role: Literal["student", "teacher", "admin"] = "student"
    display_name: str = Field(min_length=2, max_length=50)
    email: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=6, max_length=64)
    student_id: str | None = None
    class_id: str | None = None
    cohort_id: str | None = None
    bio: str | None = ""
```

#### 8.1.2 用户登录模型

```python
class AuthLoginPayload(BaseModel):
    email: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=6, max_length=64)
```

#### 8.1.3 管理员创建用户模型

```python
class AdminUserCreatePayload(BaseModel):
    role: Literal["student", "teacher", "admin"] = "student"
    display_name: str = Field(min_length=1, max_length=50)
    email: str = Field(min_length=1, max_length=100)
    password: Optional[str] = Field(default=None, max_length=64)
    student_id: Optional[str] = None
    class_id: Optional[str] = None
    cohort_id: Optional[str] = None
    bio: Optional[str] = ""
```

#### 8.1.4 管理员更新用户模型

```python
class AdminUserUpdatePayload(BaseModel):
    role: Optional[Literal["student", "teacher", "admin"]] = None
    display_name: Optional[str] = None
    email: Optional[str] = None
    student_id: Optional[str] = None
    class_id: Optional[str] = None
    cohort_id: Optional[str] = None
    bio: Optional[str] = None
    status: Optional[Literal["active", "disabled"]] = None
```

#### 8.1.5 批量创建用户模型

```python
class AdminBatchCreateUsersPayload(BaseModel):
    role: Literal["student", "teacher"] = "student"
    prefix: str = Field(min_length=1, max_length=32)
    start_index: int = Field(default=1, ge=1, le=100000)
    count: int = Field(default=1, ge=1, le=500)
    password_suffix: str = Field(default="123", max_length=64)
    invite_code: Optional[str] = None
    team_name: Optional[str] = None
    team_invite_code: Optional[str] = None
```

### 8.2 团队相关模型

#### 8.2.1 创建团队模型

```python
class TeamCreatePayload(BaseModel):
    teacher_id: str
    teacher_name: str = ""
    team_name: str = Field(min_length=1, max_length=100)
    invite_code: Optional[str] = None
```

#### 8.2.2 加入团队模型

```python
class TeamJoinPayload(BaseModel):
    user_id: str
    invite_code: str = Field(min_length=4, max_length=10)
```

#### 8.2.3 更新团队模型

```python
class TeamUpdatePayload(BaseModel):
    teacher_id: str
    team_name: str = Field(min_length=1, max_length=100)
```

---

## 九、安全特性

### 9.1 密码安全

- **哈希算法**：PBKDF2-SHA256
- **迭代次数**：120,000
- **盐值**：每个用户独立的 16 字节随机盐
- **最小长度**：6 位
- **自动生成**：管理员创建用户时如未提供密码，自动生成 10 位随机密码

### 9.2 访问控制

- **角色验证**：[useAuth] Hook 自动验证用户角色
- **路由保护**：未授权访问自动重定向到登录页
- **权限日志**：记录所有未授权访问尝试
- **API 权限**：后端验证用户身份和角色

### 9.3 数据验证

- **输入验证**：Pydantic 模型自动验证输入
- **唯一性校验**：邮箱、昵称、学号全局唯一
- **格式校验**：邀请码长度、密码长度等
- **SQL 注入防护**：使用 JSON 存储，无 SQL 风险

### 9.4 审计日志

- **登录日志**：记录所有登录尝试（成功/失败）
- **访问日志**：记录 API 访问记录
- **导入日志**：记录批量导入操作
- **日志存储**：`data/logs/access_logs.json`

---

## 十、API 端点汇总

### 10.1 认证相关

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 用户注册 |
| POST | `/api/auth/login` | 用户登录 |
| POST | `/api/auth/change-password` | 修改密码 |
| PATCH | `/api/auth/me/student-id` | 设置学号 |

### 10.2 用户管理（管理员）

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/admin/users` | 查询用户列表 |
| POST | `/api/admin/users` | 创建单个用户 |
| PATCH | `/api/admin/users/{user_id}` | 更新用户信息 |
| DELETE | `/api/admin/users/{user_id}` | 删除用户 |
| POST | `/api/admin/users/{user_id}/password` | 重置用户密码 |
| POST | `/api/admin/users/batch` | 批量创建用户 |
| POST | `/api/admin/users/import_csv` | CSV/Excel 导入用户 |
| POST | `/api/admin/teachers/batch_with_teams` | 批量创建教师及团队 |

### 10.3 团队管理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/teams` | 查询团队列表 |
| POST | `/api/teams` | 创建团队 |
| PATCH | `/api/teams/{team_id}` | 更新团队信息 |
| DELETE | `/api/teams/{team_id}` | 删除团队 |
| POST | `/api/teams/join` | 加入团队 |
| DELETE | `/api/teams/{team_id}/members/{user_id}` | 移除团队成员 |

### 10.4 教师相关

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/admin/teachers` | 查询教师列表及绩效 |

### 10.5 日志相关

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/admin/logs` | 查询访问日志 |
| POST | `/api/admin/logs/unauthorized` | 记录未授权访问 |

---

## 十一、使用指南

### 11.1 用户注册流程

1. 访问 [/auth/register] 页面
2. 选择角色（学生/教师/管理员）
3. 填写昵称、账号、密码
4. 提交注册表单
5. 系统自动跳转到对应工作台
6. 在个人中心完善学号、班级等信息

### 11.2 管理员批量创建学生

1. 登录管理员控制台
2. 进入"用户管理"标签页
3. 点击"批量创建"按钮
4. 选择角色为"学生"
5. 设置账号前缀（如 "stu"）
6. 设置起始序号（如 1）
7. 设置创建数量（如 50）
8. 设置密码后缀（如 "123"）
9. （可选）填写团队邀请码自动加入团队
10. 提交创建，系统生成账号列表

### 11.3 管理员批量创建教师

1. 登录管理员控制台
2. 进入"用户管理"标签页
3. 点击"批量创建"按钮
4. 选择角色为"教师"
5. 进行"自定义批量创建"
6. 逐个填写教师下属的团队信息
7. 提交创建

### 11.4 CSV/Excel 导入用户

1. 准备 CSV/Excel 文件，包含字段：account, name, role, email, team_name, invite_code, password
2. 登录管理员控制台
3. 进入"用户管理"标签页
4. 点击"批量导入"按钮
5. 拖拽文件到上传区域或点击选择文件
6. 预览导入数据（前 20 条）
7. 提交导入
8. 查看导入结果和日志

### 11.5 教师创建团队

1. 登录教师控制台
2. 进入团队管理页面
3. 点击"创建团队"按钮
4. 填写团队名称
5. （可选）自定义邀请码
6. 提交创建
7. 将邀请码分享给学生加入团队

### 11.6 学生加入团队

1. 获取教师提供的邀请码
2. 在个人中心或团队页面输入邀请码
3. 提交加入申请
4. 系统自动验证并加入团队

---

## 十二、常见问题

### 12.1 注册相关问题

**Q: 注册时提示"该账号名已存在"？**
A: 该邮箱/账号已被其他用户使用，请更换账号或联系管理员。

**Q: 注册后无法登录？**
A: 请检查账号和密码是否正确，密码区分大小写。如仍无法登录，联系管理员重置密码。

### 12.2 批量创建相关问题

**Q: 批量创建时部分账号未创建成功？**
A: 可能是账号或昵称重复。系统会返回重复的账号列表，请调整前缀或序号范围后重试。

**Q: 如何批量创建已有团队的学生？**
A: 在批量创建时填写团队的邀请码，创建的学生会自动加入该团队。

### 12.3 团队管理相关问题

**Q: 邀请码无效？**
A: 请检查邀请码是否正确（区分大小写），或联系教师确认邀请码是否已过期。

**Q: 如何将学生从一个团队转移到另一个团队？**
A: 需要先从原团队移除学生，然后使用新团队的邀请码重新加入。

### 12.4 权限相关问题

**Q: 学生可以访问教师端吗？**
A: 不可以。系统通过 [useAuth] Hook 严格验证用户角色，不匹配时会自动重定向到登录页。

**Q: 如何修改用户权限？**
A: 管理员可以在用户管理页面修改用户角色，将学生提升为教师或管理员。

---

## 十三、总结

BDSC 平台的用户管理系统具有以下特点：

1. **完整的用户生命周期管理**：从注册、登录到删除的全流程支持
2. **灵活的角色权限体系**：学生、教师、管理员三种角色，权限清晰
3. **强大的批量操作能力**：支持规则化批量创建、自定义批量创建、CSV/Excel 导入
4. **便捷的团队管理**：邀请码机制、成员管理、教师团队关联
5. **完善的安全机制**：密码哈希、访问控制、审计日志
6. **友好的用户界面**：分屏设计、加载状态、错误提示

系统采用 JSON 文件存储，便于部署和维护，适合中小规模的教育机构使用。后续如需扩展到大规模用户，可迁移到数据库存储。