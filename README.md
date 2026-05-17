# QCC Local Browser Excel Enricher

一个本地浏览器驱动的 Excel 数据补全工具：读取企业清单，复用本机登录态采集公开页面里的员工数信息，支持断点续跑、异常留证和结果导出。

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-browser%20automation-2EAD33)
![License](https://img.shields.io/badge/license-MIT-green)

关键词：企查查员工数采集、企业信息补全、Excel enrichment、本地浏览器自动化、Playwright、断点续跑。

## 🌱 这个 repo 是什么

这是一个围绕企业名单 Excel 做批量补全的本地工具。

我更想保留的是它处理表格任务的方式：把一个很容易失控的批量流程拆成几件可检查的事：

- 输入 Excel 不一定只有企业名，社会信用代码、地区也要保留下来。
- 浏览器会话要能复用，人工处理过的状态不应该白费。
- 批量跑到一半可能遇到页面异常、验证提示或账号状态变化，进度不能丢。
- 导出的结果不能只有成功行，还要能解释哪些行需要复核。
- 每一次补跑都应该基于上次进度继续，而不是重新开始。

如果你也要做类似的企业信息补全、公开网页数据整理、Excel enrichment 任务，这个 repo 里比较有参考价值的是：输入结构保留、SQLite 断点续跑、状态分类、Excel 导出和保守的本地浏览器流程。

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

## 🧭 这里面比较值得复用的做法

### 先保住输入结构，再谈采集

客户给的 Excel 往往不只是一个企业名。统一社会信用代码、地区、原始字段都可能在后续排查里有用。

所以我保留了 `InputRecord`，导出时也把原始字段带回去。这样结果表能和客户原表对齐，复核成本会低很多。

### 本地登录态比纯无头脚本更稳

这个项目没有假装自己是全自动云端采集器。它选择了一个更朴素的方案：用本机浏览器保存登录态，脚本接管后续重复操作。

这个方案不酷，但对真实交付很有用。遇到需要人工确认的页面时，用户能直接在浏览器里处理，脚本再继续。

### 断点续跑是批量任务的底线

批量采集最怕跑到一半中断。

这里用 SQLite 保存每一行的状态，成功记录默认跳过，失败记录可以单独导出复核。即使浏览器关闭、网络中断或手动暂停，也不用从第一行重来。

### 异常要留证

页面异常、验证提示、账号状态变化都不是同一种失败。

项目里把状态拆成 `未匹配`、`多候选`、`无员工数`、`权限不足`、`验证码`、`账号异常`、`页面异常` 等几类。最后拿到的不是一句笼统的采集失败，是一组能指导下一步动作的状态：补跑、人工复核，或者调整输入。

### 爬虫限制要进入流程设计

这个项目比较值得保留的一点，是它把批量采集的边界也放进了流程设计。

真实运行时会遇到几类限制：

- 登录态会过期，账号状态也可能变化。
- 页面可能要求人工确认，脚本不能假装没看见。
- 访问节奏太快时，结果会变得不稳定。
- 有些企业本身没有公开员工数，不能硬补成成功。
- 页面结构变化后，解析逻辑要能暴露问题，而不是悄悄导出空值。

所以我没有把它做成一个一路跑到底的黑盒脚本，限制会进入流程本身：

- 默认采用保守节奏。
- 遇到阻断状态可以停止，也可以等待人工处理后继续。
- 每一行都有状态和备注。
- 成功记录写入进度库，补跑时不会重复。
- 失败记录可以单独导出复核。

这类项目最后拼的是：限制存在时，过程还能不能恢复、解释和验收。

### 别把一次任务做成一次性脚本

同类任务很容易写成一个临时脚本：读表、打开页面、导出结果。

但只要数据量稍微大一点，临时脚本就会开始拖后腿。更稳的做法是把输入、进度、状态、导出和复核分开，每一层都能单独检查。

这套结构以后换到别的数据源也能复用，不会只绑定在某一个页面上。

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

## 🙌 参考

- [Playwright Python](https://playwright.dev/python/)：浏览器自动化。
- [pandas](https://pandas.pydata.org/)：Excel 读取和导出。
- [pytest](https://docs.pytest.org/)：项目测试。
- [GitHub README docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)：README 展示方式。

## 📄 License

MIT
