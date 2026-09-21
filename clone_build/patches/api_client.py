import json, re, time, requests, random
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin, parse_qs, urlencode
from core.constants import DOMAINS, STATUS_MAP, ID_TO_STATUS_MAP, ENG_STATUS_MAP


class _LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links=[]
        self._cur=None
    def handle_starttag(self, tag, attrs):
        if tag.lower()=='a':
            a=dict(attrs)
            self._cur={'href':a.get('href',''),'text':'','title':a.get('aria-label') or a.get('title') or ''}
    def handle_data(self, data):
        if self._cur is not None:
            self._cur['text'] += data
    def handle_endtag(self, tag):
        if tag.lower()=='a' and self._cur is not None:
            self._cur['text']=' '.join(self._cur['text'].split()) or self._cur.get('title','')
            self.links.append(self._cur)
            self._cur=None


class _FormCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms=[]
        self._form=None
        self._textarea=None
    def handle_starttag(self, tag, attrs):
        tag=tag.lower(); a=dict(attrs)
        if tag=='form':
            self._form={'action':a.get('action',''),'method':(a.get('method') or 'post').lower(),'fields':{},'textareas':[],'submit':None}
        elif self._form is not None and tag=='input':
            name=a.get('name'); typ=(a.get('type') or 'text').lower()
            if name and typ not in ('checkbox','radio','file'):
                self._form['fields'][name]=a.get('value','')
            if typ=='submit' and name and self._form.get('submit') is None:
                self._form['submit']=(name,a.get('value',''))
        elif self._form is not None and tag=='textarea':
            name=a.get('name')
            if name:
                self._textarea={'name':name,'text':''}
        elif self._form is not None and tag=='button':
            name=a.get('name')
            if name and self._form.get('submit') is None:
                self._form['submit']=(name,a.get('value',''))
    def handle_data(self, data):
        if self._textarea is not None:
            self._textarea['text'] += data
    def handle_endtag(self, tag):
        tag=tag.lower()
        if tag=='textarea' and self._form is not None and self._textarea is not None:
            self._form['textareas'].append(self._textarea)
            self._form['fields'][self._textarea['name']]=self._textarea['text']
            self._textarea=None
        elif tag=='form' and self._form is not None:
            self.forms.append(self._form)
            self._form=None
            self._textarea=None


class VintedAPI:
    def __init__(self):
        self.session=requests.Session()
        self.session.headers.update({
            'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept':'application/json, text/plain, */*','Accept-Language':'en-US,en;q=0.9'
        })
        self.domain='vinted.fr'; self._current_country_code='fr'
        self._csrf_token=None; self._csrf_token_time=0
        self._cached_user_info=None; self._user_info_time=0
        self._last_cookie_input=None; self._seller_rating_cache={}

    def _detect_code_from_domain(self, domain):
        d=(domain or '').lower().lstrip('.')
        if d.startswith('www.'): d=d[4:]
        for code,dom in DOMAINS.items():
            if d==dom or d.endswith('.'+dom) or dom in d: return code
        if d.startswith('vinted.'):
            suffix=d.replace('vinted.','',1)
            return 'co.uk' if suffix in ('co.uk','uk') else suffix if suffix in DOMAINS else None
        return None

    def set_domain(self,country_code='fr'):
        self._current_country_code=country_code if country_code in DOMAINS else 'fr'
        self.domain=DOMAINS.get(self._current_country_code,'vinted.fr')

    def set_cookie(self, cookie_input):
        """Load Cookie Helper output into the authenticated requests session.

        Keep the browser cookie domain/path information intact and reset all
        cached identity/CSRF state whenever the browser sends a new snapshot.
        """
        current_input = cookie_input.strip() if isinstance(cookie_input, str) else cookie_input
        self._last_cookie_input = current_input
        self._cached_user_info = None
        self._user_info_time = 0
        self._csrf_token = None
        self._csrf_token_time = 0

        detected_code = None
        try:
            data = json.loads(current_input) if isinstance(current_input, str) else current_input
            domain_from_json = ''
            if isinstance(data, dict):
                domain_from_json = str(data.get('domain', '') or '')
                data = data.get('cookies', data)
                detected_code = self._detect_code_from_domain(domain_from_json) or detected_code

            if isinstance(data, list):
                # The original extension sends a complete cookie snapshot.
                # Clear the previous snapshot so a re-sync cannot leave stale
                # account cookies in the requests CookieJar.
                self.session.cookies.clear()
                loaded = 0
                for cookie in data:
                    if not isinstance(cookie, dict):
                        continue
                    name = str(cookie.get('name', '') or '')
                    if not name:
                        continue
                    value = str(cookie.get('value', '') or '')
                    domain_str = str(cookie.get('domain', '') or domain_from_json or self.domain)
                    path = str(cookie.get('path', '/') or '/')
                    self.session.cookies.set(name, value, domain=domain_str, path=path)
                    loaded += 1
                    detected_code = detected_code or self._detect_code_from_domain(domain_str)

                if detected_code:
                    self.set_domain(detected_code)
                    print(f'🌍 从 Cookie 域检测到站点: {detected_code}')
                return loaded > 0

            if isinstance(data, dict):
                self.session.cookies.clear()
                loaded = 0
                for k, v in data.items():
                    if isinstance(v, (str, int, float)):
                        self.session.cookies.set(str(k), str(v), domain=self.domain, path='/')
                        loaded += 1
                return loaded > 0
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        if isinstance(current_input, str):
            self.session.cookies.clear()
            found = False
            for item in current_input.split(';'):
                if '=' not in item:
                    continue
                k, v = item.strip().split('=', 1)
                if k:
                    self.session.cookies.set(k, v, domain=self.domain, path='/')
                    found = True

            low = current_input.lower()
            if '_vinted_' in low:
                for code in DOMAINS:
                    probe = 'uk' if code == 'co.uk' else code
                    if f'_{probe}_' in low:
                        self.set_domain(code)
                        print(f'🌍 回退到 Cookie 名称检测: {code}')
                        break
            return found
        return False

    def get_current_user(self, force=False):
        now=time.time()
        if (not force) and self._cached_user_info and now-self._user_info_time < 900:
            return self._cached_user_info
        try:
            r=self.session.get(f'https://www.{self.domain}/api/v2/users/current',timeout=10)
            if r.status_code==401: return None
            r.raise_for_status(); u=r.json().get('user')
            if not u: return None
            info={'user_id':u.get('id'),'username':u.get('login') or u.get('real_name') or 'Unknown User','avatar_url':(u.get('photo') or {}).get('url')}
            self._cached_user_info=info; self._user_info_time=now; return info
        except requests.RequestException: return None

    def get_csrf_token(self):
        now=time.time()
        if self._csrf_token and now-self._csrf_token_time < 900: return self._csrf_token
        try:
            text=self.session.get(f'https://www.{self.domain}',timeout=10).text
            m=re.search(r'\\"CSRF_TOKEN\\":\\"(.*?)\\"',text) or re.search(r'"CSRF_TOKEN":"(.*?)"',text)
            self._csrf_token=m.group(1) if m else None; self._csrf_token_time=now if self._csrf_token else 0
            return self._csrf_token
        except requests.RequestException: return None

    def get_anonymous_cookie(self,country_code='fr'):
        self.set_domain(country_code); url='https://www.'+self.domain
        headers={
            'User-Agent':self.session.headers['User-Agent'],
            'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language':'en-US,en;q=0.9','Accept-Encoding':'gzip, deflate, br',
            'Connection':'keep-alive','Upgrade-Insecure-Requests':'1'
        }
        try:
            self.session.get(url,headers=headers,timeout=15,allow_redirects=True).raise_for_status()
            cookies=self.session.cookies.get_dict()
            if cookies: return {'success':True,'country_code':country_code,'domain':self.domain,'cookies':cookies}
            return {'success':False,'message':'未能获取到 Cookie'}
        except requests.Timeout: return {'success':False,'message':'请求超时，请检查网络连接'}
        except requests.RequestException as e: return {'success':False,'message':f'网络请求失败: {e}'}
        except Exception as e: return {'success':False,'message':f'获取失败: {e}'}

    def fetch_brands(self,keyword=''):
        try:
            params={'page':1,'per_page':6}
            if keyword: params['keyword']=keyword
            r=self.session.get(f'https://www.{self.domain}/api/v2/brands',params=params,timeout=5); r.raise_for_status()
            out=[]
            for item in r.json().get('brands',[]):
                out.append({'id':item.get('id'),'title':item.get('title'),'pretty_favourite_count':item.get('pretty_favourite_count','0'),'requires_authenticity_check':item.get('requires_authenticity_check',False)})
            return out
        except Exception: return []

    def _market_locale(self):
        return {
            'vinted.co.uk':'en-GB','vinted.com':'en-US','vinted.fr':'fr-FR','vinted.de':'de-DE',
            'vinted.it':'it-IT','vinted.es':'es-ES','vinted.pl':'pl-PL','vinted.nl':'nl-NL',
            'vinted.be':'fr-BE','vinted.at':'de-AT','vinted.ie':'en-IE'
        }.get(self.domain,'en-US')

    def _catalog_api_headers(self):
        site=f'https://www.{self.domain}'
        locale=self._market_locale()
        headers={
            'User-Agent':self.session.headers.get('User-Agent','Mozilla/5.0'),
            'Accept':'application/json, text/plain, */*',
            'Accept-Language':f'{locale},en;q=0.5',
            'Cache-Control':'no-cache','Pragma':'no-cache',
            'Origin':site,'Referer':site+'/',
            'Locale':locale,'Platform':'web','X-Next-App':'marketplace-web',
            'Sec-Fetch-Dest':'empty','Sec-Fetch-Mode':'cors','Sec-Fetch-Site':'same-site',
        }
        if getattr(self,'_anon_id',None): headers['X-Anon-Id']=self._anon_id
        return headers

    def _refresh_catalog_identity(self):
        # The catalogue service moved off the www host in Sep 2026.
        # Refresh the web session once so Vinted can provide the anonymous API identity header.
        try:
            site=f'https://www.{self.domain}'
            r=self.session.get(site+'/',headers={
                'User-Agent':self.session.headers.get('User-Agent','Mozilla/5.0'),
                'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language':f'{self._market_locale()},en;q=0.5',
                'Upgrade-Insecure-Requests':'1'
            },timeout=12,allow_redirects=True)
            self._anon_id=(r.headers.get('X-Anon-Id') or r.headers.get('x-anon-id') or '').strip() or getattr(self,'_anon_id',None)
        except Exception:
            pass

    def fetch_items(self,search_text='',per_page=50,price_min=None,price_max=None,status_text='全部',sort_by_popularity=False,sort_by_newest=False,brand_ids=None):
        # Current Vinted web catalogue endpoint (Sep 2026): api.<market>/svc-catalogue/items.
        # Filter keys also changed from brand_ids[]/status_ids[] to attribute_ids[...].
        params={'search_text':search_text,'per_page':int(per_page),'page':1,'order':'newest_first' if sort_by_newest else 'relevance'}
        if price_min not in (None,''): params['price_from']=price_min
        if price_max not in (None,''): params['price_to']=price_max
        bids=[str(x) for x in (brand_ids or []) if x not in (None,'')]
        if bids: params['attribute_ids[brand]']=','.join(bids)
        sids=[str(x) for x in STATUS_MAP.get(status_text,[]) if x not in (None,'')]
        if sids: params['attribute_ids[status]']=','.join(sids)

        self._refresh_catalog_identity()
        api_host='https://api.'+self.domain
        url=api_host+'/svc-catalogue/items'
        r=self.session.get(url,params=params,headers=self._catalog_api_headers(),timeout=15)
        # Refresh once on session/auth-related failures.
        if r.status_code in (401,403,404):
            self._refresh_catalog_identity()
            r=self.session.get(url,params=params,headers=self._catalog_api_headers(),timeout=15)
        r.raise_for_status()
        data=r.json()
        items=[self._parse_item(x) for x in data.get('items',[])]
        if sort_by_popularity: items.sort(key=lambda x:x.get('likes',0) or 0,reverse=True)
        return items[:int(per_page)]

    def _fetch_single_user(self,user_id):
        if not user_id: return {'feedback_count':0,'feedback_reputation':0.0}
        if user_id in self._seller_rating_cache: return self._seller_rating_cache[user_id]
        try:
            r=self.session.get(f'https://www.{self.domain}/api/v2/users/{user_id}',timeout=5); r.raise_for_status()
            u=r.json().get('user') or r.json()
            result={'feedback_count':u.get('feedback_count',0) or 0,'feedback_reputation':u.get('feedback_reputation',0.0) or 0.0}
            self._seller_rating_cache[user_id]=result
            time.sleep(random.uniform(0.02,0.08))
            return result
        except Exception:
            return {'feedback_count':0,'feedback_reputation':0.0}

    def _parse_item(self,item):
        u=item.get('user') or {}; photo=item.get('photo') or {}; price=item.get('price') or {}; raw=item.get('status') or ''; sid=str(item.get('status_id',''))
        status=ID_TO_STATUS_MAP.get(sid) or ENG_STATUS_MAP.get(str(raw).lower()) or raw or (f'未知 ({sid})' if sid else '未知')
        return {
            'id':item.get('id'),'title':item.get('title',''),'price':price.get('amount',''),'currency_code':price.get('currency_code',''),
            'image_path':photo.get('url'),'likes':item.get('favourite_count',0),'status':status,
            'seller_id':u.get('id'),'seller_avatar':(u.get('photo') or {}).get('url'),'seller_username':u.get('login') or u.get('real_name') or '',
            'seller_feedback_count':u.get('feedback_count',0) or 0,'seller_feedback_reputation':u.get('feedback_reputation',0.0) or 0.0,
            'url': item.get('url') or (f"https://www.{self.domain}{item.get('path')}" if item.get('path') else (f"https://www.{self.domain}/items/{item.get('id')}" if item.get('id') else '')),
        }

    def _report_item_meta(self, item_or_id):
        if isinstance(item_or_id, dict):
            item_id=item_or_id.get('id')
            item_url=item_or_id.get('url') or (f'https://www.{self.domain}/items/{item_id}' if item_id else '')
            seller_id=item_or_id.get('seller_id')
        else:
            item_id=item_or_id; item_url=f'https://www.{self.domain}/items/{item_id}' if item_id else ''; seller_id=None
        try: item_id=int(item_id)
        except Exception: item_id=None
        try: seller_id=int(seller_id) if seller_id not in (None,'') else None
        except Exception: seller_id=None
        return item_id,item_url,seller_id

    def _html_headers(self, referer=None):
        h={
            'User-Agent':self.session.headers.get('User-Agent','Mozilla/5.0'),
            'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language':f'{self._market_locale()},en;q=0.5',
            'Upgrade-Insecure-Requests':'1',
        }
        if referer: h['Referer']=referer
        return h

    def _extract_report_entry(self, item_or_id):
        item_id,item_url,seller_id=self._report_item_meta(item_or_id)
        if not item_id:
            return {'success':False,'message':'缺少商品 ID'}
        site=f'https://www.{self.domain}'
        try:
            r=self.session.get(item_url or f'{site}/items/{item_id}',headers=self._html_headers(site+'/'),timeout=12,allow_redirects=True)
            if r.status_code==401:
                return {'success':False,'message':'登录状态已失效 (HTTP 401)'}
            if r.status_code>=400:
                return {'success':False,'message':f'读取商品页面失败 (HTTP {r.status_code})'}
            canonical=r.url or item_url
            parser=_LinkCollector(); parser.feed(r.text or '')
            for link in parser.links:
                href=unescape(link.get('href') or '')
                if '/admin_alert/new' not in href:
                    continue
                full=urljoin(canonical,href)
                q=parse_qs(urlparse(full).query)
                if (q.get('ref_type') or [''])[0] not in ('','item'):
                    continue
                ref_id=(q.get('ref_id') or [''])[0]
                if ref_id and str(ref_id)!=str(item_id):
                    continue
                return {'success':True,'entry_url':full,'item_url':canonical,'html':r.text or ''}

            # Current UK web flow observed in the official site.  Build the
            # same entry URL only when the page did not expose its own link.
            if not seller_id:
                m=re.search(r'"user"\s*:\s*\{[^{}]{0,1800}?"id"\s*:\s*(\d+)',r.text or '',re.S)
                if m:
                    try: seller_id=int(m.group(1))
                    except Exception: seller_id=None
            path=urlparse(canonical).path or f'/items/{item_id}'
            params={'reason_id':57,'ref_id':item_id,'ref_type':'item','ref_url':path}
            if seller_id: params['offender_id']=seller_id
            return {'success':True,'entry_url':site+'/admin_alert/new?'+urlencode(params),'item_url':canonical,'html':r.text or ''}
        except requests.RequestException as e:
            return {'success':False,'message':f'读取举报入口失败: {e}'}

    @staticmethod
    def _reason_id_from_url(url):
        try:
            val=(parse_qs(urlparse(url).query).get('reason_id') or [''])[0]
            return int(val) if str(val).isdigit() else None
        except Exception:
            return None

    def get_report_reasons(self, item_or_id):
        """Read the live reason list from Vinted's current web report flow.

        This avoids the stale numeric reason IDs embedded in older builds.
        It does not submit a report.
        """
        entry=self._extract_report_entry(item_or_id)
        if not entry.get('success'):
            return entry
        try:
            r=self.session.get(entry['entry_url'],headers=self._html_headers(entry.get('item_url')),timeout=12,allow_redirects=True)
            if r.status_code>=400:
                return {'success':False,'message':f'加载当前举报原因失败 (HTTP {r.status_code})'}
            parser=_LinkCollector(); parser.feed(r.text or '')
            current_parent=self._reason_id_from_url(entry['entry_url'])
            seen=set(); reasons=[]
            for link in parser.links:
                href=unescape(link.get('href') or '')
                full=urljoin(r.url,href)
                if '/help/new' not in full and '/admin_alert/new' not in full:
                    continue
                rid=self._reason_id_from_url(full)
                if not rid or rid==current_parent or rid in seen:
                    continue
                text=' '.join((link.get('text') or link.get('title') or '').split())
                if not text or len(text)>120:
                    continue
                seen.add(rid); reasons.append({'id':rid,'label':text,'url':full})

            # Some page variants serialize report reasons in JSON rather than
            # rendering normal anchors.  Recover those IDs/titles as a fallback.
            if not reasons:
                patterns=[
                    r'"reason_id"\s*:\s*(\d+)\s*,\s*"(?:title|name|label)"\s*:\s*"([^"\\]{2,120})"',
                    r'"(?:title|name|label)"\s*:\s*"([^"\\]{2,120})"\s*,\s*"reason_id"\s*:\s*(\d+)',
                ]
                for idx,pat in enumerate(patterns):
                    for m in re.finditer(pat,r.text or '',re.I):
                        if idx==0: rid,txt=int(m.group(1)),m.group(2)
                        else: txt,rid=m.group(1),int(m.group(2))
                        if rid==current_parent or rid in seen: continue
                        txt=bytes(txt,'utf-8').decode('unicode_escape','ignore') if '\\u' in txt else txt
                        txt=' '.join(unescape(txt).split())
                        if txt:
                            seen.add(rid); reasons.append({'id':rid,'label':txt,'url':''})
            if not reasons:
                return {'success':False,'message':'Vinted 当前举报原因未能解析；已停止提交，避免使用过期原因 ID。'}
            return {'success':True,'reasons':reasons,'entry_url':entry['entry_url'],'item_url':entry.get('item_url','')}
        except requests.RequestException as e:
            return {'success':False,'message':f'加载当前举报原因失败: {e}'}

    def _resolve_reason_page(self, item_or_id, reason_id):
        live=self.get_report_reasons(item_or_id)
        if not live.get('success'):
            return live
        reason=next((x for x in live.get('reasons',[]) if int(x.get('id',-1))==int(reason_id)),None)
        if not reason:
            return {'success':False,'message':f'当前页面不存在举报原因 ID {reason_id}，请重新打开举报窗口。'}
        url=reason.get('url')
        if not url:
            entry=live.get('entry_url')
            p=urlparse(entry)
            q=parse_qs(p.query); q['reason_id']=[str(reason_id)]
            # The current flow routes leaf reasons through /help/new.
            flat={k:v[-1] for k,v in q.items() if v}
            url=f'{p.scheme}://{p.netloc}/help/new?'+urlencode(flat)
        return {'success':True,'url':url,'referer':live.get('entry_url'),'reason':reason}

    @staticmethod
    def _response_report_success(response):
        if response.status_code==204:
            return True
        text=(response.text or '').lower().replace('’',"'")
        markers=("we've received your report",'we have received your report','report received')
        if any(m in text for m in markers):
            return True
        ctype=(response.headers.get('content-type') or '').lower()
        if 'json' in ctype:
            try:
                data=response.json()
                if isinstance(data,dict):
                    if data.get('success') is True:
                        return True
                    alert=data.get('admin_alert')
                    if isinstance(alert,dict) and alert.get('id'):
                        return True
                    if response.status_code==201 and data.get('id'):
                        return True
            except Exception:
                pass
        return False

    def _submit_report_form(self, reason_page_url, referer, message=''):
        r=self.session.get(reason_page_url,headers=self._html_headers(referer),timeout=12,allow_redirects=True)
        if r.status_code>=400:
            return {'success':False,'message':f'加载举报确认页失败 (HTTP {r.status_code})'}
        parser=_FormCollector(); parser.feed(r.text or '')
        forms=parser.forms
        if not forms:
            return {'success':False,'message':'当前举报确认页没有发现可提交表单'}
        form=None
        for f in forms:
            names=' '.join(f.get('fields',{}).keys()).lower()
            action=(f.get('action') or '').lower()
            if 'report' in names or 'message' in names or 'admin_alert' in action or '/help' in action:
                form=f; break
        form=form or forms[0]
        action=urljoin(r.url,form.get('action') or r.url)
        data=dict(form.get('fields') or {})
        textareas=form.get('textareas') or []
        if textareas:
            for t in textareas:
                data[t['name']]=message or ''
        else:
            # Common Rails/JSON form field names.  Only populate an existing
            # message-ish field; do not invent unrelated hidden parameters.
            for name in list(data):
                if 'message' in name.lower() or 'description' in name.lower():
                    data[name]=message or ''
        if form.get('submit'):
            name,val=form['submit']
            if name: data.setdefault(name,val)
        headers=self._html_headers(r.url)
        if form.get('method','post')=='get':
            out=self.session.get(action,params=data,headers=headers,timeout=12,allow_redirects=True)
        else:
            out=self.session.post(action,data=data,headers=headers,timeout=12,allow_redirects=True)
        ok=self._response_report_success(out)
        detail=(out.text or '').strip().replace('\n',' ')[:220]
        if ok:
            return {'success':True,'message':f'Vinted 已确认收到举报 (HTTP {out.status_code})','final_url':out.url}
        return {'success':False,'message':f'提交后未检测到 Vinted 成功确认 (HTTP {out.status_code}, {out.url})'+(f'：{detail}' if detail else '')}

    def _submit_legacy_api_verified(self,item_id,user_id,reason_id,message=''):
        """Compatibility fallback for page variants without an HTML form.

        Unlike the previous clone, a bare HTTP 200 is never called success.
        """
        max_retries=2
        for attempt in range(max_retries):
            csrf_token=self.get_csrf_token()
            if not csrf_token:
                return {'success':False,'message':'Failed to obtain CSRF token'}
            url=f'https://www.{self.domain}/api/v2/users/{user_id}/admin_alerts'
            headers={'Content-Type':'application/json','x-csrf-token':csrf_token,'User-Agent':self.session.headers.get('User-Agent','Mozilla/5.0')}
            payload={'admin_alert':{'ref_type':'item','ref_id':int(item_id),'report_reason_id':int(reason_id),'message':message or ''}}
            response=self.session.post(url,headers=headers,json=payload,timeout=12,allow_redirects=True)
            if response.status_code in (401,403,422) and attempt < max_retries-1:
                self._csrf_token=None; self._csrf_token_time=0; continue
            if self._response_report_success(response):
                return {'success':True,'message':f'Vinted 已确认收到举报 (API HTTP {response.status_code})','final_url':response.url}
            detail=(response.text or '').strip().replace('\n',' ')[:220]
            return {'success':False,'message':f'旧接口未返回可验证的成功结果 (HTTP {response.status_code}, {response.url})'+(f'：{detail}' if detail else '')}
        return {'success':False,'message':'举报提交失败'}

    def report_item(self,item_or_id,user_id,reason_id,message=''):
        """Submit one explicitly confirmed report through Vinted's live web flow.

        The browser extension remains a cookie-only helper.  The desktop app
        reads the current report entry/reason pages with that authenticated
        session, submits the official form when available, and only marks the
        operation successful after a verifiable Vinted acknowledgement.
        """
        item_id,_,_=self._report_item_meta(item_or_id)
        if not item_id or not user_id:
            return {'success':False,'message':'缺少商品 ID 或登录用户 ID'}
        try:
            page=self._resolve_reason_page(item_or_id,reason_id)
            if not page.get('success'):
                return page
            form_result=self._submit_report_form(page['url'],page.get('referer'),message)
            if form_result.get('success'):
                return form_result
            # If the current page is a JS-only shell, try the recovered API
            # endpoint with the *live* reason ID, but still require a concrete
            # success body/204 instead of trusting a generic 200 page.
            if '没有发现可提交表单' in str(form_result.get('message','')):
                fallback=self._submit_legacy_api_verified(item_id,user_id,reason_id,message)
                if fallback.get('success'):
                    return fallback
                return {'success':False,'message':form_result.get('message','')+'；'+fallback.get('message','')}
            return form_result
        except requests.RequestException as e:
            return {'success':False,'message':f'Request error: {e}'}
        except Exception as e:
            return {'success':False,'message':f'Unexpected error: {e}'}