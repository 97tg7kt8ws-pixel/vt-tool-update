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
            'url': self._absolute_item_url(item.get('url') or item.get('path'), item.get('id')),
        }

    def _absolute_item_url(self, raw_url=None, item_id=None):
        """Normalize Vinted item URLs returned as either absolute URLs or /items/... paths."""
        site=f'https://www.{self.domain}'
        raw=str(raw_url or '').strip()
        if raw:
            if raw.startswith('//'):
                return 'https:'+raw
            if raw.startswith('/'):
                return urljoin(site+'/', raw)
            parsed=urlparse(raw)
            if parsed.scheme in ('http','https') and parsed.netloc:
                return raw
            # Defensive fallback for host/path values without a scheme.
            if raw.startswith('www.') or raw.startswith(self.domain):
                return 'https://'+raw.lstrip('/')
        return f'{site}/items/{item_id}' if item_id else ''

    def _report_item_meta(self, item_or_id):
        if isinstance(item_or_id, dict):
            item_id=item_or_id.get('id')
            item_url=self._absolute_item_url(item_or_id.get('url'), item_id)
            seller_id=item_or_id.get('seller_id')
        else:
            item_id=item_or_id; item_url=self._absolute_item_url(None, item_id); seller_id=None
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
    def _report_html_variants(text):
        """Return decoded variants of Vinted's HTML/Next.js/RSC payload."""
        raw=str(text or '')
        vals=[raw]
        cur=raw
        for _ in range(3):
            nxt=unescape(cur)
            nxt=nxt.replace('\\/','/').replace('\\u0026','&').replace('\\u003d','=').replace('\\u002f','/').replace('\\u002F','/')
            nxt=nxt.replace('\\u003f','?').replace('\\u003F','?').replace('\\u0025','%')
            if nxt==cur: break
            vals.append(nxt); cur=nxt
        out=[]
        for v in vals:
            if v not in out: out.append(v)
        return out

    @staticmethod
    def _guess_reason_label(blob, start, end, rid):
        window=blob[max(0,start-320):min(len(blob),end+320)]
        # Prefer human-readable quoted strings around the reason URL/object.
        candidates=[]
        for m in re.finditer(r'["\']([^"\']{3,100})["\']', window):
            s=' '.join(unescape(m.group(1)).split())
            low=s.lower()
            if not s or str(rid) in s or 'reason_id' in low or '/help/' in low or '/admin_alert/' in low:
                continue
            if any(x in low for x in ('ref_id','ref_type','ref_url','offender_id','component','children','href','class','button','route','query','http')):
                continue
            if re.fullmatch(r'[a-z0-9_./:=?&%-]+', low):
                continue
            alpha=sum(ch.isalpha() for ch in s)
            if alpha < 3:
                continue
            # Labels tend to be short title-like strings.
            score=0
            if 4 <= len(s) <= 60: score+=3
            if any(ch.isspace() for ch in s): score+=2
            if s[0].isupper(): score+=1
            candidates.append((score,s))
        if candidates:
            candidates.sort(key=lambda x:(-x[0],len(x[1])))
            return candidates[0][1]
        return f'Vinted reason {rid}'

    def _extract_serialized_report_reasons(self, html, base_url, current_parent=None):
        seen=set(); reasons=[]
        url_pat=re.compile(r'(?:(?:https?:)?//[^"\'<>\\\s]+)?/(?:help|admin_alert)/new\?[^"\'<>\\\s]+', re.I)
        rid_pat=re.compile(r'(?:reason_id|reasonId)["\'=: ]{1,8}(\d{1,6})', re.I)
        for blob in self._report_html_variants(html):
            for m in url_pat.finditer(blob):
                raw=m.group(0).rstrip('),]}')
                full=urljoin(base_url, raw)
                rid=self._reason_id_from_url(full)
                if not rid or rid==current_parent or rid in seen:
                    continue
                label=self._guess_reason_label(blob,m.start(),m.end(),rid)
                seen.add(rid); reasons.append({'id':rid,'label':label,'url':full})
            # RSC/Next state sometimes stores reasonId separately from the route.
            for m in rid_pat.finditer(blob):
                rid=int(m.group(1))
                if not rid or rid==current_parent or rid in seen:
                    continue
                label=self._guess_reason_label(blob,m.start(),m.end(),rid)
                # Only accept a bare serialized id when nearby content looks like a
                # human-facing reason rather than an arbitrary analytics number.
                if label.startswith('Vinted reason '):
                    continue
                seen.add(rid); reasons.append({'id':rid,'label':label,'url':''})
        return reasons

    @staticmethod
    def _reason_id_from_url(url):
        try:
            val=(parse_qs(urlparse(url).query).get('reason_id') or [''])[0]
            return int(val) if str(val).isdigit() else None
        except Exception:
            return None

    def _flatten_report_reasons(self, nodes, prefix=''):
        """Flatten Vinted's live report-reason tree into selectable leaf reasons."""
        out=[]
        if isinstance(nodes,dict):
            nodes=[nodes]
        if not isinstance(nodes,list):
            return out
        for node in nodes:
            if not isinstance(node,dict):
                continue
            rid=node.get('id')
            title=str(node.get('title') or node.get('name') or '').strip()
            path=(prefix+' > '+title).strip(' >') if title else prefix

            # Vinted has used several names for nested report reasons over time.
            child_lists=[]
            for key in ('report_reasons','children','sub_reasons','reasons','subreport_reasons','report_reason_children'):
                val=node.get(key)
                if isinstance(val,list) and val:
                    child_lists.append(val)

            # Defensive scan for nested lists of reason-like dictionaries.
            if not child_lists:
                for key,val in node.items():
                    if key in ('id','title','name','code','subtitle','report_reason_id','entity_type'):
                        continue
                    if isinstance(val,list) and val and all(isinstance(x,dict) for x in val):
                        if any(('id' in x and ('title' in x or 'name' in x)) for x in val):
                            child_lists.append(val)

            if child_lists:
                for children in child_lists:
                    out.extend(self._flatten_report_reasons(children,path))
                continue

            try:
                rid_int=int(rid)
            except Exception:
                rid_int=None
            if rid_int and title:
                out.append({
                    'id':rid_int,
                    'label':path or title,
                    'title':title,
                    'code':node.get('code') or '',
                    'raw':node
                })
        return out

    def get_report_reasons(self, item_or_id):
        """Fetch the current report-reason tree from Vinted's live API."""
        item_id,item_url,seller_id=self._report_item_meta(item_or_id)
        if not item_id:
            return {'success':False,'message':'缺少商品 ID'}
        if not seller_id:
            return {'success':False,'message':'缺少商品卖家 ID，无法读取举报原因'}
        url=f'https://www.{self.domain}/api/v2/report_reasons/item'
        try:
            r=self.session.get(
                url,
                params={'offender_id':int(seller_id)},
                headers={
                    'User-Agent':self.session.headers.get('User-Agent','Mozilla/5.0'),
                    'Accept':'application/json, text/plain, */*',
                    'Referer':item_url or f'https://www.{self.domain}/items/{item_id}',
                },
                timeout=12,
                allow_redirects=True
            )
            if r.status_code==401:
                return {'success':False,'message':'登录状态已失效 (HTTP 401)'}
            if r.status_code>=400:
                detail=(r.text or '').strip().replace('\n',' ')[:180]
                return {'success':False,'message':f'读取举报原因失败 (HTTP {r.status_code})'+(f'：{detail}' if detail else '')}
            data=r.json()
            if not isinstance(data,dict):
                return {'success':False,'message':'举报原因接口返回格式异常'}
            if data.get('code') not in (None,0):
                return {'success':False,'message':f"举报原因接口返回 code={data.get('code')}"}
            roots=data.get('report_reasons') or []
            reasons=self._flatten_report_reasons(roots)
            if not reasons:
                return {'success':False,'message':'Vinted 举报原因接口未返回可用的最终原因'}
            return {
                'success':True,
                'reasons':reasons,
                'item_url':item_url,
                'seller_id':seller_id,
                'raw':data,
            }
        except ValueError as e:
            return {'success':False,'message':f'举报原因 JSON 解析失败: {e}'}
        except requests.RequestException as e:
            return {'success':False,'message':f'读取举报原因失败: {e}'}

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
        try:
            data=response.json()
            # Current Vinted web flow observed Sep 2026 returns [{"code": 0}]
            # after a successful admin_alert submission.
            if isinstance(data,list) and data:
                if all(isinstance(x,dict) for x in data) and any(x.get('code')==0 for x in data):
                    return True
            if isinstance(data,dict):
                if data.get('code')==0:
                    return True
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
        """Submit one explicitly confirmed item report using Vinted's live API."""
        item_id,item_url,seller_id=self._report_item_meta(item_or_id)
        if not item_id or not user_id:
            return {'success':False,'message':'缺少商品 ID 或登录用户 ID'}

        # Validate the selected reason against the current live reason tree so
        # stale hard-coded ids can never be submitted.
        live=self.get_report_reasons(item_or_id)
        if not live.get('success'):
            return live
        valid_ids={int(x.get('id')) for x in live.get('reasons',[]) if x.get('id') is not None}
        try:
            reason_id=int(reason_id)
        except Exception:
            return {'success':False,'message':'无效的举报原因 ID'}
        if reason_id not in valid_ids:
            return {'success':False,'message':f'当前 Vinted 举报原因中不存在 ID {reason_id}，请重新选择'}

        site=f'https://www.{self.domain}'
        url=f'{site}/api/v2/users/{int(user_id)}/admin_alerts'
        payload={'admin_alert':{
            'ref_type':'item',
            'ref_id':int(item_id),
            'report_reason_id':reason_id,
            'message':message or ''
        }}

        # Match the successful browser flow: the POST originates from the
        # final /admin_alert/new confirmation page, not directly from the item.
        ref_path=urlparse(item_url or '').path or f'/items/{item_id}'
        report_referer=site+'/admin_alert/new?'+urlencode({
            'reason_id':reason_id,
            'ref_id':int(item_id),
            'ref_type':'item',
            'ref_url':ref_path,
            'offender_id':int(seller_id) if seller_id else ''
        })

        for attempt in range(2):
            csrf_token=self.get_csrf_token()
            if not csrf_token:
                return {'success':False,'message':'无法获取 CSRF Token，请重新同步 Cookie'}

            # X-Anon-Id is present on the real web request. Prefer the browser
            # cookie snapshot, then the catalogue identity captured earlier.
            anon_id=''
            try:
                anon_id=self.session.cookies.get('anon_id') or ''
            except Exception:
                try:
                    for ck in self.session.cookies:
                        if getattr(ck,'name','')=='anon_id':
                            anon_id=getattr(ck,'value','') or ''
                            break
                except Exception:
                    anon_id=''
            anon_id=anon_id or getattr(self,'_anon_id','') or ''

            headers={
                'Content-Type':'application/json',
                'Accept':'application/json, text/plain, */*',
                'Accept-Language':'en-GB,en;q=0.9',
                'Locale':self._market_locale(),
                'x-csrf-token':csrf_token,
                'User-Agent':self.session.headers.get('User-Agent','Mozilla/5.0'),
                'Origin':site,
                'Referer':report_referer,
                'Priority':'u=3',
                'Sec-Fetch-Dest':'empty',
                'Sec-Fetch-Mode':'cors',
                'Sec-Fetch-Site':'same-origin',
            }
            if anon_id:
                headers['X-Anon-Id']=anon_id
            try:
                response=self.session.post(url,headers=headers,json=payload,timeout=12,allow_redirects=True)
            except requests.RequestException as e:
                return {'success':False,'message':f'举报请求失败: {e}'}

            if response.status_code in (401,403,422) and attempt==0:
                self._csrf_token=None
                self._csrf_token_time=0
                continue

            if self._response_report_success(response):
                return {
                    'success':True,
                    'message':f'Vinted 已确认收到举报 (HTTP {response.status_code}, code=0)',
                    'final_url':response.url,
                    'status_code':response.status_code,
                }

            detail=(response.text or '').strip().replace('\n',' ')[:260]
            return {
                'success':False,
                'message':f'Vinted 未返回成功确认 (HTTP {response.status_code})'+(f'：{detail}' if detail else '')
            }

        return {'success':False,'message':'举报提交失败'}

