# FeelUOwn QQ 音乐 Cookie 自动续期插件

这是一个配套插件，不替代官方的 `fuo-qqmusic`。它读取 FeeluOwn QQ 音乐插件保存的 `qqmusic_user_info.json`，调用 QQ 音乐移动端 `music.login.LoginServer.Login` 接口，成功后把新的 `musickey` 写回 `qqmusic_key`，并同步已经加载的 QQ 音乐 provider。

## 安装

当前仓库尚未发布到 PyPI。可以直接从公开 GitHub 仓库安装。推荐先克隆，然后在 FeelUOwn 使用的同一个 Python 环境中安装：

```bash
git clone https://github.com/XingNian-www/feeluown-qqmusic-refresh.git
cd feeluown-qqmusic-refresh
python -m pip install -e .
```

也可以直接安装：

```bash
python -m pip install "git+https://github.com/XingNian-www/feeluown-qqmusic-refresh.git"
```

插件会通过 `fuo.plugins_v1` 自动发现。需要同时安装官方 QQ 音乐 provider：

```bash
pip install fuo-qqmusic
```

## 配置

先在 FeelUOwn 中登录 QQ 音乐，并确认生成了 `qqmusic_user_info.json`。插件默认读取同一数据目录下的这个文件，不需要复制 cookie。

可在 `~/.fuorc` 中调整：

```python
config.qqmusic_refresh.Enabled = True
config.qqmusic_refresh.IntervalHours = 24
```

如果浏览器 cookie 没有 `psrf_qqopenid`、`psrf_qqaccess_token`、`psrf_qqrefresh_token` 或 `refresh_key`，可以把这些值放在配置中。更推荐先从 QQ 音乐登录请求中获取完整字段，不要把 cookie 提交给第三方接口。

注意：`refresh_key` 不是由 `qqmusic_key` 本地计算出来的值。QQ 音乐移动端续期接口把 `refresh_token` 或 `refresh_key` 当作已有登录凭据；普通网页登录成功只代表 Cookie 可用，不保证会产生这两个字段。右键的“查看 Cookie 状态”会分别显示 `openid`、`access_token`、`refresh_token`、`refresh_key` 是否存在，不会显示值。

```python
config.qqmusic_refresh.OpenID = "..."
config.qqmusic_refresh.AccessToken = "..."
config.qqmusic_refresh.RefreshToken = "..."
config.qqmusic_refresh.RefreshKey = "..."
```

`config.qqmusic_refresh.HideUnavailableSearchResults = True`（默认值）会静默隐藏前 5 个检测结果中确认没有音源的歌曲；设为 `False` 时仍会检测并缓存状态，但保留搜索结果。

启动后会立即尝试一次，之后按 `IntervalHours` 重试。续期状态和模拟设备信息分别保存在：

- `fuo_qqmusic_refresh.json`
- `fuo_qqmusic_refresh_device.json`

它们位于 FeelUOwn 的数据目录中。插件不会把真实 cookie 写入仓库或日志。

## QQ 音乐右键菜单

重启 FeelUOwn 后，在侧边栏的 QQ 音乐提供方头像上点击右键，可以使用：

- **查看 Cookie 状态**：查看本地 Cookie 文件、音乐密钥、自动监控和最近刷新结果。
- **检测 Cookie 可用性**：使用当前 Cookie 请求 QQ 音乐用户接口，确认登录态是否有效。
- **强制更新 Cookie**：立即调用移动端续期接口，写回新的 `qqmusic_key`，并同步当前 QQ 音乐 provider。

强制更新至少需要 Cookie 或配置中的 `refresh_token` / `refresh_key` 之一。只有 `uin` 和 `qqmusic_key` 的 Cookie 仍可做有效性检测，但不能执行续期。

右键菜单由本插件注入官方 QQ 音乐 provider UI，不需要修改 `fuo-qqmusic` 源码。更新插件后需要重启 FeelUOwn，才能让插件管理器重新加载入口。

搜索结果会自动检查前 5 首歌曲的最低音质 MP3（`M500`）。每首歌曲最多请求一次，结果缓存 15 分钟；确认没有可用地址时会从搜索结果中静默隐藏。网络请求失败会保留歌曲，不会误判为歌曲没有版权。

全新网页登录时，插件会自动保留登录窗口一小段时间，收集登录后延迟写入的完整 Cookie；如果网页跳转包含 QQ 音乐登录回调 code，还会在本机交换登录响应，并合并 `psrf_qqrefresh_token` 或 `refresh_key`（如果 QQ 音乐服务器返回）。这些字段不会输出到日志，也不会发送到第三方服务。

## 手动诊断

```bash
fuo exec "import fuo_qqmusic_refresh as p; p.refresh_now()"
```

这会执行一次同步刷新，适合诊断网络或字段问题。QQ 音乐移动端接口和 QIMEI 服务都可能变化，续期失败时请查看 FeelUOwn 日志中的返回 code；日志不会输出 token 内容。

其中 `refresh_ready` 为 `False` 时，当前网页登录 Cookie 可以检测，但不能走本插件的移动端续期流程；需要重新获取包含 `psrf_qqrefresh_token` 或 `refresh_key` 的登录响应字段。

查看续期状态：

```bash
fuo exec "import pprint, fuo_qqmusic_refresh as p; pprint.pp(p.status())"
```

状态会记录在 `fuo_qqmusic_refresh.json` 的 `status` 字段中，包括最近一次尝试、成功时间、失败原因、下一次执行时间和当前 cookie 是否存在。状态查询不会输出 token。

## 开发测试

```bash
python -m unittest discover -s tests
```

测试只覆盖本地字段映射和请求构造，不会访问 QQ 音乐。
