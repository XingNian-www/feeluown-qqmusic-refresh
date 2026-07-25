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

```python
config.qqmusic_refresh.OpenID = "..."
config.qqmusic_refresh.AccessToken = "..."
config.qqmusic_refresh.RefreshToken = "..."
config.qqmusic_refresh.RefreshKey = "..."
```

启动后会立即尝试一次，之后按 `IntervalHours` 重试。续期状态和模拟设备信息分别保存在：

- `fuo_qqmusic_refresh.json`
- `fuo_qqmusic_refresh_device.json`

它们位于 FeelUOwn 的数据目录中。插件不会把真实 cookie 写入仓库或日志。

## 手动诊断

```bash
fuo exec "import fuo_qqmusic_refresh as p; p.refresh_now()"
```

这会执行一次同步刷新，适合诊断网络或字段问题。QQ 音乐移动端接口和 QIMEI 服务都可能变化，续期失败时请查看 FeelUOwn 日志中的返回 code；日志不会输出 token 内容。

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
