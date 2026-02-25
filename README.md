# crawljav GUI 操作教程

<p><b>如果 crawljav 让您的使用更便捷，可以考虑为我买杯咖啡。这将有助于持续更新！<br>通过微信或者支付宝支持：</b></p>
  <table align="center" border="0" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center">
        <img src="docs/assets/wechat-sponsor.png" alt="WeChat Pay" height="160"><br>
        <sub><b>WeChat Pay</b></sub>
      </td>
      <td align="center">
        <img src="docs/assets/alipay-sponsor.png" alt="Alipay" height="160"><br>
        <sub><b>Alipay</b></sub>
      </td>
    </tr>
  </table>

## 1. 打开程序（发布版）

### macOS

1. 下载并解压发布包。
2. 双击 `crawljav.app` 启动。
3. 如遇系统安全提示，前往“系统设置 -> 隐私与安全性”中允许运行后再次打开。

### Windows

1. 下载并解压发布包。
2. 双击 `crawljav.exe` 启动。
3. 如遇 SmartScreen 提示，点击“更多信息 -> 仍要运行”。

说明：

1. 抓取模式支持 `browser`（默认）和 `httpx`。
2. `browser` 模式依赖本机已安装 Chrome 或 Edge。
3. `browser/httpx` 两种模式都要求可读取且有效的 `cookie.json`。

## 2. 首次使用（设置页）

进入“设置”页，先完成以下默认参数：

1. `Cookie` 路径（通常是 `cookie.json`）。
2. `数据库` 路径（通常是 `userdata/actors.db`）。
3. `输出目录`（通常是 `userdata/magnets`）。
4. `站点域名`（默认 `javdb`）。
5. `抓取模式`（建议先用 `browser`）。
6. 可按需设置浏览器会话目录、无头模式、超时参数。

然后点击“保存”。

注意：
1. 若 `cookie.json` 缺失、格式错误或关键字段无效，程序会阻断抓取启动。
2. 会员内容（尤其部分磁链）依赖登录态 Cookie。

## 3. 流程页操作

在“流程”页按需勾选阶段并执行：

1. 抓取收藏列表
2. 抓取作品列表
3. 抓取磁链
4. 磁链筛选

常用步骤：

1. 先勾选收藏与作品，完成基础数据入库。
2. 再勾选磁链抓取与筛选，生成结果。
3. 点击“开始”执行，日志区域实时查看进度与错误。
4. 需要中止时点击“停止”。

## 4. 数据浏览页操作

在“数据浏览”页可进行：

1. 按演员查看作品与磁链。
2. 搜索、排序与筛选。
3. 复制番号、标题、磁链。
4. 多选作品并批量导出磁链。
5. 编辑番号/标题并写回数据库。

## 5. 常见问题

1. `httpx` 模式提示 Cookie 无效：
   检查 `cookie.json` 是否可读、是否过期。
2. `browser` 模式也要求有效 Cookie：
   与 `httpx` 一样，需要更新 `cookie.json` 后再启动。
3. `browser` 模式无法启动：
   确认本机已安装 Chrome 或 Edge。
4. 抓取结果异常：
   先在设置页确认站点域名和 Cookie，再重试。
