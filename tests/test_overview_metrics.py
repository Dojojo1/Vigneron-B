"""Dashboard indicators use the current ledger and this week's machine cycles."""
from datetime import datetime, timedelta

from backend import domain


def test_overview_metrics_ignore_archived_cancelled_and_old_cycles():
    now = datetime(2026, 11, 6, 12, tzinfo=domain.TZ)
    current = int(now.timestamp() * 1000)
    old = int((now - timedelta(days=7)).timestamp() * 1000)
    state = {
        'sales': [
            {'id': '1', 'amount': 5_000_000, 'status': 'active', 'baseTreated': 4_000_000, 'created': 1},
            {'id': '2', 'amount': 2_000_000, 'status': 'finished', 'baseTreated': 2_000_000, 'created': 2},
            {'id': '3', 'amount': 3_000_000, 'status': 'cancelled', 'created': 3},
            {'id': '4', 'amount': 4_000_000, 'status': 'finished', 'archive': 'old', 'created': 4},
        ],
        'machines': [
            {'id': '1', 'amount': 1_000_000, 'start': current, 'machineCount': 5},
            {'id': '2', 'amount': 600_000, 'start': current - 60_000, 'machineCount': 5, 'recovered': True},
            {'id': '3', 'amount': 1_000_000, 'start': old, 'machineCount': 5},
            {'id': '4', 'amount': 1_000_000, 'start': current, 'cancelled': True},
        ],
    }
    assert domain.overview_metrics(state, now) == {
        'received': 7_000_000, 'processed': 6_600_000, 'companyGain': 1_500_000,
    }


def test_overview_metrics_do_not_show_unverified_stored_values():
    now = datetime(2026, 11, 6, 12, tzinfo=domain.TZ)
    state = {
        'sales': [{'id': '1', 'amount': 5_000_000, 'status': 'active'}],
        'machines': [{'id': '1', 'amount': 1_000_000, 'start': int(now.timestamp() * 1000)}],
        'businessSources': {'sales': {'available': False}, 'machines': {'available': False}},
    }
    assert domain.overview_metrics(state, now) == {
        'received': None, 'processed': None, 'companyGain': None,
    }


def test_overview_metrics_use_confirmed_bot_cycles_despite_stale_machine_source():
    now = datetime(2026, 11, 6, 12, tzinfo=domain.TZ)
    state = {
        'sales': [],
        'machines': [
            {'id': 'confirmed', 'amount': 1_000_000, 'start': int(now.timestamp() * 1000),
             'machineCount': 5, 'botStatus': 'confirmed'},
            {'id': 'unconfirmed', 'amount': 1_000_000, 'start': int(now.timestamp() * 1000),
             'machineCount': 5, 'botStatus': 'unconfirmed'},
        ],
        'businessSources': {'machines': {'available': False}},
        'machineBridgeConfirmedOnly': True,
    }
    assert domain.overview_metrics(state, now) == {
        'received': 0, 'processed': 0, 'companyGain': 750_000,
    }


def test_overview_processed_uses_sale_progress_not_machine_turnover():
    now = datetime(2026, 11, 6, 12, tzinfo=domain.TZ)
    state = {
        'sales': [
            {'id': 'sale', 'amount': 5_000_000, 'treated': 4_000_000,
             'progressKnown': True, 'status': 'active', 'botStatus': 'confirmed', 'created': 1},
        ],
        'machines': [
            {'id': str(i), 'amount': 1_000_000, 'start': int(now.timestamp() * 1000)}
            for i in range(33)
        ],
        'salesBridgeConfirmedOnly': True,
    }
    assert domain.overview_metrics(state, now)['processed'] == 4_000_000
