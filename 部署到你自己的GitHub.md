# 把网站部署到你自己的 GitHub（一次性，约 20 分钟）

现在这个网站跑在 Dave 的 GitHub 账号下（`daveliao999.github.io`）。
交接后你要让它跑在**你自己**的账号下，地址会变成 `https://你的用户名.github.io`。

这份文档全程不需要懂编程，**照着抄命令**即可。遇到卡壳截图找 Dave。

> 原理：GitHub 有个免费功能叫 **GitHub Pages**——你把网页文件放进一个特定名字的仓库，
> GitHub 就免费帮你托管成一个公网网站。我们的网站就是这么挂上去的。

---

## 第 1 步：注册 GitHub 账号
1. 打开 https://github.com/signup ，用邮箱注册，记住你的**用户名**（下面到处要用，假设叫 `yourname`）。
2. 注册后去邮箱点验证链接激活。

## 第 2 步：创建一个「用户主页」仓库
GitHub Pages 有个规则：**仓库名 = `你的用户名.github.io`** 时，网站地址就是 `https://你的用户名.github.io`（最干净）。

1. 登录后点右上角 `+` → **New repository**。
2. **Repository name** 填：`yourname.github.io`（把 `yourname` 换成你真实用户名，必须完全一致）。
3. 选 **Public**（公开）。
4. 不要勾「Add a README」。
5. 点 **Create repository**。

> ⚠️ 仓库是公开的 → **永远不要把 `deepseek_key.txt` 或任何密钥提交进去**。
> 本项目的 `.gitignore` 已经帮你排除了它，别去动那个文件。

## 第 3 步：装 Git 并登录（如果还没装）
- 下载 Git：https://git-scm.com/download/win ，一路默认安装。
- 第一次 `git push` 时会弹出 GitHub 登录窗口，用你刚注册的账号登录一次，之后自动记住。

先告诉 Git 你是谁（命令行执行一次，邮箱换成你的）：
```
git config --global user.name "yourname"
git config --global user.email "you@example.com"
```

## 第 4 步：把本文件夹变成你的仓库并推上去
打开「命令提示符」(cmd)，`cd` 进这个交接文件夹，然后**逐行**执行（把两处 `yourname` 换成你的用户名）：

```
cd %USERPROFILE%\Desktop\FCN_Watchlist_交接

git init
git add -A
git commit -m "init my FCN watchlist site"
git branch -M main
git remote add origin https://github.com/yourname/yourname.github.io.git
git push -u origin main
```

> 这里会弹 GitHub 登录窗口 → 用你的账号登录。
> 如果提示 `remote origin already exists`，先执行 `git remote remove origin` 再重跑那行 `git remote add`。

## 第 5 步：打开 GitHub Pages 开关
1. 浏览器进你的仓库 → 顶部 **Settings** → 左侧 **Pages**。
2. **Source** 选 **Deploy from a branch**。
3. **Branch** 选 `main`，文件夹选 `/ (root)`，点 **Save**。
4. 等 1–2 分钟，刷新这个 Pages 页面，顶部会出现绿色：
   **Your site is live at https://yourname.github.io**

打开那个地址，看到网站 = 部署成功 ✅

## 第 6 步：以后每周怎么更新
部署完成后，这个文件夹已经连着**你自己**的仓库了。以后每周：
**换 3 个 Excel → 双击 `更新网站.bat`**，它会自动 `git push` 到你的仓库，网站 1–2 分钟后自动更新。
（详见 `交接使用手册.md`）

---

## 常见问题

| 现象 | 处理 |
|------|------|
| `git push` 弹登录但失败 | GitHub 现在不能用账号密码，要用浏览器弹窗登录或 Personal Access Token。装 [Git for Windows] 自带的凭据管理器会自动弹浏览器，照着登录即可 |
| Pages 页面没有「Your site is live」 | 确认仓库名严格等于 `用户名.github.io`、是 Public、Branch 选了 `main` + `/root` |
| 打开网站是 404 | 确认仓库根目录有 `index.html`；等 2 分钟 GitHub 重建；Ctrl+F5 强刷 |
| 网站打开但没数据 | 确认 `watchlist.json` 也 push 上去了（`git status` 看有没有漏） |
| 想换个网站地址 | 也可以用普通仓库名（如 `fcn`）+ 开 Pages，地址会变成 `https://yourname.github.io/fcn`，但 `用户名.github.io` 最简洁 |

---

## 部署后建议做的两件小事
1. 把 `更新网站.bat` 最后那行提示里的地址，改成你真实的 `https://yourname.github.io`，方便以后核对。
2. 把你的网站地址发给 Dave 备案，确认显示正常。
