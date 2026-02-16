# crawljav（GUI 版）

基于 PyQt5 的 JavDB 收藏抓取与数据浏览工具。
当前以 GUI 为唯一入口，不再维护 CLI 工作流。

---

## 一、功能概览

- GUI 一键流程：收藏抓取 -> 作品抓取 -> 磁链抓取 -> 磁链筛选
- 收藏维度支持：`actor / series / maker / director / code`
- 抓取模式：`browser`（默认，Playwright）与 `httpx`
- 数据浏览能力：搜索、排序、筛选、批量导出、右键复制、作品编辑
- 本地 SQLite 存储，支持断点续跑与历史记录

---

## 二、环境准备（Conda）

```bash
conda create -n crawljav python=3.11 -y
conda activate crawljav

# macOS / Linux
pip install -r requirements-mac.txt

# Windows
pip install -r requirements-win.txt
```

可选兼容安装：

```bash
pip install -r requirements.txt
```

---

## 三、启动 GUI

```bash
python gui.py
```

首次使用建议：

1. 在“设置”页配置 Cookie、数据库路径、输出目录。
2. 抓取模式优先使用 `browser`。
3. 如遇浏览器依赖问题，执行：

```bash
python -m playwright install chromium
```

---

## 四、GUI 流程说明

### 1. 流程页

- 勾选要执行的阶段（收藏、作品、磁链、筛选）
- 选择收藏维度（`actor / series / maker / director / code`）
- 点击“开始”直接执行（无二次确认弹窗）

### 2. 数据浏览页

- 按演员查看作品与磁链
- 支持作品多选导出磁链
- 支持复制番号/标题/磁链
- 支持番号/标题编辑并写回数据库

### 3. 设置页

- 默认参数管理
- Cookie 校验与保存
- 历史记录查看

---

## 五、代码结构（已分层）

```text
app/
  gui/            # GUI 入口、页面、配置读写、数据视图
  collectors/     # 收藏抓取链路与维度注册
    dimensions/   # actor/series/maker/director/code 五维度适配
  core/           # 配置、抓取运行时、存储、通用工具
  exporters/      # 磁链筛选导出
```

入口说明：
- 根目录只保留 `gui.py` 作为 GUI 启动入口。
- 业务与基础能力全部在 `app/` 下开发与维护。

---

## 六、后续模块规划（非 actor 收藏）

在现有 `actor` 基础上，后续继续强化以下 4 个模块：

- `series`（系列）
- `director`（导演）
- `maker`（片商）
- `code`（番号）

建议统一沿用 `app/collectors/` 下的同构流程：
- 收藏抓取
- 作品抓取
- 磁链抓取
- GUI 展示与筛选

---

## 七、输出与数据目录

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

数据库主要表：
- `actors / works / magnets`
- `collections / collection_works / collection_magnets`

---

## 八、注意事项

- 请遵守目标站点使用条款及相关法律法规。
- 请控制抓取频率，避免高并发或短时间高频请求。
- `cookie.json` 为敏感文件，不要上传到公开仓库。
