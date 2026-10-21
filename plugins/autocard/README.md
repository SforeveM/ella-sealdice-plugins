# 海豹一键录卡 0.9.14

Excel 角色卡解析器、卡面绘图 HTTP 后端和 SeaDice JS 扩展。创作主页：https://afdian.com/a/SNOM6563

## 能做什么

- 识别多种 DND5E / 5R、COC7、门版宝可梦卡表；读取缓存值，不执行表格宏。
- 主动导入、预览、确认后写入当前绑定的角色卡。
- 生成训练家、伙伴与规则速查卡；提取 Drawing 和 Rich Data 嵌入头像。
- 可选的背景故事评分、头像归档与 AI Token 游戏币计费。

## 从源码启动

需要 Python 3.11+。在本目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
$env:AUTOCARD_API_TOKEN = Read-Host '设置后端令牌（可见输入）'
$env:AUTOCARD_PUBLIC_BASE_URL = 'https://autocard-api.example.com'
.\.venv\Scripts\python.exe -m autocard serve --host 127.0.0.1 --port 8765
```

将 `AUTOCARD_PUBLIC_BASE_URL` 改为自己的 HTTPS 反向代理地址。导入 `sealdice/一键录卡.js`，在扩展设置中填入本地服务地址和相同令牌，再重载 JS。

QQ 官方文件事件和图文按钮依赖对应核心接口。宝可梦原生卡配合本合集的助手 1.39.1，并需要支持旅伴卡的艾拉自编译核心。普通核心能否写入每种规则，请先核对接口；仓库不附带核心程序。

AI 评分默认不配置密钥。可在扩展设置中配置，或参考 `config/review-ai.example.ps1`。该文件只含示例，不含可用密钥。

## 玩家流程

上传受支持的卡表 → `.一键录卡 列表` → `.一键录卡 导入 最新` → 核对模板与角色 → `.一键录卡 同意`。只想补发图片可用 `.一键录卡 卡图`。

## 素材与测试

没有打包玩家原始表格、真实头像、付费字体、外部游戏图标和背景素材。无图标或背景包时会使用代码里的底色与文字布局，展示图也是用虚构数据生成。

`tests/test_core.py` 的可选图标包测试在未安装图标包时跳过；解析、Rich Data 头像、HTTP 服务及 JS 回归测试仍运行。测试命令见仓库根目录 `docs/VALIDATION.md`。
