# Proposal — Blockchain Integration Strategy

**Date:** 2026-04-23
**Author:** SPECTRE
**Status:** Draft — operator review required
**Risk tier:** Mixed (see per-track tables)

---

## 0. TL;DR — honest framing

Most "blockchain for X" proposals are marketing decks, not engineering.
Before writing code, the question to answer is:

> *"What problem do we have today that is demonstrably better solved with
> a public blockchain than with our existing Postgres/SQLite + HMAC
> signatures?"*

After walking the codebase I see **four concrete problems** where
blockchain genuinely wins on trust/economics, **three pseudo-problems**
where it's pure theatre, and a **clear staged path** that delivers real
value without betting the platform on crypto-rail-only infrastructure.

### What to ship (ranked by value/effort)

| Priority | Track | What it solves | Effort | Risk |
|---|---|---|---|---|
| **P0** | **Signal provenance via on-chain commits** | *"Were these signals really issued ahead of time, or retro-fitted?"* — today this is a pure trust question, and we lose competitive ground to competitors who can prove it | 1 week | Low |
| **P1** | **On-chain copy-trading venue (Hyperliquid / GMX / dYdX v4)** | Expands copy-trading market to non-KYC users, removes per-user Binance API-key custody risk (the Fernet-key-leak scenario from §C1 of security audit) | 3–4 weeks | Medium |
| **P2** | **Smart-contract affiliate / referral payouts** | Transparent, trust-minimised payout rail; eliminates "did they actually pay my referrals?" disputes | 1–2 weeks | Low |
| **P3** | **Token-gated tiers (optional, stake-to-access)** | Organic growth flywheel if we ever launch a token; can be implemented as "hold X USDC / stablecoin for N days → Pro tier" without issuing our own | 2 weeks | Low-Medium |

### What NOT to ship

- ❌ **Our own L1/L2 chain.** No. No customer asks for this.
- ❌ **An "AnunnakiCoin" governance token** (yet). Regulatory exposure,
  distraction, and unnecessary — we have a real product.
- ❌ **"Signal NFTs"** — pointless cosmetic gimmick.
- ❌ **DAO governance** — premature for a solo-founder product.
- ❌ **On-chain ML model weights** — interesting research, zero user benefit.

Detailed per-track design below.

---

## 1. P0 — On-chain signal provenance (ship first)

### 1.1 The problem

Every crypto signals service claims their historical win-rate is
genuine. None can prove it. Today, a sceptical user has to *trust* that
our `signals.db` row was written at the timestamp shown and not
retroactively edited. The landing page counter (`4,355 signals fired`)
is as strong as our word.

For an institutional-grade platform, this is a real trust gap.

### 1.2 The fix — cryptographic commit at fire time

When the main loop fires a signal, we compute a deterministic hash:

```
leaf = keccak256(
    signal_id           // stable UUID from signal_registry
    || pair             // "BTCUSDT"
    || direction        // LONG / SHORT
    || entry_price
    || targets          // canonical JSON, fixed decimals
    || stop_loss
    || leverage
    || fired_at_unix_ms
)
```

Every N signals (or every T minutes, whichever first) we build a Merkle
tree of that batch and post **only the root** to a cheap L2:

- **Venue:** Base (gas ≈ $0.001 / tx) or Arbitrum / Optimism.
- **Contract:** `SignalRegistry.commitBatch(bytes32 root, uint256 fromTs, uint256 toTs, uint256 count)`
- **Storage cost:** ~22k gas / commit ≈ **$0.01 per batch** on Base.

**Tx frequency:** batching every 50 signals ≈ ~1 commit/hour → **~$10/year** in total gas.

### 1.3 What users get

On any closed signal we can render:

> *"This signal was committed to Base block 8,391,204 at 2026-04-23 13:05 UTC,
> 2h 14m before it closed. [View on BaseScan] [Verify Merkle proof]"*

The Merkle proof is 5–10 hashes (≈ 320 bytes) — the dashboard exposes a
"Verify" button that computes it client-side. **No trust in us required.**

### 1.4 Architecture

```
main.py (signal fires)
    │
    ▼
signal_registry_db ─────► commit_queue (SQLite table)
                                │
                                ▼
              ┌──────────────────────────────────┐
              │  batcher.py (cron, every 5 min)  │
              │   - pops pending leaves          │
              │   - builds Merkle tree           │
              │   - ethers.js / web3.py TX       │
              │   - stores (batch_id, root,     │
              │      tx_hash, block_n, proofs)  │
              └──────────────────────────────────┘
                                │
                                ▼
                  Base L2 (SignalRegistry.sol)
                                │
                                ▼
                ────►  Dashboard: "Verify on-chain"
```

### 1.5 Files to add / modify

| Path | Purpose |
|---|---|
| `contracts/SignalRegistry.sol` | Minimal: `commitBatch`, event emit, ownable |
| `blockchain/batcher.py` | Pulls pending leaves, Merkle, submits tx |
| `blockchain/web3_client.py` | `ethers`-equivalent wrapper around `web3.py` |
| `signal_registry_db.py` | New table `commit_queue(leaf, status, batch_id)` |
| `dashboard/static/js/signal-verify.js` | Client-side Merkle proof verifier |
| `dashboard/app.py` | `GET /api/signal/{id}/proof` returns JSON proof |

### 1.6 Dependencies

```
web3==7.x
eth-account==0.11.x
cryptography (already installed)
```

Wallet: one hot wallet with ~0.01 ETH on Base, rotated monthly. Key
stored in `.env` with the same operational hygiene as the existing
`FERNET_KEY` (see security audit C1 — chmod 600).

### 1.7 Risk / mitigation

| Risk | Mitigation |
|---|---|
| RPC provider outage blocks commits | Store leaves in `commit_queue`; retry loop with back-off; never block the signal fire on tx confirmation |
| Front-running / MEV | Irrelevant — we commit a hash, not a trade |
| L2 re-org → batch tx dropped | `commit_queue` status machine re-submits after 32-block confirmation; old leaves re-batched |
| Wallet key leak | $10/year at stake; rotate monthly; minimal balance |
| User ignores the feature | OK — it still matters to institutional buyers and press |

---

## 2. P1 — On-chain copy-trading (Hyperliquid-first)

### 2.1 The problem

Today, copy-trading requires:

1. User gives us their Binance API key + secret.
2. We encrypt with Fernet and store.
3. Whenever a signal fires, we call Binance on their behalf.

Issues:

- **Custody-like risk** — a breach of the Fernet key = ability to trade
  on every user's account (see security audit §C1).
- **KYC gate** — users in restricted jurisdictions can't participate.
- **Geo-block fragility** — Binance pulls out of a country, our entire
  user segment is dead.
- **Operational load** — per-user IP whitelisting, API-key expiration,
  leverage-change failures, rate-limit juggling.

### 2.2 The fix — smart-contract vault on Hyperliquid (or GMX / dYdX v4)

Flow:

1. User connects wallet (RainbowKit / WalletConnect) to `/copy-trading`.
2. User deposits USDC into an **`AnunnakiCopyVault`** contract on
   Arbitrum (Hyperliquid's L1 has its own native deposit flow — even
   better; no bridge).
3. Vault exposes `executeSignal(SignalBatch calldata)` callable **only**
   by our signer address, which opens a position on **their subset**
   of the vault at the signal's parameters (entry-band, TP, SL, leverage).
4. Trailing SL + TP updates happen via the same signer, same contract.
5. User can **withdraw at any time** — unlike Binance API, no trust in
   us required beyond the signer's discretion, and the contract caps
   per-trade position size, max leverage, blast-radius.

**Key property:** we **never custody funds**. The worst-case scenario
if our signer key is compromised is the attacker can *trade* the vault
(capped) but cannot *withdraw*. Withdrawals are user-initiated only.

### 2.3 Why Hyperliquid first

| Venue | USDT-M perps | API maturity | Fees | Our signal universe overlap |
|---|---|---|---|---|
| **Hyperliquid L1** | ✅ 100+ | Excellent (native SDK, Rust/Python/TS) | **0.025 %** taker | **~85 %** of our 566 pairs |
| GMX v2 (Arbitrum) | ⚠️ limited | Good | 0.1 % | ~30 % |
| dYdX v4 (Cosmos) | ✅ 30+ | Good | 0.05 % | ~50 % |
| Aevo (Base) | ⚠️ | Emerging | 0.05 % | ~40 % |

Hyperliquid has the best signal overlap, lowest fees, and a clean SDK.
Start there; add GMX/dYdX later as a menu option.

### 2.4 Architecture sketch

```
┌────────────────────────────────────────────────────────────┐
│              dashboard: /copy-trading (wallet)              │
│                                                             │
│  [ Connect wallet ]  [ Deposit USDC ]  [ Withdraw ]         │
│                                                             │
│  Live vault balance, PnL, open positions — read on-chain   │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│  AnunnakiCopyVault.sol (Arbitrum) — or native Hyperliquid   │
│                                                             │
│    mapping(address => UserConfig) users;                    │
│    mapping(address => uint256)   balances;                  │
│                                                             │
│    executeSignal(...)    onlySigner  capped  nonReentrant   │
│    deposit()             public                              │
│    withdraw(uint256)     public                              │
│    updateSL(...)         onlySigner                          │
│    closePosition(...)    onlySigner  or  userSelf            │
└────────────────────────────────────────────────────────────┘
                           ▲
                           │ signer tx
                           │
┌────────────────────────────────────────────────────────────┐
│    onchain_executor.py  (new, next to copy_trading.py)      │
│      - Consumes signals from main loop                      │
│      - For each on-chain user, builds execute() call        │
│      - Batches per block for gas efficiency                 │
└────────────────────────────────────────────────────────────┘
```

### 2.5 Files to add

| Path | Purpose |
|---|---|
| `contracts/AnunnakiCopyVault.sol` | Main vault; OpenZeppelin base |
| `contracts/test/VaultTests.t.sol` | Foundry test suite |
| `onchain_executor.py` | Python bridge, mirrors `copy_trading.quick_entry_trade` |
| `dashboard/static/js/wallet.js` | RainbowKit + WalletConnect integration |
| `dashboard/copy_trading_onchain.py` | On-chain variant of existing config flow |
| `dashboard/templates/copy-trading-wallet-panel.html` | New UI tab |

### 2.6 Effort breakdown

- **Week 1:** Vault contract + Foundry tests + Tenderly fork simulation
- **Week 2:** Auditable deploy (testnet), Hyperliquid SDK integration
- **Week 3:** Dashboard wallet-connect flow, deposit/withdraw UX
- **Week 4:** Main-loop integration, pilot with 3 internal accounts

### 2.7 Pre-launch requirements (hard gates)

- ✅ **External security audit** (Code4rena / Cantina / Spearbit — $5–15k for a vault this size). **Non-negotiable.**
- ✅ **Formal per-user loss cap** encoded in the contract (`maxDrawdownBps`) — contract auto-pauses user slot if breached.
- ✅ **Timelocked admin upgrades** — 48h before any signer/owner change takes effect.
- ✅ **Kill switch** — `pauseAll()` callable by a separate multisig (e.g. Gnosis Safe with founder + ops).
- ✅ **Invariant tests** — Foundry's fuzzer proves "deposits + PnL = withdrawals + balance" across 10M random ops.

### 2.8 Risks and mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Smart-contract bug drains user funds | 🔴 Critical | External audit + Foundry invariants + Immunefi bug bounty |
| Signer key leak → rogue trades | 🟡 Medium | Contract caps position size, blast-radius; users withdraw at will; hot signer separate from cold multisig |
| Hyperliquid L1 downtime | 🟡 Medium | Multi-venue support (GMX fallback) in phase 2 |
| Regulatory — are we an "investment advisor"? | 🟡 Medium | Legal review before any US marketing; terms explicitly frame the vault as user-operated |
| User bridges wrong chain / loses funds | 🟢 Low | Native Hyperliquid deposit flow (no bridge) for phase 1 |

---

## 3. P2 — Smart-contract referral payouts

### 3.1 The problem

Current referral flow is off-chain: we record `referred_by=<user_id>` in
SQLite, accrue commissions in a field, and pay out manually (or via
NOWPayments). It works but:

- Referrers must trust us to pay.
- Disputes are our word vs theirs.
- Payouts are batched (friction); users want instant.

### 3.2 The fix

**`AnunnakiReferrals.sol`** on the same chain as the vault:

```solidity
function claim(address referrer, uint256 amount, bytes calldata sig)
    external nonReentrant;

// sig is a signed voucher from our backend proving `amount` is owed
// Contract pays out from a pre-funded treasury, burns the nonce.
```

We pre-fund the contract with USDC from payment revenue; referrers
claim instantly any time. The signature proves *we* authorised the
payout, so users can't fake-claim.

### 3.3 Files to add

- `contracts/AnunnakiReferrals.sol`
- `blockchain/referral_voucher.py` (signs EIP-712 vouchers)
- Dashboard UI: `/referrals` gains a "Claim on-chain" button

Effort: 1–2 weeks including audit.

---

## 4. P3 — Token-gated access (stablecoin path, not our own token)

### 4.1 Approach

Instead of issuing our own token (regulatory burden, mercenary holders),
allow users to get a **tier upgrade by holding USDC in a specific
contract** for a rolling window:

- **Stake 100 USDC for 30 days → Pro tier access while staked.**
- **Stake 500 USDC for 30 days → Ultra.**

Contract: `StakeForAccess.sol` — standard, audited pattern (similar to
ERC4626 vaults without yield). Users can withdraw anytime; tier ends
when stake drops below threshold.

### 4.2 Why this is better than our own token

- No regulatory/legal exposure (stablecoin, not a security).
- Users aren't holding a volatile asset.
- We don't need to bootstrap token liquidity.
- Revenue model stays clean: either users pay cash (NOWPayments) or
  lock capital (losing ~5 % APY elsewhere is the implicit cost).

### 4.3 When to actually ship this

Only **after P0 and P1 are live and stable.** This is a growth feature,
not a trust feature.

---

## 5. Anti-proposals — what we should explicitly not build

### 5.1 Our own L1 / L2 chain

**No.** Zero customer demand. Millions in dev cost. We are not in the
infrastructure business.

### 5.2 "ANK Governance Token"

**Not yet.** An airdrop to build hype is a distraction from the product.
Revisit only if (a) revenue is stable at $100k+ MRR, (b) we have a
genuine DAO-governable surface (e.g. treasury allocation, risk parameters),
and (c) legal counsel has cleared the jurisdiction.

### 5.3 "Signal NFTs" / "Performance NFTs"

**No.** These are cosmetic and don't solve any problem the P0 provenance
commits don't solve better, cheaper, and with fewer lawyers.

### 5.4 "Decentralised PREDATOR strategy"

Publishing our strategy on-chain (for transparency) would destroy it —
PREDATOR's edge is partly that other participants can't model against
it. Stay off-chain.

### 5.5 On-chain AI model inference

Research-interesting, product-useless. Keep the RTX 3090.

---

## 6. Staging & dependencies

```
P0  Signal provenance        ┬──►  Public trust win
                             │
P1  On-chain copy-trading    ┼──►  New market segment + reduced custody risk
                             │
P2  Referral payouts         ┼──►  Affiliate growth flywheel
                             │
P3  Stake-for-access         ┘  (optional, growth phase)
```

P0 is a **prerequisite for taking on-chain copy-trading seriously** —
the same cryptographic commitment scheme is what makes *"trust the
signal we're about to execute on-chain in your vault"* defensible.

Everything else can ship in any order once P0 exists.

---

## 7. Cost / timeline summary

| Track | Dev time | External audit | Monthly infra | Gas / year |
|---|---|---|---|---|
| P0 Signal provenance | 1 week | Not required (no user funds) | $0 | ~$10 |
| P1 Hyperliquid vault | 4 weeks | $8–15k (Spearbit / Cantina) | $30 (RPC) | ~$200 signer gas |
| P2 Referral payouts | 1–2 weeks | $3–5k (minor) | — | ~$50 |
| P3 Stake-for-access | 2 weeks | $3–5k | — | negligible |

**First-6-months all-in: ~$25k engineering + ~$20k audits + ~$500/yr gas**
for a credible, differentiated, genuinely-decentralised surface on the
platform.

---

## 8. Questions for operator

1. **Chain preference:** Base, Arbitrum, or Hyperliquid native for the
   provenance commits (P0)? *Lean Base — cheapest + Coinbase ecosystem.*
2. **Audit firm:** Cantina / Spearbit / OpenZeppelin / Code4rena?
   *Lean Cantina or Spearbit for the vault; budget permitting.*
3. **Legal:** Do we have counsel review lined up for P1's jurisdictional
   questions (US users holding vault shares)?
4. **Treasury:** Is there ~$25k audit budget in reach over the next 6
   months, or should P1 wait for Q4 revenue?
5. **Team:** Should this be done with an external Solidity contractor,
   or do we hire? *Lean contractor for P0/P2 (weeks-scope); hire or retain
   a dedicated engineer for P1 (quarter-scope).*
6. **Branding:** Does "Anunnaki World" want the on-chain identity to be
   the same brand, or a sub-brand (e.g. "Anunnaki Vaults")? *Affects
   ENS registration, contract naming, domain allocation.*

---

## 9. Decision requested

Approve / reject / reprioritise. The cheapest and highest-trust win is
**P0 (signal provenance)** — 1 week of focused engineering, ~$10/year
gas, and a concrete on-chain answer to every skeptic who's ever asked
*"how do I know your win-rate is real?"*

If nothing else in this proposal ships, shipping P0 alone meaningfully
changes the platform's credibility.

*Nothing in this proposal has been implemented. This is a plan only.*
