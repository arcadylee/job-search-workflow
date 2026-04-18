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
            'project manager'
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
            indeed_params = {
                'q': keyword,
                'l': 'Vancouver, BC',
                'radius': self.config.distance_km,
                'fromage': '1',
                'sort': 'date'
            }
            target_url = 'https://ca.indeed.com/jobs?' + self._build_query_string(indeed_params)
            
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
                        break
                    elif response.status_code == 500 and attempt < 2:
                        logger.warning(f"  Indeed 500错误 (关键词: {keyword})，第 {attempt+1} 次重试...")
                        time.sleep(3 * (attempt + 1))
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
            
            time.sleep(2)
        
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
                
                link_elem = title_elem.find('a')
                raw_href = link_elem['href'] if link_elem and 'href' in link_elem.attrs else ''
                job_link = self._extract_indeed_detail_url(raw_href)
                
                description = ''
                
                snippet_divs = card.find_all('div', class_=lambda c: c and 'snippet' in str(c).lower())
                if snippet_divs:
                    description = '\n'.join([d.get_text(separator=' ', strip=True) for d in snippet_divs])
                
                if len(description) < 100:
                    ul_items = []
                    for ul in card.find_all('ul'):
                        for li in ul.find_all('li'):
                            text = li.get_text(strip=True)
                            if text and len(text) > 10:
                                ul_items.append(text)
                    if ul_items:
                        description = (description + '\n' + '\n'.join(ul_items)).strip()
                
                if len(description) < 100:
                    card_text = card.get_text(separator='\n', strip=True)
                    for remove in [title, company, location]:
                        card_text = card_text.replace(remove, '')
                    card_text = '\n'.join([l.strip() for l in card_text.split('\n') if len(l.strip()) > 20])
                    if len(card_text) > 50:
                        description = card_text
                
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
        """从 Indeed 的 href 中提取岗位详情页 URL"""
        from urllib.parse import urlparse, parse_qs
        
        if not href:
            return ''
        
        full_url = f"https://ca.indeed.com{href}" if href.startswith('/') else href
        
        try:
            parsed = urlparse(full_url)
            qs = parse_qs(parsed.query)
            jk = qs.get('jk', [None])[0]
            if jk:
                return f'https://ca.indeed.com/viewjob?jk={jk}'
            
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
        
        geo_id = self._get_linkedin_geo_id('Vancouver')
        if not geo_id:
            logger.warning("  无法获取 Vancouver 的 geoId，将使用 location 参数代替")
        
        for keyword in self.config.search_keywords:
            try:
                search_url = 'https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search'
                params = {
                    'keywords': keyword,
                    'location': 'Vancouver, British Columbia, Canada',
                    'f_TPR': 'r86400',
                    'start': 0,
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
        
        seen_urls = set()
        unique_jobs = []
        for job in jobs:
            url = job.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_jobs.append(job)
            elif not url:
                unique_jobs.append(job)
        
        logger.info(f"  去重前 {len(jobs)} 条 → 去重后 {len(unique_jobs)} 条")
        jobs = unique_jobs
        
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
        job_cards = soup.find_all('li')
        
        for card in job_cards:
            try:
                title_elem = card.find(attrs={'class': lambda c: c and 'title' in c.lower()}) if card else None
                company_elem = card.find(attrs={'class': lambda c: c and 'subtitle' in c.lower()}) if card else None
                location_elem = card.find(attrs={'class': lambda c: c and 'location' in c.lower()}) if card else None
                link_elem = card.find('a', attrs={'class': lambda c: c and 'full-link' in c.lower()}) if card else None
                
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
                    'description': '',
                    'posted_date': datetime.now().isoformat()
                })
                
            except Exception as e:
                logger.debug(f"  解析 LinkedIn 卡片失败: {str(e)}")
                continue
        
        return jobs
    
    def _extract_linkedin_job_id(self, url: str) -> str:
        """从 LinkedIn 岗位 URL 中提取 job_id"""
        if not url:
            return ''
        clean_url = url.split('?')[0]
        parts = clean_url.rstrip('/').split('-')
        if parts:
            return parts[-1]
        return ''
    
    def _get_linkedin_job_description(self, job_id: str) -> str:
        """用 jobs-guest jobPosting 接口拿单个岗位的 description"""
        try:
            url = f'https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}'
            response = self.session.get(url, timeout=15)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                
                for elem in soup.find_all(True):
                    text = elem.get_text(strip=True).lower()
                    if 'about the job' in text and len(text) < 50:
                        parent = elem.parent
                        if parent:
                            parent_text = parent.get_text(separator='\n', strip=True)
                            if len(parent_text) > 200:
                                logger.debug(f"  LinkedIn: 命中 'About the job' 父容器")
                                return parent_text
                        for sibling in elem.find_next_siblings():
                            sibling_text = sibling.get_text(separator='\n', strip=True)
                            if len(sibling_text) > 100:
                                logger.debug(f"  LinkedIn: 命中 'About the job' 后续内容")
                                return sibling_text
                
                for elem in soup.find_all(True):
                    classes = elem.get('class', [])
                    class_str = ' '.join(classes) if isinstance(classes, list) else str(classes)
                    if 'description__text' in class_str:
                        text = elem.get_text(separator='\n', strip=True)
                        if len(text) > 100:
                            logger.debug(f"  LinkedIn: 命中 description__text")
                            return text
                
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
    
    def get_indeed_page_html(self, job_url: str) -> str:
        """获取 Indeed 详情页 HTML"""
        try:
            if self.config.scraperapi_key:
                response = self.session.get(
                    'https://api.scraperapi.com',
                    params={
                        'api_key': self.config.scraperapi_key,
                        'url': job_url,
                        'render': 'true'
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
            
            if page_len < 500:
                logger.warning(f"  Indeed 页面太短 ({page_len} 字符)，可能不是正常岗位页: {job_url}")
                return ''
            
            return response.text
                
        except requests.exceptions.Timeout:
            logger.warning(f"  Indeed 详情页超时: {job_url}")
        except Exception as e:
            logger.warning(f"  Indeed 详情页异常: {str(e)} | {job_url}")
        return ''
    
    def is_indeed_job_active(self, html: str) -> bool:
        """检查 Indeed 岗位是否仍然有效"""
        if not html:
            return False
        
        text = BeautifulSoup(html, 'lxml').get_text(" ", strip=True).lower()
        
        expired_markers = [
            "this job has expired",
            "job has expired on indeed",
            "no longer available",
            "not accepting applications",
            "is not accepting applications",
            "position has been filled",
            "position filled",
            "job expired"
        ]
        
        return not any(marker in text for marker in expired_markers)
    
    def get_indeed_description_from_html(self, html: str, job_url: str = '') -> str:
        """从已获取的 Indeed HTML 中提取完整职位描述"""
        try:
            if not html:
                return ''
            
            soup = BeautifulSoup(html, 'lxml')
            
            desc_elem = soup.find('div', id='jobDescriptionText')
            if desc_elem and len(desc_elem.get_text(strip=True)) > 50:
                logger.info("  Indeed: 命中 id=jobDescriptionText")
                return desc_elem.get_text(separator='\n', strip=True)
            
            desc_elem = soup.find(attrs={'class': lambda c: c and 'jobDescriptionText' in str(c)})
            if desc_elem and len(desc_elem.get_text(strip=True)) > 50:
                logger.info("  Indeed: 命中 class=jobDescriptionText")
                return desc_elem.get_text(separator='\n', strip=True)
            
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
            
            candidates = []
            for div in soup.find_all('div'):
                text = div.get_text(separator='\n', strip=True)
                if 200 < len(text) < 15000:
                    candidates.append((len(text), text))
            if candidates:
                candidates.sort(reverse=True)
                logger.info(f"  Indeed: 兜底策略命中，最大块 {candidates[0][0]} 字符")
                return candidates[0][1]
            
            all_text = soup.get_text(strip=True)
            logger.warning(f"  Indeed: 所有策略都没命中 | 页面总文本={len(all_text)} 字符 | 预览: {all_text[:200]}")
                
        except Exception as e:
            logger.warning(f"  从 Indeed HTML 提取描述异常: {str(e)} | {job_url}")
        return ''
    
    def get_indeed_description(self, job_url: str) -> str:
        """获取 Indeed 单个岗位的完整职位描述"""
        html = self.get_indeed_page_html(job_url)
        return self.get_indeed_description_from_html(html, job_url)
    
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
            
            if '```json' in result_text:
                result_text = result_text.split('```json')[1]
            if '```' in result_text:
                result_text = result_text.split('```')[0]
            result_text = result_text.strip()
            
            try:
                analysis_result = json.loads(result_text)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON 直接解析失败: {e}，尝试修复截断的 JSON...")
                result_text = self._fix_truncated_json(result_text)
                analysis_result = json.loads(result_text)
            
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
        """修复被 max_tokens 截断的 JSON"""
        last_brace = text.rfind('}')
        if last_brace == -1:
            raise ValueError("无法修复：没有找到任何完整的 JSON object")
        
        text = text[:last_brace + 1]
        open_braces = text.count('{') - text.count('}')
        open_brackets = text.count('[') - text.count(']')
        text = text.rstrip().rstrip(',')
        text += ']' * open_brackets + '}' * open_braces
        
        logger.info(f"JSON 修复完成，补充了 {open_brackets} 个 ] 和 {open_braces} 个 }}")
        return text
    
    def _prepare_jobs_for_analysis(self, jobs: List[Dict[str, Any]]) -> str:
        """准备岗位信息用于分析"""
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
        
        html_content = self._create_html_report(jobs)
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'每日工作推荐 - {len(jobs)} 个高匹配度岗位 ({datetime.now().strftime("%Y-%m-%d")})'
        msg['From'] = self.config.email_sender
        msg['To'] = self.config.email_recipient
        
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)
        
        try:
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
                preview = desc[:150].replace('\n', ' ').strip()
                if len(desc) > 150:
                    preview += '...'
                html += f'            <strong>📋 岗位描述：</strong> {preview}\n'
            elif job['source'] == 'Indeed':
                html += '            <strong>📋 岗位描述：</strong> 点击下方"立即申请"按钮查看完整职位描述\n'
            else:
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
        
def make_job_key(job: Dict[str, Any]) -> str:
    """生成岗位唯一 key，用于跨天去重"""
    title = job.get('title', '').strip().lower()
    company = job.get('company', '').strip().lower()
    url = job.get('url', '').strip().lower()
    location = job.get('location', '').strip().lower()
    return f"{title}|{company}|{url or location}"


def load_sent_job_history(filepath: str = '.job_history/sent_jobs.json') -> set:
    """读取历史已发送岗位 key"""
    if not os.path.exists(filepath):
        return set()

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return set(data)
    except Exception as e:
        logger.warning(f"读取历史推荐失败: {str(e)}")
        return set()


def save_sent_job_history(job_keys: set, filepath: str = '.job_history/sent_jobs.json'):
    """保存历史已发送岗位 key"""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(sorted(list(job_keys)), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"保存历史推荐失败: {str(e)}")

def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("开始每日工作搜索...")
    logger.info("=" * 60)
    
    try:
        config = JobSearchConfig()
        
        resume = config.resume_content
        if not resume:
            logger.warning("未提供简历内容，将使用默认简历模板")
            resume = "软件工程师，精通 Python, JavaScript, 有多年后端开发经验。"
        
        scraper = JobScraper(config)
        
        indeed_jobs = scraper.scrape_indeed()
        linkedin_jobs = scraper.scrape_linkedin()
        
        all_jobs = indeed_jobs + linkedin_jobs
        logger.info(f"合并前总共 {len(all_jobs)} 个岗位")
        
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
        
        active_jobs = []
        expired_count = 0
        
        logger.info("开始过滤 Indeed 已过期岗位并补充详情...")
        for job in all_jobs:
            if job['source'] != 'Indeed' or not job.get('url'):
                active_jobs.append(job)
                continue
            
            html = scraper.get_indeed_page_html(job['url'])
            if not scraper.is_indeed_job_active(html):
                expired_count += 1
                logger.info(f"  跳过已过期 Indeed 岗位: {job['title']} | {job['company']}")
                time.sleep(1)
                continue
            
            if len(job.get('description', '')) < 200:
                full_desc = scraper.get_indeed_description_from_html(html, job['url'])
                if full_desc and len(full_desc) > len(job.get('description', '')):
                    job['description'] = full_desc
            
            active_jobs.append(job)
            time.sleep(1)
        
        all_jobs = active_jobs
        logger.info(f"过滤掉 {expired_count} 个已过期 Indeed 岗位，剩余 {len(all_jobs)} 个岗位")
        
        if not all_jobs:
            logger.warning("过滤过期岗位后没有剩余岗位，脚本结束")
            return
        
        with open(f'jobs_{datetime.now().strftime("%Y%m%d")}.json', 'w', encoding='utf-8') as f:
            json.dump(all_jobs, f, ensure_ascii=False, indent=2)
        
        analyzer = ResumeAnalyzer(config)
        top_jobs = analyzer.analyze_jobs(all_jobs, resume)
        
        if top_jobs:
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
