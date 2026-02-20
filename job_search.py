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
            'product manager',
            'project manager',
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
            
            # 最多重试 3 次，ScraperAPI 偶尔会返回 500
            for attempt in range(3):
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
                        parsed = self._parse_indeed_results(response.text)
                        jobs.extend(parsed)
                        logger.info(f"  关键词 '{keyword}' 获取了 {len(parsed)} 个岗位")
                        break  # 成功，不用再重试
                    elif response.status_code == 500 and attempt < 2:
                        logger.warning(f"  Indeed 500错误 (关键词: {keyword})，第 {attempt+1} 次重试...")
                        time.sleep(3 * (attempt + 1))  # 重试间隔逐次增加
                    else:
                        logger.warning(f"  Indeed 请求失败 (关键词: {keyword}): HTTP {response.status_code}")
                        break
                    
                except requests.exceptions.Timeout:
                    if attempt < 2:
                        logger.warning(f"  Indeed 超时 (关键词: {keyword})，第 {attempt+1} 次重试...")
                        time.sleep(3)
                    else:
                        logger.warning(f"  Indeed 持续超时 (关键词: {keyword})，放弃")
                except Exception as e:
                    logger.warning(f"  Indeed 抓取错误 (关键词: {keyword}): {str(e)}")
                    break
            
            time.sleep(2)  # 礼貌等待
        
        logger.info(f"从 Indeed 总共获取了 {len(jobs)} 个岗位")
        return jobs
    
    def _parse_indeed_results(self, html: str) -> List[Dict[str, Any]]:
        """解析 Indeed HTML 结果，直接在列表页提取尽可能完整的 description"""
        jobs = []
        soup = BeautifulSoup(html, 'lxml')
        
        job_cards = soup.find_all('div', class_='job_seen_beacon')
        
        for card in job_cards:
            try:
                title_elem = card.find('h2', class_='jobTitle')
                company_elem = card.find('span', {'data-testid': 'company-name'})
                location_elem = card.find('div', {'data-testid': 'text-location'})
                
                if not title_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                company = company_elem.get_text(strip=True) if company_elem else 'Unknown'
                location = location_elem.get_text(strip=True) if location_elem else 'Unknown'
                
                # 获取职位链接（改用 /viewjob?jk= 格式）
                link_elem = title_elem.find('a')
                raw_href = link_elem['href'] if link_elem and 'href' in link_elem.attrs else ''
                job_link = self._extract_indeed_detail_url(raw_href)
                
                # 在列表页提取更完整的 description（多层策略）
                description = ''
                
                # 策略 1: 找 card 里所有 class 包含 'snippet' 的 div，合并内容
                snippet_divs = card.find_all('div', class_=lambda c: c and 'snippet' in str(c).lower())
                if snippet_divs:
                    description = '\n'.join([d.get_text(separator=' ', strip=True) for d in snippet_divs])
                
                # 策略 2: 如果还是太短，找 card 下所有 <ul> 的内容（职位要求列表）
                if len(description) < 100:
                    ul_items = []
                    for ul in card.find_all('ul'):
                        for li in ul.find_all('li'):
                            text = li.get_text(strip=True)
                            if text and len(text) > 10:
                                ul_items.append(text)
                    if ul_items:
                        description = (description + '\n' + '\n'.join(ul_items)).strip()
                
                # 策略 3: 如果仍然很短，取 card 本身除了标题/公司/地点之外的所有文本
                if len(description) < 100:
                    card_text = card.get_text(separator='\n', strip=True)
                    # 移除标题、公司、地点（这些已经单独提取了）
                    for remove in [title, company, location]:
                        card_text = card_text.replace(remove, '')
                    # 清理后如果还有内容，就用
                    card_text = '\n'.join([l.strip() for l in card_text.split('\n') if len(l.strip()) > 20])
                    if len(card_text) > 50:
                        description = card_text
                
                # 策略 4: 兜底，至少保留 job-snippet 的短预览
                if not description:
                    snippet_elem = card.find('div', class_='job-snippet')
                    description = snippet_elem.get_text(strip=True) if snippet_elem else ''
                
                jobs.append({
                    'source': 'Indeed',
                    'title': title,
                    'company': company,
                    'location': location,
                    'url': job_link,
                    'description': description,
                    'posted_date': datetime.now().isoformat()
                })
                
            except Exception as e:
                logger.debug(f"解析 Indeed 岗位卡片失败: {str(e)}")
                continue
        
        return jobs
    
    def _extract_indeed_detail_url(self, href: str) -> str:
        """从 Indeed 的 href 中提取岗位详情页 URL
        
        Indeed 返回的 href 有两种：
        - /rc/clk?jk=XXXXX&...   → 普通跳转链接
        - /pagead/clk?...&mo=r   → 广告跳转链接（没有 jk，无法提取）
        
        从里面提取 jk 参数，拼成 Indeed 标准详情页格式：
        https://ca.indeed.com/viewjob?jk={jk}
        """
        from urllib.parse import urlparse, parse_qs
        
        if not href:
            return ''
        
        full_url = f"https://ca.indeed.com{href}" if href.startswith('/') else href
        
        try:
            parsed = urlparse(full_url)
            qs = parse_qs(parsed.query)
            
            # 从 query string 里拿 jk 参数
            jk = qs.get('jk', [None])[0]
            if jk:
                # 用 /viewjob?jk= 格式，这是 Indeed 标准的详情页路由
                return f'https://ca.indeed.com/viewjob?jk={jk}'
            
            # /pagead/clk 没有 jk，拿不到详情页，返回空
            logger.debug(f"  无法从 Indeed URL 提取 jk: {href[:80]}")
            return ''
            
        except Exception:
            return ''
    
    def scrape_linkedin(self) -> List[Dict[str, Any]]:
        """
        使用 LinkedIn jobs-guest 公开 API 抓取岗位
        不需要登录，也不需要 API key
        """
        jobs = []
        logger.info("开始抓取 LinkedIn 岗位...")
        
        # 先用 typeahead 接口拿 Vancouver 的 geoId
        geo_id = self._get_linkedin_geo_id('Vancouver')
        if not geo_id:
            logger.warning("  无法获取 Vancouver 的 geoId，将使用 location 参数代替")
        
        for keyword in self.config.search_keywords:
            try:
                # Step 1: 用 search 接口拿岗位列表（返回 HTML 片段）
                search_url = 'https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search'
                params = {
                    'keywords': keyword,
                    'location': 'Vancouver, British Columbia, Canada',
                    'f_TPR': 'r86400',  # 过去24小时
                    'start': 0,         # 分页起始位置
                }
                if geo_id:
                    params['geoId'] = geo_id
                
                response = self.session.get(search_url, params=params, timeout=30)
                
                if response.status_code == 200:
                    parsed = self._parse_linkedin_results(response.text)
                    jobs.extend(parsed)
                    logger.info(f"  关键词 '{keyword}' 获取了 {len(parsed)} 个岗位")
                else:
                    logger.warning(f"  LinkedIn search 失败 (关键词: {keyword}): HTTP {response.status_code}")
                
                time.sleep(2)
                
            except requests.exceptions.Timeout:
                logger.warning(f"  LinkedIn 超时 (关键词: {keyword})")
            except Exception as e:
                logger.warning(f"  LinkedIn 抓取错误 (关键词: {keyword}): {str(e)}")
        
        # Step 2: 先按 URL 去重（同一岗位可能被不同关键词搜到多次）
        seen_urls = set()
        unique_jobs = []
        for job in jobs:
            url = job.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_jobs.append(job)
            elif not url:
                unique_jobs.append(job)  # 没 URL 的先保留
        
        logger.info(f"  去重前 {len(jobs)} 条 → 去重后 {len(unique_jobs)} 条")
        jobs = unique_jobs
        
        # Step 3: 对去重后的岗位逐条拿 description（最多 20 条）
        logger.info(f"  开始获取 LinkedIn 岗位详情（处理 {min(len(jobs), 20)} 条）...")
        for job in jobs[:20]:
            job_id = self._extract_linkedin_job_id(job.get('url', ''))
            if job_id:
                desc = self._get_linkedin_job_description(job_id)
                if desc:
                    job['description'] = desc
                time.sleep(1)
        
        logger.info(f"从 LinkedIn 总共获取了 {len(jobs)} 个岗位")
        return jobs
    
    def _get_linkedin_geo_id(self, city: str) -> str:
        """用 LinkedIn typeahead 接口查询城市的 geoId"""
        try:
            url = 'https://www.linkedin.com/jobs-guest/api/typeaheadHits'
            params = {
                'origin': 'jserp',
                'typeaheadType': 'GEO',
                'geoTypes': 'POPULATED_PLACE',
                'query': city
            }
            response = self.session.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # 返回的是列表，找第一个匹配的
                hits = data.get('typeaheadHits', [])
                for hit in hits:
                    if 'Vancouver' in hit.get('text', ''):
                        logger.info(f"  获取到 Vancouver geoId: {hit['id']}")
                        return str(hit['id'])
        except Exception as e:
            logger.debug(f"  获取 geoId 失败: {str(e)}")
        return ''
    
    def _parse_linkedin_results(self, html: str) -> List[Dict[str, Any]]:
        """解析 LinkedIn jobs-guest search 返回的 HTML"""
        jobs = []
        soup = BeautifulSoup(html, 'lxml')
        
        # jobs-guest 返回的每个岗位卡片
        job_cards = soup.find_all('li')
        
        for card in job_cards:
            try:
                # 用 attribute selector 匹配，比 class 名更稳定
                title_elem = card.find(attrs={'class': lambda c: c and 'title' in c.lower()}) if card else None
                company_elem = card.find(attrs={'class': lambda c: c and 'subtitle' in c.lower()}) if card else None
                location_elem = card.find(attrs={'class': lambda c: c and 'location' in c.lower()}) if card else None
                link_elem = card.find('a', attrs={'class': lambda c: c and 'full-link' in c.lower()}) if card else None
                
                # 如果上面的 lambda 都没匹配到，尝试直接找 a 标签
                if not link_elem:
                    link_elem = card.find('a', href=lambda h: h and '/jobs/view/' in h)
                
                if not title_elem and not link_elem:
                    continue
                
                title = title_elem.get_text(strip=True) if title_elem else 'Unknown Title'
                url = ''
                if link_elem and link_elem.get('href'):
                    href = link_elem['href']
                    url = href if href.startswith('http') else f"https://www.linkedin.com{href}"
                
                jobs.append({
                    'source': 'LinkedIn',
                    'title': title,
                    'company': company_elem.get_text(strip=True) if company_elem else 'Unknown',
                    'location': location_elem.get_text(strip=True) if location_elem else 'Unknown',
                    'url': url,
                    'description': '',  # 后续单独请求
                    'posted_date': datetime.now().isoformat()
                })
                
            except Exception as e:
                logger.debug(f"  解析 LinkedIn 卡片失败: {str(e)}")
                continue
        
        return jobs
    
    def _extract_linkedin_job_id(self, url: str) -> str:
        """从 LinkedIn 岗位 URL 中提取 job_id
        例如: https://www.linkedin.com/jobs/view/xxx-yyy-zzz-12345?... → 12345
        """
        if not url:
            return ''
        # 先去掉 query string
        clean_url = url.split('?')[0]
        # 取最后一段，按 '-' 分割后取末尾的数字
        parts = clean_url.rstrip('/').split('-')
        if parts:
            return parts[-1]
        return ''
    
    def _get_linkedin_job_description(self, job_id: str) -> str:
        """用 jobs-guest jobPosting 接口拿单个岗位的 description（About the job）"""
        try:
            url = f'https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}'
            response = self.session.get(url, timeout=15)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                
                # 策略 1（最可靠）: 找 "About the job" 标题，取它所在容器或后续兄弟的内容
                for elem in soup.find_all(True):
                    text = elem.get_text(strip=True).lower()
                    if 'about the job' in text and len(text) < 50:  # 标题本身很短
                        # 先试父容器
                        parent = elem.parent
                        if parent:
                            parent_text = parent.get_text(separator='\n', strip=True)
                            # 排除标题本身，只要实质内容
                            if len(parent_text) > 200:
                                logger.debug(f"  LinkedIn: 命中 'About the job' 父容器")
                                return parent_text
                        # 再试后续兄弟
                        for sibling in elem.find_next_siblings():
                            sibling_text = sibling.get_text(separator='\n', strip=True)
                            if len(sibling_text) > 100:
                                logger.debug(f"  LinkedIn: 命中 'About the job' 后续内容")
                                return sibling_text
                
                # 策略 2: 找 class 精确包含 'description__text' 的元素
                for elem in soup.find_all(True):
                    classes = elem.get('class', [])
                    class_str = ' '.join(classes) if isinstance(classes, list) else str(classes)
                    if 'description__text' in class_str:
                        text = elem.get_text(separator='\n', strip=True)
                        if len(text) > 100:
                            logger.debug(f"  LinkedIn: 命中 description__text")
                            return text
                
                # 策略 3: 找包含 section > div 结构的 description 容器
                for elem in soup.find_all(True):
                    classes = elem.get('class', [])
                    class_str = ' '.join(classes) if isinstance(classes, list) else str(classes)
                    if 'description' in class_str.lower():
                        section = elem.find('section')
                        if section:
                            div = section.find('div')
                            if div and len(div.get_text(strip=True)) > 100:
                                logger.debug(f"  LinkedIn: 命中 description > section > div")
                                return div.get_text(separator='\n', strip=True)
                
                # 策略 4: 兜底——找所有 div，取文本在 200-10000 字范围内最长的
                candidates = []
                for div in soup.find_all('div'):
                    text = div.get_text(separator='\n', strip=True)
                    if 200 < len(text) < 10000:
                        candidates.append((len(text), text))
                if candidates:
                    candidates.sort(reverse=True)
                    logger.debug(f"  LinkedIn: 兜底策略命中")
                    return candidates[0][1]
                
                logger.warning(f"  LinkedIn: 所有策略都没命中 (job_id={job_id}), 页面长度={len(response.text)}")
            else:
                logger.warning(f"  LinkedIn jobPosting: HTTP {response.status_code} (job_id={job_id})")
                
        except Exception as e:
            logger.warning(f"  获取 LinkedIn 岗位详情失败 (id={job_id}): {str(e)}")
        return ''
    
    def get_indeed_description(self, job_url: str) -> str:
        """获取 Indeed 单个岗位的完整职位描述
        
        多层备选 selector，因为 Indeed 页面结构会随版本变化。
        ScraperAPI 需要 render=true 才能拿到 Indeed 动态渲染的内容。
        """
        try:
            if self.config.scraperapi_key:
                response = self.session.get(
                    'https://api.scraperapi.com',
                    params={
                        'api_key': self.config.scraperapi_key,
                        'url': job_url,
                        'render': 'true'  # 关键：Indeed 用 JS 动态渲染，不加这个拿不到内容
                    },
                    timeout=60
                )
            else:
                response = self.session.get(job_url, timeout=30)
            
            if response.status_code != 200:
                logger.warning(f"  Indeed 详情页 HTTP {response.status_code}: {job_url}")
                return ''
            
            page_len = len(response.text)
            logger.info(f"  Indeed 详情页响应长度: {page_len} 字符 | {job_url.split('/')[-1]}")
            
            # 页面太短说明不是正常岗位页（可能是 captcha / 错误页 / 空页）
            if page_len < 500:
                logger.warning(f"  Indeed 页面太短 ({page_len} 字符)，可能是错误页: {job_url}")
                return ''
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # 策略 1: id='jobDescriptionText'（经典结构）
            desc_elem = soup.find('div', id='jobDescriptionText')
            if desc_elem and len(desc_elem.get_text(strip=True)) > 50:
                logger.info("  Indeed: 命中 id=jobDescriptionText")
                return desc_elem.get_text(separator='\n', strip=True)
            
            # 策略 2: class 里包含 'jobDescriptionText'
            desc_elem = soup.find(attrs={'class': lambda c: c and 'jobDescriptionText' in str(c)})
            if desc_elem and len(desc_elem.get_text(strip=True)) > 50:
                logger.info("  Indeed: 命中 class=jobDescriptionText")
                return desc_elem.get_text(separator='\n', strip=True)
            
            # 策略 3: 找 "Full job description" 标题，取其后面的内容
            for heading in soup.find_all(['h2', 'h3', 'h4', 'span', 'div']):
                if 'full job description' in heading.get_text(strip=True).lower():
                    for sibling in heading.find_next_siblings():
                        text = sibling.get_text(separator='\n', strip=True)
                        if len(text) > 100:
                            logger.info("  Indeed: 命中 'Full job description' 后续内容")
                            return text
                    parent = heading.parent
                    if parent:
                        text = parent.get_text(separator='\n', strip=True)
                        if len(text) > 100:
                            return text
            
            # 策略 4: 兜底——取文本在 200-15000 字范围内最长的 div
            candidates = []
            for div in soup.find_all('div'):
                text = div.get_text(separator='\n', strip=True)
                if 200 < len(text) < 15000:
                    candidates.append((len(text), text))
            if candidates:
                candidates.sort(reverse=True)
                logger.info(f"  Indeed: 兜底策略命中，最大块 {candidates[0][0]} 字符")
                return candidates[0][1]
            
            # 都没命中：记录页面里实际有什么，方便诊断
            all_text = soup.get_text(strip=True)
            logger.warning(f"  Indeed: 所有策略都没命中 | 页面总文本={len(all_text)} 字符 | 预览: {all_text[:200]}")
                
        except requests.exceptions.Timeout:
            logger.warning(f"  Indeed 详情页超时: {job_url}")
        except Exception as e:
            logger.warning(f"  Indeed 详情页异常: {str(e)} | {job_url}")
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
        
        jobs_summary = self._prepare_jobs_for_analysis(jobs)
        
        prompt = f"""
你是一位专业的职业顾问和招聘专家。请根据我的简历，从下面的岗位列表中筛选出最匹配的 5-10 个岗位并分析。

注意：请直接从列表中挑选最好的岗位来分析，不需要对每个岗位都评分。只输出你选中的那些岗位的分析结果。

我的简历：
{resume}

岗位列表：
{jobs_summary}

请以如下 JSON 格式返回结果（只返回 JSON，不要包含任何其他文字，不要加 markdown 代码块）：
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
"""
        
        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是一位专业的职业顾问。请只返回纯 JSON，不要加任何解释文字或 markdown 格式。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=8000
            )
            
            result_text = response.choices[0].message.content.strip()
            logger.info(f"DeepSeek 返回了 {len(result_text)} 个字符")
            
            # 清理 markdown 代码块标记（处理各种格式）
            if '```json' in result_text:
                result_text = result_text.split('```json')[1]
            if '```' in result_text:
                result_text = result_text.split('```')[0]
            result_text = result_text.strip()
            
            # 尝试直接解析
            try:
                analysis_result = json.loads(result_text)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON 直接解析失败: {e}，尝试修复截断的 JSON...")
                result_text = self._fix_truncated_json(result_text)
                analysis_result = json.loads(result_text)
            
            # 将分析结果映射回原始岗位
            top_jobs = []
            for match in analysis_result.get('top_matches', [])[:10]:
                job_idx = match.get('job_index')
                if job_idx is not None and 0 <= job_idx < len(jobs):
                    job = jobs[job_idx].copy()
                    job['analysis'] = {
                        'match_score': match.get('match_score', 0),
                        'strengths': match.get('strengths', []),
                        'weaknesses': match.get('weaknesses', []),
                        'recommendation': match.get('recommendation', ''),
                        'key_skills_match': match.get('key_skills_match', [])
                    }
                    top_jobs.append(job)
            
            logger.info(f"DeepSeek 分析完成，找到 {len(top_jobs)} 个高匹配度岗位")
            return top_jobs
            
        except Exception as e:
            logger.error(f"DeepSeek 分析失败: {str(e)}")
            return jobs[:10]
    
    def _fix_truncated_json(self, text: str) -> str:
        """修复被 max_tokens 截断的 JSON
        
        截断最常见的断点：
        - 在某个 object 内部断了  → 需要补 }]}
        - 在 array 的两个 object 之间断了 → 需要补 ]}
        - 在某个 string 值中间断了 → 需要补 "} 然后收尾
        
        策略：从后往前找到最后一个完整的 object（以 } 结尾），截断后面的，再补收尾标记
        """
        # 找到最后一个完整的 } 位置
        last_brace = text.rfind('}')
        if last_brace == -1:
            raise ValueError("无法修复：没有找到任何完整的 JSON object")
        
        # 截到最后一个 }
        text = text[:last_brace + 1]
        
        # 数一下未闭合的 [ 和 { 数量，然后依次补上
        open_braces = text.count('{') - text.count('}')
        open_brackets = text.count('[') - text.count(']')
        
        # 如果最后一个 } 后面应该还有 , 开头的下一条，去掉尾随的逗号
        text = text.rstrip().rstrip(',')
        
        # 补上缺失的闭合标记
        text += ']' * open_brackets + '}' * open_braces
        
        logger.info(f"JSON 修复完成，补充了 {open_brackets} 个 ] 和 {open_braces} 个 }}")
        return text
    
    def _prepare_jobs_for_analysis(self, jobs: List[Dict[str, Any]]) -> str:
        """准备岗位信息用于分析
        
        有 description 的放完整信息，无 description 的只放标题+公司省 token。
        保持 index 和原始列表一致，这样 DeepSeek 返回的 job_index 才能正确映射。
        """
        jobs_text = []
        has_desc_count = 0
        no_desc_count = 0
        
        for idx, job in enumerate(jobs):
            desc = job.get('description', '').strip()
            if desc:
                has_desc_count += 1
                jobs_text.append(
                    f"职位 {idx}: {job['title']}\n"
                    f"公司: {job['company']} | 地点: {job['location']}\n"
                    f"描述: {desc[:500]}\n"
                )
            else:
                no_desc_count += 1
                # 无 description 的只放标题和公司，占用最少 token
                jobs_text.append(
                    f"职位 {idx}: {job['title']} @ {job['company']}（无详细描述）\n"
                )
        
        logger.info(f"  准备分析素材: {has_desc_count} 条有 description, {no_desc_count} 条无 description")
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
        
        <div style="margin: 12px 0; padding: 10px; background: #fff; border-radius: 6px; border-left: 3px solid #667eea; font-size: 14px; color: #555;">
"""
            desc = job.get('description', '').strip()
            if desc:
                # 有 description：显示预览（前 150 字）
                preview = desc[:150].replace('\n', ' ').strip()
                if len(desc) > 150:
                    preview += '...'
                html += f'            <strong>📋 岗位描述：</strong> {preview}\n'
            elif job['source'] == 'Indeed':
                # Indeed 无 description：引导用户点击链接查看
                html += '            <strong>📋 岗位描述：</strong> 点击下方"立即申请"按钮查看完整职位描述\n'
            else:
                # LinkedIn 无 description
                html += '            <strong>📋 岗位描述：</strong> 请访问 LinkedIn 原帖查看详情\n'
            
            html += f"""        </div>
        
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
        logger.info(f"合并前总共 {len(all_jobs)} 个岗位")
        
        # 跨源去重：Indeed 和 LinkedIn 可能有相同岗位
        # 按 title(小写前30字) + company(小写) 作为去重 key
        seen_keys = set()
        deduped_jobs = []
        for job in all_jobs:
            key = (job['title'].lower()[:30], job['company'].lower())
            if key not in seen_keys:
                seen_keys.add(key)
                deduped_jobs.append(job)
        
        all_jobs = deduped_jobs
        logger.info(f"去重后剩余 {len(all_jobs)} 个岗位")
        
        if not all_jobs:
            logger.warning("未找到任何岗位，脚本结束")
            return
        
        # Indeed 详情页拉取（用正确的 /viewjob?jk= URL 格式）
        # 只拉取列表页 description 不足 200 字的那些（大部分列表页已经有足够内容）
        indeed_to_fetch = [j for j in all_jobs 
                          if j['source'] == 'Indeed' 
                          and j.get('url')
                          and len(j.get('description', '')) < 200][:15]
        
        if indeed_to_fetch:
            logger.info(f"尝试获取 Indeed 详情页补充内容（{len(indeed_to_fetch)} 条 description < 200 字）...")
            for job in indeed_to_fetch:
                full_desc = scraper.get_indeed_description(job['url'])
                if full_desc and len(full_desc) > len(job.get('description', '')):
                    job['description'] = full_desc
                time.sleep(1)
        else:
            logger.info("所有 Indeed 岗位列表页内容充足，跳过详情页拉取")
        
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
