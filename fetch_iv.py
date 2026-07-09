# -*- coding: utf-8 -*-
"""
fetch_iv.py — 为 lists_input.xlsx 每个唯一标的取「90% 现价档、6 个月 put」的 IV，回填 IV 列。
  - 港股无期权 → 退回 6M 历史波动率(HV)。
  - 含限流重试；失败标的自动重试一轮。
  - 自动识别代码列(含"代码/名称/ticker"等)与 IV 列(无则新建)。
前提: OpenD 运行并登录。用法: python fetch_iv.py
"""
import sys, time, datetime as dt, os
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, openpyxl
from futu import OpenQuoteContext, OptionType, KLType, AuType

DIR = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(DIR, "lists_input.xlsx")
TARGET_DAYS = 183          # 目标 6 个月
MONEYNESS   = 0.90         # 取 90% 现价档

def _pick_col(headers, keys):
    for i, h in enumerate(headers):
        if any(k in str(h or "").strip().lower() for k in keys): return i
    return None

def _to_code(v):
    s = str(v).strip().split('.')[0].split()[0]
    return (f"HK.{int(s):05d}", s) if s.isdigit() else (f"US.{s.upper()}", s.upper())

def main():
    q = OpenQuoteContext(host="127.0.0.1", port=11111)

    def rq(fn, tries=4, wait=2.0):
        for _ in range(tries):
            o = fn()
            if o[0] == 0: return o[1]
            time.sleep(wait)
        return None

    def hv_6m(code):
        end = dt.date.today(); start = end - dt.timedelta(days=280)
        kl = rq(lambda: q.request_history_kline(code, start=str(start), end=str(end),
                ktype=KLType.K_DAY, autype=AuType.QFQ, max_count=200)[:2])
        if kl is None or len(kl) < 40: return None
        c = kl["close"].astype(float).values[-126:]
        return round(float(np.std(np.diff(np.log(c)), ddof=1) * np.sqrt(252) * 100), 1)

    def iv90(code):
        exps = rq(lambda: q.get_option_expiration_date(code))
        if exps is None: return ("fail", None)          # 限流/错误 → 稍后重试
        if len(exps) == 0: return ("hv", hv_6m(code))   # 真无期权 → HV
        expiry = min(exps.to_dict("records"),
                     key=lambda r: abs(r["option_expiry_date_distance"] - TARGET_DAYS))["strike_time"]
        time.sleep(0.3)
        snap = rq(lambda: q.get_market_snapshot([code]))
        if snap is None: return ("fail", None)
        spot = float(snap.iloc[0]["last_price"]); time.sleep(0.3)
        chain = rq(lambda: q.get_option_chain(code, start=expiry, end=expiry, option_type=OptionType.PUT))
        if chain is None or len(chain) == 0: return ("fail", None)
        tgt = MONEYNESS * spot
        ch = chain[["code", "strike_price"]].sort_values("strike_price")
        ks = ch["strike_price"].values; idx = int(np.argmin(np.abs(ks - tgt)))
        near = list(ch["code"].values[max(0, idx-2):idx+3]); nk = list(ks[max(0, idx-2):idx+3])
        time.sleep(0.3)
        os_ = rq(lambda: q.get_market_snapshot(near))
        if os_ is None: return ("fail", None)
        ivm = {r["code"]: r["option_implied_volatility"] for _, r in os_.iterrows()}
        pts = [(k/spot, float(ivm[c])) for c, k in zip(near, nk) if c in ivm and ivm[c] and ivm[c] > 0]
        if len(pts) < 2: return ("hv", hv_6m(code))     # 期权 IV 缺失 → HV 兜底
        pts.sort(); xs = np.array([p[0] for p in pts]); ys = np.array([p[1] for p in pts])
        return ("opt", round(float(np.interp(MONEYNESS, xs, ys)), 1))

    wb = openpyxl.load_workbook(XLSX); ws = wb.active
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    ti = _pick_col(headers, ["代码", "ticker", "code", "symbol", "名称"])
    vi = _pick_col(headers, ["iv", "波动", "vol"])
    if ti is None: raise SystemExit(f"找不到代码列, 表头={headers}")
    if vi is None:                                       # 没有 IV 列 → 末尾新建
        vi = ws.max_column; ws.cell(1, vi + 1).value = "IV"
    uniq = {}
    for i in range(2, ws.max_row + 1):
        v = ws.cell(i, ti + 1).value
        if v is None: continue
        code, raw = _to_code(v); uniq.setdefault(code, raw)
    print(f"唯一标的 {len(uniq)} 个，开始取 {int(MONEYNESS*100)}% 档 6M IV…\n")

    res = {}
    for attempt in range(2):                            # 失败标的重试一轮
        todo = [c for c in uniq if uniq[c] not in res]
        if not todo: break
        if attempt: print(f"\n重试 {len(todo)} 个失败标的…")
        for code in todo:
            src, iv = iv90(code)
            if iv is not None: res[uniq[code]] = iv
            print(f"  {code:<11}{('IV90=' + str(iv)) if iv is not None else '失败':<11}{src}")
            time.sleep(0.4)

    n = 0
    for i in range(2, ws.max_row + 1):
        v = ws.cell(i, ti + 1).value
        if v is None: continue
        _, raw = _to_code(v)
        if raw in res: ws.cell(i, vi + 1).value = res[raw]; n += 1
    wb.save(XLSX)
    miss = [uniq[c] for c in uniq if uniq[c] not in res]
    print(f"\n回填 {n} 行 IV → {XLSX}" + (f"  ⚠ 未取到: {miss}" if miss else ""))
    q.close()

if __name__ == "__main__":
    main()
