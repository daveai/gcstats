import streamlit as st
import requests
from web3 import Web3
import time
import logging

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Page config (must be first st command)
st.set_page_config(
    page_title="Gnosis Chain Stats",
    page_icon="🦉",
    layout="wide"
)

# Bloomberg-terminal style CSS
st.markdown("""
<style>
    .main .block-container {
        padding: 1rem 2rem;
    }
    .stApp {
        background-color: #0a0a0a;
    }
    h1, h2, h3 {
        color: #04795B !important;
        font-size: 1.2rem !important;
        margin-bottom: 0.5rem !important;
    }
    .positive { color: #00ff88 !important; }
    .negative { color: #ff6b6b !important; }
    .neutral { color: #888888 !important; }
    .data-table {
        font-family: 'Courier New', monospace;
        font-size: 0.85rem;
        width: 100%;
        border-collapse: collapse;
    }
    .data-table th {
        text-align: left;
        color: #04795B;
        border-bottom: 1px solid #333;
        padding: 4px 8px;
        font-weight: normal;
    }
    .data-table td {
        padding: 4px 8px;
        border-bottom: 1px solid #1a1a1a;
        color: #ccc;
    }
    .data-table tr:hover {
        background-color: #111;
    }
    .pair-col { color: #fff; font-weight: bold; }
    .addr-col { color: #666; font-size: 0.75rem; text-decoration: none; }
    .addr-col:hover { color: #04795B; text-decoration: underline; }
    .price-col { color: #fff; text-align: right; }
    .fx-col { color: #888; text-align: right; }
    .dev-col { text-align: right; }
    .timestamp { color: #444; font-size: 0.7rem; margin-top: 0.5rem; }
</style>
""", unsafe_allow_html=True)

# RPC endpoints
GNOSIS_RPC = "https://rpc.gnosischain.com"
MAINNET_RPC = "https://eth.llamarpc.com"

w3_gnosis = Web3(Web3.HTTPProvider(GNOSIS_RPC))
w3_mainnet = Web3(Web3.HTTPProvider(MAINNET_RPC))

# Bot addresses
BOTS = [
    {"address": "0x90463d5c5B7384b630FfEAF759ab91811457CBAb", "name": "BRIDGE BOT", "chain": "mainnet"},
    {"address": "0xFA0951092B227b0103062D3EDDFC2FCcB13e9C1D", "name": "TEMP BOT", "chain": "mainnet"},
]

# Uniswap V3 Pool ABI (minimal)
POOL_ABI = [
    {"inputs": [], "name": "slot0", "outputs": [
        {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
        {"internalType": "int24", "name": "tick", "type": "int24"},
        {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
        {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
        {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
        {"internalType": "uint8", "name": "feeProtocol", "type": "uint8"},
        {"internalType": "bool", "name": "unlocked", "type": "bool"},
    ], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token0", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

ERC20_ABI = [
    {"inputs": [], "name": "decimals", "outputs": [{"type": "uint8"}], "stateMutability": "view", "type": "function"},
]

# sDAI contract for convertToAssets
SDAI_ADDRESS = "0xaf204776c7245bf4147c2612bf6e5972ee483701"
SDAI_ABI = [
    {"inputs": [{"type": "uint256", "name": "shares"}], "name": "convertToAssets", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]

# sDAI vault APY contract
SDAI_VAULT_ADDRESS = "0xD499b51fcFc66bd31248ef4b28d656d67E591A94"
SDAI_VAULT_ABI = [
    {"inputs": [], "name": "vaultAPY", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]

# Pool configurations
POOLS = [
    {"address": "0x576bf065cbc15cb2d61affb156118fcff01a8238", "pair": "USDC.E/BRLA", "fx_pair": "USD/BRL"},
    {"address": "0x1bb53efa5523c80b598b561e266dfdc938f80e4f", "pair": "EURE/ZCHF", "fx_pair": "EUR/CHF"},
    {"address": "0x9fc285501a38d734e7b42147445d303cf8f7946b", "pair": "BRZ/USDC.E", "fx_pair": "BRL/USD"},
    {"address": "0x22eb73322b6334ccf07fc2f9f22690a012d22797", "pair": "GBPE/SDAI", "fx_pair": "GBP/USD", "sdai_adjust": True},
]


@st.cache_data(ttl=60)
def get_sdai_rate() -> float:
    """Get sDAI to DAI conversion rate"""
    try:
        sdai = w3_gnosis.eth.contract(address=Web3.to_checksum_address(SDAI_ADDRESS), abi=SDAI_ABI)
        assets = sdai.functions.convertToAssets(10**18).call()
        return assets / 10**18
    except Exception as e:
        logger.warning(f"Failed to fetch sDAI rate: {e}")
        return 1.0


@st.cache_data(ttl=300)
def get_sdai_apy() -> float:
    """Get sDAI vault APY in percentage"""
    try:
        vault = w3_gnosis.eth.contract(address=Web3.to_checksum_address(SDAI_VAULT_ADDRESS), abi=SDAI_VAULT_ABI)
        apy_wei = vault.functions.vaultAPY().call()
        # Convert from wei (1e18) to percentage
        return apy_wei / 10**18 * 100
    except Exception as e:
        logger.warning(f"Failed to fetch sDAI APY: {e}")
        return 0.0


@st.cache_data(ttl=300)
def get_fx_rates():
    """Fetch FX rates - cached for 5 min since they don't change frequently"""
    rates = {}
    try:
        resp = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        if resp.status_code == 200:
            usd = resp.json().get("rates", {})
            rates["USD/BRL"] = usd.get("BRL")
            rates["USD/CHF"] = usd.get("CHF")
            rates["USD/EUR"] = usd.get("EUR")
            rates["USD/GBP"] = usd.get("GBP")
            if rates.get("USD/BRL"):
                rates["BRL/USD"] = 1 / rates["USD/BRL"]
            if rates.get("USD/CHF") and rates.get("USD/EUR"):
                rates["EUR/CHF"] = rates["USD/CHF"] / rates["USD/EUR"]
            if rates.get("USD/GBP"):
                rates["GBP/USD"] = 1 / rates["USD/GBP"]
        else:
            logger.warning(f"FX API returned status {resp.status_code}")
    except Exception as e:
        logger.warning(f"Failed to fetch FX rates: {e}")
    return rates


@st.cache_data(ttl=60)
def get_pool_price(pool_address: str) -> dict:
    """Get price from Uniswap V3 pool"""
    try:
        pool = w3_gnosis.eth.contract(address=Web3.to_checksum_address(pool_address), abi=POOL_ABI)
        slot0 = pool.functions.slot0().call()
        sqrt_price_x96 = slot0[0]

        token0_addr = pool.functions.token0().call()
        token1_addr = pool.functions.token1().call()
        token0 = w3_gnosis.eth.contract(address=token0_addr, abi=ERC20_ABI)
        token1 = w3_gnosis.eth.contract(address=token1_addr, abi=ERC20_ABI)
        decimals0 = token0.functions.decimals().call()
        decimals1 = token1.functions.decimals().call()

        price = (sqrt_price_x96 / (2**96)) ** 2 * (10 ** (decimals0 - decimals1))

        return {"price": price, "success": True}
    except Exception as e:
        logger.warning(f"Failed to fetch pool price for {pool_address}: {e}")
        return {"success": False, "error": str(e)}


@st.cache_data(ttl=60)
def get_bot_balance(address: str, chain: str) -> dict:
    """Get ETH balance for a bot address"""
    try:
        w3 = w3_mainnet if chain == "mainnet" else w3_gnosis
        balance_wei = w3.eth.get_balance(Web3.to_checksum_address(address))
        balance_eth = balance_wei / 10**18
        return {"balance": balance_eth, "success": True}
    except Exception as e:
        logger.warning(f"Failed to fetch bot balance for {address} on {chain}: {e}")
        return {"success": False, "error": str(e)}


@st.cache_data(ttl=60)
def fetch_pool_data() -> tuple:
    """Fetch all pool and FX data, return rows and timestamp"""
    fx_rates = get_fx_rates()
    sdai_rate = get_sdai_rate()

    rows = []
    for pool in POOLS:
        data = get_pool_price(pool["address"])

        if data["success"]:
            pool_price = data["price"]
            if pool.get("sdai_adjust"):
                pool_price = pool_price * sdai_rate

            fx_pair = pool["fx_pair"]
            fx_rate = fx_rates.get(fx_pair) if fx_pair else None

            if fx_rate and pool_price > 0:
                dev = ((pool_price - fx_rate) / fx_rate) * 100
                if abs(dev) < 0.5:
                    dev_class = "positive"
                elif abs(dev) > 2:
                    dev_class = "negative"
                else:
                    dev_class = "neutral"
                dev_str = f"<span class='{dev_class}'>{dev:+.2f}%</span>"
            else:
                dev_str = "—"

            rows.append({
                "pair": pool["pair"],
                "addr": f"{pool['address'][:8]}..{pool['address'][-4:]}",
                "full_addr": pool["address"],
                "price": f"{pool_price:.4f}",
                "fx_pair": fx_pair or "—",
                "fx_rate": f"{fx_rate:.4f}" if fx_rate else "—",
                "dev": dev_str,
            })
        else:
            rows.append({
                "pair": pool["pair"],
                "addr": f"{pool['address'][:8]}..{pool['address'][-4:]}",
                "full_addr": pool["address"],
                "price": "ERR",
                "fx_pair": pool["fx_pair"] or "—",
                "fx_rate": "—",
                "dev": "—",
            })

    return rows, time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())


@st.cache_data(ttl=60)
def fetch_bot_data() -> tuple:
    """Fetch all bot balances, return rows and timestamp"""
    rows = []
    for bot in BOTS:
        data = get_bot_balance(bot["address"], bot["chain"])
        if data["success"]:
            balance = f"{data['balance']:.4f}"
        else:
            balance = "ERR"

        explorer = "https://etherscan.io" if bot["chain"] == "mainnet" else "https://gnosisscan.io"
        rows.append({
            "name": bot["name"],
            "address": bot["address"],
            "addr_short": f"{bot['address'][:8]}..{bot['address'][-4:]}",
            "chain": bot["chain"],
            "balance": balance,
            "explorer": explorer,
        })

    return rows, time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())


def render_pool_table(rows, timestamp):
    """Render pool table HTML"""
    table_html = """
    <table class="data-table">
    <tr>
        <th>PAIR</th>
        <th style="text-align:right">POOL</th>
        <th>FX</th>
        <th style="text-align:right">RATE</th>
        <th style="text-align:right">DEV</th>
    </tr>
    """

    for r in rows:
        table_html += f"""
    <tr>
        <td><span class="pair-col">{r['pair']}</span><br><a href="https://gnosisscan.io/address/{r['full_addr']}" target="_blank" class="addr-col">{r['addr']}</a></td>
        <td class="price-col">{r['price']}</td>
        <td class="fx-col">{r['fx_pair']}</td>
        <td class="fx-col">{r['fx_rate']}</td>
        <td class="dev-col">{r['dev']}</td>
    </tr>
    """

    table_html += "</table>"
    st.markdown(table_html, unsafe_allow_html=True)
    st.markdown(f"<p class='timestamp'>{timestamp} | Auto-refresh: 10m</p>", unsafe_allow_html=True)


def render_bot_table(rows, timestamp):
    """Render bot table HTML"""
    table_html = """
    <table class="data-table">
    <tr>
        <th>BOT</th>
        <th>CHAIN</th>
        <th style="text-align:right">ETH</th>
    </tr>
    """

    for r in rows:
        table_html += f"""
    <tr>
        <td><span class="pair-col">{r['name']}</span><br><a href="{r['explorer']}/address/{r['address']}" target="_blank" class="addr-col">{r['addr_short']}</a></td>
        <td class="fx-col">{r['chain']}</td>
        <td class="price-col">{r['balance']}</td>
    </tr>
    """

    table_html += "</table>"
    st.markdown(table_html, unsafe_allow_html=True)
    st.markdown(f"<p class='timestamp'>{timestamp}</p>", unsafe_allow_html=True)


# Layout
col1, col2 = st.columns(2)

with col1:
    st.markdown("### GNOSIS UNI-V3 FX POOLS")

    @st.fragment(run_every=600)
    def live_pool_table():
        rows, timestamp = fetch_pool_data()
        render_pool_table(rows, timestamp)

    live_pool_table()

with col2:
    st.markdown("### BOT BALANCES")

    @st.fragment(run_every=600)
    def live_bot_table():
        rows, timestamp = fetch_bot_data()
        render_bot_table(rows, timestamp)

    live_bot_table()

    st.markdown("### SDAI YIELD")

    @st.fragment(run_every=600)
    def live_sdai_apy():
        apy = get_sdai_apy()
        st.markdown(f"""
        <table class="data-table">
        <tr>
            <th>ASSET</th>
            <th style="text-align:right">APY</th>
        </tr>
        <tr>
            <td><span class="pair-col">sDAI</span><br><a href="https://gnosisscan.io/address/{SDAI_VAULT_ADDRESS}" target="_blank" class="addr-col">{SDAI_VAULT_ADDRESS[:8]}..{SDAI_VAULT_ADDRESS[-4:]}</a></td>
            <td class="price-col"><span class="positive">{apy:.2f}%</span></td>
        </tr>
        </table>
        """, unsafe_allow_html=True)

    live_sdai_apy()
