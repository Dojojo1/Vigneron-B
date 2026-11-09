from backend.sale_refs import references
from backend import domain, views
from datetime import datetime, timedelta


def test_sale_references_use_receipt_week_and_stable_order():
    rows = [
        {'id': 'long-b', 'receivedDate': '09/11/2026', 'created': 20},
        {'id': 'long-a', 'receivedDate': '09/11/2026', 'created': 10},
        {'id': 'older', 'receivedDate': '28/10/2026', 'created': 5},
    ]
    refs = references(rows)
    assert refs == {
        'long-a': 'S26-46-01',
        'long-b': 'S26-46-02',
        'older': 'S26-44-01',
    }
    assert references(list(reversed(rows))) == refs


def test_sale_references_include_year_and_fallback_to_creation_date():
    rows = [
        {'id': 'old', 'receivedDate': '28/12/2026', 'created': 0},
        {'id': 'next', 'receivedDate': '04/01/2027', 'created': 0},
        {'id': 'undated', 'receivedDate': None, 'created': 1799251200000},
    ]
    refs = references(rows)
    assert refs['old'].startswith('S26-53-')
    assert refs['next'].startswith('S27-01-')
    assert refs['undated'].startswith('S27-01-')


def test_sales_page_keeps_references_across_pagination_and_search():
    state = domain.seed()
    state['sales'] = [
        {'id': f'long-{number}', 'receivedDate': '09/11/2026', 'created': number,
         'group': 'Rubi Oscuro', 'employee': 'Ekio', 'giver': '222449',
         'amount': 5000000, 'status': 'active'}
        for number in range(1, 4)
    ]
    first = views.screen(state, 'sales', {'limit': '1'})
    second = views.screen(state, 'sales', {'limit': '1', 'salesOffset': '1'})
    assert first['saleRefs'] == second['saleRefs']
    assert first['saleRefs'][second['sales'][0]['id']] == 'S26-46-02'
    searched = views.screen(state, 'sales', {'q': 'S26-46-02'})
    assert [sale['id'] for sale in searched['sales']] == ['long-2']


def test_current_scope_excludes_old_cancelled_sale_but_keeps_active_carryover():
    today = datetime.now(domain.TZ).date()
    previous_week = today - timedelta(days=7)
    def sale(identifier, day, status):
        return {'id': identifier, 'receivedDate': day.strftime('%d/%m/%Y'),
                'created': 1794247022315, 'group': 'Rubi Oscuro', 'employee': 'Ekio',
                'giver': '222449', 'amount': 5000000, 'status': status}
    state = domain.seed()
    state['sales'] = [sale('old-cancelled', previous_week, 'cancelled'),
                      sale('old-active', previous_week, 'active'),
                      sale('current-cancelled', today, 'cancelled')]
    current = views.screen(state, 'sales', {'scope': 'current'})
    assert {row['id'] for row in current['sales']} == {'old-active', 'current-cancelled'}
    assert current['scopeCount'] == 2
    assert len(views.screen(state, 'sales', {'scope': 'all'})['sales']) == 3
