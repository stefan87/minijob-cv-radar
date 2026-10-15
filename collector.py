"""Daily BA minijob collector. No CV document or personal contacts are published."""
import argparse,base64,html,ipaddress,json,math,re,socket,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import quote,urlparse,urljoin
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
BASE='https://rest.arbeitsagentur.de/jobboerse/jobsuche-service'
S=requests.Session()
S.headers.update({'X-API-Key':'jobboerse-jobsuche','User-Agent':'PersonalMinijobFinder/1.0','Accept':'application/json'})
S.mount('https://',HTTPAdapter(max_retries=Retry(total=2,backoff_factor=1,status_forcelist=[429,500,502,503,504])))
def plain(s):
    return html.unescape(re.sub('<[^>]+>',' ',str(s or '')))
def fold(s):
    return plain(s).lower().replace('ü','ue').replace('ä','ae').replace('ö','oe').replace('ß','ss')
def hits(text,terms):
    return [x for x in terms if re.search(r'(?<!\w)'+re.escape(fold(x))+r'(?!\w)',fold(text))]
def distance(a,b):
    lat1,lon1,lat2,lon2=map(math.radians,[*a,*b]);v=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return round(6371*2*math.asin(min(1,math.sqrt(v))),1)
def api(path,params=None):
    time.sleep(.15)
    r=S.get(BASE+path,params=params,timeout=35)
    if r.status_code in (404,410):return None
    r.raise_for_status();return r.json()
def details(ref):
    return api('/pc/v4/jobdetails/'+quote(base64.b64encode(ref.encode()).decode(),safe=''))
def source_link(ref):return 'https://www.arbeitsagentur.de/jobsuche/jobdetail/'+quote(ref,safe='')
def safe_url(url):
    try:
        p=urlparse(url)
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):return False
        ips=socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)
        return bool(ips) and all(ipaddress.ip_address(i[4][0]).is_global for i in ips)
    except (ValueError,OSError):return False

def check_link(url):
    # Never forward the BA API header to an external employer.
    for _ in range(4):
        if not safe_url(url):return 'Небезбедан или недоступан URL'
        try:
            with requests.get(url,timeout=15,allow_redirects=False,stream=True,headers={'User-Agent':'PersonalMinijobFinder/1.0'}) as r:
                if r.status_code in (301,302,303,307,308):
                    url=urljoin(url,r.headers.get('Location',''));continue
                if r.status_code in (404,410):return 'Линк више није доступан'
                if 200<=r.status_code<300:return 'HTTP доступан; садржај није потврђен'
                return 'Непотврђен HTTP '+str(r.status_code)
        except requests.RequestException:return 'Провера линка није успела'
    return 'Превише преусмеравања'

def schedule_evidence(text):
    t=fold(text)
    # Only explicit advertised days / numeric start times, never infer from Schichtarbeit.
    patterns=[r'(?:nur|ausschliesslich|arbeit\w*|einsatz\w*|arbeitszeit\w*|taetigkeit\w*|schicht\w*)[^.!?\n]{0,60}(?:am wochenende|samstags|sonntags|samstag|sonntag)',r'(?:am wochenende|samstags|sonntags)\s+(?:arbeiten|taetig|ausliefern|fahren)',r'(?:ab|von)\s*(?:17|18|19|20|21|22|23)(?:[:.]\d{2})?\s*(?:uhr|h)']
    evidence=[]
    for p in patterns:
        evidence.extend(m.group(0) for m in re.finditer(p,t))
    return evidence[:5]

def analyse(summary,d,config,scope):
    ref=str(summary.get('referenznummer') or summary.get('refnr') or d.get('referenznummer') or d.get('refnr') or '')
    title=plain(d.get('stellenangebotsTitel') or d.get('titel') or summary.get('titel') or summary.get('beruf') or '')
    description=plain(d.get('stellenangebotsBeschreibung') or d.get('stellenbeschreibung') or '')
    models=d.get('arbeitszeitmodelle') or []
    text=' '.join([title,description,json.dumps(models,ensure_ascii=False)])
    if not hits(text,['minijob','mini-job','geringfuegig','geringfügig','geringfuegige','geringfügige','MINIJOB']):return None
    locations=d.get('arbeitsorte') or ([summary['arbeitsort']] if summary.get('arbeitsort') else [])
    distances=[]
    for loc in locations:
        co=loc.get('koordinaten') or {}
        if co.get('lat') is not None and co.get('lon') is not None:
            try:distances.append(distance(config['centre'],[float(co['lat']),float(co['lon'])]))
            except (TypeError,ValueError):pass
    km=min(distances) if distances else None
    remote_evidence=[]
    for sentence in re.split(r'[\n.!?]',description+' '+title):
        if re.search(r'(?:100\s*%\s*(?:remote|home\s*office)|(?:vollstaendig|komplett|fully)\s+remote|remote\s*(?:deutschlandweit|innerhalb deutschlands)|deutschlandweit\s*(?:im\s*)?(?:remote|home\s*office))',fold(sentence)):
            if not re.search(r'(?:nicht|kein|not)\s+(?:100\s*%|fully|remote|home)',fold(sentence)):remote_evidence.append(sentence.strip())
    remote_country_ok=any(fold(l.get('land','')) in ('deutschland','germany','de') for l in locations) or any('deutschland' in fold(e) for e in remote_evidence)
    if not remote_country_ok:remote_evidence=[]
    local=km is not None and km<=config['radius_km']
    if not local and not (config['mode']=='cv' and scope=='national' and remote_evidence):return None
    matched=[]
    if config['mode']=='cv':
        matched=hits(text,config['skills'])
        if not matched:return None
    else:
        if not hits(title,config['delivery_terms']):return None
    evidence=schedule_evidence(description)
    warnings=[]
    if re.search(r'(?:deutsch|german)[^.!?\n]{0,70}(?:b2|c1|c2|fliessend|fluent|verhandlungssicher)',fold(description)):
        warnings.append('Немачки B2+ / течно: проверити услов у односу на CV (почетни ниво)')
    if config['mode']=='delivery' and evidence and not re.search(r'(?:nur|ausschliesslich)[^.!?\n]{0,45}(?:wochenende|samstag|sonntag)|(?:ab|von)\s*(?:17|18|19|20|21|22|23)(?:[:.]\d{2})?\s*(?:uhr|h)',fold(description)):
        warnings.append('Викенд се помиње, али рад само викендом није потврђен')
    if config['mode']=='delivery' and not evidence:warnings.append('Термин није потврђен: проверити викенд / почетак после 17h')
    if not description:warnings.append('Недостаје опис')
    if not d.get('arbeitgeber') and not summary.get('arbeitgeber'):warnings.append('Недостаје назив компаније')
    risk=hits(description,['vorkasse','vorauszahlung','kryptowaehrung','kryptowährung','pakete weiterleiten','konto zur verfuegung','konto zur verfügung'])
    if risk:warnings.append('Ризични изрази за ручну проверу: '+', '.join(risk))
    language=[]
    for sentence in re.split(r'[\n.!?]',description):
        if re.search(r'deutsch|german|englisch|english|fuehrerschein|führerschein',sentence,re.I):language.append(sentence.strip()[:400])
    required=d.get('fertigkeiten')
    required_text=plain(json.dumps(required,ensure_ascii=False)) if required else 'Није структурирано наведено; отвори опис огласа'
    ext=d.get('externeUrl') or summary.get('externeUrl') or ''
    if not isinstance(ext,str):ext=''
    if ext and not safe_url(ext):warnings.append('Спољни линк није прихваћен (само јавни HTTPS)');ext=''
    return {'id':ref,'title':title,'company':plain(d.get('arbeitgeber') or summary.get('arbeitgeber') or 'Није наведено'),'location':', '.join(sorted(set(plain(l.get('ort','')) for l in locations))) or 'Није наведено','distance_km':km,'work_mode':'Remote Немачка (експлицитан текст)' if remote_evidence else ('Home office / хибридно: проверити' if hits(text,['homeoffice','home office','hybrid','remote']) else 'На локацији / није наведено'),'job_type':'Minijob (потврђен у тексту/моделу)','required_skills':required_text,'matched_skills':matched,'schedule_evidence':evidence,'remote_evidence':remote_evidence,'language_and_licence':language[:8],'pay':plain(d.get('verguetung') or 'Није наведено'),'published':d.get('ersteVeroeffentlichungsdatum') or summary.get('aktuelleVeroeffentlichungsdatum') or '', 'source_url':source_link(ref),'apply_url':ext or source_link(ref),'apply_type':'Спољни оглас / пријава: проверити' if ext else 'BA оглас: упутство за пријаву','warnings':warnings,'review':bool(warnings),'status':'Извор доступан','description_excerpt':description[:1800]}

def main():
    p=argparse.ArgumentParser();p.add_argument('--offline',action='store_true');args=p.parse_args()
    config=json.loads(Path('config.json').read_text(encoding='utf-8'))
    Path('data').mkdir(exist_ok=True);Path('site').mkdir(exist_ok=True)
    dbfile=Path('data/jobs.json');db=json.loads(dbfile.read_text(encoding='utf-8')) if dbfile.exists() else {}
    now=datetime.now(timezone.utc).isoformat();report={'attempted_at':now,'errors':[],'warnings':[],'queries':[],'source':'BA Jobsuche (community-documented API)','live_tested':not args.offline}
    if not args.offline:
        found={};scopes=[('local','')]
        if config['mode']=='cv':scopes += [('national',x) for x in ['remote','homeoffice','home office']]
        successful=0
        for scope,term in scopes:
            for page in range(1,config['max_pages']+1):
                params={'angebotsart':1,'arbeitszeit':'mj','size':100,'page':page}
                if term:params['was']=term
                if scope=='local':params.update({'wo':config['search_location'],'umkreis':config['search_radius_km']})
                try:
                    result=api('/pc/v6/jobs',params)
                    if not isinstance(result,dict) or not isinstance(result.get('stellenangebote'),list):raise ValueError('Unexpected API response')
                    rows=result['stellenangebote'];successful+=1
                    report['queries'].append({'scope':scope,'term':term,'page':page,'returned':len(rows)})
                    for row in rows:
                        ref=str(row.get('referenznummer') or row.get('refnr') or '')
                        if ref:
                            if ref not in found or scope=='national':found[ref]=(row,scope)
                    if len(rows)<100:break
                    if page==config['max_pages']:report['warnings'].append('Pagination cap reached: '+scope+' '+term)
                except Exception as e:
                    report['errors'].append('Search '+scope+': '+str(e));break
        if successful==0:raise RuntimeError('All searches failed; previous site and database preserved. '+str(report['errors']))
        # Recheck known listings, even when they disappear from search results.
        if config['mode']=='delivery':
            found={r:v for r,v in found.items() if hits(str(v[0].get('titel') or v[0].get('beruf') or ''),config['delivery_terms']) or r in db}
        refs=list(db)+[r for r in found if r not in db]
        if len(refs)>config['max_details']:report['warnings'].append('Detail cap reached; unchecked records marked unknown')
        checked=set()
        for ref in refs[:config['max_details']]:
            checked.add(ref)
            try:
                d=details(ref)
                if d is None:
                    if ref in db:db[ref].update(status='Извор 404/410: вероватно затворен',last_checked=now)
                    continue
                summary,scope=found.get(ref,({'refnr':ref},db.get(ref,{}).get('scope','local')))
                job=analyse(summary,d,config,scope)
                if job is None:
                    if ref in db:db[ref].update(status='Више не испуњава филтер',last_checked=now)
                    continue
                job.update(first_seen=db.get(ref,{}).get('first_seen',now),last_seen=now,last_checked=now,scope=scope)
                job['link_check']=check_link(job['apply_url'])
                if not job['link_check'].startswith('HTTP доступан'):
                    job['warnings'].append(job['link_check']);job['review']=True
                db[ref]=job
            except Exception as e:
                report['errors'].append('Detail '+ref+': '+str(e))
                if ref in db:db[ref].update(status='Провера није успела',last_checked=now)
        for ref in set(db)-checked:db[ref]['status']='Није проверен у овом покретању'
        report['completed_at']=datetime.now(timezone.utc).isoformat()
        dbfile.write_text(json.dumps(db,ensure_ascii=False,indent=2),encoding='utf-8')
    else:report['warnings'].append('Offline build: no live search or link checks performed')
    payload={'config':{'title':config['title'],'mode':config['mode'],'radius_km':config['radius_km'],'centre_label':config['centre_label']},'report':report,'jobs':list(db.values())}
    Path('site/jobs.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    # JSON is inert, escaped against HTML script termination.
    embedded=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    template=Path('web/template.html').read_text(encoding='utf-8')
    Path('site/index.html').write_text(template.replace('__PAYLOAD__',embedded),encoding='utf-8')
    print(json.dumps({'stored':len(db),'errors':report['errors'],'warnings':report['warnings']},ensure_ascii=False))
if __name__=='__main__':main()
