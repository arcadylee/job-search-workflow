#!/usr/bin/env python3
"""
Job Search Automation Script
每天自动从 Indeed 和 LinkedIn 抓取大温哥华地区的软件工程职位，
使用 DeepSeek AI 匹配简历，并将最佳匹配的岗位发送到邮箱。
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'job_search_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class JobSearchConfig:
    """工作搜索配置类"""
    def __init__(self):
        # API Keys
        self.deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')
        self.scraperapi_key = os.getenv('SCRAPERAPI_KEY')  # 可选，用于避免被封
        
        # Email 配置
        self.email_sender = os.getenv('EMAIL_SENDER')
        self.email_password = os.getenv('EMAIL_PASSWORD')
        self.email_recipient = os.getenv('EMAIL_RECIPIENT')
        
        # 简历路径（GitHub Secrets 中存储 base64 编码的简历内容）
        self.resume_content = os.getenv('RESUME_CONTENT', '')
        
        # 搜索参数
        self.search_keywords = [
            'software development engineer',
            'software engineer',
            'backend engineer',
            'full stack engineer',
            'Java developer'
        ]
        self.location = 'Greater Vancouver, BC'
        self.distance_km = 50
        
        # 温哥华的经纬度（用于精确搜索）
        self.vancouver_coords = {
            'latitude': float(os.getenv('LATITUDE')),
            'longitude': float(os.getenv('LONGITUDE'))
        }
        
        self.validate()
    
    def validate(self):
        """验证必需的配置"""
        required = {
            'DEEPSEEK_API_KEY': self.deepseek_api_key,
            'EMAIL_SENDER': self.email_sender,
            'EMAIL_PASSWORD': self.email_password,
            'EMAIL_RECIPIENT': self.email_recipient
        }
        
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")


class JobScraper:
    """工作岗位抓取器"""
    
    def __init__(self, config: JobSearchConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
    
    def scrape_indeed(self) -> List[Dict[str, Any]]:
        """
        抓取 Indeed 上的工作岗位
        使用 ScraperAPI 或直接请求
        """
        jobs = []
        logger.info("开始抓取 Indeed 岗位...")
        
        for keyword in self.config.search_keywords:
            # 先拼好 Indeed 自己的目标 URL + 参数
            indeed_params = {
                'q': keyword,
                'l': 'Vancouver, BC',
                'radius': self.config.distance_km,
                'fromage': '1',  # 过去1天
                'sort': 'date'
            }
            target_url = 'https://ca.indeed.com/jobs?' + self._build_query_string(indeed_params)
            
            try:
                if self.config.scraperapi_key:
                    # ScraperAPI 用法：把目标 URL 作为参数传给 ScraperAPI
                    # ScraperAPI 帮你发实际请求，返回结果
                    response = self.session.get(
                        'https://api.scraperapi.com',
                        params={
                            'api_key': self.config.scraperapi_key,
                            'url': target_url
                        },
                        timeout=60  # ScraperAPI 需要更长时间处理
                    )
                else:
                    # 没有 ScraperAPI，直接请求 Indeed（成功率较低）
                    response = self.session.get(target_url, timeout=30)
                
                if response.status_code == 200:
                    parsed = self._parse_indeed_results(response.text)
                    jobs.extend(parsed)
                    logger.info(f"  关键词 '{keyword}' 获取了 {len(parsed)} 个岗位")
                else:
                    logger.warning(f"  Indeed 请求失败 (关键词: {keyword}): HTTP {response.status_code}")
                
                time.sleep(2)  # 礼貌等待
                
            except requests.exceptions.Timeout:
                logger.warning(f"  Indeed 请求超时 (关键词: {keyword})，跳过继续下一个关键词")
            except Exception as e:
                logger.warning(f"  Indeed 抓取错误 (关键词: {keyword}): {str(e)}")
        
        logger.info(f"从 Indeed 总共获取了 {len(jobs)} 个岗位")
        return jobs
    
    def _parse_indeed_results(self, html: str) -> List[Dict[str, Any]]:
        """解析 Indeed HTML 结果"""
        jobs = []
        soup = BeautifulSoup(html, 'lxml')
        
        # Indeed 使用 mosaic-provider-jobcards 类
        job_cards = soup.find_all('div', class_='job_seen_beacon')
        
        for card in job_cards:
            try:
                # 提取基本信息
                title_elem = card.find('h2', class_='jobTitle')
                company_elem = card.find('span', {'data-testid': 'company-name'})
                location_elem = card.find('div', {'data-testid': 'text-location'})
                
                if not title_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                company = company_elem.get_text(strip=True) if company_elem else 'Unknown'
                location = location_elem.get_text(strip=True) if location_elem else 'Unknown'
                
                # 获取职位链接
                link_elem = title_elem.find('a')
                job_link = f"https://ca.indeed.com{link_elem['href']}" if link_elem and 'href' in link_elem.attrs else ''
                
                # 提取 job description 片段
                snippet_elem = card.find('div', class_='job-snippet')
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ''
                
                jobs.append({
                    'source': 'Indeed',
                    'title': title,
                    'company': company,
                    'location': location,
                    'url': job_link,
                    'description': snippet,
                    'posted_date': datetime.now().isoformat()
                })
                
            except Exception as e:
                logger.debug(f"解析 Indeed 岗位卡片失败: {str(e)}")
                continue
        
        return jobs
    
    def scrape_linkedin(self) -> List[Dict[str, Any]]:
        """
        抓取 LinkedIn 上的工作岗位
        """
        jobs = []
        logger.info("开始抓取 LinkedIn 岗位...")
        
        for keyword in self.config.search_keywords:
            # 拼好 LinkedIn 目标 URL
            linkedin_params = {
                'keywords': keyword,
                'location': 'Vancouver, British Columbia, Canada',
                'distance': 50,
                'f_TPR': 'r86400',  # 过去24小时
                'position': 1,
                'pageNum': 0
            }
            target_url = 'https://www.linkedin.com/jobs/search?' + self._build_query_string(linkedin_params)
            
            try:
                if self.config.scraperapi_key:
                    response = self.session.get(
                        'https://api.scraperapi.com',
                        params={
                            'api_key': self.config.scraperapi_key,
                            'url': target_url
                        },
                        timeout=60
                    )
                else:
                    response = self.session.get(target_url, timeout=30)
                
                if response.status_code == 200:
                    parsed = self._parse_linkedin_results(response.text)
                    jobs.extend(parsed)
                    logger.info(f"  关键词 '{keyword}' 获取了 {len(parsed)} 个岗位")
                else:
                    logger.warning(f"  LinkedIn 请求失败 (关键词: {keyword}): HTTP {response.status_code}")
                
                time.sleep(3)  # LinkedIn 需要更长等待
                
            except requests.exceptions.Timeout:
                logger.warning(f"  LinkedIn 请求超时 (关键词: {keyword})，跳过继续下一个关键词")
            except Exception as e:
                logger.warning(f"  LinkedIn 抓取错误 (关键词: {keyword}): {str(e)}")
        
        logger.info(f"从 LinkedIn 总共获取了 {len(jobs)} 个岗位")
        return jobs
    
    def _parse_linkedin_results(self, html: str) -> List[Dict[str, Any]]:
        """解析 LinkedIn HTML 结果"""
        jobs = []
        soup = BeautifulSoup(html, 'lxml')
        
        # LinkedIn 使用不同的类名
        job_cards = soup.find_all('div', class_='base-card')
        
        for card in job_cards:
            try:
                title_elem = card.find('h3', class_='base-search-card__title')
                company_elem = card.find('h4', class_='base-search-card__subtitle')
                location_elem = card.find('span', class_='job-search-card__location')
                link_elem = card.find('a', class_='base-card__full-link')
                
                if not title_elem:
                    continue
                
                jobs.append({
                    'source': 'LinkedIn',
                    'title': title_elem.get_text(strip=True),
                    'company': company_elem.get_text(strip=True) if company_elem else 'Unknown',
                    'location': location_elem.get_text(strip=True) if location_elem else 'Unknown',
                    'url': link_elem['href'] if link_elem and 'href' in link_elem.attrs else '',
                    'description': '',  # LinkedIn 需要单独请求详情页
                    'posted_date': datetime.now().isoformat()
                })
                
            except Exception as e:
                logger.debug(f"解析 LinkedIn 岗位卡片失败: {str(e)}")
                continue
        
        return jobs
    
    def get_job_description(self, job_url: str) -> str:
        """获取完整的职位描述"""
        try:
            response = self.session.get(job_url, timeout=30)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                
                # Indeed 的职位描述
                if 'indeed.com' in job_url:
                    desc_elem = soup.find('div', id='jobDescriptionText')
                    if desc_elem:
                        return desc_elem.get_text(separator='\n', strip=True)
                
                # LinkedIn 的职位描述
                elif 'linkedin.com' in job_url:
                    desc_elem = soup.find('div', class_='show-more-less-html__markup')
                    if desc_elem:
                        return desc_elem.get_text(separator='\n', strip=True)
            
        except Exception as e:
            logger.debug(f"获取职位描述失败 {job_url}: {str(e)}")
        
        return ''
    
    def _build_query_string(self, params: Dict) -> str:
        """构建查询字符串"""
        return '&'.join([f"{k}={v}" for k, v in params.items()])


class ResumeAnalyzer:
    """简历匹配分析器 - 使用 DeepSeek AI"""
    
    def __init__(self, config: JobSearchConfig):
        self.config = config
        self.client = OpenAI(
            api_key=config.deepseek_api_key,
            base_url="https://api.deepseek.com"
        )
    
    def analyze_jobs(self, jobs: List[Dict[str, Any]], resume: str) -> List[Dict[str, Any]]:
        """
        使用 DeepSeek 分析工作岗位与简历的匹配度
        返回排序后的前 5-10 个最佳匹配岗位
        """
        logger.info(f"开始使用 DeepSeek 分析 {len(jobs)} 个岗位...")
        
        if not jobs:
            return []
        
        # 准备批量分析的提示词
        jobs_summary = self._prepare_jobs_for_analysis(jobs)
        
        prompt = f"""
你是一位专业的职业顾问和招聘专家。我将给你我的简历和一系列软件工程职位，请帮我：

1. 分析每个职位与我简历的匹配度（0-100分）
2. 列出每个职位的优势和劣势
3. 给出申请建议
4. 按匹配度从高到低排序，选出前 5-10 个最佳匹配的职位

我的简历：
{resume}

职位列表：
{jobs_summary}

请以 JSON 格式返回结果，格式如下：
{{
    "top_matches": [
        {{
            "job_index": 0,
            "match_score": 85,
            "strengths": ["优势1", "优势2"],
            "weaknesses": ["劣势1"],
            "recommendation": "申请建议",
            "key_skills_match": ["匹配的关键技能"]
        }}
    ]
}}

只返回 JSON，不要包含任何其他文字。
"""
        
        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是一位专业的职业顾问，擅长分析工作岗位和简历的匹配度。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=4000
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # 清理可能的 markdown 代码块标记
            if result_text.startswith('```json'):
                result_text = result_text[7:]
            if result_text.startswith('```'):
                result_text = result_text[3:]
            if result_text.endswith('```'):
                result_text = result_text[:-3]
            result_text = result_text.strip()
            
            analysis_result = json.loads(result_text)
            
            # 将分析结果映射回原始岗位
            top_jobs = []
            for match in analysis_result.get('top_matches', [])[:10]:
                job_idx = match['job_index']
                if 0 <= job_idx < len(jobs):
                    job = jobs[job_idx].copy()
                    job['analysis'] = {
                        'match_score': match['match_score'],
                        'strengths': match['strengths'],
                        'weaknesses': match['weaknesses'],
                        'recommendation': match['recommendation'],
                        'key_skills_match': match.get('key_skills_match', [])
                    }
                    top_jobs.append(job)
            
            logger.info(f"DeepSeek 分析完成，找到 {len(top_jobs)} 个高匹配度岗位")
            return top_jobs
            
        except Exception as e:
            logger.error(f"DeepSeek 分析失败: {str(e)}")
            # 如果 AI 分析失败，返回前10个岗位
            return jobs[:10]
    
    def _prepare_jobs_for_analysis(self, jobs: List[Dict[str, Any]]) -> str:
        """准备岗位信息用于分析"""
        jobs_text = []
        for idx, job in enumerate(jobs):
            jobs_text.append(f"""
职位 {idx}:
标题: {job['title']}
公司: {job['company']}
地点: {job['location']}
描述: {job.get('description', 'N/A')[:500]}...
""")
        return '\n'.join(jobs_text)


class EmailSender:
    """邮件发送器"""
    
    def __init__(self, config: JobSearchConfig):
        self.config = config
    
    def send_report(self, jobs: List[Dict[str, Any]]):
        """发送工作岗位报告到邮箱"""
        logger.info(f"准备发送邮件，包含 {len(jobs)} 个岗位...")
        
        # 创建邮件内容
        html_content = self._create_html_report(jobs)
        
        # 创建邮件
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'每日工作推荐 - {len(jobs)} 个高匹配度岗位 ({datetime.now().strftime("%Y-%m-%d")})'
        msg['From'] = self.config.email_sender
        msg['To'] = self.config.email_recipient
        
        # 添加 HTML 内容
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)
        
        try:
            # 使用 Gmail SMTP
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(self.config.email_sender, self.config.email_password)
                server.send_message(msg)
            
            logger.info("邮件发送成功！")
            
        except Exception as e:
            logger.error(f"邮件发送失败: {str(e)}")
    
    def _create_html_report(self, jobs: List[Dict[str, Any]]) -> str:
        """创建 HTML 格式的工作报告"""
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 30px;
        }}
        .job-card {{
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            background: #f9f9f9;
        }}
        .job-title {{
            font-size: 20px;
            font-weight: bold;
            color: #2c3e50;
            margin-bottom: 10px;
        }}
        .company {{
            font-size: 16px;
            color: #7f8c8d;
            margin-bottom: 5px;
        }}
        .location {{
            font-size: 14px;
            color: #95a5a6;
            margin-bottom: 15px;
        }}
        .match-score {{
            display: inline-block;
            background: #27ae60;
            color: white;
            padding: 5px 15px;
            border-radius: 20px;
            font-weight: bold;
            margin-bottom: 15px;
        }}
        .strengths, .weaknesses {{
            margin: 10px 0;
        }}
        .strengths h4 {{
            color: #27ae60;
            margin-bottom: 5px;
        }}
        .weaknesses h4 {{
            color: #e74c3c;
            margin-bottom: 5px;
        }}
        ul {{
            margin: 5px 0;
            padding-left: 20px;
        }}
        .recommendation {{
            background: #ecf0f1;
            padding: 15px;
            border-left: 4px solid #3498db;
            margin: 15px 0;
        }}
        .apply-button {{
            display: inline-block;
            background: #3498db;
            color: white;
            padding: 10px 20px;
            text-decoration: none;
            border-radius: 5px;
            margin-top: 10px;
        }}
        .apply-button:hover {{
            background: #2980b9;
        }}
        .footer {{
            text-align: center;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            color: #7f8c8d;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🎯 每日工作推荐</h1>
        <p>{datetime.now().strftime("%Y年%m月%d日")} - 为您精选 {len(jobs)} 个高匹配度岗位</p>
    </div>
"""
        
        for idx, job in enumerate(jobs, 1):
            analysis = job.get('analysis', {})
            match_score = analysis.get('match_score', 0)
            
            html += f"""
    <div class="job-card">
        <div class="job-title">#{idx} {job['title']}</div>
        <div class="company">🏢 {job['company']}</div>
        <div class="location">📍 {job['location']}</div>
        <div class="match-score">匹配度: {match_score}%</div>
        
        <div class="strengths">
            <h4>✅ 优势：</h4>
            <ul>
"""
            for strength in analysis.get('strengths', []):
                html += f"                <li>{strength}</li>\n"
            
            html += """
            </ul>
        </div>
        
        <div class="weaknesses">
            <h4>⚠️ 注意事项：</h4>
            <ul>
"""
            for weakness in analysis.get('weaknesses', []):
                html += f"                <li>{weakness}</li>\n"
            
            html += f"""
            </ul>
        </div>
        
        <div class="recommendation">
            <strong>💡 建议：</strong> {analysis.get('recommendation', '建议申请')}
        </div>
        
        <a href="{job['url']}" class="apply-button" target="_blank">立即申请 →</a>
    </div>
"""
        
        html += """
    <div class="footer">
        <p>本报告由自动化脚本生成 | Powered by DeepSeek AI</p>
        <p>祝您求职顺利！🚀</p>
    </div>
</body>
</html>
"""
        return html


def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("开始每日工作搜索...")
    logger.info("=" * 60)
    
    try:
        # 初始化配置
        config = JobSearchConfig()
        
        # 获取简历内容
        resume = config.resume_content
        if not resume:
            logger.warning("未提供简历内容，将使用默认简历模板")
            resume = "软件工程师，精通 Python, JavaScript, 有多年后端开发经验。"
        
        # 初始化抓取器
        scraper = JobScraper(config)
        
        # 抓取岗位
        indeed_jobs = scraper.scrape_indeed()
        linkedin_jobs = scraper.scrape_linkedin()
        
        all_jobs = indeed_jobs + linkedin_jobs
        logger.info(f"总共抓取到 {len(all_jobs)} 个岗位")
        
        if not all_jobs:
            logger.warning("未找到任何岗位，脚本结束")
            return
        
        # 获取完整的职位描述（前20个）
        logger.info("获取详细职位描述...")
        for job in all_jobs[:20]:
            if job['url']:
                full_desc = scraper.get_job_description(job['url'])
                if full_desc:
                    job['description'] = full_desc
                time.sleep(1)
        
        # 保存原始数据
        with open(f'jobs_{datetime.now().strftime("%Y%m%d")}.json', 'w', encoding='utf-8') as f:
            json.dump(all_jobs, f, ensure_ascii=False, indent=2)
        
        # 使用 DeepSeek 分析匹配度
        analyzer = ResumeAnalyzer(config)
        top_jobs = analyzer.analyze_jobs(all_jobs, resume)
        
        if top_jobs:
            # 发送邮件报告
            email_sender = EmailSender(config)
            email_sender.send_report(top_jobs)
            
            logger.info(f"成功完成！发送了 {len(top_jobs)} 个岗位推荐")
        else:
            logger.warning("未找到匹配的岗位")
        
    except Exception as e:
        logger.error(f"脚本执行失败: {str(e)}", exc_info=True)
        raise
    
    logger.info("=" * 60)
    logger.info("每日工作搜索完成")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
