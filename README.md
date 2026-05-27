# Obscura Studio

一个面向私域用户的 AI 图像生成网站首版：公开入口页、访问凭证、创作工作台、参考图、任务可视化、作品历史、管理员后台、Provider/模型管理、SQLite 持久化和可部署运行脚本。

## 快速启动

```bash
python3 server.py
```

打开 `http://127.0.0.1:8080`。

默认访问凭证：`PRIVATE-STUDIO`

默认管理员：`admin` / `ChangeMe123!`

首次生产部署后请立刻通过环境变量修改默认密码、默认访问码和密钥。

## 环境变量

```bash
ART_HOST=0.0.0.0
ART_PORT=8080
ART_SECRET_KEY=replace-with-long-random-secret
ART_DATA_DIR=/var/lib/obscura
ART_IMAGE_DIR=/var/lib/obscura/images
ART_DB_PATH=/var/lib/obscura/art.db
ART_ADMIN_USER=admin
ART_ADMIN_PASSWORD=replace-me
ART_DEFAULT_ACCESS_CODE=PRIVATE-STUDIO
ART_PROVIDER_BASE_URL=https://api.example.com/v1
ART_PROVIDER_API_KEY=provider-key
ART_PROVIDER_MODEL=image-model-id
```

如果没有配置真实 Provider，系统会创建 `mock://local` Provider，用于完整验证流程。真实生成需要在后台配置 OpenAI-compatible 图片 API 或兼容返回结构的 Provider。

## 测试

```bash
make test
```

## systemd 示例

复制 `deploy/obscura.service` 到 `/etc/systemd/system/obscura.service`，按你的路径和用户修改后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now obscura
```

## Nginx 反向代理

复制 `deploy/nginx.conf` 中的 server block，修改域名后 reload Nginx。

## 数据安全

数据库和图片目录通过环境变量配置。部署脚本不会覆盖已有数据库、图片和密钥文件。API Key 会以本地密钥派生的可逆加密形式保存，并在后台默认脱敏显示。
