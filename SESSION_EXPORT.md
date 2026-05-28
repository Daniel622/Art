# Obscura Studio 会话执行记录导出

导出时间：2026-05-27

说明：这是当前项目会话的可见执行记录摘要。Codex App 内部完整原始聊天数据库和所有历史会话不暴露给我直接读取；因此本文件整理的是本项目中已执行、已提交、已部署、可复现的关键记录。

## 项目信息

- 本地目录：`/Users/kuihe/Documents/Art`
- GitHub 仓库：`https://github.com/Daniel622/Art`
- GitHub Pages 外部介绍页：`https://daniel622.github.io/Art/`
- VPS 域名：`https://art.cba.pp.ua`
- VPS IP：`95.181.191.155`
- SSH 用户：`root`

## VPS 部署位置

- 应用代码目录：`/opt/obscura-studio`
- 数据目录：`/var/lib/obscura-studio`
- 图片目录：`/var/lib/obscura-studio/images`
- 环境变量文件：`/etc/obscura-studio/obscura.env`
- systemd 服务：`/etc/systemd/system/obscura-studio.service`
- 服务名：`obscura-studio`
- Caddy 配置：`/opt/proxy/caddy/Caddyfile`
- Caddy 配置备份：`/opt/proxy/caddy/Caddyfile.bak.*`

## 重要账号与入口

- 前台访问码：`PRIVATE-STUDIO`
- 后台入口：`https://art.cba.pp.ua/admin`
- 默认管理员：`admin`
- 默认管理员密码：`ChangeMe123!`

建议生产使用时立即修改默认管理员密码和访问码。

## 主要实现内容

- 从空 Git 仓库创建私密 AI 图像生成网站
- 使用 Python 标准库 HTTP server + SQLite + 静态前端
- 实现公开入口页
- 实现访问码登录、会话 Cookie、额度校验
- 实现图像生成工作台
- 实现参考图上传，最多 9 张
- 实现参考图缩略图和大图预览
- 实现生成任务卡、进度阶段、结果展示
- 实现作品历史
- 实现创作配方保存与复用
- 实现管理员后台
- 实现访问凭证管理
- 实现 API Provider 管理
- 实现模型拉取、手动添加、勾选启用、默认模型选择
- 保留 Provider 测试按钮
- 删除前台 API 设置
- 删除前台模型选择器
- 生成时自动使用后台默认/优先 Provider 和模型
- 实现 API Key 加密存储和脱敏显示
- 实现生成记录保存
- 实现图片保存到服务端本地目录
- 实现 GitHub Pages 静态介绍页
- 部署到 VPS 并绑定 `art.cba.pp.ua`
- 接入现有 Caddy 容器，只新增 `art.cba.pp.ua` 站点块

## Git 提交记录

```text
7dc084f Improve provider model selection
212113c Route image generation through admin defaults
212a638 Use admin-managed image providers
fb02dad Refine generator order panel
12b6bc1 Build private AI image studio
```

## 各提交概要

### `12b6bc1 Build private AI image studio`

创建首版项目：

- `.gitignore`
- `Makefile`
- `README.md`
- `server.py`
- `static/index.html`
- `static/app.js`
- `static/styles.css`
- `tests/test_core.py`
- `deploy/install.sh`
- `deploy/nginx.conf`
- `deploy/obscura.service`
- `docs/index.html`

### `fb02dad Refine generator order panel`

参考截图优化前台生图面板：

- 深色下单面板
- API 设置区初版
- 风格按钮宫格
- 质量/清晰度/比例按钮
- 底部“下单”按钮
- 尺寸参数映射

### `212a638 Use admin-managed image providers`

按要求删除前台 API 设置：

- 删除前台 API URL / API Key
- 模型和 Provider 改为管理员后台统一配置
- 参考图上限改为 9 张
- 图片预览状态修复

### `212113c Route image generation through admin defaults`

按要求删除前台模型选择器：

- 前台不再显示模型选择
- 后端自动选择后台默认/优先模型
- 吸收参考源码中的 1K/2K/4K 尺寸映射
- 反向提示词合并为 `--no ...`

### `7dc084f Improve provider model selection`

优化后台 Provider 与模型管理：

- 删除“模型 JSON”文本框
- 输入 API URL / Key 后可拉取模型
- 拉取模型后用列表展示
- 模型默认不全部启用
- 支持勾选启用模型
- 支持选择默认模型
- 支持手动添加模型
- 保留测试按钮

## 已执行的关键本地验证

```bash
make test
python3 -m unittest discover -s tests
node --check static/app.js
PYTHONPYCACHEPREFIX=/private/tmp/art-pycache python3 -m py_compile server.py
```

测试结果多次为：

```text
Ran 5 tests
OK
```

## 已执行的关键远端验证

```bash
systemctl is-active obscura-studio
cd /opt/obscura-studio && python3 -m unittest discover -s tests
curl -sS https://art.cba.pp.ua/api/config
curl -sS https://art.cba.pp.ua/app.js
```

验证过：

- `obscura-studio` 为 `active`
- `/api/config` 返回 `maxReferences: 9`
- 前台资源中没有 `API 设置`
- 前台资源中没有 `模型 (Model)` 选择器
- 后端不传模型也能生成，返回默认模型 `mock-vision-xl`
- 后台 Provider 模型选择器存在
- 后台旧的 `模型 JSON` 文本框已删除

## 部署方式

本地上传到 VPS 的方式：

```bash
tar --exclude='.git' \
  --exclude='data' \
  --exclude='__pycache__' \
  --exclude='friend-image-gen' \
  --exclude='pixelforge-source-20260527-083452.tar.gz' \
  -czf - . \
| ssh -i /private/tmp/obscura_vps_key.pem -o IdentitiesOnly=yes root@95.181.191.155 \
  'tar -xzf - -C /opt/obscura-studio && systemctl restart obscura-studio && sleep 1 && systemctl is-active obscura-studio'
```

## VPS 常用维护命令

```bash
ssh root@95.181.191.155
systemctl status obscura-studio
systemctl restart obscura-studio
journalctl -u obscura-studio -f
```

查看 Caddy：

```bash
docker logs caddy --tail 300
sed -n '1,260p' /opt/proxy/caddy/Caddyfile
tail -n 300 /opt/proxy/caddy/logs/art-access.log
```

查看数据：

```bash
ls -lah /var/lib/obscura-studio
ls -lah /var/lib/obscura-studio/images
sqlite3 /var/lib/obscura-studio/art.db '.tables'
```

## 参考源码

用户提供的参考源码：

- `/Users/kuihe/Documents/Art/pixelforge-source-20260527-083452.tar.gz`
- `/Users/kuihe/Documents/Art/friend-image-gen/`

处理方式：

- 只读取参考
- 未提交进 Git
- 部署时排除上传

## 当前 Git 状态备注

参考源码目录和压缩包仍是未跟踪文件：

```text
?? friend-image-gen/
?? pixelforge-source-20260527-083452.tar.gz
```

它们没有进入 GitHub 仓库，也没有部署到 VPS 应用目录。

