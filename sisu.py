from web3 import Web3
import json, requests, time

def cs(address):
    return Web3.to_checksum_address(address)

infura_url = "https://mainnet.infura.io/v3/90d0df01d1b84a00a8c54330b1a3c54d"  
w3 = Web3(Web3.HTTPProvider(infura_url))

ENTRYPOINT_ADDRESS = cs("0x1306A3d7A1a554B6a356F7241B07e4D377f6044E")  
PAYMASTER_ADDRESS = cs("0x0000000000000000000000000000000000000000")  
BUNDLER_API = "https://api.bundler.network/rpc"  

PRIVATE_KEY = input("Enter Private Key: ").strip()
MY_ADDRESS = cs(input("Enter Your Wallet Address: ").strip())

AAVE_POOL_ADDRESS = cs("0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2")
UNISWAP_ROUTER_ADDRESS = cs("0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D")
DAI_ADDRESS = cs("0x6B175474E89094C44Da98b954EedeAC495271d0F")
WETH_ADDRESS = cs("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")

AAVE_POOL_ABI = '''[{"inputs":[{"internalType":"address","name":"receiver","type":"address"},
{"internalType":"address","name":"asset","type":"address"},{"internalType":"uint256","name":"amount","type":"uint256"},
{"internalType":"bytes","name":"params","type":"bytes"},{"internalType":"uint16","name":"referralCode","type":"uint16"}],
"name":"flashLoanSimple","outputs":[],"stateMutability":"nonpayable","type":"function"}]'''

UNISWAP_ROUTER_ABI = '''[{"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},
{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},
{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],
"name":"swapExactTokensForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],
"stateMutability":"nonpayable","type":"function"}]'''

AAVE_POOL = w3.eth.contract(address=AAVE_POOL_ADDRESS, abi=json.loads(AAVE_POOL_ABI))
UNISWAP_ROUTER = w3.eth.contract(address=UNISWAP_ROUTER_ADDRESS, abi=json.loads(UNISWAP_ROUTER_ABI))

def get_gas_price():
    try:
        response = requests.get("https://ethgasstation.info/api/ethgasAPI.json")
        return w3.to_wei(response.json()["fast"] / 10, "gwei")
    except:
        return w3.eth.gas_price

def get_token_price():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=dai,ethereum&vs_currencies=usd"
    response = requests.get(url).json()
    return response['ethereum']['usd'], response['dai']['usd']

def send_user_operation(user_op):
    headers = {"Content-Type": "application/json"}
    payload = {"method": "eth_sendUserOperation", "params": [user_op, ENTRYPOINT_ADDRESS], "id": 1, "jsonrpc": "2.0"}
    response = requests.post(BUNDLER_API, json=payload, headers=headers)
    return response.json()

def execute_gasless_arbitrage():
    eth_price, dai_price = get_token_price()
    flashloan_amount = w3.to_wei(10, "ether")

    print("\n🔄 Flashloan Process Started")
    print(f"🔹 Borrowing {flashloan_amount / 1e18} ETH from AAVE")
    print(f"🔹 ETH Price: ${eth_price}, DAI Price: ${dai_price}")

    flashloan_tx = AAVE_POOL.functions.flashLoanSimple(
        MY_ADDRESS, WETH_ADDRESS, flashloan_amount, b"", 0
    ).build_transaction({
        "from": MY_ADDRESS, "gas": 1000000, "gasPrice": get_gas_price(),
        "nonce": w3.eth.get_transaction_count(MY_ADDRESS)
    })

    signed_tx = w3.eth.account.sign_transaction(flashloan_tx, PRIVATE_KEY)
    raw_tx = signed_tx.rawTransaction.hex()

    user_op = {
        "sender": MY_ADDRESS, "nonce": hex(w3.eth.get_transaction_count(MY_ADDRESS)), "callData": raw_tx,
        "callGasLimit": hex(1000000), "verificationGasLimit": hex(500000),
        "preVerificationGas": hex(200000), "maxFeePerGas": hex(get_gas_price()),
        "maxPriorityFeePerGas": hex(w3.to_wei(1, "gwei")), "paymasterAndData": PAYMASTER_ADDRESS, 
        "signature": raw_tx  # 🔥 Fixed Signature Issue
    }

    response = send_user_operation(user_op)
    print("🚀 ERC-4337 Gasless Flashloan Executed!", response)

    amount_in = flashloan_amount
    path = [WETH_ADDRESS, DAI_ADDRESS]
    amount_out_min = int(amount_in * eth_price / dai_price * 0.99)  

    print(f"🔹 Swapping {amount_in / 1e18} ETH → {amount_out_min / 1e18} DAI")

    swap_tx = UNISWAP_ROUTER.functions.swapExactTokensForTokens(
        amount_in, amount_out_min, path, MY_ADDRESS, int(time.time()) + 60
    ).build_transaction({
        "from": MY_ADDRESS, "gas": 200000, "gasPrice": get_gas_price(),
        "nonce": w3.eth.get_transaction_count(MY_ADDRESS)
    })

    signed_swap_tx = w3.eth.account.sign_transaction(swap_tx, PRIVATE_KEY)
    swap_receipt = w3.eth.send_raw_transaction(signed_swap_tx.rawTransaction)

    print("✅ Swap Completed! Tx Hash:", w3.to_hex(swap_receipt))

    final_eth = int(amount_out_min * dai_price / eth_price * 0.99)  

    print(f"🔹 Selling {amount_out_min / 1e18} DAI → {final_eth / 1e18} ETH")

    final_profit = (final_eth - flashloan_amount) / 1e18  
    print(f"\n💰 Final Profit: {final_profit:.6f} ETH ($ {final_profit * eth_price:.2f})\n")

    if final_profit <= 0:
        print("⚠ Loss Detected! Transaction Skipped ❌")
        return

    repayment_tx = AAVE_POOL.functions.flashLoanSimple(
        MY_ADDRESS, WETH_ADDRESS, flashloan_amount, b"", 0
    ).build_transaction({
        "from": MY_ADDRESS, "gas": 100000, "gasPrice": get_gas_price(),
        "nonce": w3.eth.get_transaction_count(MY_ADDRESS)
    })

    signed_repayment_tx = w3.eth.account.sign_transaction(repayment_tx, PRIVATE_KEY)
    w3.eth.send_raw_transaction(signed_repayment_tx.rawTransaction)

    print("✅ Flashloan Repaid Successfully!")

if __name__ == "__main__":
    print("Starting ERC-4337 Gasless Arbitrage Bot - CRYPTOGRAPHYTUBE")
    while True:
        try:
            execute_gasless_arbitrage()
            time.sleep(30)
        except Exception as e:
            print(f"Error: {e}")