"""Dashboard indicators use the current ledger and this week's machine cycles."""
from datetime import datetime, timedelta

from backend import domain


def test_overview_metrics_ignore_archived_cancelled_and_old_cycles():
    now = datetime(2026, 11, 6, 12, tzinfo=domain.TZ)
    current = int(now.timestamp() * 1000)
    old = int((now - timedelta(days=7)).timestamp() * 1000)
    state = {
        'sales': [
            {'id': '1', 'amount': 5_000_000, 'status': 'active'},
            {'id': '2', 'amount': 2_000_000, 'status': 'finished'},
            {'id': '3', 'amount': 3_000_000, 'status': 'cancelled'},
            {'id': '4', 'amount': 4_000_000, 'status': 'finished', 'archive': 'old'},
        ],
        'machines': [
            {'id': '1', 'amount': 1_000_000, 'start': current, 'machineCount': 5},
            {'id': '2', 'amount': 600_000, 'start': current - 60_000, 'machineCount': 5, 'recovered': True},
            {'id': '3', 'amount': 1_000_000, 'start': old, 'machineCount': 5},
            {'id': '4', 'amount': 1_000_000, 'start': current, 'cancelled': True},
        ],
    }
    assert domain.overview_metrics(state, now) == {
        'received': 7_000_000, 'processed': 1_600_000, 'companyGain': 1_500_000,
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
