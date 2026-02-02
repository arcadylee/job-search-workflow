# 自动化工作搜索系统

## 📋 功能简介

这个自动化系统每天早上 7:00（PST/PDT 时间）自动执行以下任务：

1. 🔍 从 **Indeed** 和 **LinkedIn** 抓取过去 24 小时内在大温哥华地区（50公里范围内）新发布的软件开发工程师相关岗位
2. 🤖 使用 **DeepSeek AI** 分析每个岗位与您的简历的匹配度
3. 📊 筛选出匹配度最高的 5-10 个岗位
4. 📧 将分析结果（包括优势、劣势和建议）发送到您的邮箱

## 🚀 快速开始

### 第一步：Fork 本仓库

1. 点击右上角的 **Fork** 按钮，将仓库复制到您的 GitHub 账号
2. Clone 到本地（可选）

### 第二步：配置 GitHub Secrets

GitHub Secrets 是安全存储敏感信息的方式，**永远不要将 API 密钥、密码等信息直接写在代码中**。

进入您 Fork 的仓库，点击 **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

需要配置以下 Secrets：

#### 1. `DEEPSEEK_API_KEY` (必需)

**获取方式：**
1. 访问 [DeepSeek API 平台](https://platform.deepseek.com/)
2. 注册/登录账号
3. 进入 **API Keys** 页面
4. 点击 **Create API Key**
5. 复制生成的 API Key

**在 GitHub 中添加：**
- Name: `DEEPSEEK_API_KEY`
- Secret: `sk-xxxxxxxxxxxxxxxxxxxx`（您的 DeepSeek API Key）

**费用说明：** DeepSeek API 非常便宜，`deepseek-chat` 模型输入 $0.14/M tokens，输出 $0.28/M tokens。每天的使用成本约 $0.01-0.05。

---

#### 2. `EMAIL_SENDER` (必需)

发送邮件的 Gmail 地址

**示例：**
- Name: `EMAIL_SENDER`
- Secret: `your_email@gmail.com`

---

#### 3. `EMAIL_PASSWORD` (必需)

Gmail 应用专用密码（**不是**您的 Gmail 登录密码）

**获取方式：**
1. 登录您的 Gmail 账号
2. 访问 [Google 账户安全设置](https://myaccount.google.com/security)
3. 开启 **两步验证**（如果还没开启）
4. 搜索 "应用专用密码" 或直接访问 [App Passwords](https://myaccount.google.com/apppasswords)
5. 选择 **邮件** 和 **其他（自定义名称）**，输入 "GitHub Actions"
6. 点击 **生成**
7. 复制生成的 16 位密码（格式：xxxx xxxx xxxx xxxx）

**在 GitHub 中添加：**
- Name: `EMAIL_PASSWORD`
- Secret: `xxxxxxxxxxxxxxxx`（移除空格）

---

#### 4. `EMAIL_RECIPIENT` (必需)

接收工作推荐邮件的邮箱地址

**示例：**
- Name: `EMAIL_RECIPIENT`
- Secret: `your_email@gmail.com`

---

#### 5. `RESUME_CONTENT` (必需)

您的简历内容（纯文本格式）

**准备简历内容：**

方法 A - 直接复制简历文本：
```
软件工程师

技能：
- Python, JavaScript, TypeScript
- Django, React, Node.js
- AWS, Docker, Kubernetes

工作经验：
2020-2023 高级软件工程师 @ ABC 公司
- 开发和维护微服务架构
- 领导团队完成XX项目
...
```

方法 B - 从 PDF 提取文本：
1. 使用在线工具（如 [PDF to Text](https://www.pdf2go.com/pdf-to-text)）转换 PDF 为文本
2. 复制转换后的文本内容

**在 GitHub 中添加：**
- Name: `RESUME_CONTENT`
- Secret: （粘贴您的简历文本）

**重要提示：**
- GitHub Secrets 最大 64KB，足够存储简历文本
- 建议简历控制在 2-3 页，重点突出技能和经验
- 使用英文简历效果更好（因为大部分岗位描述是英文）

#### 7. `LATITUDE`, `LONGITUDE` (必需)

个人坐标经纬度

---

#### 7. `SCRAPERAPI_KEY` (可选，强烈推荐)

ScraperAPI 用于避免被网站反爬虫系统封禁，提高成功率

**获取方式：**
1. 访问 [ScraperAPI](https://www.scraperapi.com/)
2. 注册账号（免费账号每月 1,000 次请求，足够日常使用）
3. 在 Dashboard 获取 API Key

**在 GitHub 中添加：**
- Name: `SCRAPERAPI_KEY`
- Secret: `xxxxxxxxxxxxxxxxx`（您的 ScraperAPI Key）

**费用说明：**
- 免费计划：1,000 次/月
- 如果免费额度用完，系统会自动切换到直接请求模式
- Hobby 计划：$49/月，25,000 次请求

---

### 第三步：启用 GitHub Actions

1. 进入您的仓库
2. 点击 **Actions** 标签
3. 如果看到提示，点击 **I understand my workflows, go ahead and enable them**
4. 找到 **Daily Job Search** workflow
5. 点击 **Enable workflow**

### 第四步：测试运行

不用等到早上 7 点，您可以立即手动触发测试：

1. 进入 **Actions** 标签
2. 点击左侧的 **Daily Job Search**
3. 点击右侧的 **Run workflow** 下拉按钮
4. 点击绿色的 **Run workflow** 按钮

几分钟后，您应该会在邮箱收到工作推荐邮件！

## ⚙️ 高级配置

### 修改搜索关键词

编辑 `job_search.py` 文件中的 `JobSearchConfig` 类：

```python
self.search_keywords = [
    'software development engineer',
    'software engineer',
    'backend engineer',
    'full stack engineer',
    'python developer',  # 添加更多关键词
]
```

### 修改搜索范围

修改距离（公里）：

```python
self.distance_km = 50  # 改为 30 或其他值
```

### 修改运行时间

编辑 `.github/workflows/job_search.yml` 文件：

```yaml
schedule:
  - cron: '0 14 * * *'  # PDT 早上 7 点
  - cron: '0 15 * * *'  # PST 早上 7 点
```

**时区转换：**
- PST（冬令时）= UTC + 8 小时
- PDT（夏令时）= UTC + 7 小时
- 例如：PST 早上 7:00 = UTC 下午 3:00 (15:00) → cron: '0 15 * * *'

使用 [Crontab Guru](https://crontab.guru/) 工具帮助生成 cron 表达式

### 修改匹配岗位数量

在 `job_search.py` 的 `analyze_jobs` 方法中：

```python
for match in analysis_result.get('top_matches', [])[:10]:  # 改为 [:5] 或 [:15]
```

## 📊 查看运行日志

1. 进入 **Actions** 标签
2. 点击最近的 workflow 运行记录
3. 点击 **job-search** 查看详细日志
4. 下载 **Artifacts** 中的日志文件（保留 30 天）

## 🔧 故障排查

### 问题：没有收到邮件

**解决方案：**
1. 检查 Actions 日志，查看是否有错误
2. 确认 Gmail 应用专用密码是否正确
3. 检查垃圾邮件文件夹
4. 确认 Gmail 账号已开启两步验证

### 问题：抓取不到岗位

**解决方案：**
1. 检查是否配置了 `SCRAPERAPI_KEY`
2. 尝试修改搜索关键词，使用更通用的词
3. 查看日志中的具体错误信息
4. 网站可能更新了 HTML 结构，需要更新解析代码

### 问题：DeepSeek API 错误

**解决方案：**
1. 检查 API Key 是否正确
2. 确认账户是否有余额
3. 检查 API 调用限制是否超出

### 问题：Workflow 没有按时运行

**解决方案：**
1. GitHub Actions 的 schedule 可能有 5-15 分钟延迟
2. 检查仓库是否有至少一次 commit
3. 确认 workflow 文件路径正确：`.github/workflows/job_search.yml`

## 🔒 安全最佳实践

1. ✅ **永远使用 GitHub Secrets** 存储敏感信息
2. ✅ **不要将 Secrets 打印到日志**
3. ✅ 定期更新 API Keys 和密码
4. ✅ 使用 Gmail 应用专用密码，而不是主密码
5. ✅ 定期检查 GitHub Actions 使用量

## 💰 成本估算

每天运行一次的大约成本：

| 服务 | 免费额度 | 实际使用 | 成本 |
|------|---------|---------|------|
| GitHub Actions | 2,000 分钟/月 | ~10 分钟/月 | $0 |
| DeepSeek API | 按使用付费 | ~$0.02/天 | ~$0.60/月 |
| ScraperAPI | 1,000 次/月 | ~60 次/月 | $0 |
| Gmail | 免费 | 免费 | $0 |
| **总计** | | | **~$0.60/月** |

## 📝 注意事项

1. **合法性：** 抓取公开的招聘信息用于个人求职是合法的，但请遵守网站的 robots.txt 和服务条款
2. **频率限制：** 避免过于频繁的请求，建议使用 ScraperAPI
3. **数据隐私：** 您的简历内容存储在 GitHub Secrets 中，只有您能访问
4. **邮件过滤：** 建议在邮箱中创建过滤规则，自动归类这些邮件

## 🎯 功能路线图

- [ ] 支持更多求职网站（Glassdoor, ZipRecruiter 等）
- [ ] 添加 Slack/Discord 通知
- [ ] 提供 Web Dashboard 查看历史记录
- [ ] 自动申请功能（填写基本信息）
- [ ] 薪资趋势分析

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

## 🙏 致谢

- [DeepSeek](https://www.deepseek.com/) - AI 分析引擎
- [ScraperAPI](https://www.scraperapi.com/) - 反爬虫解决方案
- [GitHub Actions](https://github.com/features/actions) - 自动化平台

---

**祝您求职顺利！🚀**

如有问题，请提交 Issue 或查看详细日志。
