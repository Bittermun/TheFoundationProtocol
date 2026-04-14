# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Credit Formula for Compute Tasks

Calculates credits based on task difficulty, hardware trust,
uptime factor, and verification confidence. Integrates with
existing decay/staking logic.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CreditCalculation:
    """Result of credit calculation."""

    base_reward: int
    hardware_trust_multiplier: float
    uptime_factor: float
    verification_confidence: float
    final_credits: int
    breakdown: dict


class CreditFormula:
    """
    Calculate credits for compute tasks.

    Formula:
      Credits = base_task_reward × hardware_trust × uptime_factor × verification_confidence

    All multipliers are 0.0-2.0 range, with 1.0 being baseline.
    """

    # Base rewards by difficulty (1-10)
    BASE_REWARDS = {
        1: 10,
        2: 20,
        3: 35,
        4: 50,
        5: 75,
        6: 100,
        7: 150,
        8: 200,
        9: 300,
        10: 500,
    }

    def __init__(
        self,
        min_hardware_trust: float = 0.5,
        max_hardware_trust: float = 1.5,
        min_uptime_factor: float = 0.8,
        max_uptime_factor: float = 1.2,
        min_verification_confidence: float = 0.0,
        max_verification_confidence: float = 2.0,
    ):
        self._min_hardware_trust = min_hardware_trust
        self._max_hardware_trust = max_hardware_trust
        self._min_uptime_factor = min_uptime_factor
        self._max_uptime_factor = max_uptime_factor
        self._min_verification_confidence = min_verification_confidence
        self._max_verification_confidence = max_verification_confidence

    def calculate_credits(
        self,
        difficulty: int,
        hardware_trust: float,
        uptime_hours: float,
        verification_confidence: float,
        is_charging: bool = False,
        task_completion_time: Optional[float] = None,
        estimated_time: Optional[float] = None,
    ) -> CreditCalculation:
        """
        Calculate final credits for a completed task.

        Args:
            difficulty: Task difficulty (1-10)
            hardware_trust: Device trust score (0.0-1.0+, from HABP)
            uptime_hours: Device uptime in hours
            verification_confidence: Verification confidence (0.0-1.0, from HABP)
            is_charging: Whether device was charging during execution
            task_completion_time: Actual completion time (seconds)
            estimated_time: Estimated completion time (seconds)

        Returns:
            CreditCalculation with breakdown
        """
        # Base reward from difficulty
        base_reward = self.BASE_REWARDS.get(difficulty, 50)

        # Hardware trust multiplier (0.5x - 1.5x)
        # Trust scores > 1.0 come from TEE attestation bonuses
        hardware_multiplier = self._clamp(
            hardware_trust, self._min_hardware_trust, self._max_hardware_trust
        )

        # Uptime factor (0.8x - 1.2x)
        # Rewards stable devices, penalizes frequently rebooting ones
        uptime_factor = self._calculate_uptime_factor(uptime_hours)
        uptime_factor = self._clamp(
            uptime_factor, self._min_uptime_factor, self._max_uptime_factor
        )

        # Verification confidence (0.0x - 2.0x)
        # Directly from HABP consensus/TEE results
        verif_factor = self._clamp(
            verification_confidence * 2.0,  # Scale 0-1 to 0-2
            self._min_verification_confidence,
            self._max_verification_confidence,
        )

        # Charging bonus (1.1x if charging)
        charging_bonus = 1.1 if is_charging else 1.0

        # Speed bonus (up to 1.2x for faster than estimated)
        speed_bonus = 1.0
        if task_completion_time and estimated_time:
            if task_completion_time < estimated_time:
                ratio = task_completion_time / estimated_time
                speed_bonus = 1.0 + (0.2 * (1.0 - ratio))  # Up to 1.2x

        # Calculate final
        final_credits = int(
            base_reward
            * hardware_multiplier
            * uptime_factor
            * verif_factor
            * charging_bonus
            * speed_bonus
        )

        return CreditCalculation(
            base_reward=base_reward,
            hardware_trust_multiplier=round(hardware_multiplier, 3),
            uptime_factor=round(uptime_factor, 3),
            verification_confidence=round(verif_factor, 3),
            final_credits=final_credits,
            breakdown={
                "charging_bonus": round(charging_bonus, 3),
                "speed_bonus": round(speed_bonus, 3),
                "total_multiplier": round(
                    hardware_multiplier
                    * uptime_factor
                    * verif_factor
                    * charging_bonus
                    * speed_bonus,
                    3,
                ),
            },
        )

    def _calculate_uptime_factor(self, uptime_hours: float) -> float:
        """
        Calculate uptime factor based on device stability.

        Optimal uptime: 24-48 hours (factor = 1.2)
        Too short (< 1h): factor = 0.8 (frequent reboots)
        Too long (> 72h): factor = 0.9 (needs rest)
        """
        if uptime_hours < 1:
            return 0.8
        elif uptime_hours < 6:
            return 0.9
        elif uptime_hours < 24:
            return 1.0
        elif uptime_hours < 48:
            return 1.2
        elif uptime_hours < 72:
            return 1.1
        else:
            return 0.9

    def _clamp(self, value: float, min_val: float, max_val: float) -> float:
        """Clamp value between min and max."""
        return max(min_val, min(max_val, value))

    def get_base_reward(self, difficulty: int) -> int:
        """Get base reward for a difficulty level."""
        return self.BASE_REWARDS.get(difficulty, 50)

    def update_base_rewards(self, rewards: dict) -> None:
        """Update base reward table."""
        self.BASE_REWARDS.update(rewards)


def calculate_task_credits(
    difficulty: int,
    hardware_trust: float,
    uptime_hours: float,
    verification_confidence: float,
    is_charging: bool = False,
) -> int:
    """Convenience function for quick credit calculation."""
    formula = CreditFormula()
    result = formula.calculate_credits(
        difficulty=difficulty,
        hardware_trust=hardware_trust,
        uptime_hours=uptime_hours,
        verification_confidence=verification_confidence,
        is_charging=is_charging,
    )
    return result.final_credits
