import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime, timedelta
import json
import os
import time  # 追加

# ------------------------------------------------------------------------------
# ページ基本設定
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="水島流 MTF スキャルピング & 自動売買シミュレーター",
    page_icon="⚡",
    layout="wide"
)

# 自動更新用の設定（サイドバー等に設置してもOK）
# 5分足のスキャルピングであれば、10秒〜30秒ごとの更新が現実的です
UPDATE_INTERVAL = 10 

# UIスタイルの最適化
st.markdown("""
<style>
    .stMetric {
        background-color: #1e222d;
        padding: 12px;
        border-radius: 8px;
        border: 1px solid #2a2e39;
    }
    .stMetric label, .stMetric [data-testid="stMetricValue"], .stMetric [data-testid="stMetricDelta"] {
        color: #f0f2f6 !important;
    }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# 0. 設定の保存・復元処理
# ------------------------------------------------------------------------------
SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "pair_symbol": "USDJPY=X",
    "htf_trend": "1H Uptrend (Buy Only)",
    "min_pip_target": 10.0,
    "stop_pips": 8.0,
    "trail_activation_pips": 5.0,
    "auto_trade": True,
    "enable_trail": True
}

if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, "r") as f:
            DEFAULT_SETTINGS.update(json.load(f))
    except Exception:
        pass

query_params = st.query_params

pair_options_keys = ["USDJPY=X", "EURUSD=X", "GBPJPY=X", "EURJPY=X"]
htf_options = ["1H Uptrend (Buy Only)", "1H Downtrend (Sell Only)", "1H Range Zone (No Trade)"]

init_pair = query_params.get("pair", DEFAULT_SETTINGS["pair_symbol"])
init_htf = query_params.get("htf", DEFAULT_SETTINGS["htf_trend"])
init_min_pip = float(query_params.get("min_pip", DEFAULT_SETTINGS["min_pip_target"]))
init_stop = float(query_params.get("stop", DEFAULT_SETTINGS["stop_pips"]))
init_trail_act = float(query_params.get("trail_act", DEFAULT_SETTINGS["trail_activation_pips"]))
init_auto = query_params.get("auto", str(DEFAULT_SETTINGS["auto_trade"])).lower() == "true"
init_trail = query_params.get("trail", str(DEFAULT_SETTINGS["enable_trail"])).lower() == "true"

# ------------------------------------------------------------------------------
# 1. サイドバー設定
# ------------------------------------------------------------------------------
st.sidebar.header("🌍 FXマーケット・銘柄設定")

pair_options = {
    "USDJPY=X": "USD/JPY (ドル円)",
    "EURUSD=X": "EUR/USD (ユーロドル)",
    "GBPJPY=X": "GBP/JPY (ポンド円)",
    "EURJPY=X": "EUR/JPY (ユーロ円)"
}

pair_index = pair_options_keys.index(init_pair) if init_pair in pair_options_keys else 0
pair_symbol = st.sidebar.selectbox(
    "通貨ペアを選択",
    options=list(pair_options.keys()),
    index=pair_index,
    format_func=lambda x: pair_options[x]
)

pip_value = 0.01 if "JPY" in pair_symbol else 0.0001

st.sidebar.markdown("---")
st.sidebar.header("⚙️ スキャルピング・パラメータ")

htf_index = htf_options.index(init_htf) if init_htf in htf_options else 0
htf_trend = st.sidebar.selectbox(
    "1H 上位足トレンド環境（環境認識）",
    htf_options,
    index=htf_index
)

min_pip_target = st.sidebar.slider("10 pips 値幅フィルター (Pips)", 3.0, 25.0, init_min_pip, 0.5)
stop_pips = st.sidebar.number_input("初期損切り幅 (SL pips)", value=init_stop, step=1.0)
trail_activation_pips = st.sidebar.number_input("建値トレール発動幅 (pips)", value=init_trail_act, step=1.0)

st.sidebar.markdown("---")
st.sidebar.header("🤖 自動売買 (Auto-Trader)")
auto_trade = st.sidebar.toggle("自動売買エンジン", value=init_auto)
enable_trail = st.sidebar.toggle("建値トレールストップ機能", value=init_trail)

# チャート表示オプション
st.sidebar.markdown("---")
st.sidebar.header("📊 チャートの表示項目調整")
show_ema20 = st.sidebar.checkbox("5M EMA(20) [移動平均線]", value=True)
show_trendlines = st.sidebar.checkbox("高値・安値サポート・レジスタンス", value=True)
show_rsi_band = st.sidebar.checkbox("RSI状態を背景透過カラー表示", value=True)
show_history_trades = st.sidebar.checkbox("過去トレード履歴ライン", value=False)
show_trading_lines = st.sidebar.checkbox("エントリー/TP/SL ライン", value=True)

st.query_params.update({
    "pair": pair_symbol,
    "htf": htf_trend,
    "min_pip": min_pip_target,
    "stop": stop_pips,
    "trail_act": trail_activation_pips,
    "auto": auto_trade,
    "trail": enable_trail
})

if st.sidebar.button("💾 現在の設定を保存", use_container_width=True):
    current_settings = {
        "pair_symbol": pair_symbol, "htf_trend": htf_trend,
        "min_pip_target": min_pip_target, "stop_pips": stop_pips,
        "trail_activation_pips": trail_activation_pips, "auto_trade": auto_trade,
        "enable_trail": enable_trail
    }
    with open(SETTINGS_FILE, "w") as f:
        json.dump(current_settings, f, indent=4)
    st.sidebar.success("保存完了")

# ------------------------------------------------------------------------------
# 2. 為替データ取得 (キャッシュ時間を短縮)
# ------------------------------------------------------------------------------
@st.cache_data(ttl=10)  # 更新頻度に合わせてTTLを10秒に短縮
def load_market_data(symbol):
    is_simulated = False
    try:
        df = yf.download(tickers=symbol, period="5d", interval="5m", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        if df.empty or len(df) < 20:
            raise ValueError()
    except Exception:
        is_simulated = True
        # シミュレーションデータが毎回ランダムに動くよう、シード値に現在の「分」を混ぜるなどの工夫
        np.random.seed(int(time.time()) % 1000)
        periods = 80
        base_price = 155.00 if "JPY" in symbol else 1.0850
        times = [datetime.now() - timedelta(minutes=5 * (periods - i)) for i in range(periods)]
        step = 0.03 if "JPY" in symbol else 0.0003
        changes = np.random.normal(step * 0.1, step, periods)
        prices = base_price + np.cumsum(changes)
        
        df = pd.DataFrame({
            "Datetime": times,
            "Open": prices - changes / 2,
            "High": prices + np.abs(np.random.normal(step * 0.5, step * 0.3, periods)),
            "Low": prices - np.abs(np.random.normal(step * 0.5, step * 0.3, periods)),
            "Close": prices
        })
    
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()

    # RSI (14)
    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=1).mean()
    rs = gain / (loss + 1e-10)
    df["RSI"] = 100 - (100 / (1 + rs))

    return df, is_simulated

df, is_simulated_data = load_market_data(pair_symbol)

# ------------------------------------------------------------------------------
# 3. ロジック判定エンジン
# ------------------------------------------------------------------------------
current_price = float(df["Close"].iloc[-1])
recent_high = float(df["High"].iloc[-20:-1].max())
recent_low = float(df["Low"].iloc[-20:-1].min())

buy_target_pips = round((recent_high - current_price) / pip_value, 1)
sell_target_pips = round((current_price - recent_low) / pip_value, 1)

recent_5m_high = float(df["High"].iloc[-6:-1].max())
recent_5m_low = float(df["Low"].iloc[-6:-1].min())

htf_pass = "Uptrend" in htf_trend or "Downtrend" in htf_trend
breakout_pass = (current_price >= recent_5m_high) if "Uptrend" in htf_trend else (current_price <= recent_5m_low)
target_pass = (buy_target_pips >= min_pip_target) if "Uptrend" in htf_trend else (sell_target_pips >= min_pip_target)

signal = "NONE"
if htf_pass and breakout_pass and target_pass:
    signal = "BUY" if "Uptrend" in htf_trend else "SELL"

# ------------------------------------------------------------------------------
# 4. ヘッダー表示
# ------------------------------------------------------------------------------
st.title("⚡ 水島流 MTF スキャルピング & 自動売買シミュレーター")

# 最終更新時刻を表示して、動いているか視認できるようにする
st.caption(f"最終更新日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ( {UPDATE_INTERVAL}秒ごとに自動更新中 )")

if is_simulated_data:
    st.info("💡 市場休場中または取得制限のため、シミュレーション用チャートを表示しています。")

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("通貨ペア", pair_symbol.replace("=X", ""))
k2.metric("現在価格", f"{current_price:.3f}" if "JPY" in pair_symbol else f"{current_price:.5f}")
k3.metric("狙える値幅 (TP)", f"{buy_target_pips if 'Uptrend' in htf_trend else sell_target_pips} pips")
k4.metric("自動売買", "稼働中" if auto_trade else "停止中")
k5.metric("シグナル", signal)

st.markdown("---")

# ------------------------------------------------------------------------------
# 5. チャート描画
# ------------------------------------------------------------------------------
col_chart, col_logic = st.columns([3.2, 1])

time_col = "Datetime" if "Datetime" in df.columns else df.columns[0]
trade_history_data = [
    {"日時": "2026-07-24 18:35", "銘柄": "USD/JPY", "种別": "BUY", "エントリー価格": 155.120, "決済価格": 155.240, "獲得Pips": "+12.0 pips", "損益 ($)": "+$120.00"},
    {"日時": "2026-07-24 14:25", "銘柄": "EUR/USD", "种別": "SELL", "エントリー価格": 1.08650, "決済価格": 1.08510, "獲得Pips": "+14.0 pips", "損益 ($)": "+$140.00"}
]

with col_logic:
    st.subheader("🔍 条件チェック")
    st.write("**1. 上位足トレンド**", "✅ クリア" if htf_pass else "❌ ミスマッチ")
    st.write("**2. 直近高安ブレイク**", "✅ 発生" if breakout_pass else "⏳ 待機中")
    st.write(f"**3. {min_pip_target}pips値幅**", "✅ 確保" if target_pass else "❌ 不足")
    st.markdown("---")
    st.write("**ポジション見通し**")
    fmt = ".3f" if "JPY" in pair_symbol else ".5f"
    if signal != "NONE" and auto_trade:
        st.success(f"⚡ **{signal} 約定**\n現在価格: {current_price:{fmt}}")
    else:
        planned = recent_5m_high if "Uptrend" in htf_trend else recent_5m_low
        st.info(f"⏳ **ブレイク待機**\n予定位置: {planned:{fmt}}")

with col_chart:
    st.subheader(f"📈 5分足メインチャート ({pair_symbol.replace('=X', '')})")
    
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df[time_col], open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"], name="価格",
        increasing_line_color="#00E676", decreasing_line_color="#FF5252"
    ))

    if show_ema20:
        fig.add_trace(go.Scatter(
            x=df[time_col], y=df["EMA20"],
            line=dict(color="#2962FF", width=2), name="EMA(20)"
        ))

    if show_trendlines:
        fig.add_hline(y=recent_high, line_dash="dash", line_color="#FF4081", line_width=1, annotation_text="直近高値")
        fig.add_hline(y=recent_low, line_dash="dash", line_color="#00E5FF", line_width=1, annotation_text="直近安値")

    if show_rsi_band:
        last_rsi = float(df["RSI"].iloc[-1])
        if last_rsi >= 70:
            fig.add_vrect(x0=df[time_col].iloc[-10], x1=df[time_col].iloc[-1],
                          fillcolor="rgba(255, 82, 82, 0.15)", line_width=0,
                          annotation_text="RSI 買われすぎ", annotation_position="top left")
        elif last_rsi <= 30:
            fig.add_vrect(x0=df[time_col].iloc[-10], x1=df[time_col].iloc[-1],
                          fillcolor="rgba(0, 230, 118, 0.15)", line_width=0,
                          annotation_text="RSI 売られすぎ", annotation_position="bottom left")

    price_fmt = ".3f" if "JPY" in pair_symbol else ".5f"
    if show_history_trades:
        for t in trade_history_data:
            if ("JPY" in pair_symbol and "JPY" in t["銘柄"]) or ("USD" in pair_symbol and "USD" in t["銘柄"]):
                fig.add_hline(y=float(t["エントリー価格"]), line_dash="dot", line_color="#80D8FF", line_width=1)
                fig.add_hline(y=float(t["決済価格"]), line_dash="dot", line_color="#00E676", line_width=1)

    if show_trading_lines:
        if signal == "BUY":
            fig.add_hline(y=current_price, line_color="#00B0FF", line_width=2, annotation_text=f"BUY ENTRY: {current_price:{price_fmt}}")
            fig.add_hline(y=recent_high, line_dash="longdash", line_color="#00E676", line_width=1.5, annotation_text="TP (利確)")
            fig.add_hline(y=current_price - stop_pips * pip_value, line_dash="longdash", line_color="#FF5252", line_width=1.5, annotation_text="SL (損切)")
        elif signal == "SELL":
            fig.add_hline(y=current_price, line_color="#00B0FF", line_width=2, annotation_text=f"SELL ENTRY: {current_price:{price_fmt}}")
            fig.add_hline(y=recent_low, line_dash="longdash", line_color="#00E676", line_width=1.5, annotation_text="TP (利確)")
            fig.add_hline(y=current_price + stop_pips * pip_value, line_dash="longdash", line_color="#FF5252", line_width=1.5, annotation_text="SL (損切)")
        else:
            planned = recent_5m_high if "Uptrend" in htf_trend else recent_5m_low
            fig.add_hline(y=planned, line_dash="dashdot", line_color="#FFD600", line_width=1.5, annotation_text=f"PLANNED ENTRY: {planned:{price_fmt}}")

    fig.update_layout(
        height=560, xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=10, b=10), template="plotly_dark",
        paper_bgcolor="#131722", plot_bgcolor="#131722",
        yaxis=dict(title="Price", side="right", showgrid=True, gridcolor="#2a2e39"),
        xaxis=dict(showgrid=True, gridcolor="#2a2e39")
    )
    st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------------------
# 6. 約定履歴テーブル
# ------------------------------------------------------------------------------
st.subheader("📋 トレード実行ログ")
st.dataframe(pd.DataFrame(trade_history_data), use_container_width=True)

# ------------------------------------------------------------------------------
# 7. ★自動更新エンジン (ここを追加)
# ------------------------------------------------------------------------------
time.sleep(UPDATE_INTERVAL)
st.rerun()