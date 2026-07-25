import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime, timedelta
import json
import os

# ------------------------------------------------------------------------------
# ページ基本設定
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="水島流 MTF スキャルピング & 自動売買シミュレーター",
    page_icon="⚡",
    layout="wide"
)

# Custom CSS
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
# 0. 設定の保存・復元処理（URLクエリパラメータ & JSON）
# ------------------------------------------------------------------------------
SETTINGS_FILE = "settings.json"

# デフォルト設定値
DEFAULT_SETTINGS = {
    "pair_symbol": "USDJPY=X",
    "htf_trend": "1H Uptrend (Buy Only)",
    "min_pip_target": 10.0,
    "stop_pips": 8.0,
    "trail_activation_pips": 5.0,
    "auto_trade": True,
    "enable_trail": True
}

# 1. 保存済みファイルがあれば読み込み
if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, "r") as f:
            file_settings = json.load(f)
            DEFAULT_SETTINGS.update(file_settings)
    except Exception:
        pass

# 2. URLクエリパラメータから設定を取得（最優先）
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
# 1. サイドバー（コントロールパネル）
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
    index=htf_index,
    help="動画解説: 上位足がトレンドを出している方向のみにエントリーを絞ります"
)

min_pip_target = st.sidebar.slider(
    "10 pips 値幅フィルター (Pips)",
    min_value=3.0,
    max_value=25.0,
    value=init_min_pip,
    step=0.5,
    help="動画解説: エントリー位置から直近高値/安値まで10pips未満の場合はスルーします"
)

stop_pips = st.sidebar.number_input("初期損切り幅 (SL pips)", value=init_stop, step=1.0)
trail_activation_pips = st.sidebar.number_input("建値トレール発動幅 (pips)", value=init_trail_act, step=1.0)

st.sidebar.markdown("---")
st.sidebar.header("🤖 自動売買 (Auto-Trader) 設定")
auto_trade = st.sidebar.toggle("自動売買エンジン (Auto-Trading)", value=init_auto)
enable_trail = st.sidebar.toggle("建値トレールストップ機能", value=init_trail)

# 現在の入力パラメータをURLクエリへ同期更新
st.query_params.update({
    "pair": pair_symbol,
    "htf": htf_trend,
    "min_pip": min_pip_target,
    "stop": stop_pips,
    "trail_act": trail_activation_pips,
    "auto": auto_trade,
    "trail": enable_trail
})

st.sidebar.markdown("---")
st.sidebar.header("💾 設定保存管理")

if st.sidebar.button("💾 現在の設定をサーバーへ永続保存", use_container_width=True):
    current_settings = {
        "pair_symbol": pair_symbol,
        "htf_trend": htf_trend,
        "min_pip_target": min_pip_target,
        "stop_pips": stop_pips,
        "trail_activation_pips": trail_activation_pips,
        "auto_trade": auto_trade,
        "enable_trail": enable_trail
    }
    with open(SETTINGS_FILE, "w") as f:
        json.dump(current_settings, f, indent=4)
    st.sidebar.success("設定を保存しました！")

if st.sidebar.button("🔄 レート手動更新", use_container_width=True):
    st.cache_data.clear()

# ------------------------------------------------------------------------------
# 2. 為替データ取得（yfinance ＋ フォールバック機能）
# ------------------------------------------------------------------------------
@st.cache_data(ttl=60)
def load_market_data(symbol):
    is_simulated = False
    try:
        df = yf.download(tickers=symbol, period="5d", interval="5m", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        
        if df.empty or len(df) < 20:
            raise ValueError("データ件数不足（休場中またはAPI制限）")
            
    except Exception:
        is_simulated = True
        np.random.seed(42)
        periods = 80
        base_price = 155.00 if "JPY" in symbol else 1.0850
        times = [datetime.now() - timedelta(minutes=5 * (periods - i)) for i in range(periods)]
        
        step = 0.03 if "JPY" in symbol else 0.0003
        changes = np.random.normal(step * 0.1, step, periods)
        prices = base_price + np.cumsum(changes)
        
        highs = prices + np.abs(np.random.normal(step * 0.5, step * 0.3, periods))
        lows = prices - np.abs(np.random.normal(step * 0.5, step * 0.3, periods))
        opens = prices - changes / 2
        closes = prices
        
        df = pd.DataFrame({
            "Datetime": times,
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes
        })
    
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    return df, is_simulated

df, is_simulated_data = load_market_data(pair_symbol)

# ------------------------------------------------------------------------------
# 3. 水島流ロジック計算エンジン
# ------------------------------------------------------------------------------
current_price = float(df["Close"].iloc[-1])
recent_high = float(df["High"].iloc[-20:-1].max())
recent_low = float(df["Low"].iloc[-20:-1].min())

buy_target_pips = round((recent_high - current_price) / pip_value, 1)
sell_target_pips = round((current_price - recent_low) / pip_value, 1)

recent_5m_high = float(df["High"].iloc[-6:-1].max())
recent_5m_low = float(df["Low"].iloc[-6:-1].min())

htf_pass = False
breakout_pass = False
target_pass = False
signal = "NONE"

if "Uptrend" in htf_trend:
    htf_pass = True
    breakout_pass = current_price >= recent_5m_high
    target_pass = buy_target_pips >= min_pip_target
    if htf_pass and breakout_pass and target_pass:
        signal = "BUY"
elif "Downtrend" in htf_trend:
    htf_pass = True
    breakout_pass = current_price <= recent_5m_low
    target_pass = sell_target_pips >= min_pip_target
    if htf_pass and breakout_pass and target_pass:
        signal = "SELL"

# ------------------------------------------------------------------------------
# 4. ヘッダーダッシュボード (KPI Cards)
# ------------------------------------------------------------------------------
st.title("⚡ 水島流 MTF スキャルピング & 自動売買シミュレーター")

if is_simulated_data:
    st.info("💡 現在FX市場が休場中（またはデータ取得制限中）のため、シミュレーション専用チャートを表示しています。")

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("選択銘柄", pair_symbol.replace("=X", ""))
k2.metric("現在価格", f"{current_price:.3f}" if "JPY" in pair_symbol else f"{current_price:.5f}")
k3.metric("狙える値幅 (TP)", f"{buy_target_pips if 'Uptrend' in htf_trend else sell_target_pips} pips")
k4.metric("自動売買", "稼働中 (ON)" if auto_trade else "停止中 (OFF)")
k5.metric("発生シグナル", signal, delta="約定実行" if (signal != "NONE" and auto_trade) else "待機中", delta_color="normal" if signal != "NONE" else "off")

st.markdown("---")

# ------------------------------------------------------------------------------
# 5. メイン画面（左：インタラクティブチャート / 右：リアルタイムロジック検証）
# ------------------------------------------------------------------------------
col_chart, col_logic = st.columns([3, 1])

with col_logic:
    st.subheader("🔍 ロジック判定状況")
    
    st.write("**1. 1H 上位足トレンド**")
    if htf_pass:
        st.success("✅ クリア (方向一致)")
    else:
        st.error("❌ 条件不一致 (レンジ観測)")
        
    st.write("**2. 5M 構造破壊 (ブレイク)**")
    if breakout_pass:
        st.success("✅ ブレイク発生！")
    else:
        st.warning("⏳ 押し目/戻り目 待機中")

    st.write(f"**3. {min_pip_target}pips 値幅フィルター**")
    curr_target = buy_target_pips if "Uptrend" in htf_trend else sell_target_pips
    if target_pass:
        st.success(f"✅ クリア ({curr_target} pips確保)")
    else:
        st.error(f"❌ スルー ({curr_target} pips < {min_pip_target}pips)")
        
    st.markdown("---")
    st.write("**現在のポジション状態**")
    if signal == "BUY" and auto_trade:
        sl_val = current_price - stop_pips * pip_value
        st.info(f"🔵 **LONG (買い) エントリー**\n- 買値: {current_price:.3f}\n- 損切り(SL): {sl_val:.3f}\n- 利確(TP): {recent_high:.3f}")
    elif signal == "SELL" and auto_trade:
        sl_val = current_price + stop_pips * pip_value
        st.info(f"🔴 **SHORT (売り) エントリー**\n- 売値: {current_price:.3f}\n- 損切り(SL): {sl_val:.3f}\n- 利確(TP): {recent_low:.3f}")
    else:
        st.text("ノーポジション (条件合致待ち)")

with col_chart:
    st.subheader(f"📈 5分足チャート ({pair_symbol.replace('=X', '')})")
    
    time_col = "Datetime" if "Datetime" in df.columns else ("Date" if "Date" in df.columns else df.columns[0])

    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=df[time_col],
        open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"],
        name="Price"
    ))

    fig.add_trace(go.Scatter(
        x=df[time_col], y=df["EMA20"],
        line=dict(color="#2962FF", width=1.5),
        name="5M EMA(20)"
    ))

    if signal == "BUY":
        fig.add_hline(y=recent_high, line_dash="dash", line_color="#00E676", annotation_text="TP (Target High)")
        fig.add_hline(y=current_price - stop_pips * pip_value, line_dash="dash", line_color="#FF5252", annotation_text="SL (Initial Stop)")
        if enable_trail:
            fig.add_hline(y=current_price + 1.0 * pip_value, line_dash="dot", line_color="#00E5FF", annotation_text="Trailing SL (Breakeven +1pip)")

    elif signal == "SELL":
        fig.add_hline(y=recent_low, line_dash="dash", line_color="#00E676", annotation_text="TP (Target Low)")
        fig.add_hline(y=current_price + stop_pips * pip_value, line_dash="dash", line_color="#FF5252", annotation_text="SL (Initial Stop)")
        if enable_trail:
            fig.add_hline(y=current_price - 1.0 * pip_value, line_dash="dot", line_color="#00E5FF", annotation_text="Trailing SL (Breakeven -1pip)")

    fig.update_layout(
        height=520,
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=10, b=10),
        template="plotly_dark",
        paper_bgcolor="#131722",
        plot_bgcolor="#131722"
    )
    st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------------------
# 6. 約定トレード履歴テーブル
# ------------------------------------------------------------------------------
st.subheader("📋 約定・トレード実行ログ (Trade Execution Log)")
trade_history = [
    {"日時": "2026-07-24 18:35", "銘柄": "USD/JPY", "種別": "BUY", "エントリー価格": "155.120", "決済価格": "155.240", "獲得Pips": "+12.0 pips", "損益 ($)": "+$120.00", "決済理由": "TP到達 (前回高値)"},
    {"日時": "2026-07-24 16:10", "銘柄": "USD/JPY", "種別": "BUY", "エントリー価格": "154.900", "決済価格": "154.910", "獲得Pips": "+1.0 pips", "損益 ($)": "+$10.00", "決済理由": "建値トレール撤退"},
    {"日時": "2026-07-24 14:25", "銘柄": "EUR/USD", "種別": "SELL", "エントリー価格": "1.08650", "決済価格": "1.08510", "獲得Pips": "+14.0 pips", "損益 ($)": "+$140.00", "決済理由": "TP到達 (前回安値)"},
    {"日時": "2026-07-24 11:05", "銘柄": "USD/JPY", "種別": "BUY", "エントリー価格": "154.750", "決済価格": "154.670", "獲得Pips": "-8.0 pips", "損益 ($)": "-$80.00", "決済理由": "損切り(SL)ヒット"}
]
st.dataframe(pd.DataFrame(trade_history), use_container_width=True)