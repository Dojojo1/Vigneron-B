"""Journal métier permanent, distinct du fil d'activité et des secrets techniques."""
from contextvars import ContextVar
from datetime import datetime, timedelta
import json
import re
import uuid
import hashlib
import time
import asyncio
from http.cookies import SimpleCookie, CookieError
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

context = ContextVar('heritage_audit_context', default=None)
SECRET_KEYS = {'token', 'accesstoken', 'refreshtoken', 'clientsecret', 'bottoken', 'password',
               'secret', 'authorization', 'cookie', 'csrf', 'signature', 'nonce', 'privatekey', 'state',
               'accesscode','codehash','codesalt','accesscodehash'}


def clean(value):
    if isinstance(value, dict):
        if isinstance(value.get('path'),str) and any(re.sub(r'[^a-z]','',part.lower()) in SECRET_KEYS for part in value['path'].split('/')):
            value={**value,**{key:'[CONFIDENTIEL]' for key in ('before','after') if key in value}}
        return {str(key): '[CONFIDENTIEL]' if re.sub(r'[^a-z]', '', str(key).lower()) in SECRET_KEYS
                or any(word in re.sub(r'[^a-z]', '', str(key).lower()) for word in ('password', 'secret', 'token', 'privatekey'))
                else clean(item) for key,item in value.items()}
    if isinstance(value, (tuple,list)): return [clean(item) for item in value]
    return value


def user_snapshot(row):
    if row is None: return None
    result={key:row[key] for key in ('id','username','discord_avatar','display_name','avatar_file',
                                   'created','last_login','member','role_ids')}
    result['role_ids']=json.loads(result['role_ids'])
    return result


def differences(before, after, path=''):
    """Valeurs complètes des champs modifiés ; aucun tronquage des listes."""
    if before == after: return []
    if isinstance(before,dict) and isinstance(after,dict):
        result=[]
        for key in sorted(set(before)|set(after)):
            child=path+'/'+str(key).replace('~','~0').replace('/','~1')
            if key not in before or key not in after:
                result.append({'path':child,'before':before.get(key),'after':after.get(key),
                               'beforeExists':key in before,'afterExists':key in after})
            else: result.extend(differences(before[key],after[key],child))
        return result
    if isinstance(before,list) and isinstance(after,list):
        def keyed(items):
            return all(isinstance(v,dict) and 'id' in v for v in items) and len({str(v['id']) for v in items})==len(items)
        if keyed(before) and keyed(after):
            return differences({str(v['id']):v for v in before},{str(v['id']):v for v in after},path)
    return [{'path':path or '/','before':before,'after':after,'beforeExists':True,'afterExists':True}]


def business_changes(before,after):
    # Le fil d'activité est une vue ; sa rotation ne doit pas polluer les changements métier.
    return differences(clean({k:v for k,v in before.items() if k!='events'}),
                       clean({k:v for k,v in after.items() if k!='events'}))


def route_info(path):
    if path in ('/internal/bot/events','/internal/bot/commands','/internal/bot/ack'):
        return path,None
    if path in ('/','/app','/auth/start','/auth/callback','/auth/access-code','/auth/logout','/api/status',
                '/api/me','/api/me/profile','/api/me/avatar','/api/client-errors','/api/bootstrap'):
        return path, 'profile' if path.startswith('/api/me') else None
    match=re.fullmatch(r'/(?:api/(?:pages|actions|visits)|spaces)/([a-z][a-z0-9_-]{0,60})(?:/.*)?',path)
    if match: return '/'+path.strip('/').split('/')[0]+'/'+('/'.join(path.strip('/').split('/')[1:3])),match[1]
    if re.fullmatch(r'/api/admin/(?:access|users|audit|bot-connection|reset-test-data|roles/[0-9]{1,24})',path):
        return '/api/admin/roles' if '/roles/' in path else path,'council'
    if re.fullmatch(r'/api/admin/(?:access-accounts(?:/guest-[0-9a-f]{32}(?:/rotate-code)?)?|accounts/(?:[0-9]{1,24}|guest-[0-9a-f]{32}|local-preview)/site-access)',path):
        return '/api/admin/accounts' if '/accounts/' in path else '/api/admin/access-accounts','council'
    return '[route inconnue]',None


class DurableAuditWriter:
    """Regrouper les logs concurrents ; chaque appel attend son COMMIT durable."""
    def __init__(self, store):
        self.store = store
        self.queue = asyncio.Queue(maxsize=2048)
        self.task = None
        self.closed = False
        self.submissions = set()

    async def _enqueue(self, entry):
        await self.queue.put(entry)
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._drain())

    async def append(self, actor, kind, detail, session_hash=None):
        if self.closed:
            raise RuntimeError('Le journal est fermé.')
        future = asyncio.get_running_loop().create_future()
        # Une déconnexion HTTP ne doit ni annuler le COMMIT, ni perdre son log.
        future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        # Protéger aussi l'attente d'une place dans la file : l'annulation d'une
        # requête sous charge ne doit pas effacer un événement déjà accepté.
        submission = asyncio.create_task(self._enqueue((actor, kind, dict(detail), session_hash, future)))
        self.submissions.add(submission)
        submission.add_done_callback(self.submissions.discard)
        await asyncio.shield(submission)
        await asyncio.shield(future)

    async def _drain(self):
        while not self.queue.empty():
            # Petite fenêtre bornée pour partager un seul COMMIT entre les requêtes concurrentes.
            await asyncio.sleep(.002)
            batch = []
            while len(batch) < 128 and not self.queue.empty():
                batch.append(self.queue.get_nowait())
            try:
                await run_in_threadpool(self._persist, batch)
            except Exception as error:
                for *_, future in batch:
                    if not future.done(): future.set_exception(error)
            else:
                for *_, future in batch:
                    if not future.done(): future.set_result(None)
            finally:
                for _ in batch: self.queue.task_done()

    def _persist(self, batch):
        with self.store.connect(True) as db:
            for actor, kind, detail, session_hash, _ in batch:
                if not actor and session_hash:
                    row = db.execute('SELECT s.user_id FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.hash=? AND s.expires>? AND u.member=1',
                                     (session_hash, time.time())).fetchone()
                    if row: actor = row['user_id']
                self.store.audit(db, actor, kind, detail)

    async def close(self):
        self.closed = True
        # Les soumissions acceptées avant la fermeture peuvent encore attendre
        # leur place ; les vider avant de fermer le stockage.
        if self.submissions:
            await asyncio.shield(asyncio.gather(*tuple(self.submissions)))
        if self.task is not None:
            await asyncio.shield(self.task)


class AuditHTTPMiddleware:
    def __init__(self,app,store,session_cookie,writer=None):
        self.app,self.store,self.session_cookie=app,store,session_cookie
        self.writer = writer or DurableAuditWriter(store)

    async def __call__(self,scope,receive,send):
        if scope['type']!='http': return await self.app(scope,receive,send)
        path,page=route_info(scope['path'])
        request_id=uuid.uuid4().hex
        token=context.set({'requestId':request_id,'route':path,'method':scope['method']})
        started=False
        async def record(status):
            state=scope.get('state',{});identity=state.get('identity')
            actor=identity['id'] if identity else state.get('audit_actor')
            headers=dict(scope.get('headers',[]))
            visit=headers.get(b'x-heritage-visit')==b'1' and scope['path'].startswith('/api/pages/')
            if status>=400: kind='request_refused' if status<500 else 'request_failed'
            elif state.get('audit_navigation_logged'): return
            elif state.get('audit_log_entry'): kind='journal_entry_viewed'
            elif visit: kind='page_view'
            elif scope['path']=='/': kind='site_opened'
            elif scope['method'] not in ('GET','HEAD','OPTIONS'): kind='request_completed'
            elif state.get('audit_export') or headers.get(b'x-heritage-export')==b'1': kind='data_exported'
            elif scope['path'].startswith(('/api/pages/','/api/admin/')) and not state.get('audit_background'): kind='data_read'
            else: return
            session_hash = None
            if not actor:
                # Attribution seule, sans accorder un accès ni effectuer d'appel Discord.
                try:
                    cookies=SimpleCookie();cookies.load(headers.get(b'cookie',b'').decode('latin1'))
                    value=cookies.get(self.session_cookie)
                    if value:
                        session_hash=hashlib.sha256(value.value.encode()).hexdigest()
                except (CookieError,UnicodeError): pass
            detail={'page':page,'status':status,'result':'refused' if 400<=status<500 else 'failure' if status>=500 else state.get('audit_outcome','success')}
            if state.get('audit_action'): detail['action']=state['audit_action']
            if state.get('audit_log_entry'): detail['record']=str(state['audit_log_entry'])
            if state.get('audit_exception'): detail['errorType']=state['audit_exception']
            if status>=400 and state.get('audit_stage'): detail['stage']=state['audit_stage']
            # Capturer le contexte propre à CETTE requête avant le regroupement des écritures.
            await self.writer.append(actor,kind,{**(context.get() or {}),**detail},session_hash)
        async def audited_send(message):
            nonlocal started
            if message['type']=='http.response.start':
                await record(message['status'])
                message['headers']=list(message.get('headers',[]))+[(b'x-request-id',request_id.encode())]
                started=True
            await send(message)
        try:
            await self.app(scope,receive,audited_send)
        except Exception as error:
            if started: raise
            scope.setdefault('state',{})['audit_exception']=type(error).__name__
            # Aucun message d'exception, corps de requête ou URL OAuth2 dans le journal.
            try: await record(500)
            except Exception: pass  # Disque indisponible : aucune écriture métier auditée ne peut être validée.
            await JSONResponse({'detail':'Le serveur n’a pas pu terminer la demande. Réessaie plus tard.'},status_code=500,
                               headers={'Cache-Control':'no-store','X-Request-ID':request_id})(scope,receive,send)
        finally: context.reset(token)


def query_log(store,params,pages,legacy=False):
    from .views import number
    conditions=[];values=[]
    expressions={'actor':'actor','kind':'kind','page':"json_extract(detail,'$.page')",'result':"json_extract(detail,'$.result')"}
    for key,expr in expressions.items():
        value=params.get(key,'').strip()
        if value:
            if len(value)>100: raise HTTPException(400,'Filtre trop long.')
            if key=='page' and value not in pages: raise HTTPException(400,'Page inconnue.')
            if key=='result' and value not in ('success','failure','refused','duplicate'): raise HTTPException(400,'Résultat inconnu.')
            conditions.append(expr+'=?');values.append(value)
    if params.get('before'):
        conditions.append('id<?');values.append(number(params,'before',maximum=9223372036854775807))
    for key,operator in (('from','>='),('to','<')):
        if params.get(key):
            try:
                day=datetime.strptime(params[key],'%Y-%m-%d').replace(tzinfo=ZoneInfo('Europe/Brussels'))
                if key=='to': day+=timedelta(days=1)
            except (ValueError,OverflowError): raise HTTPException(400,'Date de filtre invalide.') from None
            conditions.append('at'+operator+'?');values.append(day.timestamp())
    search=params.get('q','').strip()
    if len(search)>100: raise HTTPException(400,'Recherche trop longue.')
    if search:
        escaped=search.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        conditions.append("(coalesce(actor,'')||' '||kind||' '||coalesce(json_extract(detail,'$.actorName'),'')||' '||coalesce(json_extract(detail,'$.action'),'')||' '||coalesce(json_extract(detail,'$.record'),'')) LIKE ? ESCAPE '\\'")
        values.append('%'+escaped+'%')
    size=number(params,'limit',200 if legacy else 50,200 if legacy else 100)
    if not size: raise HTTPException(400,'Taille de page invalide.')
    columns="id,at,actor,kind,detail" if legacy else "id,at,actor,kind,json_extract(detail,'$.actorName') actorName,json_extract(detail,'$.page') page,json_extract(detail,'$.action') action,json_extract(detail,'$.result') result,json_extract(detail,'$.record') record,json_array_length(json_extract(detail,'$.changes')) changeCount"
    with store.connect() as db:
        rows=[dict(row) for row in db.execute('SELECT '+columns+' FROM audit'+(' WHERE '+' AND '.join(conditions) if conditions else '')+' ORDER BY id DESC LIMIT ?',[*values,size+1])]
        kinds=[row[0] for row in db.execute('SELECT DISTINCT kind FROM audit ORDER BY kind')]
    more=len(rows)>size;rows=rows[:size]
    return {'audit':rows,'nextBefore':rows[-1]['id'] if more else None,'kinds':kinds,'limit':size,
            'pages':[{'id':p['id'],'label':p['label']} for p in pages.values()]}


def log_entry(store,entry_id):
    if not 1<=entry_id<=9223372036854775807: raise HTTPException(400,'Identifiant invalide.')
    with store.connect() as db: row=db.execute('SELECT * FROM audit WHERE id=?',(entry_id,)).fetchone()
    if not row: raise HTTPException(404,'Événement introuvable.')
    result=dict(row);result['detail']=clean(json.loads(result['detail']))
    return result
