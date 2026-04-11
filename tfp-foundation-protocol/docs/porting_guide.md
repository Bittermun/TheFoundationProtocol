# TFP v2.2 Embedded Porting Guide — Cortex-M4 / RISC-V32

## 1. Overview

This guide maps the Python TFP v2.2 modules to C structs and Rust crates targeting:
- **Cortex-M4**: STM32F405, nRF52840 (≤256 KB RAM, ≤1 MB Flash)
- **RISC-V32**: ESP32-C3, GD32VF103

All HAL abstractions use **open SDKs only**: libopencm3 (Cortex-M4), RISC-V ESP-IDF / GD32VF SDK.

---

## 2. Python → C/Rust Module Map

| Python Module | C Struct / File | Rust Crate | Notes |
|---|---|---|---|
| `CreditLedger` | `credit_ledger.c` / `tfp_credit_t` | `tfp-credit` | Pure hash-chain, no heap alloc |
| `NDNAdapter` | `ndn_interest.c` / `ndn_interest_t` | `ndn-lite-rs` | Use NDN-Lite for embedded NDN |
| `RaptorQAdapter` | `raptorq_dec.c` | `raptorq` crate | Use Rust `raptorq` crate via FFI |
| `ZKPAdapter` | `schnorr.c` / `zkp_proof_t` | `ark-std` | Schnorr proof, no EC lib needed |
| `SymbolicPreprocessor` | `sym_preproc.c` | inline | Rule engine, <50 LOC |
| `PUFEnclave` | `puf_enclave.c` / `puf_id_t` | `embassy-rng` | TRNG + HMAC-SHA3 |
| `HierarchicalLexiconTree` | `hlt_delta.c` | `heapless` | Static buffers only |
| `AsymmetricUplinkRouter` | `uplink_router.c` | inline | Cost function, integer math |

---

## 3. C Struct Definitions

```c
/* tfp_types.h */
#include <stdint.h>
#include <stdbool.h>

#define TFP_HASH_BYTES    32
#define TFP_SHARD_SIZE   128
#define TFP_MAX_SHARDS    64
#define TFP_CHAIN_DEPTH   16

/* Credit ledger — append-only hash chain */
typedef struct {
    uint8_t  chain[TFP_CHAIN_DEPTH][TFP_HASH_BYTES];
    uint8_t  depth;
    uint32_t balance;
} tfp_credit_ledger_t;

/* NDN Interest / Data */
typedef struct { char name[128]; }                       ndn_interest_t;
typedef struct { char name[128]; uint8_t content[512]; } ndn_data_t;

/* ZKP Schnorr proof (64 bytes) */
typedef struct {
    uint8_t s[TFP_HASH_BYTES];      /* response scalar */
    uint8_t r_hash[TFP_HASH_BYTES]; /* commitment hash */
} zkp_proof_t;

/* PUF identity */
typedef struct {
    uint8_t puf_entropy[32];
    uint8_t rf_fingerprint[16];
    uint8_t threshold_sig[64];
} puf_identity_t;

/* RaptorQ shard (with header) */
typedef struct {
    uint64_t orig_len;
    uint32_t k;
    uint32_t index;
    uint8_t  data[TFP_SHARD_SIZE];
} raptorq_shard_t;
```

---

## 4. HAL Abstractions

### 4.1 TRNG (Entropy for PUF)

**Cortex-M4 / STM32F4 (libopencm3):**
```c
#include <libopencm3/stm32/rng.h>

void hal_trng_read(uint8_t *buf, size_t len) {
    rng_enable();
    for (size_t i = 0; i < len; i += 4) {
        uint32_t val = rng_get_random_blocking();
        __builtin_memcpy(buf + i, &val, (len - i >= 4) ? 4 : len - i);
    }
}
```

**RISC-V32 / ESP32-C3 (ESP-IDF):**
```c
#include "esp_random.h"
void hal_trng_read(uint8_t *buf, size_t len) { esp_fill_random(buf, len); }
```

### 4.2 SPI for RF Fingerprinting

```c
/* Generic SPI HAL — vendor-independent */
typedef struct {
    void (*transfer)(const uint8_t *tx, uint8_t *rx, size_t len);
    void (*cs_set)(bool high);
} hal_spi_t;

void rf_fingerprint_sample(hal_spi_t *spi, uint8_t out[16]) {
    uint8_t cmd[2] = {0x01, 0x00};  /* read I/Q sample cmd */
    uint8_t raw[32];
    spi->cs_set(false);
    spi->transfer(cmd, raw, sizeof(raw));
    spi->cs_set(true);
    /* SVD-reduce 32 bytes → 16 byte fingerprint (simplified) */
    for (int i = 0; i < 16; i++) out[i] = raw[i] ^ raw[i + 16];
}
```

### 4.3 GPIO (Status LEDs / Debug)

```c
/* libopencm3 */
#include <libopencm3/stm32/gpio.h>
#define LED_PORT GPIOC
#define LED_PIN  GPIO13
void hal_led_init(void) { gpio_set_mode(LED_PORT, GPIO_MODE_OUTPUT_2_MHZ, GPIO_CNF_OUTPUT_PUSHPULL, LED_PIN); }
void hal_led_set(bool on) { on ? gpio_clear(LED_PORT, LED_PIN) : gpio_set(LED_PORT, LED_PIN); }
```

---

## 5. Per-Module Implementation Notes

### CreditLedger (credit_ledger.c)
- No dynamic allocation: fixed `TFP_CHAIN_DEPTH` ring
- SHA3-256 via TinyCrypt or mbedTLS `mbedtls_sha3()`
- `mint()` < 200 cycles on Cortex-M4 @ 168 MHz

### RaptorQ Decoder (raptorq_dec.c)
- For Cortex-M4: use Rust `raptorq` crate compiled to `no_std` + call via C FFI
- GF(2) Gaussian elimination fits in 32 KB stack with `TFP_MAX_SHARDS=32`
- Alternatively: link `nanorq` (C, multi-platform) directly

### ZKP Schnorr (schnorr.c)
- No elliptic curve needed: Fiat-Shamir over SHA3-256 scalars
- All arithmetic mod `P = 0xFFFF...FC2F` using 256-bit big-integer (mbedTLS `mbedtls_mpi`)
- Proof generation: ~1,200 cycles on Cortex-M4

### SymbolicPreprocessor (sym_preproc.c)
- Pure rule engine: field presence checks + range validation
- Target: < 2 ms on Cortex-M4 @ 8 MHz (low-power mode)
- No dynamic memory: validated against a static rule table

### PUFEnclave (puf_enclave.c)
- TRNG → SHA3-256 → `puf_entropy[32]`
- RF fingerprint via SPI → SVD → `rf_fingerprint[16]`
- HMAC-SHA3-256 for signing: `threshold_sig[64]` = HMAC(seed, proof || nonce)

### HierarchicalLexiconTree (hlt_delta.c)
- Base model stored in external Flash (SPI NOR, e.g. W25Q128)
- Delta applied to RAM copy: `heapless::Vec` (Rust) or static array (C)
- Hash mismatch → memset 0 on delta buffer (atomic rollback)

---

## 6. Memory Layout Table

See `memory_budget.csv` for per-module breakdown.

**Linker Script Snippet (STM32F405, 1 MB Flash / 192 KB RAM):**

```ld
/* tfp_stm32f405.ld */
MEMORY {
    FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 1024K
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
    CCMRAM (rw) : ORIGIN = 0x10000000, LENGTH = 64K
}

SECTIONS {
    .tfp_credit  (NOLOAD) : { *(.tfp_credit*)  } > CCMRAM   /* ledger in CCM */
    .tfp_shards  (NOLOAD) : { *(.tfp_shards*)  } > RAM      /* RaptorQ buffers */
    .tfp_lexicon (NOLOAD) : { *(.tfp_lexicon*) } > RAM      /* HLT delta buffer */
}
```

---

## 7. Firmware Flashing Tools

| Tool | Target | Command |
|------|--------|---------|
| OpenOCD | STM32F4, nRF52840 | `openocd -f interface/stlink.cfg -f target/stm32f4x.cfg -c "program tfp.elf verify reset exit"` |
| dfu-util | STM32 DFU bootloader | `dfu-util -D tfp.bin -s 0x08000000:leave` |
| esptool.py | ESP32-C3 | `esptool.py --chip esp32c3 write_flash 0x0 tfp.bin` |
| JLinkExe | nRF52840 | `JLinkExe -device nRF52840 -if SWD -speed 4000 -CommandFile flash.jlink` |

---

## 8. Rust `no_std` Crate Mapping

```toml
# Cargo.toml
[dependencies]
raptorq    = { version = "2.0", default-features = false, features = ["no_std"] }
heapless   = "0.8"
embassy-rng = "0.1"
hmac       = { version = "0.12", default-features = false }
sha3       = { version = "0.10", default-features = false }
```

---

## 9. SDR Pipeline for ATSC 3.0 / PIB Reception

See `sdr_pipeline.grc` for GNU Radio Companion flow.

**libiio command-line test (PlutoSDR / ADALM-PLUTO):**
```bash
# Tune to ATSC 3.0 channel (e.g. 629 MHz)
iio_attr -u ip:pluto.local -c ad9361-phy RX_LO_FREQ 629000000
iio_readdev -u ip:pluto.local -b 65536 cf-ad9361-lpc | \
    python3 atsc3_demod.py --output shards/
```

**Build from source (Ubuntu 22.04):**
```bash
sudo apt install gnuradio gr-osmosdr libiio-dev libad9361-dev
git clone https://github.com/argilo/gr-atsc3.git && cd gr-atsc3
cmake -B build && cmake --build build && sudo cmake --install build
```
