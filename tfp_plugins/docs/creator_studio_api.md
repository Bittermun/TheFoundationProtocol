# TFP Creator Studio API

## Building Monetization & Access Control Tools on TFP

This document describes how developers can build monetization, licensing, and access control tools **on top of** the TFP protocol. 

## Core Philosophy

**TFP Core NEVER:**
- Enforces DRM or access restrictions
- Blocks hash resolution
- Validates licenses
- Prevents content sharing

**TFP Plugins CAN:**
- Manage encryption keys
- Track licenses and payments
- Implement time-locks and paywalls
- Create community gates
- Build creator studios and marketplaces

The protocol provides the **infrastructure**; plugins provide the **policy**.

---

## Plugin Architecture

```
┌─────────────────────────────────────────────────────┐
│                 TFP CORE (Protocol)                  │
│  - Hash resolution (always works)                    │
│  - NDN routing                                       │
│  - RaptorQ encoding                                  │
│  - Credit ledger                                     │
│  - PUF identity                                      │
└─────────────────────────────────────────────────────┘
                          │
                          │ Public APIs
                          ▼
┌─────────────────────────────────────────────────────┐
│              PLUGIN LAYER (Your Code)                │
│  - license_manager.py    → Time-locks, paywalls     │
│  - threshold_release.py  → Multi-sig releases       │
│  - your_plugin.py        → Custom logic             │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   CREATOR STUDIO UI   │
              │   MARKETPLACE APP     │
              │   COMMUNITY GATE      │
              └───────────────────────┘
```

---

## Getting Started

### 1. Import Core Modules

```python
from tfp_core.compute.task_mesh import ComputeMesh, TaskRecipe
from tfp_core.compute.verify_habp import HABPVerifier, generate_execution_proof
from tfp_core.compute.device_safety import DeviceSafetyGuard, create_device_metrics
from tfp_core.compute.credit_formula import CreditFormula

from tfp_plugins.access_control.license_manager import LicenseManager, LicenseType
from tfp_plugins.access_control.threshold_release import ThresholdReleaser
```

### 2. Create a License Manager

```python
# Initialize the license manager
manager = LicenseManager()

# Create paywalled content
content_hash = "abc123..."  # SHA3-256 of your content
license_obj = manager.create_license(
    content_hash=content_hash,
    license_type=LicenseType.PAYWALL,
    creator_id="creator_001",
    price_credits=100
)

# Check if user has access
has_access, reason = manager.check_access(content_hash, "user_456")
if not has_access:
    print(f"Access denied: {reason}")
    # Prompt user to purchase
else:
    print(f"Access granted: {reason}")
    # Provide decryption key
```

### 3. Create Time-Locked Content

```python
import time

# Unlock in 24 hours
unlock_time = time.time() + (24 * 3600)

license_obj = manager.create_license(
    content_hash=content_hash,
    license_type=LicenseType.TIME_LOCKED,
    creator_id="creator_001",
    unlock_conditions={"unlock_at": unlock_time}
)

# Users can see the content exists but can't decrypt until unlock_time
```

### 4. Create Community-Gated Content

```python
# Only members of specific groups can access
license_obj = manager.create_license(
    content_hash=content_hash,
    license_type=LicenseType.COMMUNITY_GATE,
    creator_id="creator_001",
    allowed_groups=["researchers", "premium_members"]
)

# Register users to groups
manager.register_user_group("user_456", "researchers")

# Check access
has_access, reason = manager.check_access(content_hash, "user_456")
# Returns True if user is in any allowed group
```

### 5. Multi-Signature Release

```python
releaser = ThresholdReleaser()

# Create a 3-of-5 threshold release
release = releaser.create_release(
    content_hash=content_hash,
    required_signatures=3,
    authorized_keys=["key_a", "key_b", "key_c", "key_d", "key_e"],
    duration_hours=168  # 7 days
)

# Contributors add signatures
success, msg = releaser.contribute_signature(
    release_id=release.release_id,
    key_id="key_a",
    signature="sig_abc123..."
)

# Check status
status = releaser.check_release_status(release.release_id)
print(f"{status['collected']}/{status['required']} signatures collected")

# Get released key when threshold is met
decryption_key = releaser.get_release_key(release.release_id)
```

---

## Integration Patterns

### Pattern 1: Marketplace App

```python
class MarketplaceApp:
    def __init__(self):
        self.license_manager = LicenseManager()
        self.credits_ledger = ...  # Connect to TFP credit system
        
    def list_content(self, creator_id, content_hash, price_credits):
        """List content for sale."""
        self.license_manager.create_license(
            content_hash=content_hash,
            license_type=LicenseType.PAYWALL,
            creator_id=creator_id,
            price_credits=price_credits
        )
        
    def purchase(self, buyer_id, content_hash):
        """Handle purchase transaction."""
        license_obj = self.license_manager.get_license(content_hash)
        
        # Deduct credits from buyer
        self.credits_ledger.transfer(buyer_id, license_obj.creator_id, license_obj.price_credits)
        
        # Grant access
        self.license_manager.grant_access(
            content_hash=content_hash,
            user_id=buyer_id,
            reason=f"Purchased for {license_obj.price_credits} credits"
        )
        
        return True
```

### Pattern 2: Creator Studio

```python
class CreatorStudio:
    def __init__(self):
        self.license_manager = LicenseManager()
        self.releaser = ThresholdReleaser()
        
    def publish_with_options(self, content_hash, options):
        """Publish content with various access options."""
        if options["type"] == "free":
            self.license_manager.create_license(
                content_hash=content_hash,
                license_type=LicenseType.OPEN,
                creator_id=options["creator_id"]
            )
            
        elif options["type"] == "paid":
            self.license_manager.create_license(
                content_hash=content_hash,
                license_type=LicenseType.PAYWALL,
                creator_id=options["creator_id"],
                price_credits=options["price"]
            )
            
        elif options["type"] == "early_access":
            # Paid early access, then free after date
            early_unlock = time.time() + (options["early_days"] * 86400)
            self.license_manager.create_license(
                content_hash=content_hash,
                license_type=LicenseType.TIME_LOCKED,
                creator_id=options["creator_id"],
                unlock_conditions={"unlock_at": early_unlock},
                price_credits=options["early_price"]
            )
```

### Pattern 3: Collaborative Release

```python
class CollaborativePublisher:
    def __init__(self):
        self.releaser = ThresholdReleaser()
        
    def create_collaborative_work(self, content_hash, contributors):
        """Create content that requires all contributors to release."""
        self.releaser.create_release(
            content_hash=content_hash,
            required_signatures=len(contributors),  # All must agree
            authorized_keys=[c["public_key"] for c in contributors],
            duration_hours=720  # 30 days to decide
        )
```

---

## Best Practices

### 1. Never Block Hash Resolution

Content hashes should **always** resolve via NDN. Your plugin controls **decryption keys**, not content availability.

```python
# ❌ WRONG: Don't block content
if not has_license:
    raise Exception("Content not available")

# ✅ RIGHT: Control the key
if not has_license:
    return None  # No decryption key
else:
    return decryption_key
```

### 2. Use Envelope Encryption

Encrypt content with a symmetric key, then manage the key separately:

```python
# Content encryption (done by creator)
content_key = generate_random_key()
encrypted_content = encrypt(content, content_key)

# Publish encrypted content (hash always resolves)
publish_to_tfp(encrypted_content)

# Manage key access via plugin
license_manager.create_license(
    content_hash=hash(encrypted_content),
    license_type=LicenseType.PAYWALL,
    unlock_conditions={"key": content_key}  # Released on payment
)
```

### 3. Graceful Degradation

If your plugin service is unavailable, content should still be accessible for open/unlocked items:

```python
def get_content(content_hash, user_id):
    # Always try to fetch content first
    content = tfp_fetch(content_hash)
    
    # Try to get decryption key
    try:
        key = license_manager.get_key(content_hash, user_id)
        if key:
            return decrypt(content, key)
    except ServiceUnavailable:
        pass
    
    # Return encrypted content with metadata
    return {
        "encrypted": True,
        "content": content,
        "license_info": license_manager.get_license(content_hash)
    }
```

### 4. Transparent Pricing

Always show users:
- What they're paying for
- How long access lasts
- What happens if service goes offline

---

## API Reference

### LicenseManager

| Method | Description |
|--------|-------------|
| `create_license(...)` | Create a new license |
| `check_access(content_hash, user_id)` | Check if user has access |
| `grant_access(content_hash, user_id, reason, duration_hours)` | Grant access |
| `register_user_group(user_id, group)` | Add user to community group |
| `get_license(content_hash)` | Get license info |
| `get_user_grants(user_id)` | Get all grants for user |

### ThresholdReleaser

| Method | Description |
|--------|-------------|
| `create_release(content_hash, required_signatures, authorized_keys, duration_hours)` | Create threshold release |
| `contribute_signature(release_id, key_id, signature)` | Add signature |
| `check_release_status(release_id)` | Get release status |
| `get_release_key(release_id)` | Get key if released |
| `get_pending_releases()` | List unreleased items |
| `cancel_release(release_id)` | Cancel release |

### ComputeMesh

| Method | Description |
|--------|-------------|
| `broadcast_task(recipe)` | Broadcast compute task |
| `submit_bid(bid)` | Submit execution bid |
| `select_winner(task_id)` | Select best bid |
| `complete_task(task_id, result_hash, success)` | Mark task complete |

---

## Example Projects

### 1. Academic Paper Repository
- Time-lock papers until publication date
- Community gate for university members
- Free access after embargo period

### 2. Indie Game Distribution
- Paywall for games
- Demo versions as open content
- DLC as threshold releases (community votes)

### 3. Collaborative Research
- Multi-sig release for joint publications
- All authors must approve release
- Automatic credit distribution

### 4. Music Label Platform
- Early access paywall for fans
- Time-lock until official release
- Community gates for fan clubs

---

## Support

For questions about building on TFP:
- Documentation: `/tfp-plugins/docs/`
- Core modules: `/tfp-core/compute/`
- Plugin examples: `/tfp-plugins/access-control/`

Remember: **Build policy in plugins, not core.**
