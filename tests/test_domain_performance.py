"""Selection and calendar totals preserve behavior while avoiding repeated work."""
import copy
from datetime import datetime, timedelta

import pytest

from backend import domain, views


@pytest.mark.parametrize('inactive',[
    [],
    [{'id':'cancelled','cancelled':True},{'id':'recovered','recovered':True},
     {'id':'historical','historical':True},{'id':'disabled','trackingDisabled':True}],
])
def test_current_batch_returns_none_for_empty_or_all_inactive(inactive):
    state={'machines':inactive}
    before=copy.deepcopy(state)
    assert domain.current_batch(state) is None
    assert state==before


def test_current_batch_keeps_first_latest_tie_and_excludes_each_inactive_flag():
    first={'id':'first-latest','start':20,'nested':{'notes':['stored']}}
    later={'id':'second-latest','start':20}
    state={'machines':[{'id':'old','start':10},first,
                       {'id':'cancelled','start':100,'cancelled':True},
                       {'id':'recovered','start':101,'recovered':True},
                       {'id':'historical','start':102,'historical':True},
                       {'id':'disabled','start':103,'trackingDisabled':True},later]}
    before=copy.deepcopy(state)
    assert domain.current_batch(state) is first
    assert state==before
    state['machines'].reverse()
    assert domain.current_batch(state) is later


def freeze_views_time(monkeypatch,instant):
    moment=datetime.fromisoformat(instant)
    converted=[]
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls,tz=None):return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)
        @classmethod
        def fromtimestamp(cls,value,tz=None):
            converted.append(value)
            return datetime.fromtimestamp(value,tz)
    monkeypatch.setattr(views,'datetime',FrozenDateTime)
    return moment,converted


def sale(identifier,moment,amount,status='active'):
    return {'id':str(identifier),'created':int(moment.timestamp()*1000),
            'amount':amount,'baseTreated':0,'status':status}


@pytest.mark.parametrize('instant,utc_instants',[
    ('2026-03-30T12:00:00+02:00',('2026-03-28T23:30:00+00:00','2026-03-29T00:30:00+00:00',
                                '2026-03-29T01:30:00+00:00','2026-03-29T22:30:00+00:00')),
    ('2026-10-26T12:00:00+01:00',('2026-10-24T22:30:00+00:00','2026-10-25T00:30:00+00:00',
                                '2026-10-25T01:30:00+00:00','2026-10-25T23:30:00+00:00')),
])
@pytest.mark.parametrize('available',[True,False])
def test_stats_seven_brussels_calendar_dates_cross_both_dst_changes_once_per_sale(monkeypatch,instant,utc_instants,available):
    now,converted=freeze_views_time(monkeypatch,instant)
    today=now.astimezone(domain.TZ).date()
    dates=[today-timedelta(days=offset) for offset in range(6,-1,-1)]
    sales=[sale(i,datetime.combine(day,datetime.min.time(),domain.TZ)+timedelta(hours=12),i+1)
           for i,day in enumerate(dates)]
    sales.extend(sale('dst-'+str(i),datetime.fromisoformat(value),amount)
                 for i,(value,amount) in enumerate(zip(utc_instants,(100,200,400,800))))
    before_window=datetime.combine(dates[0],datetime.min.time(),domain.TZ)-timedelta(milliseconds=1)
    after_window=datetime.combine(today+timedelta(days=1),datetime.min.time(),domain.TZ)
    sales.extend([sale('before',before_window,10000),sale('after',after_window,20000),
                  sale('cancelled',now,30000,'cancelled'),
                  {'id':'cancelled-invalid-date','created':10**30,'amount':40000,'status':'cancelled'}])
    state={'sales':sales,'machines':[],'machineStats':{'users':{}},
           'businessSources':{'sales':{'available':available}}}
    before=copy.deepcopy(state)
    result=views.screen(state,'stats',{})
    expected=[1,2,3,4,5,706,807] if available else [None]*7
    assert result['days']==[{'label':label,'amount':amount}
                            for label,amount in zip(('mar.','mer.','jeu.','ven.','sam.','dim.','lun.'),expected)]
    assert len(converted)==(len([item for item in sales if item['status']!='cancelled']) if available else 0)
    assert state==before


def test_stats_empty_sales_has_all_seven_zero_dates_without_conversions(monkeypatch):
    _,converted=freeze_views_time(monkeypatch,'2026-10-26T12:00:00+01:00')
    state={'sales':[],'machines':[],'machineStats':{'users':{}}}
    assert views.screen(state,'stats',{})['days']==[
        {'label':label,'amount':0} for label in ('mar.','mer.','jeu.','ven.','sam.','dim.','lun.')]
    assert converted==[]


@pytest.mark.parametrize('invalid_timestamp',[10**30,-10**30,float('inf')])
def test_stats_preserves_invalid_active_timestamp_failure(monkeypatch,invalid_timestamp):
    freeze_views_time(monkeypatch,'2026-10-26T12:00:00+01:00')
    state={'sales':[{'id':'invalid','created':invalid_timestamp,'amount':1,'status':'active'}],
           'machines':[],'machineStats':{'users':{}}}
    with pytest.raises((OverflowError,OSError,ValueError)):
        views.screen(state,'stats',{})
