# -*- coding: utf-8 -*-
"""
FCN 单标的·执行价/敲入价/票息 建议器
====================================================================
结构（已与老板确认）:
  - 单标的、6 个月、欧式敲入（仅到期日观察）
  - 敲入价 = 执行价 − 10 个百分点  (Strike 80% → KI 70%)
  - 票息为年化
  - IV 取"对应执行价档"的隐含波动率（skew 点，如 80% 执行价用 80% spot 的 IV）

方法（两层）:
  第1层 结构定价器: 用给定 IV 算内嵌 down-and-in put 的理论价值 V(占名义%),
                     折算 "理论年化票息" = V / 期限(年)。
  第2层 标定:        用交易台真实报价拟合  台报票息 = α × 理论票息 + β。
                     α 吸收交易台加价, β 吸收资金/借券。

用法:
  1) 把交易台数据填进 desk_quotes.csv（格式见 desk_quotes_template.csv），
     或直接改本文件底部 SAMPLE_QUOTES。
  2) python strike_coupon_advisor.py
     → 打印标定系数、拟合优度(R²)、逐档残差；
       并演示 反解: 给目标票息区间 → 建议执行价/敲入价/预期票息。

依赖: numpy (已在 requirements.txt)。norm CDF 用 math.erf 实现, 不需 scipy。
"""
import csv, math, os, sys
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")   # Windows 控制台默认 GBK, 强制 UTF-8
except Exception:
    pass

_DIR = os.path.dirname(os.path.abspath(__file__))

# ── 市场默认无风险利率 / 分红率（拿不到就用默认, 会被 α,β 吸收）──────────
MARKET_RATE = {"US": 0.043, "HK": 0.045}   # 年化无风险利率(粗略)
DEFAULT_Q   = 0.0                            # 分红率, 有数据可逐名覆盖
TENOR_Y     = 0.5                            # 6 个月
KI_OFFSET   = 10.0                           # 敲入价 = 执行价 − 10(百分点)

def _N(x):
    """标准正态 CDF"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def di_put_value(strike_pct, iv_pct, T=TENOR_Y, r=0.043, q=DEFAULT_Q):
    """
    内嵌欧式 down-and-in put 的理论价值 V（占名义的比例, 0~1）。
    初始价归一为 1。执行价 k、敲入 b = k − 10%。
    到期损失(触发时) = (k − S_T)/k = 1 − S_T/k, 仅当 S_T < b。
    V = e^{-rT} N(-d2(b)) − (1/k) e^{-qT} N(-d1(b))
    """
    k = strike_pct / 100.0
    b = (strike_pct - KI_OFFSET) / 100.0
    sig = iv_pct / 100.0
    if b <= 0 or sig <= 0:
        return 0.0
    srt = sig * math.sqrt(T)
    d2 = (-math.log(b) + (r - q - 0.5 * sig * sig) * T) / srt
    d1 = d2 + srt
    V = math.exp(-r * T) * _N(-d2) - (1.0 / k) * math.exp(-q * T) * _N(-d1)
    return max(V, 0.0)

def theo_coupon(strike_pct, iv_pct, market="US", q=DEFAULT_Q):
    """理论年化票息(%) = V / 期限。作为标定回归的自变量。"""
    r = MARKET_RATE.get(market, 0.043)
    V = di_put_value(strike_pct, iv_pct, TENOR_Y, r, q)
    return (V / TENOR_Y) * 100.0

# ── 标定 ─────────────────────────────────────────────────────────────────
def calibrate(quotes):
    """
    quotes: list of dict, 每档一条:
        ticker, market, strike_pct, iv_pct, coupon_pa   (敲入价=执行价-10, 隐含)
    拟合 coupon_pa ≈ α * theo_coupon + β  (最小二乘)。
    返回 (alpha, beta, r2, rows) ; rows 含每档 理论/实际/拟合/残差。
    """
    x = np.array([theo_coupon(q["strike_pct"], q["iv_pct"], q["market"]) for q in quotes])
    y = np.array([q["coupon_pa"] for q in quotes])
    A = np.column_stack([x, np.ones_like(x)])
    (alpha, beta), *_ = np.linalg.lstsq(A, y, rcond=None)
    yhat = alpha * x + beta
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    rows = []
    for q, xi, yi, yh in zip(quotes, x, y, yhat):
        rows.append({**q, "theo": xi, "fit": yh, "resid": yi - yh})
    return alpha, beta, r2, rows

def coupon_hat(strike_pct, iv_pct, alpha, beta, market="US", q=DEFAULT_Q):
    """标定后的预测票息(%)"""
    return alpha * theo_coupon(strike_pct, iv_pct, market, q) + beta

# ── 反解: 给目标票息区间 → 建议执行价 ────────────────────────────────────
def suggest_strike(iv_at_strike, alpha, beta, target_lo, target_hi,
                   market="US", q=DEFAULT_Q, k_min=50.0, k_max=95.0):
    """
    iv_at_strike: 函数 k(%) → 该执行价档的 IV(%)。(不同执行价 IV 不同, 需 skew)
    目标: 找 k 使 预测票息 落在 [target_lo, target_hi], 取中值优先。
    票息随执行价单调递增 → 二分。
    返回 dict: 建议执行价/敲入价/预期票息, 及可行性标记。
    """
    target_mid = 0.5 * (target_lo + target_hi)
    def f(k):
        return coupon_hat(k, iv_at_strike(k), alpha, beta, market, q) - target_mid
    lo_c = coupon_hat(k_min, iv_at_strike(k_min), alpha, beta, market, q)
    hi_c = coupon_hat(k_max, iv_at_strike(k_max), alpha, beta, market, q)
    # 单调递增: k_max 给最高票息
    if hi_c < target_lo:
        return {"feasible": False, "reason": f"连 {k_max:.0f}% 执行价票息仅 {hi_c:.1f}%, 达不到目标下限 {target_lo:.0f}%",
                "max_coupon": hi_c}
    if lo_c > target_hi:
        return {"feasible": False, "reason": f"连 {k_min:.0f}% 执行价票息已 {lo_c:.1f}%, 超过目标上限 {target_hi:.0f}%",
                "min_coupon": lo_c}
    a, b = k_min, k_max
    for _ in range(60):
        m = 0.5 * (a + b)
        if f(m) > 0: b = m
        else:        a = m
    k = 0.5 * (a + b)
    cpn = coupon_hat(k, iv_at_strike(k), alpha, beta, market, q)
    return {"feasible": True, "strike_pct": round(k, 1), "ki_pct": round(k - KI_OFFSET, 1),
            "coupon_pa": round(cpn, 1)}

def load_quotes(path):
    """读 desk_quotes.csv。列: ticker,market,strike_pct,iv_pct,coupon_pa (其余列忽略)"""
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if not row.get("ticker"): continue
            out.append({"ticker": row["ticker"].strip(),
                        "market": (row.get("market") or "US").strip().upper(),
                        "strike_pct": float(row["strike_pct"]),
                        "iv_pct": float(row["iv_pct"]),
                        "coupon_pa": float(row["coupon_pa"])})
    return out

# ── 示例数据（合成, 仅为跑通演示; 请用真实交易台数据替换）────────────────
# 每标的三档: 执行价 90/80/70%, 对应该档 IV, 及台报年化票息。
SAMPLE_QUOTES = [
    # 低波类蓝筹（IV 较低）
    {"ticker":"AAPL","market":"US","strike_pct":90,"iv_pct":30,"coupon_pa":16.0},
    {"ticker":"AAPL","market":"US","strike_pct":80,"iv_pct":32,"coupon_pa":10.5},
    {"ticker":"AAPL","market":"US","strike_pct":70,"iv_pct":35,"coupon_pa": 6.8},
    {"ticker":"MSFT","market":"US","strike_pct":90,"iv_pct":28,"coupon_pa":14.5},
    {"ticker":"MSFT","market":"US","strike_pct":80,"iv_pct":30,"coupon_pa": 9.3},
    {"ticker":"MSFT","market":"US","strike_pct":70,"iv_pct":33,"coupon_pa": 5.9},
    # 高波类（IV 较高）
    {"ticker":"NVDA","market":"US","strike_pct":90,"iv_pct":52,"coupon_pa":29.0},
    {"ticker":"NVDA","market":"US","strike_pct":80,"iv_pct":55,"coupon_pa":20.0},
    {"ticker":"NVDA","market":"US","strike_pct":70,"iv_pct":58,"coupon_pa":13.5},
    {"ticker":"TSLA","market":"US","strike_pct":90,"iv_pct":58,"coupon_pa":33.0},
    {"ticker":"TSLA","market":"US","strike_pct":80,"iv_pct":61,"coupon_pa":23.0},
    {"ticker":"TSLA","market":"US","strike_pct":70,"iv_pct":64,"coupon_pa":15.5},
]

if __name__ == "__main__":
    qpath = os.path.join(_DIR, "desk_quotes.csv")
    quotes = load_quotes(qpath) if os.path.exists(qpath) else SAMPLE_QUOTES
    src = "desk_quotes.csv" if os.path.exists(qpath) else "SAMPLE_QUOTES(合成示例)"
    print(f"数据源: {src}  | 档数: {len(quotes)}\n")

    alpha, beta, r2, rows = calibrate(quotes)
    print(f"标定结果:  台报票息 ≈ {alpha:.3f} × 理论票息 + {beta:.2f}   R² = {r2:.3f}")
    print(f"  (α={alpha:.3f} 即票息透传率; β={beta:.2f}% 约资金/借券截距)\n")
    print(f"{'标的':<6}{'执行价%':>7}{'IV%':>6}{'台报':>8}{'拟合':>8}{'残差':>8}")
    for r in rows:
        print(f"{r['ticker']:<6}{r['strike_pct']:>7.0f}{r['iv_pct']:>6.0f}"
              f"{r['coupon_pa']:>8.1f}{r['fit']:>8.1f}{r['resid']:>8.1f}")

    print("\n── 反解演示: 给目标票息区间 → 建议执行价/敲入价 ──")
    # 用每个标的自己的 3 档 IV 线性插值出 skew 曲线
    by_name = {}
    for q in quotes:
        by_name.setdefault(q["ticker"], {"market": q["market"], "pts": []})
        by_name[q["ticker"]]["pts"].append((q["strike_pct"], q["iv_pct"]))
    def make_skew(pts):
        pts = sorted(pts)
        ks = [p[0] for p in pts]; vs = [p[1] for p in pts]
        return lambda k: float(np.interp(k, ks, vs))
    # 低波精选目标 15-20%, 高波精选目标 18-30%
    targets = {"AAPL":(15,20),"MSFT":(15,20),"NVDA":(18,30),"TSLA":(18,30)}
    for name,(lo,hi) in targets.items():
        info = by_name[name]
        skew = make_skew(info["pts"])
        res = suggest_strike(skew, alpha, beta, lo, hi, info["market"])
        band = f"目标{lo}-{hi}%"
        if res["feasible"]:
            print(f"  {name:<6}{band:<11} → 执行价 {res['strike_pct']:.1f}% / "
                  f"敲入 {res['ki_pct']:.1f}% / 预期票息 {res['coupon_pa']:.1f}%")
        else:
            print(f"  {name:<6}{band:<11} → 不可行: {res['reason']}")
