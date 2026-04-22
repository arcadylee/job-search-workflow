#!/usr/bin/env python3
"""
Job Search Automation Script
每天自动从 Indeed、LinkedIn 和 Vancouver 官方网站抓取岗位，
按 3 个求职方向分别匹配对应简历，并将最佳匹配岗位汇总发送到邮箱。
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import List, Dict, Any
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from bs4 import BeautifulSoup
from openai import OpenAI


# =========================
# Logging
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'job_search_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# =========================
# Config
# =========================
class JobSearchConfig:
    """工作搜索配置类"""

    def __init__(self):
        # API Keys
        self.deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')
        self.scraperapi_key = os.getenv('SCRAPERAPI_KEY')

        # Email 配置
        self.email_sender = os.getenv('EMAIL_SENDER')
        self.email_password = os.getenv('EMAIL_PASSWORD')
        self.email_recipient = os.getenv('EMAIL_RECIPIENT')

        # 其他配置
        self.distance_km = 50
        self.max_history = 1000
        self.max_email_jobs_per_category = 5

        # 温哥华经纬度（保留）
        self.vancouver_coords = {
            'latitude': float(os.getenv('LATITUDE')),
            'longitude': float(os.getenv('LONGITUDE'))
        }

        # 三类岗位配置
        self.job_categories = {
            "pm": {
                "display_name": "Product / Project / Program Management",
                "resume": os.getenv("RESUME_PM_CONTENT", ""),
                "keywords": [
                    "product manager",
                    "project manager",
                    "program manager"
                ],
                "min_match_score": 70
            },
            "marketing": {
                "display_name": "Marketing / Brand / Communications",
                "resume": os.getenv("RESUME_MARKETING_CONTENT", ""),
                "keywords": [
                    "marketing manager",
                    "brand manager",
                    "communications manager",
                    "communication manager"
                ],
                "min_match_score": 70
            },
            "admin": {
                "display_name": "Administrative / IT Administration",
                "resume": os.getenv("RESUME_ADMIN_CONTENT", ""),
                "keywords": [
                    "administrative assistant",
                    "administrative coordinator",
                    "office administrator",
                    "it administrator",
                    "it administration"
                ],
                "min_match_score": 65
            }
        }

        self.validate()

    def validate(self):
        required = {
            'DEEPSEEK_API_KEY': self.deepseek_api_key,
            'EMAIL_SENDER': self.email_sender,
            'EMAIL_PASSWORD': self.email_password,
            'EMAIL_RECIPIENT': self.email_recipient
        }

        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")


# =========================
# Scraper
# =========================
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

    def scrape_indeed(self, keywords: List[str], category_key: str) -> List[Dict[str, Any]]:
        jobs = []
        logger.info(f"[{category_key}] 开始抓取 Indeed 岗位...")

        for keyword in keywords:
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
                        parsed = self._parse_indeed_results(response.text, category_key)
                        jobs.extend(parsed)
                        logger.info(f"  [{category_key}] 关键词 '{keyword}' 获取了 {len(parsed)} 个岗位")
                        break
                    elif response.status_code == 500 and attempt < 2:
                        logger.warning(f"  [{category_key}] Indeed 500错误 (关键词: {keyword})，第 {attempt + 1} 次重试...")
                        time.sleep(3 * (attempt + 1))
                    else:
                        logger.warning(f"  [{category_key}] Indeed 请求失败 (关键词: {keyword}): HTTP {response.status_code}")
                        break

                except requests.exceptions.Timeout:
                    if attempt < 2:
                        logger.warning(f"  [{category_key}] Indeed 超时 (关键词: {keyword})，第 {attempt + 1} 次重试...")
                        time.sleep(3)
                    else:
                        logger.warning(f"  [{category_key}] Indeed 持续超时 (关键词: {keyword})，放弃")
                except Exception as e:
                    logger.warning(f"  [{category_key}] Indeed 抓取错误 (关键词: {keyword}): {str(e)}")
                    break

            time.sleep(2)

        logger.info(f"[{category_key}] Indeed 总共获取了 {len(jobs)} 个岗位")
        return jobs

    def _parse_indeed_results(self, html: str, category_key: str) -> List[Dict[str, Any]]:
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
                    'category': category_key,
                    'title': title,
                    'company': company,
                    'location': location,
                    'url': job_link,
                    'description': description,
                    'posted_date': datetime.now().isoformat()
                })

            except Exception as e:
                logger.debug(f"[{category_key}] 解析 Indeed 岗位卡片失败: {str(e)}")
                continue

        return jobs

    def _extract_indeed_detail_url(self, href: str) -> str:
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
            return ''
        except Exception:
            return ''

    def scrape_linkedin(self, keywords: List[str], category_key: str) -> List[Dict[str, Any]]:
        jobs = []
        logger.info(f"[{category_key}] 开始抓取 LinkedIn 岗位...")

        geo_id = self._get_linkedin_geo_id('Vancouver')
        if not geo_id:
            logger.warning(f"[{category_key}] 无法获取 Vancouver 的 geoId，将使用 location 参数代替")

        for keyword in keywords:
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
                    parsed = self._parse_linkedin_results(response.text, category_key)
                    jobs.extend(parsed)
                    logger.info(f"  [{category_key}] 关键词 '{keyword}' 获取了 {len(parsed)} 个岗位")
                else:
                    logger.warning(f"  [{category_key}] LinkedIn search 失败 (关键词: {keyword}): HTTP {response.status_code}")

                time.sleep(2)

            except requests.exceptions.Timeout:
                logger.warning(f"  [{category_key}] LinkedIn 超时 (关键词: {keyword})")
            except Exception as e:
                logger.warning(f"  [{category_key}] LinkedIn 抓取错误 (关键词: {keyword}): {str(e)}")

        seen_urls = set()
        unique_jobs = []
        for job in jobs:
            url = job.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_jobs.append(job)
            elif not url:
                unique_jobs.append(job)

        logger.info(f"[{category_key}] LinkedIn 去重前 {len(jobs)} 条 → 去重后 {len(unique_jobs)} 条")
        jobs = unique_jobs

        logger.info(f"[{category_key}] 开始获取 LinkedIn 岗位详情（处理 {min(len(jobs), 20)} 条）...")
        for job in jobs[:20]:
            job_id = self._extract_linkedin_job_id(job.get('url', ''))
            if job_id:
                desc = self._get_linkedin_job_description(job_id)
                if desc:
                    job['description'] = desc
                time.sleep(1)

        logger.info(f"[{category_key}] LinkedIn 总共获取了 {len(jobs)} 个岗位")
        return jobs

    def scrape_vancouver_jobs(self, keywords: List[str], category_key: str) -> List[Dict[str, Any]]:
        jobs = []
        logger.info(f"[{category_key}] 开始抓取 Vancouver 官方岗位...")

        base_url = "https://jobs.vancouver.ca/"
        seen_urls = set()

        try:
            response = self.session.get(base_url, timeout=30)
            if response.status_code != 200:
                logger.warning(f"[{category_key}] Vancouver jobs 请求失败: HTTP {response.status_code}")
                return jobs

            soup = BeautifulSoup(response.text, 'lxml')
            lower_keywords = [k.lower() for k in keywords]

            for link in soup.find_all('a', href=True):
                title = link.get_text(" ", strip=True)
                href = link.get('href', '').strip()

                if not title or not href:
                    continue

                title_lower = title.lower()

                if not any(k in title_lower for k in lower_keywords):
                    continue

                if any(bad in title_lower for bad in ['login', 'search', 'home', 'apply now', 'sign in']):
                    continue

                if href.startswith('http'):
                    job_url = href
                else:
                    job_url = base_url.rstrip('/') + '/' + href.lstrip('/')

                if job_url in seen_urls:
                    continue
                seen_urls.add(job_url)

                jobs.append({
                    'source': 'Vancouver',
                    'category': category_key,
                    'title': title,
                    'company': 'City of Vancouver',
                    'location': 'Vancouver, BC',
                    'url': job_url,
                    'description': title,
                    'posted_date': datetime.now().isoformat()
                })

        except requests.exceptions.Timeout:
            logger.warning(f"[{category_key}] Vancouver jobs 请求超时")
        except Exception as e:
            logger.warning(f"[{category_key}] Vancouver jobs 抓取失败: {str(e)}")

        logger.info(f"[{category_key}] Vancouver Jobs 获取 {len(jobs)} 条")
        return jobs

    def _get_linkedin_geo_id(self, city: str) -> str:
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
                        logger.info(f"获取到 Vancouver geoId: {hit['id']}")
                        return str(hit['id'])
        except Exception as e:
            logger.debug(f"获取 geoId 失败: {str(e)}")
        return ''

    def _parse_linkedin_results(self, html: str, category_key: str) -> List[Dict[str, Any]]:
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
                    'category': category_key,
                    'title': title,
                    'company': company_elem.get_text(strip=True) if company_elem else 'Unknown',
                    'location': location_elem.get_text(strip=True) if location_elem else 'Unknown',
                    'url': url,
                    'description': '',
                    'posted_date': datetime.now().isoformat()
                })

            except Exception as e:
                logger.debug(f"[{category_key}] 解析 LinkedIn 卡片失败: {str(e)}")
                continue

        return jobs

    def _extract_linkedin_job_id(self, url: str) -> str:
        if not url:
            return ''
        clean_url = url.split('?')[0]
        parts = clean_url.rstrip('/').split('-')
        if parts:
            return parts[-1]
        return ''

    def _get_linkedin_job_description(self, job_id: str) -> str:
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
                                return parent_text
                        for sibling in elem.find_next_siblings():
                            sibling_text = sibling.get_text(separator='\n', strip=True)
                            if len(sibling_text) > 100:
                                return sibling_text

                for elem in soup.find_all(True):
                    classes = elem.get('class', [])
                    class_str = ' '.join(classes) if isinstance(classes, list) else str(classes)
                    if 'description__text' in class_str:
                        text = elem.get_text(separator='\n', strip=True)
                        if len(text) > 100:
                            return text

                for elem in soup.find_all(True):
                    classes = elem.get('class', [])
                    class_str = ' '.join(classes) if isinstance(classes, list) else str(classes)
                    if 'description' in class_str.lower():
                        section = elem.find('section')
                        if section:
                            div = section.find('div')
                            if div and len(div.get_text(strip=True)) > 100:
                                return div.get_text(separator='\n', strip=True)

                candidates = []
                for div in soup.find_all('div'):
                    text = div.get_text(separator='\n', strip=True)
                    if 200 < len(text) < 10000:
                        candidates.append((len(text), text))
                if candidates:
                    candidates.sort(reverse=True)
                    return candidates[0][1]

            return ''
        except Exception as e:
            logger.warning(f"获取 LinkedIn 岗位详情失败 (id={job_id}): {str(e)}")
            return ''

    def get_indeed_page_html(self, job_url: str) -> str:
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
                logger.warning(f"Indeed 详情页 HTTP {response.status_code}: {job_url}")
                return ''

            if len(response.text) < 500:
                logger.warning(f"Indeed 页面太短，可能不是正常岗位页: {job_url}")
                return ''

            return response.text

        except Exception as e:
            logger.warning(f"Indeed 详情页异常: {str(e)} | {job_url}")
            return ''

    def is_indeed_job_active(self, html: str) -> bool:
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
        try:
            if not html:
                return ''

            soup = BeautifulSoup(html, 'lxml')

            desc_elem = soup.find('div', id='jobDescriptionText')
            if desc_elem and len(desc_elem.get_text(strip=True)) > 50:
                return desc_elem.get_text(separator='\n', strip=True)

            desc_elem = soup.find(attrs={'class': lambda c: c and 'jobDescriptionText' in str(c)})
            if desc_elem and len(desc_elem.get_text(strip=True)) > 50:
                return desc_elem.get_text(separator='\n', strip=True)

            for heading in soup.find_all(['h2', 'h3', 'h4', 'span', 'div']):
                if 'full job description' in heading.get_text(strip=True).lower():
                    for sibling in heading.find_next_siblings():
                        text = sibling.get_text(separator='\n', strip=True)
                        if len(text) > 100:
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
                return candidates[0][1]

            return ''
        except Exception as e:
            logger.warning(f"从 Indeed HTML 提取描述异常: {str(e)} | {job_url}")
            return ''

    def _build_query_string(self, params: Dict[str, Any]) -> str:
        return '&'.join([f"{k}={v}" for k, v in params.items()])


# =========================
# Analyzer
# =========================
class ResumeAnalyzer:
    def __init__(self, config: JobSearchConfig):
        self.config = config
        self.client = OpenAI(
            api_key=config.deepseek_api_key,
            base_url="https://api.deepseek.com"
        )

    def analyze_jobs(self, jobs: List[Dict[str, Any]], resume: str, max_jobs: int) -> List[Dict[str, Any]]:
        logger.info(f"开始使用 DeepSeek 分析 {len(jobs)} 个岗位...")

        if not jobs:
            return []

        jobs_summary = self._prepare_jobs_for_analysis(jobs)

        prompt = f"""
你是一位专业的职业顾问和招聘专家。请根据我的简历，从下面的岗位列表中筛选出最匹配的岗位并分析。

注意：
1. 请直接从列表中挑选最好的岗位来分析，不需要对每个岗位都评分。
2. 输出数量不超过 {max_jobs} 个。
3. 只返回 JSON，不要包含任何其他文字。

我的简历：
{resume}

岗位列表：
{jobs_summary}

请以如下 JSON 格式返回结果：
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

            if '```json' in result_text:
                result_text = result_text.split('```json')[1]
            if '```' in result_text:
                result_text = result_text.split('```')[0]
            result_text = result_text.strip()

            try:
                analysis_result = json.loads(result_text)
            except json.JSONDecodeError:
                result_text = self._fix_truncated_json(result_text)
                analysis_result = json.loads(result_text)

            top_jobs = []
            for match in analysis_result.get('top_matches', [])[:max_jobs]:
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
            return jobs[:max_jobs]

    def _fix_truncated_json(self, text: str) -> str:
        last_brace = text.rfind('}')
        if last_brace == -1:
            raise ValueError("无法修复：没有找到任何完整的 JSON object")

        text = text[:last_brace + 1]
        open_braces = text.count('{') - text.count('}')
        open_brackets = text.count('[') - text.count(']')
        text = text.rstrip().rstrip(',')
        text += ']' * open_brackets + '}' * open_braces
        return text

    def _prepare_jobs_for_analysis(self, jobs: List[Dict[str, Any]]) -> str:
        jobs_text = []
        for idx, job in enumerate(jobs):
            desc = job.get('description', '').strip()
            if desc:
                jobs_text.append(
                    f"职位 {idx}: {job['title']}\n"
                    f"公司: {job['company']} | 地点: {job['location']}\n"
                    f"描述: {desc[:500]}\n"
                )
            else:
                jobs_text.append(
                    f"职位 {idx}: {job['title']} @ {job['company']}（无详细描述）\n"
                )
        return '\n'.join(jobs_text)


# =========================
# Email
# =========================
class EmailSender:
    def __init__(self, config: JobSearchConfig):
        self.config = config

    def send_combined_report(self, category_results: Dict[str, Dict[str, Any]]):
        total_jobs = sum(len(v["jobs"]) for v in category_results.values())
        logger.info(f"准备发送汇总邮件，总岗位数 {total_jobs}")

        html_content = self._create_combined_html_report(category_results)

        subject_parts = []
        for _, data in category_results.items():
            if data["jobs"]:
                subject_parts.append(f'{data["short_name"]} ({len(data["jobs"])})')

        if subject_parts:
            subject_suffix = " | ".join(subject_parts)
        else:
            subject_suffix = "No qualified jobs"

        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Daily Job Matches — {subject_suffix} ({datetime.now().strftime("%Y-%m-%d")})'
        msg['From'] = self.config.email_sender
        msg['To'] = self.config.email_recipient

        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)

        try:
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(self.config.email_sender, self.config.email_password)
                server.send_message(msg)
            logger.info("汇总邮件发送成功！")
        except Exception as e:
            logger.error(f"邮件发送失败: {str(e)}")

    def _create_combined_html_report(self, category_results: Dict[str, Dict[str, Any]]) -> str:
        total_jobs = sum(len(v["jobs"]) for v in category_results.values())

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
            max-width: 900px;
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
        .category-section {{
            margin-bottom: 40px;
        }}
        .category-title {{
            font-size: 24px;
            font-weight: bold;
            margin: 24px 0 12px 0;
            color: #2c3e50;
            border-bottom: 2px solid #ddd;
            padding-bottom: 8px;
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
        .empty-note {{
            color: #888;
            font-style: italic;
            padding: 10px 0 20px 0;
        }}
        .footer {{
            text-align: center;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            color: #7f8c8d;
        }}
        ul {{
            margin: 5px 0;
            padding-left: 20px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🎯 Daily Job Matches</h1>
        <p>{datetime.now().strftime("%Y-%m-%d")} — {total_jobs} qualified matches across all categories</p>
    </div>
"""

        for _, data in category_results.items():
            display_name = data["display_name"]
            jobs = data["jobs"]

            html += f'<div class="category-section"><div class="category-title">{display_name}</div>'

            if not jobs:
                html += '<div class="empty-note">No qualified new jobs today.</div></div>'
                continue

            for idx, job in enumerate(jobs, 1):
                analysis = job.get('analysis', {})
                match_score = analysis.get('match_score', 0)

                html += f"""
    <div class="job-card">
        <div class="job-title">#{idx} {job['title']}</div>
        <div class="company">🏢 {job['company']}</div>
        <div class="location">📍 {job['location']}</div>
        <div class="match-score">Match Score: {match_score}%</div>

        <div><strong>Source:</strong> {job.get('source', 'Unknown')}</div>

        <div style="margin-top: 10px;">
            <strong>Strengths:</strong>
            <ul>
"""
                for strength in analysis.get('strengths', []):
                    html += f"<li>{strength}</li>"

                html += """
            </ul>
        </div>

        <div>
            <strong>Weaknesses:</strong>
            <ul>
"""
                for weakness in analysis.get('weaknesses', []):
                    html += f"<li>{weakness}</li>"

                html += f"""
            </ul>
        </div>

        <div class="recommendation">
            <strong>Recommendation:</strong> {analysis.get('recommendation', 'Consider applying')}
        </div>
"""

                desc = job.get('description', '').strip()
                if desc:
                    preview = desc[:180].replace('\n', ' ').strip()
                    if len(desc) > 180:
                        preview += '...'
                    html += f'<div><strong>Description Preview:</strong> {preview}</div>'

                html += f"""
        <a href="{job['url']}" class="apply-button" target="_blank">View Job →</a>
    </div>
"""
            html += '</div>'

        html += """
    <div class="footer">
        <p>This report was generated automatically | Powered by DeepSeek AI</p>
        <p>Good luck with your job search! 🚀</p>
    </div>
</body>
</html>
"""
        return html


# =========================
# Helpers
# =========================
def make_job_key(job: Dict[str, Any]) -> str:
    url = job.get('url', '').strip().lower()
    if url:
        return url

    title = job.get('title', '').strip().lower()
    company = job.get('company', '').strip().lower()
    return f"{title}|{company}"


def dedupe_jobs(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_keys = set()
    deduped = []
    for job in jobs:
        key = make_job_key(job)
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(job)
    return deduped


def get_history_file(category_key: str) -> str:
    return f'.job_history/sent_jobs_{category_key}.json'


def load_sent_job_history(filepath: str) -> List[str]:
    if not os.path.exists(filepath):
        return []

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"读取历史推荐失败: {str(e)}")
        return []


def save_sent_job_history(job_keys: List[str], filepath: str):
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(job_keys, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"保存历史推荐失败: {str(e)}")


def append_unique_job_keys(existing_keys: List[str], new_keys: List[str], max_history: int) -> List[str]:
    merged = list(existing_keys)
    seen = set(existing_keys)

    for key in new_keys:
        if key not in seen:
            merged.append(key)
            seen.add(key)

    if len(merged) > max_history:
        merged = merged[-max_history:]

    return merged


def filter_expired_indeed_jobs(jobs: List[Dict[str, Any]], scraper: JobScraper) -> List[Dict[str, Any]]:
    active_jobs = []
    expired_count = 0

    for job in jobs:
        if job['source'] != 'Indeed' or not job.get('url'):
            active_jobs.append(job)
            continue

        html = scraper.get_indeed_page_html(job['url'])
        if not scraper.is_indeed_job_active(html):
            expired_count += 1
            logger.info(f"跳过已过期 Indeed 岗位: {job['title']} | {job['company']}")
            time.sleep(1)
            continue

        if len(job.get('description', '')) < 200:
            full_desc = scraper.get_indeed_description_from_html(html, job['url'])
            if full_desc and len(full_desc) > len(job.get('description', '')):
                job['description'] = full_desc

        active_jobs.append(job)
        time.sleep(1)

    logger.info(f"过滤掉 {expired_count} 个已过期 Indeed 岗位，剩余 {len(active_jobs)} 个岗位")
    return active_jobs


def filter_sent_history(jobs: List[Dict[str, Any]], category_key: str) -> (List[Dict[str, Any]], List[str]):
    history_file = get_history_file(category_key)
    sent_keys = load_sent_job_history(history_file)
    sent_key_set = set(sent_keys)

    new_jobs = []
    duplicate_sent_count = 0

    for job in jobs:
        job_key = make_job_key(job)
        if job_key in sent_key_set:
            duplicate_sent_count += 1
            logger.info(f"[{category_key}] 跳过历史已推荐岗位: {job['title']} | {job['company']}")
            continue
        new_jobs.append(job)

    logger.info(f"[{category_key}] 过滤掉 {duplicate_sent_count} 个历史已推荐岗位，剩余 {len(new_jobs)} 个新岗位")
    return new_jobs, sent_keys


# =========================
# Main
# =========================
def main():
    logger.info("=" * 60)
    logger.info("开始每日工作搜索...")
    logger.info("=" * 60)

    try:
        config = JobSearchConfig()
        scraper = JobScraper(config)
        analyzer = ResumeAnalyzer(config)

        category_results: Dict[str, Dict[str, Any]] = {}

        for category_key, category_cfg in config.job_categories.items():
            logger.info("=" * 30)
            logger.info(f"处理类别: {category_key} / {category_cfg['display_name']}")
            logger.info("=" * 30)

            resume = category_cfg["resume"]
            keywords = category_cfg["keywords"]
            min_match_score = category_cfg["min_match_score"]

            if not resume:
                logger.warning(f"[{category_key}] 未提供对应简历，跳过该类别")
                category_results[category_key] = {
                    "display_name": category_cfg["display_name"],
                    "short_name": category_key.upper(),
                    "jobs": []
                }
                continue

            indeed_jobs = scraper.scrape_indeed(keywords, category_key)
            linkedin_jobs = scraper.scrape_linkedin(keywords, category_key)
            vancouver_jobs = scraper.scrape_vancouver_jobs(keywords, category_key)

            all_jobs = indeed_jobs + linkedin_jobs + vancouver_jobs
            logger.info(f"[{category_key}] 合并前总共 {len(all_jobs)} 个岗位")

            all_jobs = dedupe_jobs(all_jobs)
            logger.info(f"[{category_key}] 去重后剩余 {len(all_jobs)} 个岗位")

            if not all_jobs:
                category_results[category_key] = {
                    "display_name": category_cfg["display_name"],
                    "short_name": category_key.upper(),
                    "jobs": []
                }
                continue

            all_jobs = filter_expired_indeed_jobs(all_jobs, scraper)

            if not all_jobs:
                category_results[category_key] = {
                    "display_name": category_cfg["display_name"],
                    "short_name": category_key.upper(),
                    "jobs": []
                }
                continue

            all_jobs, sent_keys = filter_sent_history(all_jobs, category_key)

            if not all_jobs:
                category_results[category_key] = {
                    "display_name": category_cfg["display_name"],
                    "short_name": category_key.upper(),
                    "jobs": []
                }
                continue

            with open(f'jobs_{category_key}_{datetime.now().strftime("%Y%m%d")}.json', 'w', encoding='utf-8') as f:
                json.dump(all_jobs, f, ensure_ascii=False, indent=2)

            analyzed_jobs = analyzer.analyze_jobs(
                jobs=all_jobs,
                resume=resume,
                max_jobs=config.max_email_jobs_per_category
            )

            filtered_jobs = [
                job for job in analyzed_jobs
                if job.get('analysis', {}).get('match_score', 0) >= min_match_score
            ][:config.max_email_jobs_per_category]

            logger.info(
                f"[{category_key}] AI 推荐 {len(analyzed_jobs)} 个岗位，"
                f"过滤到 {len(filtered_jobs)} 个 (最低匹配度 {min_match_score})"
            )

            category_results[category_key] = {
                "display_name": category_cfg["display_name"],
                "short_name": category_key.upper(),
                "jobs": filtered_jobs
            }

            if filtered_jobs:
                new_sent_keys = [make_job_key(job) for job in filtered_jobs]
                updated_history = append_unique_job_keys(
                    existing_keys=sent_keys,
                    new_keys=new_sent_keys,
                    max_history=config.max_history
                )
                save_sent_job_history(updated_history, get_history_file(category_key))

        total_jobs = sum(len(v["jobs"]) for v in category_results.values())

        if total_jobs > 0:
            email_sender = EmailSender(config)
            email_sender.send_combined_report(category_results)
            logger.info(f"成功完成！共发送 {total_jobs} 个岗位推荐")
        else:
            logger.warning("今天没有符合条件的新岗位，未发送邮件")

    except Exception as e:
        logger.error(f"脚本执行失败: {str(e)}", exc_info=True)
        raise

    logger.info("=" * 60)
    logger.info("每日工作搜索完成")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
