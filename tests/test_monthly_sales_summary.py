"""Monthly statistics count dated, confirmed dossiers without inventing progress."""
from datetime import datetime

from backend import domain


def test_monthly_summary_uses_received_date_and_known_progress():
    now = datetime(2026, 11, 8, 12, tzinfo=domain.TZ)
    def sale(ident, received, treated, status='active'):
        return {'id': ident, 'amount': 5_000_000, 'receivedDate': received, 'created': 0,
                'treated': treated, 'progressKnown': treated is not None,
                'botStatus': 'confirmed', 'status': status}
    state = {'sales': [sale('a', '02/11/2026', 4_000_000),
                       sale('b', '06/11/2026', None),
                       sale('old', '31/10/2026', 5_000_000),
                       sale('cancelled', '07/11/2026', 0, 'cancelled'),
                       sale('undated', '', 0)],
             'machines': [], 'salesBridgeConfirmedOnly': True}
    assert domain.monthly_sales_summary(state, now) == {
        'month': '2026-11', 'available': True, 'partial': False,
        'count': 2, 'received': 10_000_000, 'company': 1_500_000,
        'group': 8_000_000, 'treated': 4_000_000,
        'knownProgressCount': 1, 'undatedCount': 1,
    }


def test_monthly_summary_preserves_unavailable_and_real_zero():
    now = datetime(2026, 11, 8, 12, tzinfo=domain.TZ)
    state = {'sales': [], 'machines': [],
             'businessSources': {'sales': {'available': False}}}
    missing = domain.monthly_sales_summary(state, now)
    assert missing['available'] is False and missing['received'] is None
    state['businessSources']['sales']['available'] = True
    empty = domain.monthly_sales_summary(state, now)
    assert empty['available'] is True and empty['received'] == empty['treated'] == 0
