# -*- coding: utf-8 -*-
"""
反解流程: 读 IV及票息.xlsx → 标定模型 → 按 IV 自动分组 → 反解每只票的
          建议执行价/敲入价/预期票息 → 写入新工作表「AI建议」(每票一行)。

分组规则(可调): IV(90%档) >= HIGH_VOL_IV_CUT → 高波精选(目标 18-30%)
                           <  HIGH_VOL_IV_CUT → 低波精选(目标 15-20%)
执行价搜索区间: [K_MIN, K_MAX]; 敲入价 = 执行价 - 10。
标定来自 desk_quotes.csv (48 点), 每次运行重新拟合 α,β。
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, openpyxl
from strike_coupon_advisor import load_quotes, calibrate, suggest_strike, coupon_hat

_DIR = os.path.dirname(os.path.abspath(__file__))
XLSX = r"C:\Users\liy22223\Desktop\IV及票息.xlsx"

HIGH_VOL_IV_CUT = 70.0                 # IV(90%) 分组阈值(仅无组别标签时的兜底)
TARGET = {"低波精选": (15, 20), "高波精选": (18, 30), "市场热度型": (25, 40)}
# 名单里可能出现的组别简写 → 标准组名
GROUP_ALIAS = {"低波": "低波精选", "低波精选": "低波精选",
               "高波": "高波精选", "高波精选": "高波精选",
               "热度": "市场热度型", "热度榜": "市场热度型", "市场热度型": "市场热度型",
               "热门": "市场热度型", "热门榜单": "市场热度型"}
K_MIN, K_MAX = 50.0, 95.0              # 执行价下限 50 / 上限 95

def build_skews_from_xlsx(path):
    """从 Excel 读每票的 (执行价% -> IV%) 点, 返回 {code: {'market','spot_iv90','skew'}}。"""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Sheet1"]
    pts = {}
    for i in range(2, ws.max_row + 1):
        tk = ws.cell(i, 2).value
        if not tk: continue
        sym = tk.split()[0]
        kf = ws.cell(i, 3).value      # 执行价 0.9/0.8/...
        iv = ws.cell(i, 8).value      # IV 列(小数)
        if kf is None or iv is None: continue
        pts.setdefault(sym, []).append((kf * 100, iv * 100))
    out = {}
    for sym, ps in pts.items():
        ps.sort()
        xs = np.array([p[0] for p in ps]); ys = np.array([p[1] for p in ps])
        skew = (lambda xs, ys: (lambda k: float(np.interp(k, xs, ys))))(xs, ys)
        out[sym] = {"market": "US", "iv90": skew(90.0), "skew": skew}
    return out

# ── 按 IV 绝对水平定票息目标(老板新规则, 不靠榜单) ──────────────────────
def target_for_iv(iv):
    """返回 ((票息lo,票息hi), 标签)。IV 30-70→15-25%; 70-100→25-30%。"""
    if iv < 30:  return None, "IV<30(超范围)"
    if iv < 70:  return (15, 25), "IV 30-70"
    if iv <= 100: return (25, 30), "IV 70-100"
    return (25, 30), "IV>100(按70-100处理)"

STRIKE_CAP = 85.0   # 中值倒推的执行价高于此 → 改以票息下限定价, 避免推荐过薄缓冲

def solve_for_coupon(target, iv, alpha, beta, market="US"):
    """在 [K_MIN,K_MAX] 内二分, 求票息=target% 的执行价; 越界钳到边界。"""
    lo_c = coupon_hat(K_MIN, iv, alpha, beta, market)
    hi_c = coupon_hat(K_MAX, iv, alpha, beta, market)
    if target >= hi_c: return K_MAX
    if target <= lo_c: return K_MIN
    a, b = K_MIN, K_MAX
    for _ in range(60):
        m = (a + b) / 2
        if coupon_hat(m, iv, alpha, beta, market) < target: a = m
        else: b = m
    return (a + b) / 2

def solve_band(iv, alpha, beta, lo, hi, market="US"):
    lo_c = coupon_hat(K_MIN, iv, alpha, beta, market)   # 50%档票息(最低)
    if lo_c > hi:                                       # 连50%都超上限 → 太烫, 挂最深
        return 50, 40, f"超上限默认50/40（50%执行价票息已{lo_c:.1f}%）"
    k = solve_for_coupon((lo + hi) / 2, iv, alpha, beta, market)   # 先取区间中值
    note = ""
    if k > STRIKE_CAP:                                  # 高于85 → 改以票息下限倒推
        k = solve_for_coupon(lo, iv, alpha, beta, market)
        note = f"执行价>{STRIKE_CAP:.0f}%，改以票息下限{lo:.0f}%定价"
    if k > STRIKE_CAP:                                  # 仍高于85 → 硬顶 85, 票息随行
        c = coupon_hat(STRIKE_CAP, iv, alpha, beta, market)
        k, note = STRIKE_CAP, f"执行价硬顶{STRIKE_CAP:.0f}%（票息约{c:.1f}%，低于下限{lo:.0f}%）"
    s = int(round(k))
    return s, s - 10, note

def advise_by_iv(path):
    """按唯一标的 + IV 分档反解执行价/敲入价(不分榜单)。"""
    alpha, beta = load_calib()
    seen = {}
    for rec in read_list(path):
        t = rec["ticker"].upper()
        seen.setdefault(t, rec["iv"])          # 同一标的取一次
    rows = []
    for t, iv in sorted(seen.items(), key=lambda kv: kv[1]):
        band, lbl = target_for_iv(iv)
        mk = "HK" if t.isdigit() else "US"
        if band is None:
            rows.append([t, iv, lbl, "跳过", "", "IV 超出设定范围"]); continue
        lo, hi = band
        strike, ki, reason = solve_band(iv, alpha, beta, lo, hi, mk)
        rows.append([t, iv, f"{lo}-{hi}%", strike, ki, reason])
    print(f"{'代码':<8}{'IV':>6}{'目标票息':>10}{'执行价':>8}{'敲入价':>8}")
    for r in rows:
        sp = f"{r[3]}%" if isinstance(r[3], (int, float)) else r[3]
        kp = f"{r[4]}%" if isinstance(r[4], (int, float)) else r[4]
        print(f"{r[0]:<8}{r[1]:>6.0f}{r[2]:>10}{sp:>8}{kp:>8}" + (f"  ({r[5]})" if r[5] else ""))
    import csv as _c
    for out in [os.path.join(_DIR, "建议结构.csv"),
                os.path.join(_DIR, "建议结构_new.csv")]:
        try:
            with open(out, "w", newline="", encoding="utf-8-sig") as f:
                w = _c.writer(f)
                w.writerow(["代码", "IV", "目标票息", "建议执行价%", "建议敲入价%", "备注"])
                w.writerows(rows)
            print(f"\n已输出 → {out}（按 IV 分档，每标的一行）")
            return
        except PermissionError:
            print(f"（{os.path.basename(out)} 被占用，改写备用名…）")
    print("写出失败：请关闭已打开的 建议结构.csv 后重跑。")

def solve(group, iv_func, alpha, beta, market="US"):
    """给组别 + IV(可为常数flat skew) → (执行价整数, 敲入价整数) 或 ('不可行','')。"""
    lo, hi = TARGET[group]
    res = suggest_strike(iv_func, alpha, beta, lo, hi, market, k_min=K_MIN, k_max=K_MAX)
    if not res["feasible"]:
        return "不可行", "", res["reason"]
    strike = int(round(res["strike_pct"]))
    return strike, strike - 10, ""       # 敲入价 = 执行价 - 10

def load_calib():
    a, b, r2, _ = calibrate(load_quotes(os.path.join(_DIR, "desk_quotes.csv")))
    print(f"标定: 票息 ≈ {a:.3f}×理论 + {b:.2f}   R²={r2:.3f}   (执行价区间 {K_MIN:.0f}-{K_MAX:.0f}%)\n")
    return a, b

# ── go-forward 正式入口: 读名单(组别+代码+IV) → 输出执行价/敲入价 ──────────
def _pick_col(headers, keys):
    """按关键词在表头里找列索引(0-based)。"""
    for i, h in enumerate(headers):
        hs = str(h or "").strip().lower()
        if any(k in hs for k in keys): return i
    return None

def read_list(path):
    """读名单, 支持 .csv / .xlsx; 自动按表头识别 组别/代码/IV 三列。
    返回 [{'group','ticker','iv'}]。IV 兼容小数(0.42)与百分数(42)。"""
    if path.lower().endswith((".xlsx", ".xlsm")):
        wb = openpyxl.load_workbook(path, data_only=True); ws = wb.active
        rowvals = list(ws.iter_rows(values_only=True))
        headers = rowvals[0]; body = rowvals[1:]
    else:
        import csv
        with open(path, encoding="utf-8-sig") as f:
            rowvals = [r for r in csv.reader(f)]
        headers = rowvals[0]; body = rowvals[1:]
    gi = _pick_col(headers, ["组", "榜", "group", "类型"])
    ti = _pick_col(headers, ["代码", "ticker", "symbol", "code", "名称"])
    vi = _pick_col(headers, ["iv", "波动", "vol"])
    if None in (gi, ti, vi):
        raise SystemExit(f"名单缺列: 需要 组别/代码/IV 三列, 实际表头={headers}")
    out = []
    for r in body:
        if not r or ti >= len(r) or not r[ti]: continue
        iv = float(r[vi])
        if iv <= 1.5: iv *= 100          # 兼容 0.42 → 42
        out.append({"group": str(r[gi]).strip(), "ticker": str(r[ti]).strip(), "iv": iv})
    return out

def advise_from_list(path):
    """名单(组别+代码+IV, csv/xlsx) → 建议执行价/敲入价。IV 为单一锚定值。"""
    alpha, beta = load_calib()
    rows = []
    for rec in read_list(path):
        grp = GROUP_ALIAS.get(rec["group"])
        if grp is None:
            print(f"跳过 {rec['ticker']}: 未知组别 {rec['group']}"); continue
        iv = rec["iv"]
        strike, ki, reason = solve(grp, lambda k: iv, alpha, beta)  # flat skew
        rows.append([rec["ticker"].upper(), grp, iv, strike, ki, reason])
    print(f"{'代码':<8}{'组别':<9}{'IV':>6}{'执行价':>9}{'敲入价':>9}")
    for r in rows:
        sp = f"{r[3]}%" if isinstance(r[3], (int, float)) else r[3]
        kp = f"{r[4]}%" if isinstance(r[4], (int, float)) else r[4]
        print(f"{r[0]:<8}{r[1]:<9}{r[2]:>6.0f}{sp:>9}{kp:>9}" + (f"  ({r[5]})" if r[5] else ""))
    out = os.path.join(_DIR, "建议结构.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        import csv as _c; w = _c.writer(f)
        w.writerow(["代码", "组别", "IV", "建议执行价%", "建议敲入价%", "备注"])
        w.writerows(rows)
    print(f"\n已输出 → {out}（可直接把执行价/敲入价填进三个入选榜单 Excel）")

# ── 演示入口: 读 IV及票息.xlsx(4档IV, 按IV阈值兜底分组) ───────────────────
def demo_from_xlsx():
    alpha, beta = load_calib()
    names = build_skews_from_xlsx(XLSX)
    rows = []
    for sym, info in sorted(names.items(), key=lambda kv: kv[1]["iv90"]):
        grp = "高波精选" if info["iv90"] >= HIGH_VOL_IV_CUT else "低波精选"
        strike, ki, _ = solve(grp, info["skew"], alpha, beta, info["market"])
        rows.append([sym, grp, round(info["iv90"], 1), strike, ki])
    print(f"{'标的':<7}{'组别':<9}{'IV90':>6}{'建议执行价':>10}{'建议敲入价':>10}")
    for r in rows:
        sp = f"{r[3]}%" if isinstance(r[3], (int, float)) else r[3]
        kp = f"{r[4]}%" if isinstance(r[4], (int, float)) else r[4]
        print(f"{r[0]:<7}{r[1]:<9}{r[2]:>6}{sp:>10}{kp:>10}")
    wb = openpyxl.load_workbook(XLSX)
    if "AI建议" in wb.sheetnames: del wb["AI建议"]
    ws = wb.create_sheet("AI建议")
    ws.append(["代码", "组别(按IV自动)", "IV(90%档)%", "建议执行价%", "建议敲入价%"])
    for r in rows: ws.append(r)
    wb.save(XLSX)
    print(f"\n已写入工作表「AI建议」→ {XLSX}")

if __name__ == "__main__":
    import glob
    cand = ([os.path.join(_DIR, "lists_input.xlsx")] +
            sorted(glob.glob(os.path.join(_DIR, "lists_input.csv"))))
    lst = next((p for p in cand if os.path.exists(p)), None)
    if lst:
        advise_by_iv(lst)           # 有名单 → 按 IV 分档反解(老板新规则)
    else:
        demo_from_xlsx()            # 否则 → 演示模式
