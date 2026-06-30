# GitHub Actions 部署指南（完整版 process.py + 榜单脚本 / uv / 云端自动跑）

> 适合你现在的情况：**没有服务器，也不想一直开电脑**。目标是在 GitHub Actions 上自动「全源爬取 → 聚合 → 筛两份榜单 → 推到 Gist」：
>
> - **干净家宽榜**：`clash_clean.yaml`，只保留住宅/家宽 IP，国家均衡，延迟最低 Top100；
> - **速度榜**：`clash_fast.yaml`，全部存活节点纯按延迟取 Top100。

---

## ⚠️ 先读：GitHub Actions 有封号 / 风控风险

论坛帖子里多次有人反馈：

- 有人 GitHub 大号被禁用 Actions；
- 有人小号直接被 ban；
- 也有人跑几个月没事。

**结论：**

1. 最稳妥：优先本地跑，见 [本地部署指南](本地部署指南.md)。
2. 一定要用 Actions：强烈建议使用**专门小号**，不要用主力 GitHub 账号。
3. 定时不要太频繁，建议每天一次或每 1～3 天一次，不要沿用两小时一次的高频玩法。

---

## 一、这份指南和官方 workflow 的区别

项目自带 workflow：

- `Collect` / `Refresh`：主要跑简化版 `collect.py`；
- `Process`：只跑 `process.py`，不包含 `rank.py` 榜单筛选；
- 默认依赖安装使用 `pip3 install -r requirements.txt`。

本指南：

- 跑**完整版** `process.py`；
- 再跑 `subscribe/scripts/rank.py` 生成两份精选榜单；
- 用 **uv** 安装依赖和执行 Python；
- 最后推送两份榜单到 Gist，客户端订阅 Gist raw 链接。

---

## 二、最终数据流

```text
自定义 workflow（rank.yaml）定时触发：
  1. uv run python -u subscribe/process.py -s config.json --overwrite
       ↓
     全源爬取 → data/raw.yaml
       ↓
  2. uv run python -u subscribe/scripts/rank.py
       ↓
     测延迟 + 住宅 IP 检测 + 国家均衡
       ↓
     data/clash_clean.yaml
     data/clash_fast.yaml
       ↓
  3. gh gist edit
       ↓
     推到你的 Gist
       ↓
  4. 客户端订阅 Gist raw 链接
```

---

## 三、准备清单

| 必需项 | 说明 |
|---|---|
| 一个 GitHub 账号 | 建议专门小号 |
| Fork 后的 aggregator 仓库 | 在你自己的账号下 |
| 一个 Gist | 存放 `clash_clean.yaml` 和 `clash_fast.yaml` |
| 一个 classic Token | 同时用于 GitHub 搜索和写入 Gist |
| 一个 ipapi.is API Key | 用于住宅 IP 检测 |
| `config.json` | 完整版 `process.py` 配置 |
| `.github/workflows/rank.yaml` | 自定义 Actions workflow |

---

## 四、部署步骤

### 第 1 步：Fork 项目

打开 <https://github.com/wzdnzd/aggregator>，点右上角 **Fork** 到你自己的账号。

### 第 2 步：启用 Actions

进入你 fork 后的仓库 → 顶部 **Actions** → 点击：

```text
I understand my workflows, go ahead and enable them
```

找不到 Actions 标签，通常说明你还在看作者原仓库，或者 fork 没成功。

### 第 3 步：禁用自带 workflow

本指南使用自己的 `rank.yaml`，所以建议禁用自带 workflow，避免重复消耗和误触发：

- `Collect`
- `Refresh`
- `Process`
- `Checkin`
- `Delete`

操作：Actions 页面左侧选择对应 workflow → 右上角 `···` → **Disable workflow**。

---

## 五、创建 Gist

1. 打开 <https://gist.github.com>；
2. 创建一个 secret gist；
3. 文件名随便，例如 `placeholder.txt`；
4. 内容写 `placeholder`；
5. 创建后 URL 类似：

```text
https://gist.github.com/yourname/8054c4b67509fde37574fc2a48561
```

记下：

```text
yourname = GitHub 用户名
gist_id  = 8054c4b67509fde37574fc2a48561
```

后面 Secrets 只需要填 `gist_id`。

---

## 六、创建 Token

使用 **classic token**：

1. 打开 <https://github.com/settings/tokens>；
2. 点击 **Generate new token (classic)**；
3. Note 随便填，例如 `aggregator`；
4. Expiration 选久一点；
5. Select scopes 勾选 **`gist`**；
6. Generate token 后复制 `ghp_...`，只显示一次。

说明：

- GitHub 公开代码搜索本身不需要特殊 scope，但 `GH_TOKEN` 可以提高限额；
- 推送 Gist 必须有 `gist` 权限。

---

## 七、注册 ipapi.is Key

1. 打开 <https://ipapi.is/>；
2. 注册账号；
3. 在控制台复制 API Key。

没有 Key 也能跑，但家宽榜准确性会下降，而且更容易受限流影响。

---

## 八、配置 Repository Secrets / Variables

进入你 fork 的仓库：

```text
Settings → Secrets and variables → Actions
```

### 8.1 Secrets

添加这些 **Repository secrets**：

| Name | Value | 用途 |
|---|---|---|
| `GH_TOKEN` | 第六步的 token | `process.py` 的 GitHub 爬虫 |
| `GIST_PAT` | 同一个 token | `gh gist edit` 推送榜单 |
| `IPAPI_IS_API_KEY` | 第七步的 key | `rank.py` 住宅 IP 检测 |
| `GIST_ID` | 第五步的 gist_id，只填 ID | 推送目标 Gist |

> `GH_TOKEN` 和 `GIST_PAT` 可以填同一个 token。分成两个名字只是为了 workflow 语义清晰。

### 8.2 Variables

添加这些 **Repository variables**：

| Name | Value | 推荐值 | 用途 |
|---|---|---:|---|
| `SKIP_ALIVE_CHECK` | `true` / `false` | `true` | 爬取阶段跳过测活，统一交给 `rank.py` |
| `ENABLE_SPECIAL_PROTOCOLS` | `true` / `false` | `true` | 是否保留 hysteria2 / vless / hysteria 等新协议 |

---

## 九、创建完整版配置 `config.json`

> 之前有些文档写 `crawl.json`，只是为了表达“这是爬取配置”。但 `process.py -s` 接收任意 JSON 文件名；官方 README 常用 `config.json`。为了降低小白困惑，本指南统一使用 **`config.json`**。

在 fork 仓库根目录新建 `config.json`：GitHub 网页上 **Add file → Create new file**，文件名填 `config.json`，内容如下：

```json
{
    "crawl": {
        "enable": true,
        "exclude": "",
        "threshold": 2,
        "singlelink": true,
        "github": {
            "enable": true,
            "pages": 5,
            "push_to": ["raw"]
        },
        "google": {
            "enable": true,
            "limits": 100,
            "push_to": ["raw"]
        },
        "yandex": {
            "enable": true,
            "within": 3,
            "pages": 5,
            "push_to": ["raw"]
        },
        "telegram": {
            "enable": true,
            "pages": 5,
            "users": {
                "jichang_list": {
                    "push_to": ["raw"]
                }
            }
        },
        "pages": []
    },
    "groups": {
        "raw": {
            "emoji": false,
            "list": true,
            "targets": {
                "clash": "raw-clash"
            }
        }
    },
    "storage": {
        "engine": "local",
        "items": {
            "raw-clash": {
                "fileid": "raw.yaml",
                "folderid": "data"
            }
        }
    }
}
```

提交到 `main` 分支。

### 配置关键点

```text
crawl.*.push_to = raw
        ↓
groups.raw
        ↓
groups.raw.targets.clash = raw-clash
        ↓
storage.items.raw-clash
```

这几处名字必须一致，否则 `process.py` 会报配置错误。

---

## 十、创建自定义 workflow：`.github/workflows/rank.yaml`

在 fork 仓库中新建文件：

```text
.github/workflows/rank.yaml
```

内容如下：

```yaml
name: Rank

on:
  schedule:
    - cron: "05 03 * * *"   # 每天 03:05，北京时间；不要太频繁，降低风控风险
  workflow_dispatch:

concurrency:
  group: ${{ github.repository }}-rank
  cancel-in-progress: true

env:
  TZ: Asia/Shanghai
  GH_TOKEN: ${{ secrets.GH_TOKEN }}
  IPAPI_IS_API_KEY: ${{ secrets.IPAPI_IS_API_KEY }}
  SKIP_ALIVE_CHECK: ${{ vars.SKIP_ALIVE_CHECK }}
  ENABLE_SPECIAL_PROTOCOLS: ${{ vars.ENABLE_SPECIAL_PROTOCOLS }}

jobs:
  rank:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          ref: main

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          architecture: "x64"

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Install dependencies
        run: uv pip install --system -r requirements.txt

      - name: Crawl
        run: uv run python -u subscribe/process.py -s config.json --overwrite

      - name: Rank
        run: uv run python -u subscribe/scripts/rank.py

      - name: Push to Gist
        env:
          GH_TOKEN: ${{ secrets.GIST_PAT }}
        run: |
          gh gist edit ${{ secrets.GIST_ID }} -a data/clash_clean.yaml
          gh gist edit ${{ secrets.GIST_ID }} -a data/clash_fast.yaml

      - name: Timestamp
        run: date
```

提交到 `main` 分支。

---

## 十一、手动运行一次验证

1. 进入 Actions；
2. 左侧选择 **Rank**；
3. 点击 **Run workflow**；
4. 等待运行完成。

检查日志：

- `Crawl`：应生成 `data/raw.yaml`；
- `Rank`：应打印可用节点数量、住宅节点数量、国家分布；
- `Push to Gist`：应成功更新 Gist。

运行完成后，打开你的 Gist，应能看到：

```text
clash_clean.yaml
clash_fast.yaml
```

---

## 十二、获取持久订阅地址

打开 Gist 中的 `clash_clean.yaml` → 点击 **Raw**。

Raw 地址一般会带版本 hash，例如：

```text
https://gist.githubusercontent.com/yourname/gist_id/raw/一串版本hash/clash_clean.yaml
```

把中间版本 hash 删除，得到持久地址：

```text
https://gist.githubusercontent.com/yourname/gist_id/raw/clash_clean.yaml
https://gist.githubusercontent.com/yourname/gist_id/raw/clash_fast.yaml
```

推荐优先订阅 `clash_clean.yaml`。

如果客户端报 `unsupported proxy type: hysteria2`：

1. 换 Clash Verge Rev / FlClash；或
2. 把 Repository variable `ENABLE_SPECIAL_PROTOCOLS` 改成 `false` 后重跑。

---

## 十三、如何调整频率和榜单数量

### 13.1 调整频率

修改 `.github/workflows/rank.yaml`：

```yaml
schedule:
  - cron: "05 03 * * *"
```

已设置 `TZ: Asia/Shanghai`，按北京时间理解即可。建议：

- 保守：每 2～3 天一次；
- 常用：每天一次；
- 不建议：每 2 小时一次，论坛里这类高频 Actions 有明显风控风险。

### 13.2 调整榜单数量

例如每份榜单 50 个、延迟上限 3000ms：

```yaml
      - name: Rank
        run: uv run python -u subscribe/scripts/rank.py -t 50 -d 3000
```

---

## 十四、爬取源推荐

结合帖子讨论和当前代码，推荐：

1. **主力：`github`**
   - 当前最稳；
   - 必须配置 `GH_TOKEN`；
   - `pages` 先设 5，结果少再加到 8～10。

2. **补充：`google` / `yandex`**
   - 能补到公开网页上的订阅；
   - 依赖 Actions runner 当时的网络可用性。

3. **可开但不要依赖：`telegram`**
   - 帖子里反复提到 `jichang_list` 频道后期失效 / 不稳定；
   - 开着没坏处，但不能把它当唯一来源。

4. **高质量进阶：`pages`**
   - 如果你自己找到固定分享页，把它加入 `pages`；
   - 比盲搜更稳定，但需要维护 URL。

5. **不推荐小白先开：`twitter` / `repositories`**
   - `twitter` 受登录和反爬影响较大；
   - `repositories` 需要你知道具体仓库。

---

## 十五、常见问题排查

| 现象 | 原因 / 解决 |
|---|---|
| Actions 里没有 Rank | `.github/workflows/rank.yaml` 路径或 YAML 缩进写错 |
| `cannot start crawl from github` | `GH_TOKEN` secret 没配或无效 |
| `data/raw.yaml` 不存在 | 没爬到任何节点；调大 `pages`，或检查配置 / 网络 |
| Telegram 没结果 | 正常，帖子里已反馈 `jichang_list` 可能失效 |
| 家宽榜为空 | 免费节点多为机房 IP，或 `IPAPI_IS_API_KEY` 未配置 / 被限流 |
| 推 Gist 报 404 | `GIST_ID` 填错，或 Gist 不存在 |
| 推 Gist 报 403 | Token 没有 `gist` scope，重建 token |
| 推 Gist 报 422 | 榜单文件没生成；先看 `Rank` 步骤日志 |
| raw 链接过段时间 404 | 账号或 Gist 可能被风控；检查账号状态 |
| Actions 标签消失 | 账号可能被限制 Actions；换号或转本地跑 |

---

## 十六、安全与风险提示

1. 免费节点来源未知，节点提供方可能看到你的流量；不要用于网银、主力账号、敏感通信。
2. 公开 Gist raw 链接可能被别人爬走，节点失效会更快。
3. GitHub Actions 跑这类任务存在风控风险；不要用主力号，不要高频运行。
4. 项目仅供学习爬虫技术，禁止盈利及违法用途。
