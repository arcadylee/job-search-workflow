# GitHub Secrets 配置完整指南

## 🔐 什么是 GitHub Secrets？

GitHub Secrets 是一个安全存储敏感信息的功能，确保您的 API 密钥、密码等不会被公开。

**重要原则：永远不要将密钥直接写在代码中！**

## 📋 需要配置的 6 个 Secrets

### 1️⃣ DEEPSEEK_API_KEY ⭐ (必需)

**用途：** DeepSeek AI 分析引擎的 API 密钥

**获取步骤：**

```
1. 打开浏览器，访问：https://platform.deepseek.com/
2. 点击右上角 "Sign Up" 注册账号（支持 Google/GitHub 登录）
3. 登录后，进入 "API Keys" 页面
4. 点击 "Create API Key" 按钮
5. 复制生成的密钥（格式：sk-xxxxxxxxxxxxxxxxxxxx）
```

**添加到 GitHub：**

```
仓库页面 → Settings → Secrets and variables → Actions → New repository secret

Name: DEEPSEEK_API_KEY
Secret: sk-xxxxxxxxxxxxxxxxxxxx  (粘贴您的密钥)
```

**费用：**
- 计费方式：按使用付费
- deepseek-chat 模型：输入 $0.14/M tokens，输出 $0.28/M tokens
- 每天使用成本：约 $0.01-0.05
- 月成本：约 $0.30-1.50

**充值方式：**
- 访问 https://platform.deepseek.com/usage
- 最低充值 $5
- 支持信用卡

---

### 2️⃣ EMAIL_SENDER ⭐ (必需)

**用途：** 发送邮件的 Gmail 地址

**示例：**

```
Name: EMAIL_SENDER
Secret: your_email@gmail.com
```

**要求：**
- 必须是 Gmail 邮箱
- 需要开启两步验证
- 需要生成应用专用密码（见下一步）

---

### 3️⃣ EMAIL_PASSWORD ⭐ (必需)

**用途：** Gmail 应用专用密码

**⚠️ 注意：这不是您的 Gmail 登录密码！**

**获取步骤：**

```
第一步：开启两步验证
1. 访问：https://myaccount.google.com/security
2. 找到 "登录 Google" 部分
3. 点击 "两步验证"
4. 按照提示开启

第二步：生成应用专用密码
1. 访问：https://myaccount.google.com/apppasswords
   （或在安全设置中搜索 "应用专用密码"）
2. 选择应用：邮件
3. 选择设备：其他（自定义名称）
4. 输入名称：GitHub Actions
5. 点击 "生成"
6. 复制显示的 16 位密码（格式：xxxx xxxx xxxx xxxx）
```

**添加到 GitHub：**

```
Name: EMAIL_PASSWORD
Secret: xxxxxxxxxxxxxxxx  (16位密码，去掉空格)
```

**故障排查：**
- 如果提示 "应用专用密码" 选项不存在，请确保已开启两步验证
- 生成的密码只显示一次，请立即保存
- 如果忘记了，可以删除旧密码并生成新的

---

### 4️⃣ EMAIL_RECIPIENT ⭐ (必需)

**用途：** 接收工作推荐邮件的邮箱

**示例：**

```
Name: EMAIL_RECIPIENT
Secret: your_email@gmail.com
```

**说明：**
- 可以与 EMAIL_SENDER 相同（发给自己）
- 也可以是不同的邮箱（发给其他邮箱）

---

### 5️⃣ RESUME_CONTENT ⭐ (必需)

**用途：** 您的简历内容（纯文本格式）

**准备简历：**

**方法 A - 从 Word/PDF 复制：**

```
1. 打开您的简历文档
2. 全选并复制所有内容
3. 粘贴到文本编辑器（如记事本）
4. 确保格式清晰，保留换行和缩进
```

**方法 B - 从 PDF 提取：**

```
1. 访问在线工具：https://www.pdf2go.com/pdf-to-text
2. 上传您的 PDF 简历
3. 转换后复制文本内容
```

**简历格式示例：**

```
张三 - 高级软件工程师

联系方式：
- Email: zhang.san@email.com
- 电话：(604) 123-4567
- LinkedIn: linkedin.com/in/zhangsan

技能：
- 编程语言：Python, JavaScript, TypeScript, Java
- 后端框架：Django, Flask, FastAPI, Spring Boot
- 前端框架：React, Vue.js, Next.js
- 数据库：PostgreSQL, MySQL, MongoDB, Redis
- 云服务：AWS (EC2, S3, Lambda), Azure, GCP
- DevOps：Docker, Kubernetes, Jenkins, GitHub Actions
- 其他：Git, REST API, GraphQL, Microservices

工作经验：

高级软件工程师 | ABC 科技公司 | 温哥华，BC
2020年6月 - 2023年12月
- 设计和实现微服务架构，处理每日 100 万+ 请求
- 优化数据库查询，将响应时间减少 40%
- 领导 5 人团队完成核心产品重构
- 使用 Python/Django 和 React 构建全栈应用

软件工程师 | XYZ 初创公司 | 温哥华，BC  
2018年1月 - 2020年5月
- 开发和维护公司主要产品的后端 API
- 实现 CI/CD 流程，提高部署效率 50%
- 与产品团队合作，快速迭代新功能

教育背景：

计算机科学学士 | 不列颠哥伦比亚大学
2014年9月 - 2018年5月
- GPA: 3.8/4.0
- 相关课程：数据结构、算法、数据库系统、软件工程

项目经历：

开源项目贡献者 | GitHub
- 为多个流行开源项目贡献代码（Django, FastAPI）
- 累计 500+ stars，100+ forks

个人项目：
- 构建了一个实时聊天应用，使用 WebSocket 和 Redis
- 开发了一个 Chrome 扩展，帮助开发者提高效率
```

**添加到 GitHub：**

```
Name: RESUME_CONTENT
Secret: (粘贴上面的简历内容)
```

**重要提示：**
- GitHub Secrets 最大 64KB，足够存储完整简历
- 建议使用英文简历（因为岗位描述多为英文）
- 突出关键技能和量化成果
- 保持简历在 2-3 页以内

---

### 6️⃣ SCRAPERAPI_KEY 💎 (可选但强烈推荐)

**用途：** 避免被网站反爬虫系统封禁

**为什么需要：**
- Indeed 和 LinkedIn 有反爬虫保护
- 直接请求可能被限制或封 IP
- ScraperAPI 提供住宅 IP 代理和自动处理验证码

**获取步骤：**

```
1. 访问：https://www.scraperapi.com/
2. 点击 "Start Free Trial" 注册
3. 确认邮箱
4. 登录后进入 Dashboard
5. 复制 "API Key"（显示在页面顶部）
```

**添加到 GitHub：**

```
Name: SCRAPERAPI_KEY
Secret: xxxxxxxxxxxxxxxxxxxxxxxx  (您的 API Key)
```

**费用：**
- 免费计划：1,000 次请求/月
- Hobby 计划：$49/月，25,000 次请求
- 每天运行一次约使用 20-30 次请求
- 免费额度完全够用

**如果不配置：**
- 脚本会自动切换到直接请求模式
- 成功率可能较低
- 可能需要手动运行几次

---

## ✅ 配置检查清单

完成所有配置后，请检查：

- [ ] 已添加 `DEEPSEEK_API_KEY`
- [ ] 已添加 `EMAIL_SENDER`  
- [ ] 已添加 `EMAIL_PASSWORD`（应用专用密码，不是登录密码）
- [ ] 已添加 `EMAIL_RECIPIENT`
- [ ] 已添加 `RESUME_CONTENT`（完整简历文本）
- [ ] （推荐）已添加 `SCRAPERAPI_KEY`

## 🧪 测试配置

添加完所有 Secrets 后，测试是否正常工作：

```
1. 进入 Actions 标签
2. 选择 "Daily Job Search" workflow
3. 点击 "Run workflow" 下拉菜单
4. 点击绿色的 "Run workflow" 按钮
5. 等待 3-5 分钟
6. 检查邮箱是否收到邮件
```

## 🔒 安全提示

1. ✅ **永远不要**在代码或 Issue 中分享您的 API 密钥
2. ✅ **永远不要**将 `.env` 文件提交到 Git
3. ✅ 定期轮换 API 密钥和密码
4. ✅ 使用应用专用密码，而不是 Gmail 主密码
5. ✅ 如果密钥泄露，立即重新生成

## ❓ 常见问题

**Q: 我忘记了应用专用密码怎么办？**
A: 删除旧的应用专用密码，重新生成一个新的。

**Q: DeepSeek API 需要绑定信用卡吗？**
A: 是的，需要充值才能使用，最低充值 $5。

**Q: 可以使用其他邮箱服务吗？**
A: 可以，但需要修改 `job_search.py` 中的 SMTP 配置。Gmail 最简单。

**Q: 简历可以是中文的吗？**
A: 可以，但建议使用英文或中英文双语，因为大多数岗位描述是英文。

**Q: 如何修改 Secret？**
A: 进入 Settings → Secrets and variables → Actions，点击 Secret 名称，选择 "Update"。

## 📞 需要帮助？

如果遇到问题：
1. 查看 Actions 页面的运行日志
2. 在 GitHub Issues 中提问
3. 参考 README.md 的故障排查部分

---

**配置完成后，您就可以享受自动化求职啦！🎉**
