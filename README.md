# Два независна Minijob radar пројекта

Овај пакет је један засебан репозиторијум. Други пакет се поставља у други репозиторијум.

## Шта је припремљено
- Python collector, HTML табела, JSON база, тестови и GitHub Actions + Pages workflow.
- Сваки дан 10:00 Europe/Berlin; GitHub може одложити или прескочити scheduled run.
- Нови огласи се додају по BA референтном броју. Постојећи се поново проверавају и архивирају, не бришу.
- Претрага, сортирање, фаворити у прегледачу, CSV export и аутоматско освежавање приказа.
- Нема измишљених огласа. Почетна HTML страница је празна док live collector не успе.

## CV претрага
Вештине су извучене из Stefan_Markovic__CV.pdf: project management, PMO, business analysis, support, ITSM, ServiceNow, Jira, Confluence, Power BI, Microsoft 365, SharePoint, SAP, GitLab, SaaS, API, payments и друга наведена искуства.
Поклапање је детерминистичка претрага кључних речи, не AI процена кандидата. Једна реч је довољна за улазак; прочитај захтеве у огласу. Захтеви за напредним немачким добијају упозорење, јер CV наводи почетни немачки. Не претпоставља се возачка дозвола.
- Локални Minijob у кругу 15 km од подесиве тачке у Минхену.
- Home office / hybrid локално.
- Ван круга: само експлицитно потпуни remote у Немачкој. Претрага национално без параметра wo.

## Достава
Нема CV филтера. Назив позиције мора садржати термин за возача/курира/доставу.
Непотврђен распоред је у приказу За ручну проверу. Изричити рад само викендом или почетак од 17h је текстуални сигнал, не гаранција да нема других обавезних смена. Огласи са непознатом удаљеношћу се искључују, да не би били лажно означени као локални.

## Колоне
Позиција, компанија, тип посла, локација, удаљеност, начин рада, вештине из извора, поклапање са CV-јем, радно време/доказ, језик/дозвола, накнада, датум објаве, први пут пронађен, последња провера, статус извора, провера линка/ризик, пријава, сачувај.
Слика дизајна није била доступна. Ово је нов табеларни dashboard, не потврђена копија слике.

## Извор и ограничења
Користи се само BA Jobsuche, преко community-документованог, не званично подржаног API-ја. Не обухвата све немачке портале. API може променити формат, ограничити приступ или престати да ради. Пре коришћења провери услове извора. Не заобилази блокаде.
HTTP 200 значи само да линк одговара. Није доказ да је оглас активан, без спама или да је компанија проверена. Скрипта означава 404/410, непотврђене линкове, недостајуће податке и неке ризичне изразе. То није потпуна антиспам заштита. Линк је спољни оглас када је наведен, иначе BA страница са упутствима за пријаву; није увек директан формулар.

Постављени су лимити 5 страница по упиту и 300 детаљних провера по покретању. Ако се достигну, HTML показује упозорење; листа није потпуна. Повећај max_pages/max_details у config.json ако је потребно, уз поштовање ограничења извора. Стари огласи имају приоритет за поновну проверу.

## Тачка и радијус
config.json: centre је [latitude, longitude], radius_km је 15. Подразумевана тачка је центар Минхена, не твоја кућна адреса. search_location је München, search_radius_km 25 за шире прикупљање; коначни филтер је 15 km ваздушном линијом од centre. За другачију тачку промени centre и centre_label, и по потреби search_location/search_radius_km. Не објављуј приватну адресу/координате у јавном репозиторијуму.

## GitHub: корак по корак, без терминала
1. Распакуј ZIP.
2. На GitHub: + > New repository. Име minijob-cv-radar или minijob-delivery-radar. За GitHub Free + Pages користи Public. Додај README да репозиторијум има main грану. Create repository.
3. Code > Add file > Upload files. Убаци collector.py, config.json, requirements.txt, web, tests, data и site директоријуме из пакета. Не убацуј спољни ZIP folder као додатни ниво. Commit changes (или предложи и merge-уј измене у main).
4. Скривени .github folder може бити изостављен при upload-у. Ако workflow није видљив: Add file > Create new file. Име .github/workflows/daily.yml. Копирај цео садржај истог фајла из ZIP-а. Commit у main. Workflow мора бити баш на тој путањи.
5. Settings > Pages > Build and deployment > Source: GitHub Actions. Не Deploy from a branch. Workflow већ постоји, не додај други шаблон.
6. Actions > Daily job radar > Run workflow > main > Run workflow.
7. Провери build и deploy. Ако build пада на API-ју, отвори лог корака python collector.py. Нема гаранције да ће community API радити са GitHub runner-а. Ако git push даје 403, провери дозволе Actions/организације и заштиту main гране. Workflow захтева contents: write. Не додај приватни token у код.
8. Settings > Pages > Visit site даје стварни линк твог сајта.
9. Понови поступак за други ZIP у другом репозиторијуму.
10. Од тада workflow има дневни распоред 10:00 Europe/Berlin. У јавним репозиторијумима GitHub може искључити распоред после 60 дана без активности. Проверавај Actions и време последње провере у HTML-у.

## Локално тестирање (опционо)
Python 3.12:
```sh
pip install -r requirements.txt
python -m unittest discover -s tests -v
python collector.py --offline
python collector.py
```
--offline само генерише HTML из постојеће базе, не претражује интернет.

## Приватност
Не upload-уј цео CV, контакт податке, приватну адресу, .env или токене. Јавни config садржи само листу вештина. GitHub Pages је јавни сајт и код приватног репозиторијума није гаранција приватности објављене странице.

## Статус тестирања овог пакета
Тестови правила и offline HTML build су проверени. Live API smoke test је блокиран sandbox policy-јем (HTTP 403), па live преузимање, GitHub deployment и распоред нису потврђени из овог окружења. Ниједан GitHub репозиторијум није креиран у твоје име.

## Документација
- [API](https://jobsuche.api.bund.dev/openapi.yaml)
- [Community API status](https://github.com/bundesAPI/jobsuche-api)
- [Workflow schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule)
- [Pages setup](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
- [File upload](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)
- [Manual workflow](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)

Визуелни browser render није проверен: browser executable није доступан. JavaScript синтакса и уграђени JSON су проверени.
