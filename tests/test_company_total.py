"""The opening total already includes old records; confirmed new activity adds once."""
import copy
from backend.company_history import project_company_total
from test_company_history import post,declaration
from test_business_connection import setup,sale,snapshot,sync
from test_partial_sales_projection import partial


def opening(env,*,partial_source=False):
    setup(env)
    old=sale(amount=200,treated=200,status='finished')
    source=partial(records=[old],revision=0) if partial_source else snapshot(records=[old],revision=0)
    assert sync(env,source).status_code==200
    response=post(env);assert response.status_code==200,response.text
    h=response.json()['companyHistory']
    new=sale(id='new-sale',amount=300,created=h['recordedAt']+1000,receivedDate='31/10/2026',treated=0)
    return old,new,h


def total(env):return project_company_total(env['store'].read_domain())


def test_opening_includes_existing_cards_without_adding_them(env):
    old,new,h=opening(env)
    assert total(env)['gross']==1000 and total(env)['operations']==2
    assert total(env)['additionalOperations']==0
    assert sync(env,snapshot(records=[old,new],revision=1)).status_code==200
    assert total(env)['gross']==1300 and total(env)['company']==195 and total(env)['group']==1040
    assert total(env)['operations']==3 and total(env)['completed'] is False
    assert sync(env,snapshot(records=[old,new],revision=1)).status_code==200
    assert total(env)['gross']==1300


def test_finishing_or_archiving_same_sale_does_not_add_again(env):
    old,new,h=opening(env)
    assert sync(env,snapshot(records=[old,new],revision=1)).status_code==200
    assert sync(env,snapshot(records=[old,{**new,'status':'finished','archive':'s44'}],revision=2)).status_code==200
    assert total(env)['gross']==1300 and total(env)['operations']==3


def test_new_correction_and_cancellation_apply_net_difference(env):
    old,new,h=opening(env)
    for revision,record,gross,count in [(1,new,1300,3),(2,{**new,'amount':500},1500,3),
             (3,{**new,'amount':500,'status':'cancelled'},1000,2),
             (4,{**new,'amount':500,'status':'active'},1500,3)]:
        assert sync(env,snapshot(records=[old,record],revision=revision)).status_code==200
        assert (total(env)['gross'],total(env)['operations'])==(gross,count)


def test_existing_confirmed_cancellation_adjusts_initial_total_once(env):
    old,new,h=opening(env)
    assert sync(env,snapshot(records=[{**old,'status':'cancelled'}],revision=1)).status_code==200
    assert total(env)['gross']==800 and total(env)['operations']==1
    assert sync(env,snapshot(records=[{**old,'status':'cancelled'}],revision=2)).status_code==200
    assert total(env)['gross']==800


def test_disappearing_messages_or_history_window_expiry_does_not_erase_money(env):
    old,new,h=opening(env)
    assert sync(env,snapshot(records=[old,new],revision=1)).status_code==200
    assert sync(env,snapshot(records=[],revision=2)).status_code==200
    assert total(env)['gross']==1300 and total(env)['operations']==3


def test_outage_keeps_last_total_and_marks_refresh_pending(env):
    old,new,h=opening(env)
    assert sync(env,snapshot(records=[old,new],revision=1)).status_code==200
    assert sync(env,snapshot(records=[],revision=2,available=False,complete=False)).status_code==200
    assert total(env)['gross']==1300 and total(env)['upToDate'] is False
    assert sync(env,snapshot(records=[old,new],revision=3)).status_code==200
    assert total(env)['gross']==1300 and total(env)['upToDate'] is True


def test_old_unresolved_card_restored_is_already_covered(env):
    old,new,h=opening(env,partial_source=True)
    state=env['store'].read_domain();covered=state['companyHistory']['tracking']['coveredIds'];assert covered
    restored={**new,'id':covered[0],'amount':700}
    assert sync(env,snapshot(records=[old,restored],revision=1)).status_code==200
    assert total(env)['gross']==1000 and total(env)['operations']==2


def test_late_old_week_import_does_not_add_again(env):
    old,new,h=opening(env)
    historical={**new,'id':'restored-old','receivedDate':'01/01/2019'}
    assert sync(env,snapshot(records=[old,historical],revision=1)).status_code==200
    assert total(env)['gross']==1000 and total(env)['operations']==2


def test_reused_storage_without_cancellation_is_reviewed_not_double_counted(env):
    old,new,h=opening(env)
    # Capture a physical reference as part of a new opening declaration.
    old={**old,'storage':{'sheetId':'book','worksheet':'En cours','row':10}}
    assert sync(env,snapshot(records=[old],revision=1)).status_code==200
    updated=post(env,declaration(expectedId=h['id'],operationKey='recapture')).json()['companyHistory']
    new={**new,'created':updated['recordedAt']+1000,'storage':old['storage']}
    assert sync(env,snapshot(records=[old,new],revision=2)).status_code==200
    assert total(env)['gross']==1000 and total(env)['upToDate'] is False
    # Explicit cancellation makes the slot reusable, even if incoming order is new then old.
    assert sync(env,snapshot(records=[new,{**old,'status':'cancelled'}],revision=3)).status_code==200
    assert total(env)['gross']==1100 and total(env)['operations']==2


def test_replacing_total_captures_current_cards_without_readding_them(env):
    old,new,h=opening(env)
    assert sync(env,snapshot(records=[old,new],revision=1)).status_code==200
    replacement=declaration(gross=1300,company=195,group=1040,operations=3,
                           expectedId=h['id'],operationKey='new-opening')
    result=post(env,replacement);assert result.status_code==200
    assert total(env)['gross']==1300 and total(env)['additionalOperations']==0
    assert sync(env,snapshot(records=[old,new],revision=2)).status_code==200
    assert total(env)['gross']==1300
    for page in ('overview','stats'):
        value=env['client'].get('/api/pages/'+page+'?view=screen').json()
        assert value['companyTotal']['gross']==1300


def test_projection_is_readonly_and_operational_allocations_remain_independent(env):
    from backend import domain
    old,new,h=opening(env)
    assert sync(env,snapshot(records=[old,new],revision=1)).status_code==200
    state=env['store'].read_domain();before=copy.deepcopy(state)
    assert project_company_total(state)['gross']==1300 and state==before
    assert domain.financial(state)['gross']==500
    assert domain.allocations(state)[new['id']]==0
