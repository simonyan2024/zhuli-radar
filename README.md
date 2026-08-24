# 主力鉴 · 研究雷达

个人用上证主板研究雷达（分析 only，公开行情）。支持本地运行、Render 免费部署与 GitHub Actions 自动部署。

## 本地运行

```bash
pip install -r requirements.txt
python -m uvicorn server.main:app --host 127.0.0.1 --port 8765
```

打开 http://127.0.0.1:8765/

## GitHub Actions 自动化

仓库已包含：

| 工作流 | 文件 | 作用 |
|--------|------|------|
| CI | `.github/workflows/ci.yml` | 推送/PR 时安装依赖、导入检查、启动冒烟 |
| Deploy Render | `.github/workflows/deploy-render.yml` | 推送 `main`/`master` 时触发 Render 重新部署 |
| Deploy Railway | `.github/workflows/deploy-railway.yml` | 手动触发 Railway 部署 |

### 推荐：Render + Actions

**第一步：先让 Render 连上仓库（只需一次）**

1. [render.com](https://render.com) 用 GitHub 登录  
2. **New → Web Service** → 选本仓库  
3. Build: `pip install -r requirements.txt`  
4. Start: `uvicorn server.main:app --host 0.0.0.0 --port $PORT`  
5. Plan: **Free** → Create  

Render 本身也可在每次 git push 时自动部署；下面 Hook 用于「用 Actions 显式触发」。

**第二步：配置 Deploy Hook（给 Actions 用）**

1. Render 控制台 → 你的 Web Service → **Settings**  
2. 找到 **Deploy Hook**，复制 URL（形如 `https://api.render.com/deploy/srv-xxx?key=yyy`）  
3. GitHub 仓库 → **Settings** → **Secrets and variables** → **Actions**  
4. **New repository secret**  
   - Name: `RENDER_DEPLOY_HOOK`  
   - Value: 刚才的 Hook URL  

之后每次推送到 `main`/`master`，Actions 会 POST 该 Hook，Render 开始部署。  
也可在 GitHub **Actions** 页手动跑 **Deploy Render**。

**第三步：看结果**

- GitHub → **Actions** 看 CI / Deploy 是否绿勾  
- Render 仪表盘看 Deploy 日志  
- 手机打开 Render 给的 `https://xxx.onrender.com`

Free 实例闲置会休眠，唤醒可能需 30～60 秒。

### 可选：Railway

1. [railway.app](https://railway.app) 创建项目并关联仓库（或先 CLI link）  
2. 账户 Tokens 生成 token  
3. GitHub Secret：`RAILWAY_TOKEN`  
4. Actions 里手动运行 **Deploy Railway**

## 接口

- `GET /` 页面  
- `GET /api/health`  
- `GET /api/scan`  
- `GET /api/backtest`

## 说明

公开行情可能延迟或失败。不构成投资建议。
