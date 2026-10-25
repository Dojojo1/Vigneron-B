import pytest
from datetime import datetime

from backend import domain
from backend.views import number
from conftest import headers, login, SUPREME
from fastapi import HTTPException


def test_seed_catalogues_are_independent_of_each_other_and_configuration():
    first=domain.seed();second=domain.seed()
    assert first['catalog'] is not second['catalog']
    assert first['catalog'] is not domain.CONFIG['catalog']
    assert first['catalog']['voitures'] is not second['catalog']['voitures']


def test_numeric_zero_is_an_amount_only_when_explicitly_allowed():
    assert domain.amount(0,allow_zero=True)==0
    with pytest.raises(ValueError): domain.amount(0,default=1000000)
    with pytest.raises(ValueError): domain.amount(False,default=1000000)


def test_numeric_amounts_keep_their_value_and_reject_fractional_values():
    assert domain.amount(1000000.0)==1000000
    with pytest.raises(ValueError): domain.amount(1.5)
    with pytest.raises(ValueError): domain.amount(float('inf'))


def test_numeric_sale_amount_is_not_multiplied_by_ten(env):
    login(env,SUPREME)
    result=env['client'].post('/api/actions/sales',json={
        'action':'add-sale','values':{'group':'Rubi Oscuro','employee':'Tom Kerrigan','amount':1000000.0}
    },headers=headers(env))
    assert result.status_code==200
    assert env['store'].read_domain()['sales'][-1]['amount']==1000000


def test_tombola_numeric_zero_price_is_preserved(env):
    login(env,SUPREME)
    result=env['client'].post('/api/actions/tombola',json={
        'action':'raffle-record','values':{'vehicle0':'Windsor','price0':0,'vehicle1':'Bati','price1':'0'}
    },headers=headers(env))
    assert result.status_code==200
    vehicles=env['store'].read_domain()['tombolaRecords'][0]['vehicles']
    assert [vehicle['price'] for vehicle in vehicles]==[0,0]


def test_long_numeric_pagination_is_an_invalid_request_and_not_a_server_error():
    with pytest.raises(HTTPException) as error: number({'offset':'9'*5000},'offset')
    assert error.value.status_code==400
    assert number({'offset':'0'*5000+'12'},'offset')==12


@pytest.mark.parametrize('instant,expected',[
    ('2021-01-01T12:00:00+01:00','2020-s53'),
    ('2024-12-30T12:00:00+01:00','2025-s01'),
])
def test_sales_archives_follow_iso_year_and_preserve_previous_closures(monkeypatch,instant,expected):
    moment=datetime.fromisoformat(instant)
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls,tz=None): return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)
    monkeypatch.setattr(domain,'datetime',FrozenDateTime)
    state=domain.seed()
    before=domain.allocations(state)
    domain.mutate(state,'sales','confirm-sales-reset',None,{},'Compte test')
    assert state['salesWeek']['archives'][0]['name']==expected
    assert all(sale['archive']==expected for sale in state['sales'])
    domain.mutate(state,'sales','confirm-sales-reset',None,{},'Compte test')
    assert [archive['name'] for archive in state['salesWeek']['archives']]==[expected,expected+'-2']
    assert all(sale['archive']==expected for sale in state['sales'])
    assert domain.allocations(state)==before


def test_finished_sales_keep_their_fifo_share_and_cancelled_sales_never_receive_credit():
    state=domain.seed()
    state['sales'][0].update(amount=5000000,baseTreated=0,status='finished')
    state['sales'][1].update(amount=5000000,baseTreated=0)
    state['machines'][0].update(amount=7000000,recovered=True)
    assert domain.allocations(state)=={'041':5000000,'032':2000000}
    state['sales'][0]['status']='cancelled'
    assert domain.allocations(state)=={'041':0,'032':5000000}
    summary=domain.financial(state)
    assert summary=={'gross':5000000,'company':750000,'group':4000000,'loss':250000,
                     'treated':5000000,'pending':0,'restitute':4000000}
