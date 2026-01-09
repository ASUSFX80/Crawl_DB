## crawljav 使用说明

抓取收藏演员、作品列表与磁链数据，写入 SQLite；支持全流程、分步执行或 GUI 操作。

### 快速开始

```bash
uv sync
uv run python main.py
```

如果你更偏好图形界面：

```bash
uv run python gui.py
```

### 环境准备

1. 安装依赖（推荐使用 [uv](https://github.com/astral-sh/uv)）：
   ```bash
   uv sync
   ```
2. 准备 `cookie.json`，内容示例：
   ```json
   {
     "cookie": "over18=1; cf_clearance=xxx; _jdb_session=yyy"
   }
   ```
3. 数据库初始化：首次运行 `main.py` 会自动创建 `userdata/actors.db` 并执行 `schema.sql`。

### 全流程（一键）

```bash
uv run python main.py \
  --tags s,d \
```

可用 `--tags` 筛选，`--skip-collect/works/magnets` 跳过阶段。

### GUI 运行

`gui.py` 集成了流程控制、日志、数据浏览与 Cookie 校验。

```bash
uv run python gui.py
```

### 分步运行

#### 1. 抓取收藏演员列表

```bash
uv run python get_collect_actors.py
```

写入 `actors` 表。

#### 演员作品

```bash
uv run python get_actor_works.py \
  --tags s,d \
  --actor-name 名1,名2 \\  # 可选，逗号分隔，默认抓全部
```

写入 `works` 表。

#### 磁链抓取

```bash
uv run python get_works_magnet.py \
  --actor-name 名1,名2 \\  # 可选，逗号分隔，默认抓全部
```

写入 `magnets` 表，`--actor-name` 可指定一人或多名演员（逗号分隔），默认抓全部（`main.py` 同默认）。

#### 磁链筛选

最佳磁链导出 TXT：

```bash
uv run python mdcx_magnets.py
# 仅处理当前目录，可用 --current-only
uv run python mdcx_magnets.py userdata/magnets/坂井なるは --current-only --db userdata/actors.db
```

- 递归遍历目录，为每位演员生成同名 TXT；已存在的磁链不会重复写入。
- `main.py` 全流程会在抓取后自动筛选一次。

### 常用参数

- `--cookie`：Cookie JSON 路径（默认 `cookie.json`）。
- `--db-path/--db`：SQLite 数据库路径（默认 `userdata/actors.db`）。
- `--magnets-dir/--output-dir`：TXT 导出根目录（默认 `userdata/magnets`）。
- `--tags`：作品标签过滤，逗号分隔（例如 `s` 或 `s,d`）。
- `--actor-name`：指定演员，逗号分隔。

### 常见问题

- **抓取 0 条**：多为 Cookie 失效，检查 `cf_clearance`，必要时看 `debug_*.html`。
- **访问频率**：已添加 0.8~1.6 s 随机延时，仍请适度使用。
- **中途断点**：抓取支持断点续跑，断点信息保存在 `userdata/checkpoints.json`。

### 目录结构

```
userdata/
  actors.db                  # SQLite 数据库（actors / works / magnets 三张表）
  magnets/                   # mdcx_magnets.py 输出的精选磁链 TXT 根目录
  history.jsonl              # 抓取历史记录
  checkpoints.json           # 断点信息
logs/
  2025-11-02.log             # 每日日志文件，自动追加
cookie.json                  # 你的登录 Cookie
schema.sql                   # 数据库结构定义（供手动初始化使用）
config.py / storage.py / utils.py 等核心脚本
```

### 日志说明

- 所有脚本默认输出到标准输出和 `logs/<当天日期>.log`，方便排查问题。
- 如果只运行单个脚本（例如 `mdcx_magnets.py`），也会自动创建相同的日志文件并追加内容。
