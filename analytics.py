"""
analytics.py — Market intel from USASpending award history.

Fetches past awards for a keyword and derives competitor, price-trend and
regional stats for the app's market tab and the Advisor's tools.
"""
import logging, requests
from datetime import datetime, timedelta, timezone
import pandas as pd

logger = logging.getLogger(__name__)
USASPENDING_URL = 'https://api.usaspending.gov/api/v2/search/spending_by_award/'

# Field names must exactly match the API's documented list — invalid names = 422
SAFE_FIELDS = ['Award ID', 'Award Amount', 'Description', 'Awarding Agency',
               'Recipient Name', 'Place of Performance State Code',
               'Place of Performance Zip5', 'Start Date', 'End Date']


def fetch_historical_awards(keyword, naics_code=None, days_back=365, max_results=100):
    keyword = (keyword or '').strip()
    if len(keyword) < 3:
        logger.warning('Keyword too short for USASpending: %r', keyword)
        return pd.DataFrame()
    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=days_back)).strftime('%Y-%m-%d')
    end_date = now.strftime('%Y-%m-%d')
    filters = {'keywords': [keyword], 'time_period': [{'start_date': start_date, 'end_date': end_date}], 'award_type_codes': ['A','B','C','D']}
    if naics_code:
        filters['naics_codes'] = [str(naics_code)]
    payload = {'filters': filters, 'fields': SAFE_FIELDS, 'sort': 'Start Date', 'order': 'desc', 'limit': min(max_results, 100), 'page': 1}  # API max is 100
    try:
        resp = requests.post(USASPENDING_URL, json=payload, timeout=30)
        resp.raise_for_status()
        results = resp.json().get('results', [])
    except requests.HTTPError as exc:
        body = getattr(getattr(exc, 'response', None), 'text', '')[:300]
        logger.error('USASpending rejected payload (%s): %s', exc, body)
        return pd.DataFrame()
    except Exception as exc:
        logger.error('USASpending error: %s', exc)
        return pd.DataFrame()
    rows = []
    for award in results:
        amount = award.get('Award Amount')
        if not amount or float(amount) <= 0:
            continue
        rows.append({'award_id': award.get('Award ID',''), 'amount': float(amount), 'description': str(award.get('Description') or keyword)[:80], 'agency': award.get('Awarding Agency') or 'Unknown', 'recipient': award.get('Recipient Name') or 'Unknown', 'state': award.get('Place of Performance State Code') or 'Unknown', 'zip': str(award.get('Place of Performance Zip5') or '')[:5], 'start_date': award.get('Start Date'), 'end_date': award.get('End Date')})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df['start_date'] = pd.to_datetime(df['start_date'], errors='coerce')
    df['end_date'] = pd.to_datetime(df['end_date'], errors='coerce')
    df = df.dropna(subset=['amount'])
    df = df.sort_values('start_date', ascending=True)
    return df

def compute_competitor_stats(df):
    if df.empty:
        return pd.DataFrame()
    stats = df.groupby('recipient').agg(total_wins=('amount','count'), total_revenue=('amount','sum'), avg_price=('amount','mean'), min_price=('amount','min'), max_price=('amount','max'), last_win=('start_date','max')).reset_index().sort_values('total_wins', ascending=False)
    stats['avg_price'] = stats['avg_price'].round(2)
    stats['total_revenue'] = stats['total_revenue'].round(2)
    stats['win_rate_pct'] = (stats['total_wins'] / stats['total_wins'].sum() * 100).round(1)
    return stats

def compute_price_trend(df):
    if df.empty or 'start_date' not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df['month'] = df['start_date'].dt.to_period('M').dt.to_timestamp()
    trend = df.groupby('month').agg(avg_price=('amount','mean'), min_price=('amount','min'), max_price=('amount','max'), num_awards=('amount','count')).reset_index().sort_values('month')
    trend['avg_price'] = trend['avg_price'].round(2)
    trend['min_price'] = trend['min_price'].round(2)
    trend['max_price'] = trend['max_price'].round(2)
    return trend

def compute_regional_stats(df):
    if df.empty:
        return pd.DataFrame()
    regional = df.groupby('state').agg(num_awards=('amount','count'), avg_price=('amount','mean'), total_spend=('amount','sum')).reset_index().sort_values('total_spend', ascending=False)
    regional['avg_price'] = regional['avg_price'].round(2)
    regional['total_spend'] = regional['total_spend'].round(2)
    return regional

def beat_this_price(competitor_price, your_cogs, shipping_cost, minimum_margin_pct=0.15):
    target_bid = round(competitor_price * 0.95, 2)
    total_cogs = your_cogs + shipping_cost
    margin_at_target = (target_bid - total_cogs) / target_bid if target_bid > 0 else 0
    min_viable_bid = round(total_cogs / (1 - minimum_margin_pct), 2)
    can_undercut = target_bid >= min_viable_bid
    verdict = 'You can undercut and stay profitable' if can_undercut else 'Cannot undercut - min viable bid is ' + str(min_viable_bid)
    return {'competitor_price': competitor_price, 'target_undercut_bid': target_bid, 'undercut_pct': 5.0, 'your_total_cogs': round(total_cogs, 2), 'margin_at_target_pct': round(margin_at_target * 100, 1), 'minimum_viable_bid': min_viable_bid, 'can_profitably_undercut': can_undercut, 'verdict': verdict}