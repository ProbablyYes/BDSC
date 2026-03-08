# Web

## Run

```bash
npm install
npm.cmd run dev
```

Set `NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000` if needed.

## Troubleshooting

- If you see `Cannot find module './xxx.js'` in Next.js dev:

```bash
rmdir /s /q .next
npm.cmd run dev
```

## Pages

- `/` 首页角色分流
- `/student` 学生端
- `/teacher` 教师端
