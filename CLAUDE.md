# CLAUDE.md — Agent 部署运行手册

> 你（Claude Code）正在帮一位**非技术用户**把这个 FCN Watchlist 网站部署到**他自己的 GitHub**，
> 并教会他每周更新。用户能复制粘贴、能点浏览器，但不懂编程。**用中文和他交流。**
> 详细背景见 `代码逻辑说明.md`、`交接使用手册.md`、`部署到你自己的GitHub.md`；本文件是给你执行用的精简runbook。

## 黄金规则
1. **凡是标 🧑 HUMAN 的步骤，你不能代做**——停下来，用一句话清楚告诉用户去做什么，等他说完成再继续。
2. 优先用命令行（`gh`、`git`、`python`），不要让用户去点 GitHub 网页（除非 `gh` 不可用时的兜底）。
3. **每步做完都验证**（命令退出码 / 文件存在 / 网址可访问），失败就停下解释，不要硬推。
4. 涉及密钥：`deepseek_key.txt` 绝不能被 commit。它已在 `.gitignore` 里，别动。
5. 全程不要把任何 key 写进会提交的文件。

## 开始前先问用户收集 3 样东西
- 🧑 **GitHub 用户名**（记为 `USERNAME`）
- 🧑 **DeepSeek API key**（向 Dave 索取后给你，你写进 `deepseek_key.txt`）
- 🧑 是否要用富途分析师数据（可选；要的话他需自己装并登录 Futu OpenD）

---

## 阶段 A：环境准备

1. 检查工具是否就绪：
   ```
   git --version
   python --version
   gh --version
   ```
2. 缺什么装什么（Windows 可用 winget，装完可能要重开终端让 PATH 生效）：
   ```
   winget install --id Git.Git -e
   winget install --id Python.Python.3.12 -e
   winget install --id GitHub.cli -e
   ```
   - `gh` 不是必须的；没有它就走阶段 C 的「兜底：纯 git + 网页」。
3. 装 Python 依赖：
   ```
   pip install -r requirements.txt
   ```
   验证：`pip show yfinance openai pandas` 都能查到。

## 阶段 B：配置 DeepSeek key
1. 🧑 找用户要 key。
2. 把 key 写进本目录 `deepseek_key.txt`（**只有一行，无引号无空格**）。
3. 验证：确认 `.gitignore` 里含 `deepseek_key.txt`（已有）；**绝不 `git add` 它**。

## 阶段 C：部署到用户自己的 GitHub

### 首选路径（有 gh）
1. 🧑 让用户完成浏览器授权登录（你发起，他点）：
   ```
   gh auth login
   ```
   （选 GitHub.com → HTTPS → Login with a web browser，用户在弹出的浏览器里点授权）
   验证：`gh auth status` 显示已登录。
2. 用「用户主页仓库」命名规则建仓库并推送（站点地址最干净 = `https://USERNAME.github.io`）：
   ```
   git init
   git add -A
   git commit -m "init my FCN watchlist site"
   git branch -M main
   gh repo create USERNAME.github.io --public --source=. --remote=origin --push
   ```
   - 若提示已存在 origin：先 `git remote remove origin` 再重试 `gh repo create`。
3. 开启 GitHub Pages（从 main 分支根目录发布）：
   ```
   gh api -X POST repos/USERNAME/USERNAME.github.io/pages -f "source[branch]=main" -f "source[path]=/"
   ```
   - 若返回 409/已存在则忽略；若 API 失败，转「兜底」第 3 步用网页开。
4. 验证上线（等 1–2 分钟，可能要重试几次）：
   ```
   curl -s -o NUL -w "%{http_code}" https://USERNAME.github.io
   ```
   返回 `200` = 成功。把地址 `https://USERNAME.github.io` 告诉用户打开确认。

### 兜底路径（没有 gh）
1. 🧑 让用户在浏览器手动建一个 **Public** 仓库，名字必须是 `USERNAME.github.io`，不要勾 README。
2. 推送：
   ```
   git init
   git add -A
   git commit -m "init my FCN watchlist site"
   git branch -M main
   git remote add origin https://github.com/USERNAME/USERNAME.github.io.git
   git push -u origin main
   ```
   🧑 首次 push 会弹浏览器登录，用户登录一次。
3. 🧑 让用户在仓库 **Settings → Pages → Source: Deploy from a branch → main / (root) → Save**。
4. 同上 `curl` 验证 `200`。

## 阶段 D：交付与教学
1. 跑一次快速自检（不必等完整 25 分钟）：
   ```
   python generate_watchlist.py --dry-run
   ```
   能正常跑前几只 = 环境通了。（要完整生成就去掉 `--dry-run`，约 25 分钟）
2. 告诉用户**以后每周**只需：换 3 个 Excel（`低波精选组.xlsx` / `高波精选组.xlsx` / `市场热度榜.xlsx`）→ 双击 `更新网站.bat`。
3. 🧑 提醒用户把 `更新网站.bat` 末尾的占位地址改成真实 `https://USERNAME.github.io`，并把地址发给 Dave 备案。

---

## 排错速查
| 现象 | 处理 |
|------|------|
| `gh auth login` 卡住 | 必须用户在浏览器点授权，这步你代替不了 |
| `git push` 被拒 / 认证失败 | GitHub 不支持账号密码，需浏览器授权或 PAT；让用户用 Git 凭据管理器弹窗登录 |
| Pages 不出现「site is live」| 仓库必须 Public、名字严格 `USERNAME.github.io`、Branch=main、root |
| 网站 200 但无数据 | 确认 `watchlist.json` 也 push 上去了（`git status` 别漏） |
| 生成脚本报「未找到 DeepSeek key」| `deepseek_key.txt` 不在本目录或内容不是单行 key |
| 报「Futu 连接失败」| 可忽略；想要分析师数据让用户开并登录 Futu OpenD 再重跑 |
| 详情页个别标的缺段落 | `python repair_watchlist.py` 后 `git add watchlist.json && git commit -m repair && git push` |
