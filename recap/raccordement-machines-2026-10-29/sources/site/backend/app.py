import hashlib
import hmac
import io
import json
import secrets
import sqlite3
import time
import warnings
import asyncio
import copy
import re
import math
from pathlib import Path
from urllib.parse import urlencode, urlparse
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles
from PIL import Image, ImageOps
from .config import Settings
from .storage import Store
from .security import Security, EmployeeRoleRequired, COOKIE, STATE_COOKIE, hashed
from .access_accounts import AccessAccounts, SiteAccessRevoked, is_guest, assert_site_access, active_credential
from .budget_counter import LimitReached
from .discord_api import DiscordAPI, DiscordOAuthError, DiscordVerificationError
from .limits import BodyLimitMiddleware
from .traffic import TrafficLimits, VisitorLimitMiddleware, APIBudgetExceeded
from .local_preview import LocalPreviewSecurity
from .registry import discover_pages
from . import domain
from . import views
from .bot_bridge import BotBridge, PATH as BOT_PATH
from .auditing import AuditHTTPMiddleware, DurableAuditWriter, business_changes, user_snapshot, query_log, log_entry


def create_app(settings=None, provider=None):
    cfg = settings or Settings.load()
    cfg.validate_local_preview()
    cfg.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    store = Store(cfg.data_dir / 'heritage-test.sqlite3')
    bridge = BotBridge(cfg,store)
    traffic = TrafficLimits(cfg)
    api = provider or DiscordAPI(cfg)
    security = LocalPreviewSecurity(cfg, store, api) if cfg.local_preview else Security(cfg, store, api)
    static = cfg.root / 'static'
    pages = discover_pages(static)
    accounts=AccessAccounts(store,cfg,pages)
    code_login_slots=asyncio.Semaphore(2)
    def initial_domain():
        initial=domain.seed()
        if not cfg.local_preview and not cfg.seed_demo_data:
            initial.update(sales=[],machines=[],events=[],raffles=[],tombolaRecords=[],
                           salesWeek={'archives':[],'lastResetDate':None})
        return initial
    with store.connect(True) as db:
        db.execute('INSERT OR IGNORE INTO domain_store VALUES(1,?)',(json.dumps(initial_domain()),))
    audit_writer = DurableAuditWriter(store)
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await audit_writer.close()
            if hasattr(store, 'close'): store.close()
    app = FastAPI(title='L’Héritage — prévisualisation',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.store, app.state.security, app.state.settings, app.state.pages = store, security, cfg, pages
    app.state.traffic = traffic
    app.state.audit_writer = audit_writer
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=[urlparse(cfg.base_url).hostname,'127.0.0.1','localhost','testserver'])

    @app.exception_handler(APIBudgetExceeded)
    async def api_budget_error(request, error):
        return JSONResponse({'detail': error.detail, 'reason': error.reason},
                            status_code=error.status_code, headers=error.headers)

    def auth(request): return request.state.identity
    def require(request,page):
        user=auth(request);security.require_page(user,page,pages);return user
    def supreme(request):
        user=auth(request)
        if not security.is_supreme(user): raise HTTPException(403,'Le Conseil des Accès est réservé à l’Administrateur Suprême.')
        return user
    def require_live_session(request,db,page=None):
        user=auth(request);assert_site_access(store,user['id'],db)
        session=request.state.session
        if 'hash' in session and not db.execute('SELECT 1 FROM sessions WHERE hash=? AND expires>?',(session['hash'],time.time())).fetchone():raise HTTPException(401,'Ta session n’est plus valide.')
        if is_guest(user):active_credential(store,user['id'])
        if page:security.require_page(user,page,pages)

    def csrf(request,session):
        if request.headers.get('origin')!=cfg.base_url or not hmac.compare_digest(request.headers.get('x-csrf-token','').encode('utf-8'),session['csrf'].encode('utf-8')):
            raise HTTPException(403,'Protection CSRF : recharge la page avant de réessayer.')

    async def json_body(request):
        """Une entrée invalide est une erreur de formulaire, pas une panne du serveur."""
        def invalid_constant(value):
            raise ValueError('Nombre JSON non fini.')
        def finite_float(value):
            number=float(value)
            if not math.isfinite(number): raise ValueError('Nombre JSON non fini.')
            return number
        def unique_keys(pairs):
            result={}
            for key,value in pairs:
                if key in result: raise ValueError('Clé JSON répétée.')
                result[key]=value
            return result
        try:
            return json.loads(await request.body(),parse_constant=invalid_constant,parse_float=finite_float,object_pairs_hook=unique_keys)
        except (ValueError,UnicodeError,RecursionError):
            raise HTTPException(400,'Le formulaire contient des données JSON invalides.') from None
    def session_cookie(response, token):
        response.set_cookie(COOKIE,token,max_age=cfg.session_seconds,httponly=True,secure=cfg.secure,samesite='lax',path='/')
    def profile(user):
        role=security.highest_role(user)
        return {'id':user['id'],'discordName':user['username'],'discordAvatar':user['discord_avatar'],
                'displayName':user['display_name'] or user['username'],
                'avatar':f"/api/me/avatar?v={user['avatar_file']}" if user['avatar_file'] else user['discord_avatar'],
                'customName':user['display_name'],'customAvatar':bool(user['avatar_file']),
                'role':{'id':role['id'],'name':role['name'],'position':role['position']},
                'supreme':security.is_supreme(user),'createdAt':user['created'],'lastLogin':user['last_login'],
                'authProvider':'access_code' if is_guest(user) else 'local' if user['id']=='local-preview' else 'discord'}

    def configuration():
        return {'preview':True,'configured':cfg.configured,'localPreview':cfg.local_preview}

    def data_version(body, user, role_id):
        return hashlib.sha256((user['id']+'\0'+role_id+'\0').encode()+body).hexdigest()

    def screen_response(data, user, request):
        """Validation en un appel, après authentification et autorisation réelles."""
        response = JSONResponse(data)
        role_id = security.highest_role(user)['id']
        version = data_version(response.body,user,role_id)
        metadata = {'X-Heritage-Data-Version':version,'X-Heritage-User':user['id'],
                    'X-Heritage-Role':role_id,'Cache-Control':'no-store'}
        previous = request.headers.get('x-heritage-cache','')
        if re.fullmatch(r'[0-9a-f]{64}',previous) and hmac.compare_digest(previous,version):
            return Response(status_code=304,headers=metadata)
        response.headers.update(metadata)
        return response

    public_files={'/'+p.name for p in static.iterdir() if p.is_file() and p.suffix in ('.css','.js')}

    @app.middleware('http')
    async def protect(request, call_next):
        path=request.url.path
        try:
            if cfg.local_preview:
                security.check_request(request)
            if request.method in ('POST','PUT','PATCH'):
                length=request.headers.get('content-length')
                if length and (not length.isdigit() or int(length)>2*1024*1024): raise HTTPException(413,'Requête trop volumineuse.')
            public=path in {'/','/api/status','/auth/start','/auth/callback','/auth/access-code','/auth/logout',BOT_PATH+'/events',BOT_PATH+'/commands',BOT_PATH+'/ack'} or path in public_files or path.startswith('/assets/')
            if not public:
                request.state.audit_stage='authentication'
                user,session=await security.resolve(request)
                request.state.identity,request.state.session=user,session
                request.state.audit_stage='authorization'
                if path.startswith(('/api/pages/','/api/actions/','/api/visits/','/spaces/')):
                    page=path.split('/')[3 if path.startswith('/api/') else 2]
                    await run_in_threadpool(security.require_page,user,page,pages)
                elif path.startswith('/api/admin/') or path not in {'/app','/api/me','/api/me/profile','/api/me/avatar','/api/client-errors','/api/bootstrap'}:
                    if not security.is_supreme(user): raise HTTPException(403,'Cet espace n’a pas encore d’autorisation configurée.')
                if request.method not in ('GET','HEAD','OPTIONS'):
                    request.state.audit_stage='csrf';csrf(request,session)
                request.state.audit_stage='handling'
            response=await call_next(request)
        except HTTPException as error:
            payload={'detail':error.detail}
            if path=='/api/me': payload.update(configuration())
            if isinstance(error,(EmployeeRoleRequired,DiscordVerificationError,SiteAccessRevoked)): payload['reason']=error.reason
            if isinstance(error,APIBudgetExceeded): payload['reason']=error.reason
            if isinstance(error,DiscordVerificationError):
                def log_verification():
                    with store.connect(True) as db:
                        store.audit(db,None,'verification_failed',{'reason':error.reason,**error.diagnostic})
                await run_in_threadpool(log_verification)
            response=JSONResponse(payload,status_code=error.status_code,headers=error.headers)
        current_session=getattr(request.state,'session',None)
        if current_session and not cfg.local_preview and response.status_code<400:
            now=time.time()
            renew_every=min(86400,cfg.session_seconds/4)
            if current_session['expires']-now <= cfg.session_seconds-renew_every:
                # Only extend a still-valid session after membership/role checks succeed.
                def renew():
                    with store.connect(True) as db:
                        expiry=now+cfg.session_seconds
                        if is_guest(request.state.identity):
                            account=db.execute('SELECT expires_at FROM access_accounts WHERE user_id=?',(request.state.identity['id'],)).fetchone()
                            expiry=min(expiry,account['expires_at'] or math.inf)
                        return db.execute('UPDATE sessions SET expires=? WHERE hash=? AND expires>?',
                                          (expiry,current_session['hash'],now)).rowcount
                updated=await run_in_threadpool(renew)
                if updated: session_cookie(response,request.cookies[COOKIE])
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob: https://cdn.discordapp.com https://media.discordapp.net; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if path.startswith(('/api/','/auth/','/app','/spaces/')): response.headers['Cache-Control']='no-store'
        return response

    @app.get('/api/status')
    async def status():
        return {'preview':True,'configured':cfg.configured,'callback':cfg.callback,'guildId':cfg.guild_id,'localPreview':cfg.local_preview}

    @app.api_route(BOT_PATH+'/{operation}',methods=['GET','POST'])
    async def bot_exchange(operation:str,request:Request):
        if (operation,request.method) not in {('commands','GET'),('events','POST'),('ack','POST')}:
            raise HTTPException(405,'Opération du connecteur inconnue.')
        body=await request.body()
        nonce=bridge.verify(request.method,request.url.path,request.headers,body)
        payload=await json_body(request) if request.method=='POST' else None
        async with security.lock:
            return await run_in_threadpool(bridge.handle,operation,nonce,payload)

    @app.get('/auth/start')
    def start():
        if cfg.local_preview: return RedirectResponse('/app#overview',status_code=303)
        if not cfg.configured: return RedirectResponse('/?login_error=configuration',status_code=303)
        state=secrets.token_urlsafe(40)
        with store.connect(True) as db:
            db.execute('DELETE FROM oauth_states WHERE expires<?',(time.time(),))
            db.execute('INSERT INTO oauth_states VALUES(?,?)',(hashed(state),time.time()+600))
            store.audit(db,None,'login_started',{'provider':'discord'})
        query=urlencode({'response_type':'code','client_id':cfg.client_id,'scope':'identify guilds.members.read','redirect_uri':cfg.callback,'state':state,'prompt':'consent'})
        response=RedirectResponse('https://discord.com/oauth2/authorize?'+query,status_code=303)
        response.set_cookie(STATE_COOKIE,state,max_age=600,httponly=True,secure=cfg.secure,samesite='lax',path='/auth')
        return response

    @app.get('/auth/callback')
    async def callback(request:Request):
        if cfg.local_preview: return RedirectResponse('/app#overview',status_code=303)
        def failed(reason):
            response=RedirectResponse('/?login_error='+reason,status_code=303)
            response.delete_cookie(STATE_COOKIE,path='/auth')
            return response

        state=request.query_params.get('state','');cookie=request.cookies.get(STATE_COOKIE,'')
        if not state or not cookie or not state.isascii() or not cookie.isascii() or not hmac.compare_digest(state,cookie): raise HTTPException(400,'Retour OAuth2 invalide ou expiré.')
        def consume_state():
            with store.connect(True) as db:
                return db.execute('DELETE FROM oauth_states WHERE hash=? AND expires>? RETURNING hash',(hashed(state),time.time())).fetchone()
        item=await run_in_threadpool(consume_state)
        if not item: raise HTTPException(400,'Cette connexion a expiré ou a déjà été utilisée.')
        if request.query_params.get('error'): return failed('cancelled')
        if request.query_params.get('iss','https://discord.com')!='https://discord.com': raise HTTPException(400,'Émetteur OAuth2 invalide.')
        code=request.query_params.get('code','')
        if not code or len(code)>2048: raise HTTPException(400,'Code OAuth2 manquant.')
        stage='exchange'
        try:
            credentials=await api.exchange(code)
            stage='identity'
            identity=await api.user(credentials['access_token'])
            stage='membership'
            member=await api.member(str(identity['id']))
            if str(member.get('user',{}).get('id',identity['id']))!=str(identity['id']): raise HTTPException(403,'Identité Discord incohérente.')
            stage='roles'
            await security.synchronize_roles(force=True)
            stage='eligibility'
            security.require_employee(str(identity['id']),member.get('roles',[]))
            await run_in_threadpool(security.highest_role,{'id':str(identity['id']),'role_ids':json.dumps(member.get('roles',[]))})
        except HTTPException as error:
            reason=error.reason if isinstance(error,(DiscordOAuthError,EmployeeRoleRequired,DiscordVerificationError,APIBudgetExceeded)) else ('membership' if stage=='membership' and error.status_code==403 else 'discord_unavailable')
            detail={'stage':stage,'status':error.status_code,'reason':reason}
            if isinstance(error,DiscordVerificationError): detail.update(error.diagnostic)
            def log_failure():
                with store.connect(True) as db: store.audit(db,None,'login_failed',detail)
            await run_in_threadpool(log_failure)
            return failed(reason)
        try:token=await run_in_threadpool(security.create_login,identity,member,credentials)
        except SiteAccessRevoked:
            def log_blocked():
                with store.connect(True) as db:store.audit(db,str(identity['id']),'login_failed',{'provider':'discord','reason':'site_access_revoked'})
            await run_in_threadpool(log_blocked)
            return failed('site_access_revoked')
        request.state.identity=await run_in_threadpool(store.read_user,str(identity['id']))
        old=request.cookies.get(COOKIE)
        if old:
            def revoke_previous():
                with store.connect(True) as db: db.execute('DELETE FROM sessions WHERE hash=?',(hashed(old),))
            await run_in_threadpool(revoke_previous)
        overview_allowed=await run_in_threadpool(security.allowed,{'id':str(identity['id']),'role_ids':json.dumps(member.get('roles',[]))},'overview')
        landing='overview' if overview_allowed else 'profile'
        response=RedirectResponse('/app#'+landing,status_code=303)
        response.delete_cookie(STATE_COOKIE,path='/auth')
        session_cookie(response,token)
        return response

    @app.post('/auth/access-code')
    async def code_login(request:Request):
        # Origin exact + JSON : pas de connexion forcée par un formulaire tiers.
        if request.headers.get('origin')!=cfg.base_url or request.headers.get('content-type','').split(';')[0].strip().lower()!='application/json':
            raise HTTPException(403,'Recharge la page de connexion avant de réessayer.')
        data=await json_body(request)
        if code_login_slots.locked():raise HTTPException(429,'Connexions en cours. Réessaie dans quelques secondes.',headers={'Retry-After':'2'})
        async with code_login_slots:
            try:await run_in_threadpool(traffic.counters.consume,'access-code-global',[('access-code-minute',60,60)])
            except LimitReached as error:raise HTTPException(429,'Trop de tentatives de connexion. Patiente avant de réessayer.',headers={'Retry-After':str(error.retry_after)}) from None
            token,user_id=await run_in_threadpool(accounts.login,data)
        request.state.identity=await run_in_threadpool(store.read_user,user_id)
        old=request.cookies.get(COOKIE)
        if old:
            def revoke_previous():
                with store.connect(True) as db:db.execute('DELETE FROM sessions WHERE hash=?',(hashed(old),))
            await run_in_threadpool(revoke_previous)
        landing='overview' if await run_in_threadpool(security.allowed,request.state.identity,'overview') else 'profile'
        response=JSONResponse({'ok':True,'landing':landing});session_cookie(response,token)
        return response

    @app.post('/auth/logout')
    async def logout(request:Request):
        token=request.cookies.get(COOKIE,'')
        local_user=None
        if cfg.local_preview:
            local_user,current=await security.resolve(request);csrf(request,current)
            request.state.identity=local_user
        def commit_logout():
            with store.connect(True) as db:
                session=db.execute('SELECT * FROM sessions WHERE hash=?',(hashed(token),)).fetchone()
                if session:
                    csrf(request,session)
                    request.state.audit_actor=session['user_id']
                    db.execute('DELETE FROM sessions WHERE hash=?',(hashed(token),))
                    store.audit(db,session['user_id'],'logout',{'before':{'connected':True},'after':{'connected':False}})
                elif local_user:
                    store.audit(db,local_user['id'],'logout',{'mode':'local_preview'})
        await run_in_threadpool(commit_logout)
        response=JSONResponse({'ok':True});response.delete_cookie(COOKIE,path='/');return response

    @app.get('/api/me')
    def me(request:Request):
        user=auth(request)
        return {'user':profile(user),'csrf':request.state.session['csrf'],
                'pages':[value for key,value in pages.items() if security.allowed(user,key)],**configuration()}

    @app.post('/api/client-errors')
    async def client_error(request:Request):
        user=auth(request);data=await json_body(request)
        def commit_operation():
            if not isinstance(data,dict) or not {'kind','page'}<=set(data) or set(data)-{'kind','page','key','occurredAt'} or not isinstance(data['kind'],str) or not isinstance(data['page'],str) or data['kind'] not in ('script','network','timeout','unexpected','offline'):
                raise HTTPException(400,'Signalement invalide.')
            if data['page'] not in pages and data['page']!='welcome': raise HTTPException(400,'Page inconnue.')
            key=data.get('key')
            if key is not None and (not isinstance(key,str) or not re.fullmatch(r'client-error-[A-Za-z0-9_-]{16,80}',key)): raise HTTPException(400,'Identifiant invalide.')
            occurred=data.get('occurredAt')
            if occurred is not None and (type(occurred) not in (int,float) or not 0<=occurred<=253402300799000): raise HTTPException(400,'Date invalide.')
            fingerprint=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
            with store.connect(True) as db:
                if key:
                    previous=db.execute('SELECT fingerprint FROM operation_keys WHERE user_id=? AND key=?',(user['id'],key)).fetchone()
                    if previous:
                        if previous['fingerprint']!=fingerprint: raise HTTPException(409,'Identifiant déjà utilisé.')
                        request.state.audit_outcome='duplicate'
                        return {'ok':True,'duplicate':True}
                store.audit(db,user['id'],'client_error',{'result':'failure','page':data['page'],'category':data['kind'],'source':'browser','reportedClientAt':occurred})
                if key: db.execute('INSERT INTO operation_keys VALUES(?,?,?,?)',(user['id'],key,fingerprint,time.time()))
            return {'ok':True}
        return await run_in_threadpool(commit_operation)

    @app.get('/api/pages/{page}/access')
    def page_access(page:str,request:Request):
        user=require(request,page)
        request.state.audit_background=True
        return {'userId':user['id'],'roleId':security.highest_role(user)['id']}

    @app.get('/api/pages/journal/entries/{entry_id}')
    def journal_entry(entry_id:int,request:Request):
        require(request,'journal')
        request.state.audit_log_entry=entry_id
        return log_entry(store,entry_id)

    screen_fields={
        'sales':('sales','machines','events','salesWeek'),
        'machines':('machines',),
        'tombola':('tombolaRecords',),
        'history':('events',),
        'overview':('sales','machines'),
        'stats':('sales','machines','machineStats','machineBridgeConfirmedOnly'),
    }

    def team_data(params,screen=True):
        size=views.number(params,'limit',50,100) if screen else 10000000
        if not size: raise HTTPException(400,'La taille de page doit être positive.')
        with store.connect() as db:
            total=db.execute('SELECT count(*) FROM users WHERE member=1').fetchone()[0]
            offset=min(views.number(params,'teamOffset'),((total-1)//size)*size if total else 0)
            rows=db.execute('SELECT id,username,display_name,created,avatar_file,discord_avatar FROM users WHERE member=1 ORDER BY created,id LIMIT ? OFFSET ?',(size,offset))
            members=[{'id':row['id'],'displayName':row['display_name'] or row['username'],
                      'discordName':row['username'],'joinedAt':row['created'],
                      'avatar':f"/api/pages/team/avatars/{row['id']}?v={hashlib.sha256(row['avatar_file'].encode()).hexdigest()[:16]}" if row['avatar_file'] else row['discord_avatar']} for row in rows]
        return {**views.base({}),'members':members,'pagination':{'team':{'total':total,'offset':offset,'limit':size,'hasMore':offset+size<total}}}

    def machine_projection(state):
        if cfg.local_preview:return state
        state=copy.deepcopy(state)
        state['machineBridgeConfirmedOnly']=True
        for machine in state.get('machines',[]):
            if not machine.get('botMachineId'):
                machine.update(botStatus='unconfirmed',historical=True,trackingDisabled=True)
        return state

    def screen_data(page,request,params,shared_state=None):
        """Même construction des écrans pour une lecture seule ou groupée."""
        if page=='journal': return query_log(store,params,pages)
        if page=='profile': return {'page':page}
        if page=='council':
            return {'page':page,'access':access(request),'accounts':users(request)}
        if page=='team': return team_data(params)
        state=shared_state if shared_state is not None else store.read_domain(
            screen_fields.get(page,()),array_counts=('machineSheetHistory',) if page=='machines' else ())
        if page in ('machines','overview','stats'):state=machine_projection(state)
        result=views.screen(state,page,params)
        if page=='machines':result.update(bridge.machine_status())
        return result

    @app.get('/api/bootstrap')
    def bootstrap(request:Request):
        user=auth(request)
        requested=request.query_params.getlist('pages')
        if requested:
            selected=list(dict.fromkeys(requested))
            # Valider toute la sélection avant de lire la moindre collection.
            for page in selected: security.require_page(user,page,pages)
        else:
            selected=[page for page in pages if security.allowed(user,page)]
        request.state.audit_background=True
        domain_pages=[page for page in selected if page not in ('profile','council','journal','team')]
        fields=tuple(dict.fromkeys(field for page in domain_pages for field in screen_fields.get(page,())))
        # Un seul décodage des collections utiles, jamais le catalogue, les images
        # ou les détails du journal. Chaque projection reste propre à sa page.
        shared=store.read_domain(fields,array_counts=('machineSheetHistory',) if 'machines' in selected else ()) if fields else None
        role_id=security.highest_role(user)['id']
        screens={page:screen_data(page,request,{},shared) for page in selected}
        versions={page:data_version(JSONResponse(data).body,user,role_id) for page,data in screens.items()}
        return {'pages':screens,'versions':versions,'identity':{'userId':user['id'],'roleId':role_id}}

    @app.post('/api/visits/{page}')
    def visit(page:str,request:Request):
        user=require(request,page)
        with store.connect(True) as db:
            store.audit(db,user['id'],'page_view',{'page':page,'route':'/api/visits/'+page,'source':'navigation'})
        request.state.audit_navigation_logged=True
        return {'ok':True}

    @app.get('/api/pages/{page}')
    def page_data(page:str,request:Request):
        user=require(request,page)
        if page=='journal': return query_log(store,request.query_params,pages)
        if page=='profile': return {'page':page}
        if page=='council':
            if request.query_params.get('view')=='screen':
                return screen_data(page,request,request.query_params)
            return {'page':page}
        view=request.query_params.get('view','legacy')
        if view not in ('legacy','screen','catalog','sheets','active','export'):
            raise HTTPException(400,'Vue inconnue.')
        request.state.audit_background=view=='active'
        special={'catalog':'tombola','sheets':'machines','active':'machines','export':'history'}
        if view in special and special[view]!=page: raise HTTPException(404,'Vue introuvable.')
        if page=='team':
            data=team_data(request.query_params,view=='screen')
            return screen_response(data,user,request) if view=='screen' else data
        if view=='screen':
            return screen_response(screen_data(page,request,request.query_params),user,request)
        elif view in ('catalog','sheets','active','export'):
            state=store.read_domain({'catalog':('catalog',),'sheets':('machineSheetHistory',),'active':('machines',),'export':('events',)}[view])
        else: state=store.read_domain()
        if view=='catalog': return {'catalog':state['catalog']}
        if view=='sheets':
            rows,meta=views.paginate(state.get('machineSheetHistory',[]),request.query_params,'sheets')
            return {'machineSheetHistory':rows,'pagination':{'sheets':meta}}
        if view=='active':
            state=machine_projection(state)
            batch=domain.current_batch(state)
            return {'machines':[batch] if batch else []}
        if view=='export':
            request.state.audit_export=True
            return {'events':state['events']}
        if page in ('machines','overview','stats'):state=machine_projection(state)
        result=domain.project(state,page)
        if page=='machines':result.update(bridge.machine_status())
        return result

    @app.post('/api/actions/{page}')
    async def action(page:str,request:Request):
        user=await run_in_threadpool(require,request,page)
        data=await json_body(request)
        if not isinstance(data,dict) or set(data)-{'action','id','values'}: raise HTTPException(400,'Requête invalide.')
        values=data.get('values',{})
        if not isinstance(values,dict) or len(values)>160: raise HTTPException(400,'Formulaire invalide.')
        request_key=request.headers.get('idempotency-key')
        if request_key is not None and not re.fullmatch(r'[A-Za-z0-9_-]{16,100}',request_key):
            raise HTTPException(400,'Identifiant d’envoi invalide.')
        fingerprint=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
        values={**values,'_actor_id':user['id']}
        def commit_operation():
            try:
                with store.connect(True) as db:
                    require_live_session(request,db,page)
                    if request_key:
                        previous=db.execute('SELECT fingerprint FROM operation_keys WHERE user_id=? AND key=?',(user['id'],request_key)).fetchone()
                        if previous:
                            if previous['fingerprint']!=fingerprint: raise HTTPException(409,'Cet identifiant d’envoi a déjà servi pour une autre opération.')
                            request.state.audit_outcome='duplicate'
                            return {'ok':True,'duplicate':True}
                    state=json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()['body'])
                    if page=='machines' and not cfg.local_preview:
                        result=bridge.queue_machine(db,data.get('action'),data.get('id'),values,user['id'],user['display_name'] or user['username'],state)
                        if request_key:db.execute('INSERT INTO operation_keys VALUES(?,?,?,?)',(user['id'],request_key,fingerprint,time.time()))
                        return result
                    before=copy.deepcopy(state)
                    if data.get('action') in domain.ACTIONS.get(page,set()): request.state.audit_action=data['action']
                    changed=domain.mutate(state,page,data.get('action'),data.get('id'),values,user['display_name'] or user['username'])
                    if changed is not False:
                        db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(state,ensure_ascii=False),))
                        collection={'sales':'sales','machines':'machines','tombola':'tombolaRecords'}[page]
                        record=data.get('id')
                        if record is None:
                            existing={item['id'] for item in before[collection]}
                            record=next((item['id'] for item in state[collection] if item['id'] not in existing),None)
                        store.audit(db,user['id'],'business_action',{'page':page,'action':data.get('action'),'record':record,
                                                                   'changes':business_changes(before,state)})
                        bridge.enqueue(db,page,data['action'],record,values,user['id'],user['display_name'] or user['username'],state)
                    else: request.state.audit_outcome='duplicate'
                    if request_key: db.execute('INSERT INTO operation_keys VALUES(?,?,?,?)',(user['id'],request_key,fingerprint,time.time()))
            except (ValueError,TypeError,KeyError,OverflowError): raise HTTPException(400,'Les informations du formulaire sont invalides ou la fiche n’est plus modifiable.') from None
            return {'ok':True,**({'duplicate':True} if changed is False else {})}
        return await run_in_threadpool(commit_operation)

    @app.patch('/api/me/profile')
    async def update_profile(request:Request):
        user=auth(request);data=await json_body(request)
        def commit_operation():
            if not isinstance(data,dict) or set(data)-{'displayName','resetName','resetAvatar'}: raise HTTPException(400,'Modification de profil invalide.')
            name=data.get('displayName',user['display_name'])
            if data.get('resetName') is True: name=None
            if name is not None and (not isinstance(name,str) or not 1<=len(name.strip())<=60): raise HTTPException(400,'Choisis un pseudo de 1 à 60 caractères.')
            with store.connect(True) as db:
                require_live_session(request,db)
                before=user_snapshot(db.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone())
                db.execute('UPDATE users SET display_name=? WHERE id=?',(name.strip() if name else None,user['id']))
                if data.get('resetAvatar') is True: db.execute('UPDATE users SET avatar_file=NULL WHERE id=?',(user['id'],))
                after=user_snapshot(db.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone())
                store.audit(db,user['id'],'profile_changed',{'page':'profile','before':before,'after':after})
            return {'user':profile(store.read_user(user['id']))}
        return await run_in_threadpool(commit_operation)

    @app.post('/api/me/avatar')
    async def upload_avatar(request:Request,file:UploadFile=File(...)):
        user=auth(request);data=await file.read(1048577)
        def commit_operation():
            if not data or len(data)>1048576: raise HTTPException(400,'Photo : maximum 1 Mo.')
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error',Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(data),formats=('JPEG','PNG','WEBP')) as image:
                        if image.format not in ('JPEG','PNG','WEBP') or image.width*image.height>16000000: raise ValueError()
                        image.verify()
                    with Image.open(io.BytesIO(data),formats=('JPEG','PNG','WEBP')) as image:
                        normalized=ImageOps.exif_transpose(image).convert('RGBA' if 'A' in image.getbands() else 'RGB')
                        normalized.thumbnail((512,512))
                        output=io.BytesIO();normalized.save(output,format='PNG')
            except Exception: raise HTTPException(400,'Photo invalide : utilise un véritable JPG, PNG ou WebP.') from None
            directory=cfg.data_dir/'avatars';directory.mkdir(exist_ok=True,mode=0o700)
            name=secrets.token_hex(24)+'.png';path=directory/name
            path.write_bytes(output.getvalue());path.chmod(0o600)
            try:
                with store.connect(True) as db:
                    require_live_session(request,db)
                    before=user_snapshot(db.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone())
                    db.execute('UPDATE users SET avatar_file=? WHERE id=?',(name,user['id']))
                    after=user_snapshot(db.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone())
                    store.audit(db,user['id'],'avatar_changed',{'page':'profile','before':before,'after':after})
            except BaseException:
                path.unlink(missing_ok=True);raise
            return {'user':profile(store.read_user(user['id']))}
        return await run_in_threadpool(commit_operation)

    @app.get('/api/me/avatar')
    def own_avatar(request:Request):
        return avatar_response(auth(request)['avatar_file'])

    def avatar_response(name):
        if not name or not isinstance(name,str) or not name.endswith('.png') or Path(name).name!=name: raise HTTPException(404,'Avatar introuvable.')
        directory=cfg.data_dir/'avatars';path=directory/name
        if not path.is_file() or path.resolve().parent!=directory.resolve(): raise HTTPException(404,'Avatar introuvable.')
        return FileResponse(path,media_type='image/png')

    @app.get('/api/pages/team/avatars/{user_id}')
    def team_avatar(user_id:str,request:Request):
        require(request,'team')
        with store.connect() as db:
            member=db.execute('SELECT avatar_file FROM users WHERE id=? AND member=1',(user_id,)).fetchone()
        if not member: raise HTTPException(404,'Avatar introuvable.')
        return avatar_response(member['avatar_file'])

    @app.get('/api/admin/access')
    def access(request:Request):
        supreme(request)
        with store.connect() as db:
            roles=[dict(row) for row in db.execute('SELECT id,name,position,active FROM roles ORDER BY position DESC,id')]
            permissions=[dict(row) for row in db.execute('SELECT * FROM role_permissions')]
            selected=[row['role_id'] for row in db.execute('SELECT role_id FROM access_roles')]
        return {'roles':roles,'pages':list(pages.values()),'permissions':permissions,'selectedRoles':selected}

    @app.put('/api/admin/access')
    async def access_matrix(request:Request):
        user=supreme(request);data=await json_body(request)
        def commit_operation():
            if not isinstance(data,dict) or set(data)!={'selectedRoles','permissions'}:
                raise HTTPException(400,'Configuration des accès invalide.')
            selected=data['selectedRoles'];permissions=data['permissions']
            if not isinstance(selected,list) or len(selected)>1000 or any(not isinstance(role,str) for role in selected) or len(set(selected))!=len(selected):
                raise HTTPException(400,'Sélection de rôles invalide.')
            if not isinstance(permissions,dict) or set(permissions)!=set(selected):
                raise HTTPException(400,'Configure uniquement les rôles retenus.')
            private_pages={page for page,value in pages.items() if value['kind']=='private'}
            for values in permissions.values():
                if not isinstance(values,dict) or set(values)-private_pages or any(type(allowed) is not bool for allowed in values.values()):
                    raise HTTPException(400,'Seules les pages configurables sont modifiables.')
            with store.connect(True) as db:
                active={row['id'] for row in db.execute('SELECT id FROM roles WHERE active=1')}
                if set(selected)-active: raise HTTPException(400,'Un rôle sélectionné n’existe plus sur Discord. Recharge la page.')
                before={'selectedRoles':[row['role_id'] for row in db.execute('SELECT role_id FROM access_roles')],
                        'permissions':[dict(row) for row in db.execute('SELECT * FROM role_permissions')]}
                db.execute('DELETE FROM access_roles')
                db.executemany('INSERT INTO access_roles VALUES(?)',[(role,) for role in selected])
                db.execute('DELETE FROM role_permissions')
                db.executemany('INSERT INTO role_permissions VALUES(?,?,?)',
                               [(role,page,int(values.get(page,False))) for role,values in permissions.items() for page in private_pages])
                store.audit(db,user['id'],'access_matrix_changed',{'page':'council','before':before,'after':data})
            return {'ok':True}
        return await run_in_threadpool(commit_operation)

    @app.put('/api/admin/roles/{role_id}')
    async def permission(role_id:str,request:Request):
        user=supreme(request);data=await json_body(request)
        def commit_operation():
            if not isinstance(data,dict) or set(data)!={'permissions'} or not isinstance(data['permissions'],dict): raise HTTPException(400,'Permissions invalides.')
            for page,allowed in data['permissions'].items():
                if page not in pages or pages[page]['kind']!='private' or type(allowed) is not bool: raise HTTPException(400,'Seules les pages configurables sont modifiables.')
            with store.connect(True) as db:
                if not db.execute('SELECT 1 FROM roles WHERE id=? AND active=1',(role_id,)).fetchone(): raise HTTPException(404,'Rôle introuvable.')
                if not db.execute('SELECT 1 FROM access_roles WHERE role_id=?',(role_id,)).fetchone(): raise HTTPException(409,'Sélectionne d’abord ce rôle dans les rôles du domaine.')
                before={row['page_id']:bool(row['allowed']) for row in db.execute('SELECT page_id,allowed FROM role_permissions WHERE role_id=?',(role_id,))}
                for page,allowed in data['permissions'].items(): db.execute('INSERT OR REPLACE INTO role_permissions VALUES(?,?,?)',(role_id,page,int(allowed)))
                after={row['page_id']:bool(row['allowed']) for row in db.execute('SELECT page_id,allowed FROM role_permissions WHERE role_id=?',(role_id,))}
                store.audit(db,user['id'],'permissions_changed',{'page':'council','roleId':role_id,'before':before,'after':after})
            return {'ok':True}
        return await run_in_threadpool(commit_operation)

    @app.get('/api/admin/users')
    def users(request:Request):
        supreme(request)
        with store.connect() as db:
            result=[{**{key:row[key] for key in ('id','username','display_name','created','last_login','member','role_ids')},'siteAccess':accounts.snapshot(db,row['id']),'protected':accounts.protected(row['id'])} for row in db.execute('SELECT * FROM users ORDER BY last_login DESC')]
        return {'users':result}

    @app.post('/api/admin/access-accounts')
    async def create_access_account(request:Request):
        user=supreme(request);data=await json_body(request)
        return await run_in_threadpool(accounts.create,user['id'],data)

    @app.patch('/api/admin/access-accounts/{user_id}')
    async def update_access_account(user_id:str,request:Request):
        user=supreme(request);data=await json_body(request)
        async with security.lock:return await run_in_threadpool(accounts.update,user['id'],user_id,data)

    @app.post('/api/admin/access-accounts/{user_id}/rotate-code')
    async def rotate_access_code(user_id:str,request:Request):
        user=supreme(request)
        async with security.lock:return await run_in_threadpool(accounts.rotate,user['id'],user_id)

    @app.post('/api/admin/accounts/{user_id}/site-access')
    async def change_site_access(user_id:str,request:Request):
        user=supreme(request);data=await json_body(request)
        if not isinstance(data,dict) or set(data)!={'blocked'}:raise HTTPException(400,'Modification de l’accès invalide.')
        async with security.lock:return await run_in_threadpool(accounts.change_access,user['id'],user_id,data['blocked'])

    @app.get('/api/admin/audit')
    def audit(request:Request):
        supreme(request)
        return query_log(store,request.query_params,pages,legacy=True)

    @app.get('/api/admin/bot-connection')
    def bot_connection(request:Request):
        supreme(request)
        with store.connect() as db:
            seen=db.execute("SELECT value FROM metadata WHERE key='bot_last_seen'").fetchone()
            pending=db.execute('SELECT count(*) FROM bot_commands WHERE acknowledged IS NULL').fetchone()[0]
        return {'discordConfigured':cfg.configured,'connectorConfigured':bool(cfg.connector_secret),
                'commandsEnabled':cfg.bot_commands_enabled,'pendingCommands':pending,
                'lastEvent':json.loads(seen['value']) if seen else None}

    @app.post('/api/admin/reset-test-data')
    def reset_test_data(request:Request):
        user=supreme(request)
        backup=cfg.data_dir/f'backup-{time.time_ns()}.sqlite3'
        with sqlite3.connect(store.path) as source, sqlite3.connect(backup) as destination: source.backup(destination)
        backup.chmod(0o600)
        with store.connect(True) as db:
            before=json.loads(db.execute('SELECT body FROM domain_store WHERE id=1').fetchone()[0]);after=initial_domain()
            db.execute('UPDATE domain_store SET body=? WHERE id=1',(json.dumps(after),))
            store.audit(db,user['id'],'test_data_reset',{'backup':backup.name,'changes':business_changes(before,after)})
        return {'ok':True}

    @app.get('/app')
    def shell(request:Request): return FileResponse(static/'index.html')
    @app.get('/spaces/{page}')
    def space(page:str,request:Request):
        require(request,page);return RedirectResponse('/app#'+page,status_code=303)
    @app.get('/')
    def welcome(): return FileResponse(static/'index.html')
    app.mount('/assets',StaticFiles(directory=static/'assets'),name='assets')
    @app.get('/{filename}')
    def public_file(filename:str):
        if filename not in {p.name for p in static.iterdir() if p.is_file() and p.suffix in ('.css','.js')}:
            raise HTTPException(404,'Fichier introuvable.')
        return FileResponse(static/filename)
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(VisitorLimitMiddleware, limits=traffic)
    app.add_middleware(AuditHTTPMiddleware, store=store, session_cookie=COOKIE,writer=audit_writer)
    return app
