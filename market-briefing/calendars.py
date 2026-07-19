# -*- coding: utf-8 -*-
"""
한국/미국 증시 휴장일 판별.
  하드스톱 시점까지 소스(버터대디/증시각도기)가 없을 때, 그날이 애초에
  휴장일이었다면 굳이 총평 없는 부실한 리포트를 보내지 않고 건너뛰기 위함.
"""


def is_kr_market_holiday(d):
    """d: datetime.date. 주말이거나 한국 공휴일이면 True."""
    if d.weekday() >= 5:  # 토(5)/일(6)
        return True
    import holidays
    kr = holidays.KR(years=d.year)
    return d in kr


def is_us_market_holiday(d):
    """d: datetime.date. 주말이거나 뉴욕증권거래소(NYSE) 휴장일이면 True."""
    if d.weekday() >= 5:
        return True
    import pandas_market_calendars as mcal
    nyse = mcal.get_calendar("NYSE")
    sched = nyse.schedule(start_date=d.isoformat(), end_date=d.isoformat())
    return sched.empty
