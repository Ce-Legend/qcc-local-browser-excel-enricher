# QCC Local Browser Excel Enricher

一个本地浏览器驱动的 Excel 数据补全工具：读取企业清单，复用本机登录态采集公开页面里的员工数信息，支持断点续跑、异常留证和结果导出。

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-browser%20automation-2EAD33)
![License](https://img.shields.io/badge/license-MIT-green)

关键词：企查查员工数采集、企业信息补全、Excel enrichment、本地浏览器自动化、Playwright、断点续跑。

## 🌱 这个 repo 是什么

前阵子做过一个企业员工数补全项目。

一开始看起来只是把一批企业名称导进去，然后把最近几年的员工数导出来。真做起来才发现，麻烦点不在写一个页面脚本，而在这些细节：

- 输入 Excel 不一定只有企业名，社会信用代码、地区也要保留下来。
- 浏览器登录态要复用，不能每次都从干净环境重新开始。
- 批量跑到一半可能遇到页面异常、验证提示或账号状态变化，进度不能丢。
- 最后交付不能只给一个结果表，还要能解释哪些行成功、哪些行需要复核。
- 公开代码时，真实 Excel、日志、截图、浏览器 profile 都不能放进仓库。

所以我把这次项目整理成一个脱敏后的本地工具仓库。它保留了 CLI、Excel I/O、进度库、解析逻辑、异常状态和测试，适合当作“浏览器自动化 + 表格交付”的作品参考。

## 🚀 先跑一下

```bash
git clone https://github.com/Ce-Legend/qcc-local-browser-excel-enricher.git
cd qcc-local-browser-excel-enricher
python -m pip install -e .
python -m playwright install chromium
```

生成脱敏样例输入：

```bash
qcc-excel-enricher init-sample --output samples/input_sample.xlsx
```

跑测试：

```bash
python -m pytest -q
```

登录态初始化需要手动打开浏览器完成：

```bash
qcc-excel-enricher login --profile browser_profiles/qcc
```

批量运行示例：

```bash
qcc-excel-enricher run \
  --input samples/input_sample.xlsx \
  --db data/progress.sqlite \
  --output outputs/result_sample.xlsx \
  --limit 3
```

## 📦 里面有什么

```text
.
├── qcc_employee_scraper/
│   ├── cli.py              # 命令行入口
│   ├── scraper.py          # Playwright 浏览器流程和页面解析
│   ├── excel_io.py         # Excel 输入输出
│   ├── storage.py          # SQLite 断点续跑
│   ├── delivery.py         # 本地交付路径和浏览器检查
│   └── models.py           # 输入记录和采集结果模型
├── tests/                  # 解析、Excel、进度库、交付路径测试
├── samples/                # 脱敏样例输入
└── docs/                   # 项目复盘、质量清单和脱敏边界
```

## 🧭 我最想留下来的几个经验

### 1. 先保住输入结构，再谈采集

客户给的 Excel 往往不只是一个企业名。统一社会信用代码、地区、原始字段都可能在后续排查里有用。

所以我没有把输入直接压扁成字符串列表，而是保留成 `InputRecord`，导出时也把原始字段带回去。这样结果表能和客户原表对齐，复核成本会低很多。

### 2. 本地登录态比纯无头脚本更稳

这个项目没有假装自己是全自动云端采集器。它选择了一个更朴素的方案：用本机浏览器保存登录态，脚本接管后续重复操作。

这个方案不酷，但对真实交付很有用。遇到需要人工确认的页面时，用户能直接在浏览器里处理，脚本再继续。

### 3. 断点续跑是批量任务的底线

批量采集最怕跑到一半中断。

这里用 SQLite 保存每一行的状态，成功记录默认跳过，失败记录可以单独导出复核。即使浏览器关闭、网络中断或手动暂停，也不用从第一行重来。

### 4. 异常要留证，而不是只打印失败

页面异常、验证提示、账号状态变化都不是同一种失败。

项目里把状态拆成 `未匹配`、`多候选`、`无员工数`、`权限不足`、`验证码`、`账号异常`、`页面异常` 等几类。这样最后不是一句采集失败，而是能判断下一步该补跑、人工复核，还是调整输入。

### 5. 开源版本要主动脱敏

真实交付目录里最危险的不是代码，而是顺手留下来的东西：客户 Excel、运行日志、验证码截图、浏览器 profile、`.env`。

这个公开版本只保留脱敏样例和可复用流程，真实数据目录全部在 `.gitignore` 里。

## 🧩 输入和输出

输入 Excel 至少需要一个公司名称字段，支持这些表头：

```text
company_name, company, name, 企业名称, 公司名称, 公司名, 企业名, 名称
```

如果有这些字段，也会一起读取：

```text
credit_code, unified_social_credit_code, 统一社会信用代码, 社会信用代码
region, area, province, city, 地区, 省市, 城市
```

输出会补充匹配企业、详情页、近三年员工数、数据来源、采集状态、备注和采集时间。

## ✅ 校验方式

这个仓库里的测试覆盖了几类关键逻辑：

- 员工数文本解析。
- Excel 表头别名读取。
- SQLite 断点续跑和导出。
- 失败状态筛选。
- 客户交付路径生成。
- 验证提示识别。

运行：

```bash
python -m pytest -q
```

## 🔒 开源时别放这些

这个 repo 不包含真实客户数据。

不要把这些内容提交到 GitHub：

- 客户原始 Excel。
- 真实导出结果。
- 运行日志和截图。
- 浏览器 profile、cookie、账号信息。
- `.env`、token、密钥。
- 可直接用于高频批量请求的配置。

更完整的边界见 [docs/03-ethics-and-sanitization.md](docs/03-ethics-and-sanitization.md)。

## 🙌 参考

- [Playwright Python](https://playwright.dev/python/)：浏览器自动化。
- [pandas](https://pandas.pydata.org/)：Excel 读取和导出。
- [pytest](https://docs.pytest.org/)：项目测试。
- [GitHub README docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)：README 展示方式。

## 📄 License

MIT
