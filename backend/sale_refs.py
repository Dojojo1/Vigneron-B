"""Références courtes des dossiers, sans modifier leurs identifiants métier."""
from collections import defaultdict
from datetime import datetime

from .domain import TZ


def sale_week(sale):
    raw = sale.get('receivedDate')
    try:
        day = datetime.strptime(raw, '%d/%m/%Y').date()
    except (TypeError, ValueError):
        day = datetime.fromtimestamp(sale['created'] / 1000, TZ).date()
    year, week, _ = day.isocalendar()
    return year, week


def references(sales):
    groups = defaultdict(list)
    for sale in sales:
        identifier = str(sale.get('id', ''))
        if not identifier:
            continue
        groups[sale_week(sale)].append(sale)
    result = {}
    for (year, week), rows in groups.items():
        for number, sale in enumerate(sorted(rows, key=lambda row: (row.get('created', 0), str(row['id']))), 1):
            result[str(sale['id'])] = f"S{year % 100:02d}-{week:02d}-{number:02d}"
    return result
