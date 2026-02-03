import re

WEB3_KEYWORDS = [
    # English - General
    "web3", "web 3", "web-3", "blockchain", "crypto", "cryptocurrency",
    "defi", "decentralized finance", "nft", "non-fungible token",
    "dapp", "decentralized app",

    # English - Specific Technologies
    "solidity", "ethereum", "ethereum development", "eth",
    "bitcoin", "btc", "layer2", "layer 2",
    "smart contract", "token", "erc20", "erc721",
    "consensus", "proof of stake", "proof of work",
    "bitcoin lightning", "lightning network",

    # English - Exchanges & Trading
    "exchange", "crypto exchange", "decentralized exchange", "dex",
    "trading platform", "arbitrage", "quantitative trading",

    # English - Finance
    "crypto finance", "digital assets", "digital currency",
    "stablecoin", "yield farming", "liquidity pool",

    # Chinese - General
    "区块链", "加密货币", "加密", "智能合约",
    "代币", "币圈", "链圈", "链上", "defi",
    "nft", "cex",

    # Chinese - Specific Technologies
    "以太坊", "比特币", "solidity", "智能合约",
    "dapp", "合约审计", "安全审计",

    # Chinese - Exchanges & Trading
    "交易所", "去中心化交易", "dex", "币交易",
    "合约交易", "期货交易", "量化交易",

    # Chinese - Finance
    "数字资产", "虚拟货币", "挖矿", "矿池"

    # Chinese - General related
    "跨链", "跨链桥接",
]


def classify_job_type(description: str, default: str = "国内") -> str:
    text = description.lower()

    # 2. Web3 check
    for kw in WEB3_KEYWORDS:
        if kw.lower() in text:
            return "web3"

    # 4. Default
    return default