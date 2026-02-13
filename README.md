# crawljav 使用说明

抓取 JavDB 收藏对象、作品与磁链数据，支持：

- 命令行全流程执行
- 分阶段抓取
- GUI 可视化运行与数据浏览

---

## 一、功能概览

- 全流程抓取：收藏 -> 作品 -> 磁链 -> 磁链筛选
- 收藏维度扩展：`actor / series / maker / director / code`
- 双抓取模式：`httpx` 与 `browser`（Playwright 持久化会话）
- GUI 支持：
  - 作品多选批量导出磁链
  - 右键复制（番号/标题/磁链）
  - 番号/标题编辑并写回数据库
- 本地 SQLite 存储，支持断点续跑和历史记录

---

## 二、快速开始

### 1. 安装依赖

推荐使用 `uv`：

```bash
uv sync
```

如果使用 `pip`，可按平台安装：

```bash
# macOS
pip install -r requirements-mac.txt

# Windows
pip install -r requirements-win.txt

# 兼容入口（自动包含通用依赖）
pip install -r requirements.txt
```

### 2. 准备 Cookie

在项目根目录创建 `cookie.json`，示例：

```json
{
  "cookie": "over18=1; cf_clearance=xxx; _jdb_session=yyy"
}
```

### 3. 初始化并运行

```bash
uv run python main.py
```

---

## 三、运行方式

### 1. 一键全流程

```bash
uv run python main.py \
  --tags s,d
```

常见开关：

- `--skip-collect`
- `--skip-works`
- `--skip-magnets`
- `--collect-scope actor|series|maker|director|code`

浏览器模式示例：

```bash
uv run python main.py \
  --fetch-mode browser \
  --browser-user-data-dir userdata/browser_profile/javdb \
  --challenge-timeout-seconds 240
```

非演员维度示例：

```bash
uv run python main.py \
  --collect-scope series \
  --fetch-mode browser
```

### 2. GUI 运行

```bash
uv run python gui.py
```

GUI 流程页支持收藏维度切换；数据浏览页支持搜索、排序、筛选、批量导出、右键复制和作品编辑。

---

## 四、分步命令

### 1. 收藏抓取

```bash
uv run python get_collect_actors.py
```

调试响应落盘与对比：

```bash
uv run python get_collect_actors.py \
  --response-dump-path debug/collection_actors_runtime.html \
  --compare-with-path debug/collection_actors.html
```

抓取收藏系列：

```bash
uv run python get_collect_actors.py \
  --collect-scope series \
  --fetch-mode browser
```

说明：

- `collect-scope=actor` 写入 `actors`
- 其他维度写入 `collections`

### 2. 作品抓取（演员维度）

```bash
uv run python get_actor_works.py \
  --tags s,d \
  --actor-name 名1,名2
```

写入 `works`。

### 3. 作品抓取（非演员维度）

```bash
uv run python get_collect_scope_works.py \
  --collect-scope series \
  --fetch-mode browser
```

写入 `collection_works`。

### 4. 磁链抓取（演员维度）

```bash
uv run python get_works_magnet.py \
  --actor-name 名1,名2
```

写入 `magnets`。

### 5. 磁链抓取（非演员维度）

```bash
uv run python get_collect_scope_magnets.py \
  --collect-scope series \
  --fetch-mode browser
```

写入 `collection_magnets`。

### 6. 磁链筛选导出

```bash
uv run python mdcx_magnets.py
```

仅处理单目录：

```bash
uv run python mdcx_magnets.py userdata/magnets/坂井なるは --current-only --db userdata/actors.db
```

---

## 五、参数速查（主流程）

- `--cookie`：Cookie JSON 路径（默认 `cookie.json`）
- `--db-path`：数据库路径（默认 `userdata/actors.db`）
- `--magnets-dir`：导出目录（默认 `userdata/magnets`）
- `--tags`：作品标签过滤（如 `s,d`）
- `--collect-scope`：收藏维度（默认 `actor`）
- `--fetch-mode`：`httpx` 或 `browser`
- `--browser-user-data-dir`：浏览器会话目录
- `--browser-headless`：浏览器无头模式
- `--browser-timeout-seconds`：页面超时
- `--challenge-timeout-seconds`：人工验证等待时间

---

## 六、输出目录与数据文件

```text
userdata/
  actors.db
  magnets/
  history.jsonl
  checkpoints.json
logs/
  YYYY-MM-DD.log
debug/
  *.html / *.png
```

数据库包含：

- `actors / works / magnets`
- `collections / collection_works / collection_magnets`

---

## 七、浏览器模式说明

`browser` 模式用于 Cloudflare/登录校验场景。

- 优先复用持久化会话目录（手动过验证后可持续使用）
- 若环境缺少可用浏览器，请安装 Chromium：

```bash
uv run playwright install chromium
```

---

## 八、注意事项

- 请遵守目标站点使用条款及相关法律法规。
- 请控制抓取频率，避免高并发或短时间高频请求。
- `cookie.json` 为敏感文件，不要上传到公开仓库。

---

## 九、CI 打包说明

GitHub Actions 发布工作流：

- 平台：
  - `windows-2022` -> `windows-x64.zip`
  - `macos-14` -> `macos-arm64.dmg`
- 流程：
  1. 各平台构建并上传 artifact
  2. 统一聚合 artifact 并发布 GitHub Release

工作流文件：

`/.github/workflows/release.yml`

---

## 十、常见问题

### 1. 抓取 0 条或 403

- 优先使用 `--fetch-mode browser`
- 复用同一 `--browser-user-data-dir`
- 检查 Cookie 是否仍有效

### 2. GUI 点了停止无效

已支持可中断流程，若仍出现，请查看 `logs/` 日志定位具体阶段。

### 3. browser 模式报浏览器不可用

先确认本机有可用浏览器，再执行：

```bash
uv run playwright install chromium
```

